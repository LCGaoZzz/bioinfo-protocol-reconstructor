#!/usr/bin/env python3
"""Adjudicate one reconstruction execution from bound result checks.

This standard-library-only helper validates checks against files recorded by
``run_reconstruction.py``, mirrors the adjudication into the receipt and record
fragment, and refreshes the fragment's receipt hash.  The receipt is local,
unsigned audit evidence; this helper does not make it a trusted attestation.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
import os
import re
import sys
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from execution_contract import (
    argv_seed_bindings,
    normalized_python_child_environment,
    python_local_import_closure,
    verify_python_dependency_versions,
)


ID_RE = re.compile(r"^[A-Za-z][A-Za-z0-9_.-]*$")
SHA256_RE = re.compile(r"^(?:sha256:)?([A-Fa-f0-9]{64})$")
RECEIPT_SCHEMA_VERSION = "1.0.0"
RECEIPT_PRODUCER = "dev-reconstruct-bioinfo-protocol/run_reconstruction.py"
RECEIPT_PRODUCER_VERSION = "1.0.0"
CHECK_KEYS = {
    "check_id",
    "check",
    "metric",
    "unit",
    "observed",
    "passed",
    "analysis_ids",
    "evidence_paths",
    "verification",
}
MIRRORED_FIELDS = (
    "execution_id",
    "analysis_ids",
    "command",
    "command_argv",
    "entrypoint",
    "code_evidence_refs",
    "code_snapshot_sha256",
    "code_files",
    "working_directory",
    "started_at_utc",
    "finished_at_utc",
    "exit_code",
    "dependencies",
    "seed",
    "seed_reason",
    "inputs",
    "outputs",
    "stdout_log",
    "stderr_log",
    "checks",
    "checks_sha256",
    "observed_parameters",
    "observed_parameters_sha256",
    "adjudication_status",
    "adjudicated_at_utc",
    "supersedes_execution_ids",
    "preflight",
    "code_provenance",
)
OBSERVED_PARAMETER_KEYS = {"name", "value", "evidence_paths"}
VERIFICATION_KEYS = {"kind", "evidence_path", "selector", "expected"}
TSV_SELECTOR_REQUIRED_KEYS = {"key_column", "key_value", "value_column"}
TSV_SELECTOR_KEYS = TSV_SELECTOR_REQUIRED_KEYS | {"unit_column"}
VERIFICATION_KINDS = {
    "tsv_cell_equals",
    "json_pointer_equals",
    "text_contains",
    "sha256_equals",
}
LOCK_FILENAME = ".finalize_execution.lock"
MAX_PARAMETER_EVIDENCE_BYTES = 16 * 1024 * 1024
class FinalizationError(ValueError):
    """Raised when adjudication input is structurally invalid or unbound."""


def _validate_seed_command_binding(receipt: dict[str, Any]) -> None:
    seed = receipt.get("seed")
    argv = receipt.get("command_argv")
    values, malformed = argv_seed_bindings(argv, receipt.get("entrypoint"))
    if malformed:
        raise FinalizationError("command_argv contains an invalid or ambiguous seed-like option")
    if isinstance(seed, bool) or not isinstance(seed, (int, str)):
        raise FinalizationError("seed must be an integer or not_applicable")
    if seed == "not_applicable":
        if not str(receipt.get("seed_reason", "")).strip():
            raise FinalizationError("not_applicable seed requires a non-empty seed_reason")
        if values:
            raise FinalizationError(
                "seed=not_applicable conflicts with an explicit seed option in command_argv"
            )
        return
    if not isinstance(seed, int):
        raise FinalizationError("seed must be an integer or not_applicable")
    if not values:
        raise FinalizationError(
            "command_argv does not bind the recorded seed through a canonical long option"
        )
    if any(value != str(seed) for value in values):
        raise FinalizationError("an explicit command_argv seed option conflicts with the recorded seed")


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _reject_json_constant(value: str) -> None:
    raise FinalizationError(f"non-standard JSON number is not allowed: {value}")


def _unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise FinalizationError(f"duplicate JSON object key: {key}")
        result[key] = value
    return result


def _load_json(path: Path, label: str) -> Any:
    if not path.is_file():
        raise FinalizationError(f"{label} does not exist: {path}")
    try:
        return json.loads(
            path.read_text(encoding="utf-8"),
            object_pairs_hook=_unique_object,
            parse_constant=_reject_json_constant,
        )
    except UnicodeDecodeError as exc:
        raise FinalizationError(f"{label} is not valid UTF-8: {path}") from exc
    except json.JSONDecodeError as exc:
        raise FinalizationError(f"{label} is not valid JSON: {path}: {exc}") from exc


def _canonical_json_bytes(value: Any) -> bytes:
    try:
        rendered = json.dumps(
            value,
            sort_keys=True,
            ensure_ascii=False,
            separators=(",", ":"),
            allow_nan=False,
        )
    except (TypeError, ValueError) as exc:
        raise FinalizationError(f"value is not canonical JSON: {exc}") from exc
    return rendered.encode("utf-8")


def _canonical_sha256(value: Any) -> str:
    return hashlib.sha256(_canonical_json_bytes(value)).hexdigest()


def _json_bytes(value: Any) -> bytes:
    try:
        rendered = json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + "\n"
    except (TypeError, ValueError) as exc:
        raise FinalizationError(f"value is not writable JSON: {exc}") from exc
    return rendered.encode("utf-8")


def _atomic_write_json(path: Path, value: Any) -> None:
    payload = _json_bytes(value)
    temporary = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    try:
        with temporary.open("xb") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        try:
            temporary.unlink()
        except FileNotFoundError:
            pass


@contextmanager
def _exclusive_run_lock(lock_path: Path, execution_id: str):
    """Hold a Windows-safe, one-owner lock without reclaiming stale locks."""

    flags = os.O_CREAT | os.O_EXCL | os.O_WRONLY
    if hasattr(os, "O_BINARY"):
        flags |= os.O_BINARY
    acquired = False
    descriptor: int | None = None
    handle = None
    try:
        try:
            descriptor = os.open(lock_path, flags, 0o600)
        except FileExistsError as exc:
            raise FinalizationError(
                f"execution finalization lock already exists: {lock_path}; "
                "do not overwrite or remove a potentially stale lock automatically"
            ) from exc
        acquired = True
        handle = os.fdopen(descriptor, "w", encoding="utf-8", newline="\n")
        descriptor = None
        handle.write(
            json.dumps(
                {
                    "execution_id": execution_id,
                    "process_id": os.getpid(),
                    "created_at_utc": _utc_now(),
                },
                ensure_ascii=False,
                sort_keys=True,
            )
            + "\n"
        )
        handle.flush()
        os.fsync(handle.fileno())
        yield
    finally:
        try:
            if handle is not None:
                handle.close()
            elif descriptor is not None:
                os.close(descriptor)
        finally:
            if acquired:
                try:
                    lock_path.unlink()
                except FileNotFoundError:
                    pass


def _nonempty(value: Any) -> bool:
    if value is None:
        return False
    if isinstance(value, str):
        return bool(value.strip())
    if isinstance(value, (list, tuple, dict, set)):
        return bool(value)
    return True


def _nonempty_unique_strings(value: Any, label: str) -> list[str]:
    if not isinstance(value, list) or not value:
        raise FinalizationError(f"{label} must be a non-empty array")
    if any(not isinstance(item, str) or not item.strip() for item in value):
        raise FinalizationError(f"{label} must contain only non-empty strings")
    if len(value) != len(set(value)):
        raise FinalizationError(f"{label} must not contain duplicates")
    return value


def _project_path(root: Path, value: Any, label: str) -> tuple[Path, str]:
    if not isinstance(value, str) or not value.strip():
        raise FinalizationError(f"{label} must be a non-empty project-relative path")
    candidate = Path(value)
    if candidate.is_absolute() or candidate.drive or ".." in candidate.parts:
        raise FinalizationError(f"{label} must be a project-relative path without '..': {value}")
    resolved = (root / candidate).resolve()
    try:
        canonical = resolved.relative_to(root).as_posix()
    except ValueError as exc:
        raise FinalizationError(f"{label} escapes the project directory: {value}") from exc
    return resolved, canonical


def _project_file(root: Path, value: Any, label: str) -> tuple[Path, str]:
    resolved, canonical = _project_path(root, value, label)
    if not resolved.is_file():
        raise FinalizationError(f"{label} does not exist as a file: {value}")
    return resolved, canonical


def _normalized_sha256(value: Any, label: str) -> str:
    if not isinstance(value, str):
        raise FinalizationError(f"{label} must be a SHA-256 string")
    match = SHA256_RE.fullmatch(value)
    if not match:
        raise FinalizationError(f"{label} must be a SHA-256 string")
    return match.group(1).lower()


def _validate_receipt_metadata(receipt: dict[str, Any]) -> None:
    if receipt.get("receipt_schema_version") != RECEIPT_SCHEMA_VERSION:
        raise FinalizationError(
            f"receipt_schema_version must be {RECEIPT_SCHEMA_VERSION}"
        )
    if (
        receipt.get("producer") != RECEIPT_PRODUCER
        or receipt.get("producer_version") != RECEIPT_PRODUCER_VERSION
    ):
        raise FinalizationError("receipt producer/version is not recognized")
    if re.fullmatch(r"[0-9a-f]{32}", str(receipt.get("nonce", ""))) is None:
        raise FinalizationError("receipt nonce must be 32 lowercase hexadecimal characters")
    process_id = receipt.get("process_id")
    if not isinstance(process_id, int) or isinstance(process_id, bool) or process_id <= 0:
        raise FinalizationError("receipt process_id must be a positive integer")


def _validate_receipt_fragment_mirror(
    receipt: dict[str, Any], fragment: dict[str, Any]
) -> None:
    for field in MIRRORED_FIELDS:
        receipt_has_field = field in receipt
        fragment_has_field = field in fragment
        if receipt_has_field != fragment_has_field:
            raise FinalizationError(f"receipt and fragment differ in field presence: {field}")
        if not receipt_has_field:
            if field == "seed_reason":
                continue
            raise FinalizationError(f"receipt and fragment must both contain {field}")
        if not _strict_json_equal(receipt[field], fragment[field]):
            raise FinalizationError(f"receipt and fragment mismatch: {field}")


def _validate_recorded_inputs(root: Path, receipt: dict[str, Any]) -> set[Path]:
    inputs = receipt.get("inputs")
    if not isinstance(inputs, list) or not inputs:
        raise FinalizationError("receipt inputs must be a non-empty array")
    allowed_keys = {"artifact_id", "path", "sha256", "semantic_type"}
    artifact_ids: set[str] = set()
    input_paths: set[Path] = set()
    for index, artifact in enumerate(inputs):
        label = f"inputs[{index}]"
        if not isinstance(artifact, dict) or set(artifact) != allowed_keys:
            raise FinalizationError(f"{label} must contain exactly {sorted(allowed_keys)}")
        artifact_id = artifact["artifact_id"]
        semantic_type = artifact["semantic_type"]
        if not isinstance(artifact_id, str) or not artifact_id.strip():
            raise FinalizationError(f"{label}.artifact_id must be a non-empty string")
        if artifact_id in artifact_ids:
            raise FinalizationError(f"duplicate recorded input artifact_id: {artifact_id}")
        artifact_ids.add(artifact_id)
        if not isinstance(semantic_type, str) or not semantic_type.strip():
            raise FinalizationError(f"{label}.semantic_type must be a non-empty string")
        path, canonical = _project_file(root, artifact["path"], f"{label}.path")
        if path in input_paths:
            raise FinalizationError(f"duplicate recorded input path: {canonical}")
        input_paths.add(path)
        recorded_hash = _normalized_sha256(artifact["sha256"], f"{label}.sha256")
        if _sha256(path) != recorded_hash:
            raise FinalizationError(f"{label} file hash no longer matches the execution record")
    return input_paths


def _validate_entrypoint_snapshot(root: Path, receipt: dict[str, Any]) -> Path:
    entrypoint, _ = _project_file(root, receipt.get("entrypoint"), "entrypoint")
    recorded_hash = _normalized_sha256(
        receipt.get("code_snapshot_sha256"), "code_snapshot_sha256"
    )
    if _sha256(entrypoint) != recorded_hash:
        raise FinalizationError("entrypoint hash no longer matches code_snapshot_sha256")
    _nonempty_unique_strings(receipt.get("code_evidence_refs"), "code_evidence_refs")
    return entrypoint


def _validate_code_file_closure(
    root: Path, entrypoint: Path, receipt: dict[str, Any]
) -> None:
    code_files = receipt.get("code_files")
    if not isinstance(code_files, list) or not code_files:
        raise FinalizationError("receipt code_files must be a non-empty array")
    recorded: dict[Path, str] = {}
    for index, item in enumerate(code_files):
        label = f"code_files[{index}]"
        if not isinstance(item, dict) or set(item) != {"path", "sha256"}:
            raise FinalizationError(f"{label} must contain exactly path and sha256")
        path, _ = _project_file(root, item.get("path"), f"{label}.path")
        digest = _normalized_sha256(item.get("sha256"), f"{label}.sha256")
        if path in recorded:
            raise FinalizationError("receipt code_files must not contain duplicate paths")
        if _sha256(path) != digest:
            raise FinalizationError(f"{label} hash no longer matches the executed code bundle")
        recorded[path] = digest
    discovered, gaps = python_local_import_closure(root, entrypoint)
    if gaps:
        raise FinalizationError("local code import closure is ambiguous: " + "; ".join(gaps))
    if set(recorded) != set(discovered):
        raise FinalizationError(
            "receipt code_files does not exactly match the recursive local import closure"
        )


def _output_owners(
    artifact: dict[str, Any], label: str, record_analysis_ids: list[str]
) -> list[str]:
    if "analysis_ids" not in artifact:
        if len(record_analysis_ids) != 1:
            raise FinalizationError(
                f"{label}.analysis_ids is required for a multi-analysis execution"
            )
        artifact["analysis_ids"] = list(record_analysis_ids)
    owners = _nonempty_unique_strings(artifact["analysis_ids"], f"{label}.analysis_ids")
    unknown = set(owners) - set(record_analysis_ids)
    if unknown:
        raise FinalizationError(
            f"{label}.analysis_ids contains ids outside the execution: {sorted(unknown)}"
        )
    return owners


def _validate_execution_artifacts(
    root: Path,
    receipt: dict[str, Any],
    fragment: dict[str, Any],
    record_analysis_ids: list[str],
    missing_outputs: list[str],
) -> tuple[set[Path], dict[Path, frozenset[str]]]:
    receipt_outputs = receipt.get("outputs")
    fragment_outputs = fragment.get("outputs")
    if not isinstance(receipt_outputs, list) or not isinstance(fragment_outputs, list):
        raise FinalizationError("receipt and fragment outputs must be arrays")
    if not _strict_json_equal(receipt_outputs, fragment_outputs):
        raise FinalizationError("receipt and fragment outputs are inconsistent")

    expected_outputs = receipt.get("expected_outputs")
    if not isinstance(expected_outputs, list) or not expected_outputs:
        raise FinalizationError("receipt expected_outputs must be a non-empty array")

    expected_keys = {"artifact_id", "path", "semantic_type", "analysis_ids"}
    output_keys = expected_keys | {"sha256"}
    expected_by_id: dict[str, dict[str, Any]] = {}
    expected_paths: dict[Path, str] = {}
    expected_owner_union: set[str] = set()
    for index, artifact in enumerate(expected_outputs):
        label = f"expected_outputs[{index}]"
        if not isinstance(artifact, dict):
            raise FinalizationError(f"{label} must be an object")
        owners = _output_owners(artifact, label, record_analysis_ids)
        if set(artifact) != expected_keys:
            raise FinalizationError(f"{label} must contain exactly {sorted(expected_keys)}")
        artifact_id = artifact["artifact_id"]
        semantic_type = artifact["semantic_type"]
        if not isinstance(artifact_id, str) or not artifact_id.strip():
            raise FinalizationError(f"{label}.artifact_id must be a non-empty string")
        if artifact_id in expected_by_id:
            raise FinalizationError(f"duplicate expected output artifact_id: {artifact_id}")
        if not isinstance(semantic_type, str) or not semantic_type.strip():
            raise FinalizationError(f"{label}.semantic_type must be a non-empty string")
        path, canonical = _project_path(root, artifact["path"], f"{label}.path")
        if path in expected_paths:
            raise FinalizationError(f"duplicate expected output path: {canonical}")
        expected_by_id[artifact_id] = artifact
        expected_paths[path] = canonical
        expected_owner_union.update(owners)

    unowned = set(record_analysis_ids) - expected_owner_union
    if unowned:
        raise FinalizationError(
            "every execution analysis id must own at least one expected output: "
            + ", ".join(sorted(unowned))
        )

    allowed: set[Path] = set()
    output_owners: dict[Path, frozenset[str]] = {}
    observed_artifact_ids: set[str] = set()
    for index, artifact in enumerate(fragment_outputs):
        label = f"outputs[{index}]"
        if not isinstance(artifact, dict):
            raise FinalizationError(f"{label} must be an object")
        owners = _output_owners(artifact, label, record_analysis_ids)
        receipt_artifact = receipt_outputs[index]
        if not isinstance(receipt_artifact, dict):
            raise FinalizationError(f"receipt {label} must be an object")
        if "analysis_ids" not in receipt_artifact and len(record_analysis_ids) == 1:
            receipt_artifact["analysis_ids"] = list(record_analysis_ids)
        if not _strict_json_equal(receipt_artifact, artifact):
            raise FinalizationError(f"receipt and fragment {label} are inconsistent")
        if set(artifact) != output_keys:
            raise FinalizationError(f"{label} must contain exactly {sorted(output_keys)}")
        artifact_id = artifact["artifact_id"]
        semantic_type = artifact["semantic_type"]
        if not isinstance(artifact_id, str) or not artifact_id.strip():
            raise FinalizationError(f"{label}.artifact_id must be a non-empty string")
        if artifact_id in observed_artifact_ids:
            raise FinalizationError(f"duplicate recorded output artifact_id: {artifact_id}")
        observed_artifact_ids.add(artifact_id)
        expected = expected_by_id.get(artifact_id)
        if expected is None:
            raise FinalizationError(f"{label}.artifact_id is not declared in expected_outputs")
        for field in ("artifact_id", "path", "semantic_type", "analysis_ids"):
            if not _strict_json_equal(artifact[field], expected[field]):
                raise FinalizationError(f"{label}.{field} differs from expected_outputs")
        if not isinstance(semantic_type, str) or not semantic_type.strip():
            raise FinalizationError(f"{label}.semantic_type must be a non-empty string")
        path, canonical = _project_file(root, artifact.get("path"), f"{label}.path")
        recorded_hash = _normalized_sha256(artifact.get("sha256"), f"{label}.sha256")
        if _sha256(path) != recorded_hash:
            raise FinalizationError(f"{label} file hash no longer matches the execution record")
        if path in allowed:
            raise FinalizationError(f"duplicate recorded output path: {canonical}")
        allowed.add(path)
        output_owners[path] = frozenset(owners)

    missing_canonical: set[Path] = set()
    for index, value in enumerate(missing_outputs):
        path, _ = _project_path(root, value, f"missing_outputs[{index}]")
        if path in missing_canonical:
            raise FinalizationError("receipt missing_outputs must not contain duplicates")
        missing_canonical.add(path)
    computed_missing = set(expected_paths) - set(output_owners)
    if missing_canonical != computed_missing:
        raise FinalizationError(
            "receipt missing_outputs is inconsistent with expected_outputs and outputs"
        )

    for stream in ("stdout", "stderr"):
        path_key = f"{stream}_log"
        hash_key = f"{stream}_sha256"
        if receipt.get(path_key) != fragment.get(path_key):
            raise FinalizationError(f"receipt and fragment {path_key} are inconsistent")
        path, canonical = _project_file(root, fragment.get(path_key), path_key)
        recorded_hash = _normalized_sha256(receipt.get(hash_key), hash_key)
        if _sha256(path) != recorded_hash:
            raise FinalizationError(f"{path_key} hash no longer matches the receipt")
        if path in allowed:
            raise FinalizationError(f"duplicate output/log evidence path: {canonical}")
        allowed.add(path)
    return allowed, output_owners


def _validate_evidence_paths(
    root: Path, value: Any, allowed: set[Path], label: str
) -> list[Path]:
    paths = _nonempty_unique_strings(value, label)
    resolved_paths: list[Path] = []
    for index, item in enumerate(paths):
        resolved, _ = _project_file(root, item, f"{label}[{index}]")
        if resolved not in allowed:
            raise FinalizationError(
                f"{label}[{index}] is not a recorded output or process log: {item}"
            )
        if resolved in resolved_paths:
            raise FinalizationError(f"{label} contains duplicate canonical paths")
        resolved_paths.append(resolved)
    return resolved_paths


def _read_bounded_utf8_text(path: Path) -> str | None:
    try:
        if path.stat().st_size > MAX_PARAMETER_EVIDENCE_BYTES:
            return None
        payload = path.read_bytes()
        if b"\x00" in payload:
            return None
        return payload.decode("utf-8-sig")
    except (OSError, UnicodeDecodeError):
        return None


def _required_bounded_utf8_text(path: Path, label: str) -> str:
    try:
        size = path.stat().st_size
    except OSError as exc:
        raise FinalizationError(f"{label} cannot be inspected: {exc}") from exc
    if size > MAX_PARAMETER_EVIDENCE_BYTES:
        raise FinalizationError(
            f"{label} exceeds the {MAX_PARAMETER_EVIDENCE_BYTES}-byte text verification limit"
        )
    try:
        payload = path.read_bytes()
    except OSError as exc:
        raise FinalizationError(f"{label} cannot be read: {exc}") from exc
    if b"\x00" in payload:
        raise FinalizationError(f"{label} is not accepted as text because it contains NUL bytes")
    try:
        return payload.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise FinalizationError(f"{label} is not valid UTF-8 text") from exc


def _strict_json_equal(left: Any, right: Any) -> bool:
    if type(left) is not type(right):
        return False
    if isinstance(left, list):
        return len(left) == len(right) and all(
            _strict_json_equal(a, b) for a, b in zip(left, right)
        )
    if isinstance(left, dict):
        return left.keys() == right.keys() and all(
            _strict_json_equal(left[key], right[key]) for key in left
        )
    return left == right


def _validate_tsv_selector(selector: Any, label: str) -> dict[str, str]:
    if not isinstance(selector, dict):
        raise FinalizationError(f"{label} must be an object")
    missing = TSV_SELECTOR_REQUIRED_KEYS - set(selector)
    unknown = set(selector) - TSV_SELECTOR_KEYS
    if missing or unknown:
        raise FinalizationError(
            f"{label} must contain {sorted(TSV_SELECTOR_REQUIRED_KEYS)} and optional unit_column; "
            f"missing={sorted(missing)}, unknown={sorted(unknown)}"
        )
    for key in selector:
        if not isinstance(selector[key], str) or not selector[key]:
            raise FinalizationError(f"{label}.{key} must be a non-empty string")
    return selector


def _tsv_cell(path: Path, selector: Any, label: str) -> str:
    selected = _validate_tsv_selector(selector, f"{label}.selector")
    text = _required_bounded_utf8_text(path, f"{label}.evidence_path")
    try:
        reader = csv.DictReader(io.StringIO(text, newline=""), delimiter="\t")
        fieldnames = reader.fieldnames
        if not fieldnames or any(not name for name in fieldnames):
            raise FinalizationError(f"{label} TSV must have a non-empty header row")
        if len(fieldnames) != len(set(fieldnames)):
            raise FinalizationError(f"{label} TSV header names must be unique")
        for column_key in ("key_column", "value_column"):
            column = selected[column_key]
            if column not in fieldnames:
                raise FinalizationError(f"{label} TSV does not contain column {column!r}")

        matches: list[str] = []
        for row_number, row in enumerate(reader, start=2):
            if None in row or any(value is None for value in row.values()):
                raise FinalizationError(
                    f"{label} TSV row {row_number} has the wrong field count"
                )
            if row[selected["key_column"]] == selected["key_value"]:
                matches.append(row[selected["value_column"]])
    except csv.Error as exc:
        raise FinalizationError(f"{label} evidence is not valid TSV: {exc}") from exc
    if len(matches) != 1:
        raise FinalizationError(
            f"{label} TSV selector must match exactly one row; matched {len(matches)}"
        )
    return matches[0]


def _mechanical_check_identity(
    root: Path, verification: dict[str, Any], evidence_paths: list[Path], label: str
) -> tuple[str | None, str]:
    evidence_path, _ = _project_file(
        root, verification["evidence_path"], f"{label}.verification.evidence_path"
    )
    if evidence_path not in evidence_paths:
        raise FinalizationError(
            f"{label}.verification.evidence_path must belong to the check evidence_paths"
        )
    kind = verification["kind"]
    selector = verification["selector"]
    if kind == "tsv_cell_equals":
        selected = _validate_tsv_selector(selector, f"{label}.verification.selector")
        text = _required_bounded_utf8_text(
            evidence_path, f"{label}.verification.evidence_path"
        )
        try:
            reader = csv.DictReader(io.StringIO(text, newline=""), delimiter="\t")
            fieldnames = reader.fieldnames
            if not fieldnames or any(not name for name in fieldnames):
                raise FinalizationError(f"{label} TSV must have a non-empty header row")
            unit_column = selected.get("unit_column")
            if unit_column is not None and unit_column not in fieldnames:
                raise FinalizationError(
                    f"{label} TSV does not contain unit column {unit_column!r}"
                )
            matches = [
                row
                for row in reader
                if None not in row
                and all(value is not None for value in row.values())
                and row[selected["key_column"]] == selected["key_value"]
            ]
        except csv.Error as exc:
            raise FinalizationError(f"{label} evidence is not valid TSV: {exc}") from exc
        if len(matches) != 1:
            raise FinalizationError(
                f"{label} TSV selector must match exactly one row for unit binding; matched {len(matches)}"
            )
        unit = matches[0][unit_column] if unit_column is not None else "not_recorded"
        if not unit:
            raise FinalizationError(f"{label} selected TSV unit cell is empty")
        return selected["key_value"], unit
    if kind == "json_pointer_equals":
        if not isinstance(selector, str):
            raise FinalizationError(f"{label}.verification.selector must be a JSON Pointer string")
        return selector, "not_recorded"
    if kind in {"text_contains", "sha256_equals"}:
        return None, "not_applicable"
    raise FinalizationError(f"{label}.verification.kind is unsupported")


def _decode_json_pointer_token(token: str, label: str) -> str:
    if re.search(r"~(?:[^01]|$)", token):
        raise FinalizationError(f"{label} contains an invalid RFC6901 escape")
    return token.replace("~1", "/").replace("~0", "~")


def _json_pointer_value(path: Path, selector: Any, label: str) -> Any:
    if not isinstance(selector, str):
        raise FinalizationError(f"{label}.selector must be a JSON Pointer string")
    if selector and not selector.startswith("/"):
        raise FinalizationError(f"{label}.selector must be empty or start with '/'")
    text = _required_bounded_utf8_text(path, f"{label}.evidence_path")
    try:
        value = json.loads(
            text,
            object_pairs_hook=_unique_object,
            parse_constant=_reject_json_constant,
        )
    except (json.JSONDecodeError, FinalizationError) as exc:
        raise FinalizationError(f"{label}.evidence_path is not strict JSON: {exc}") from exc
    _canonical_json_bytes(value)
    if not selector:
        return value
    current = value
    for raw_token in selector.split("/")[1:]:
        token = _decode_json_pointer_token(raw_token, f"{label}.selector")
        if isinstance(current, dict):
            if token not in current:
                raise FinalizationError(
                    f"{label}.selector key {token!r} does not exist in the JSON document"
                )
            current = current[token]
        elif isinstance(current, list):
            if not re.fullmatch(r"0|[1-9][0-9]*", token):
                raise FinalizationError(
                    f"{label}.selector token {token!r} is not a valid array index"
                )
            index = int(token)
            if index >= len(current):
                raise FinalizationError(
                    f"{label}.selector array index {index} is out of range"
                )
            current = current[index]
        else:
            raise FinalizationError(
                f"{label}.selector cannot traverse through a JSON scalar"
            )
    return current


def _recompute_check(
    root: Path,
    verification: Any,
    evidence_paths: list[Path],
    label: str,
) -> tuple[Any, bool]:
    if not isinstance(verification, dict):
        raise FinalizationError(f"{label}.verification must be an object")
    missing = VERIFICATION_KEYS - set(verification)
    unknown = set(verification) - VERIFICATION_KEYS
    if missing or unknown:
        raise FinalizationError(
            f"{label}.verification must contain exactly {sorted(VERIFICATION_KEYS)}; "
            f"missing={sorted(missing)}, unknown={sorted(unknown)}"
        )
    kind = verification["kind"]
    if not isinstance(kind, str) or kind not in VERIFICATION_KINDS:
        raise FinalizationError(
            f"{label}.verification.kind must be one of {sorted(VERIFICATION_KINDS)}"
        )
    evidence_path, _ = _project_file(
        root, verification["evidence_path"], f"{label}.verification.evidence_path"
    )
    if evidence_path not in evidence_paths:
        raise FinalizationError(
            f"{label}.verification.evidence_path must canonically belong to "
            f"{label}.evidence_paths"
        )
    selector = verification["selector"]
    expected = verification["expected"]

    if kind == "tsv_cell_equals":
        observed = _tsv_cell(evidence_path, selector, f"{label}.verification")
        passed = _strict_json_equal(observed, expected)
    elif kind == "json_pointer_equals":
        observed = _json_pointer_value(evidence_path, selector, f"{label}.verification")
        passed = _strict_json_equal(observed, expected)
    elif kind == "text_contains":
        if selector is not None:
            raise FinalizationError(f"{label}.verification.selector must be null for text_contains")
        if not isinstance(expected, str) or not expected:
            raise FinalizationError(
                f"{label}.verification.expected must be a non-empty needle string for text_contains"
            )
        text = _required_bounded_utf8_text(
            evidence_path, f"{label}.verification.evidence_path"
        )
        observed = expected in text
        passed = observed
    else:
        if selector is not None:
            raise FinalizationError(f"{label}.verification.selector must be null for sha256_equals")
        expected_hash = _normalized_sha256(
            expected, f"{label}.verification.expected"
        )
        observed = _sha256(evidence_path)
        passed = observed == expected_hash
    return observed, passed


def _validate_checks(
    root: Path,
    raw: Any,
    record_analysis_ids: set[str],
    allowed: set[Path],
    output_owners: dict[Path, frozenset[str]],
) -> tuple[list[dict[str, Any]], set[tuple[Path, str]]]:
    if not isinstance(raw, list):
        raise FinalizationError("checks JSON must contain an array")
    check_ids: set[str] = set()
    covered_output_owners: set[tuple[Path, str]] = set()
    for index, check in enumerate(raw):
        label = f"checks[{index}]"
        if not isinstance(check, dict):
            raise FinalizationError(f"{label} must be an object")
        unknown = set(check) - CHECK_KEYS
        missing = CHECK_KEYS - set(check)
        if missing or unknown:
            raise FinalizationError(
                f"{label} must contain exactly {sorted(CHECK_KEYS)}; "
                f"missing={sorted(missing)}, unknown={sorted(unknown)}"
            )
        check_id = check["check_id"]
        if not isinstance(check_id, str) or ID_RE.fullmatch(check_id) is None:
            raise FinalizationError(
                f"{label}.check_id must match ^[A-Za-z][A-Za-z0-9_.-]*$"
            )
        if check_id in check_ids:
            raise FinalizationError(f"duplicate result check_id: {check_id}")
        check_ids.add(check_id)
        if not isinstance(check["check"], str) or not check["check"].strip():
            raise FinalizationError(f"{label}.check must be a non-empty string")
        for field in ("metric", "unit"):
            if not isinstance(check[field], str) or not check[field].strip():
                raise FinalizationError(f"{label}.{field} must be a non-empty string")
        if not isinstance(check["passed"], bool):
            raise FinalizationError(f"{label}.passed must be boolean")
        analysis_ids = _nonempty_unique_strings(check["analysis_ids"], f"{label}.analysis_ids")
        if not set(analysis_ids).issubset(record_analysis_ids):
            raise FinalizationError(f"{label}.analysis_ids are not a subset of record analysis_ids")
        evidence_paths = _validate_evidence_paths(
            root, check["evidence_paths"], allowed, f"{label}.evidence_paths"
        )
        for evidence_path in evidence_paths:
            owners = output_owners.get(evidence_path)
            if owners is not None and not set(analysis_ids).issubset(owners):
                raise FinalizationError(
                    f"{label}.analysis_ids attributes output {evidence_path.relative_to(root).as_posix()} "
                    "to an analysis that does not own it"
                )
        recomputed_observed, recomputed_passed = _recompute_check(
            root, check["verification"], evidence_paths, label
        )
        expected_metric, expected_unit = _mechanical_check_identity(
            root, check["verification"], evidence_paths, label
        )
        if expected_metric is not None and check["metric"] != expected_metric:
            raise FinalizationError(
                f"{label}.metric must equal the mechanically selected TSV key or JSON Pointer"
            )
        if check["unit"] != expected_unit:
            raise FinalizationError(
                f"{label}.unit must equal selected TSV unit metadata or {expected_unit!r}"
            )
        if not _strict_json_equal(check["observed"], recomputed_observed):
            raise FinalizationError(
                f"{label}.observed does not equal the value mechanically recomputed "
                "from its verification evidence"
            )
        if check["passed"] is not recomputed_passed:
            raise FinalizationError(
                f"{label}.passed must equal the mechanically recomputed value "
                f"{recomputed_passed}; verification establishes content equality only, "
                "not scientific correctness"
            )
        if recomputed_passed:
            verification_path, _ = _project_file(
                root,
                check["verification"]["evidence_path"],
                f"{label}.verification.evidence_path",
            )
            if verification_path in output_owners:
                covered_output_owners.update(
                    (verification_path, analysis_id) for analysis_id in analysis_ids
                )
    _canonical_json_bytes(raw)
    return raw, covered_output_owners


def _json_parameter_values(value: Any, name: str) -> list[Any]:
    found: list[Any] = []
    if isinstance(value, dict):
        for key, item in value.items():
            if isinstance(key, str) and key.lower() == name.lower():
                found.append(item)
            found.extend(_json_parameter_values(item, name))
    elif isinstance(value, list):
        for item in value:
            found.extend(_json_parameter_values(item, name))
    return found


def _literal_has_terminal(text: str, length: int, *, raw_string: bool) -> bool:
    remainder = text[length:]
    if not remainder:
        return True
    if raw_string:
        return remainder[0] in ",;#}]"
    return remainder[0].isspace() or remainder[0] in ",;#}])"


def _assignment_value_matches(text: str, expected: Any) -> bool:
    candidate = text.lstrip()
    if not candidate:
        return False
    try:
        parsed, end = json.JSONDecoder(
            object_pairs_hook=_unique_object,
            parse_constant=_reject_json_constant,
        ).raw_decode(candidate)
    except (json.JSONDecodeError, FinalizationError):
        pass
    else:
        if _strict_json_equal(parsed, expected) and _literal_has_terminal(
            candidate, end, raw_string=False
        ):
            return True

    variants: list[tuple[str, bool]] = []
    try:
        variants.append((json.dumps(expected, ensure_ascii=False, allow_nan=False), False))
    except (TypeError, ValueError):
        return False
    variants.append((repr(expected), False))
    if isinstance(expected, str) and expected and not any(character.isspace() for character in expected):
        variants.append((expected, True))
    for rendered, raw_string in sorted(set(variants), key=lambda item: len(item[0]), reverse=True):
        if candidate.startswith(rendered) and _literal_has_terminal(
            candidate, len(rendered), raw_string=raw_string
        ):
            return True
    return False


def _text_parameter_pair_state(text: str, name: str, expected: Any) -> tuple[bool, bool]:
    matched = False
    conflicting = False
    stripped = text.strip()
    json_candidates = [stripped]
    json_candidates.extend(
        line.strip()
        for line in text.splitlines()
        if line.strip().startswith(("{", "[")) and line.strip().endswith(("}", "]"))
    )
    for candidate in json_candidates:
        if not candidate:
            continue
        try:
            parsed = json.loads(
                candidate,
                object_pairs_hook=_unique_object,
                parse_constant=_reject_json_constant,
            )
        except (json.JSONDecodeError, FinalizationError):
            continue
        try:
            _canonical_json_bytes(parsed)
        except FinalizationError:
            continue
        for value in _json_parameter_values(parsed, name):
            if _strict_json_equal(value, expected):
                matched = True
            else:
                conflicting = True

    key_variants = {
        re.escape(name),
        re.escape(json.dumps(name, ensure_ascii=False)),
        re.escape(repr(name)),
    }
    assignment = re.compile(
        rf"(?<![\w.-])(?:{'|'.join(sorted(key_variants, key=len, reverse=True))})"
        rf"(?![\w.-])\s*(?:=|:)\s*",
        re.IGNORECASE,
    )
    for line in text.splitlines():
        for match in assignment.finditer(line):
            if _assignment_value_matches(line[match.end() :], expected):
                matched = True
            else:
                conflicting = True
    return matched, conflicting


def _parameter_is_observed(paths: list[Path], name: str, expected: Any) -> bool:
    matched = False
    for path in paths:
        text = _read_bounded_utf8_text(path)
        if text is None:
            continue
        path_matched, path_conflicting = _text_parameter_pair_state(text, name, expected)
        if path_conflicting:
            return False
        matched = matched or path_matched
    return matched


def _validate_observed_parameters(
    root: Path, raw: Any, allowed: set[Path], record_seed: Any
) -> list[dict[str, Any]]:
    if not isinstance(raw, list):
        raise FinalizationError("observed parameters JSON must contain an array")
    names: dict[str, str] = {}
    for index, parameter in enumerate(raw):
        label = f"observed_parameters[{index}]"
        if not isinstance(parameter, dict):
            raise FinalizationError(f"{label} must be an object")
        unknown = set(parameter) - OBSERVED_PARAMETER_KEYS
        missing = OBSERVED_PARAMETER_KEYS - set(parameter)
        if missing or unknown:
            raise FinalizationError(
                f"{label} must contain exactly {sorted(OBSERVED_PARAMETER_KEYS)}; "
                f"missing={sorted(missing)}, unknown={sorted(unknown)}"
            )
        name = parameter["name"]
        if (
            not isinstance(name, str)
            or ID_RE.fullmatch(name) is None
        ):
            raise FinalizationError(
                f"{label}.name must match ^[A-Za-z][A-Za-z0-9_.-]*$"
            )
        normalized_name = name.lower()
        if normalized_name in names:
            raise FinalizationError(
                f"duplicate observed parameter name after ASCII case normalization: "
                f"{names[normalized_name]!r} and {name!r}"
            )
        names[normalized_name] = name
        if not _nonempty(parameter["value"]):
            raise FinalizationError(f"{label}.value must be non-empty")
        if normalized_name == "seed" and not _strict_json_equal(
            parameter["value"], record_seed
        ):
            raise FinalizationError(
                f"{label}.value for normalized name 'seed' must strictly equal "
                "the receipt/fragment top-level seed"
            )
        evidence_paths = _validate_evidence_paths(
            root, parameter["evidence_paths"], allowed, f"{label}.evidence_paths"
        )
        if not _parameter_is_observed(evidence_paths, name, parameter["value"]):
            raise FinalizationError(
                f"{label} name/value is not present as one unambiguous assignment or JSON pair "
                "in its referenced text output/log, or a conflicting same-name value is present"
            )
    _canonical_json_bytes(raw)
    return raw


def _validate_receipt_process(receipt: dict[str, Any]) -> tuple[str, list[str]]:
    status = receipt.get("process_status")
    if status not in {"succeeded", "failed"}:
        raise FinalizationError("receipt process_status must be 'succeeded' or 'failed'")
    exit_code = receipt.get("exit_code")
    if not isinstance(exit_code, int) or isinstance(exit_code, bool):
        raise FinalizationError("receipt exit_code must be an integer")
    missing_outputs = receipt.get("missing_outputs")
    if not isinstance(missing_outputs, list) or any(
        not isinstance(item, str) or not item.strip() for item in missing_outputs
    ):
        raise FinalizationError("receipt missing_outputs must be an array of non-empty strings")
    if len(missing_outputs) != len(set(missing_outputs)):
        raise FinalizationError("receipt missing_outputs must not contain duplicates")
    process_succeeded = exit_code == 0 and not missing_outputs
    if (status == "succeeded") != process_succeeded:
        raise FinalizationError(
            "receipt process_status is inconsistent with exit_code and missing_outputs"
        )
    return status, missing_outputs


def _validate_existing_receipt_link(
    root: Path, run_dir: Path, receipt_path: Path, fragment: dict[str, Any]
) -> None:
    linked_path, _ = _project_file(root, fragment.get("receipt_path"), "fragment receipt_path")
    if linked_path != receipt_path:
        raise FinalizationError(
            f"fragment receipt_path must be runs/{run_dir.name}/execution_receipt.json"
        )
    recorded_hash = _normalized_sha256(
        fragment.get("receipt_sha256"), "fragment receipt_sha256"
    )
    if _sha256(receipt_path) != recorded_hash:
        raise FinalizationError("receipt hash does not match fragment receipt_sha256")


def _validate_ids(
    execution_id: str,
    receipt: dict[str, Any],
    fragment: dict[str, Any],
) -> list[str]:
    if receipt.get("execution_id") != execution_id or fragment.get("execution_id") != execution_id:
        raise FinalizationError("CLI, receipt, and fragment execution ids must be identical")
    receipt_ids = _nonempty_unique_strings(receipt.get("analysis_ids"), "receipt analysis_ids")
    fragment_ids = _nonempty_unique_strings(fragment.get("analysis_ids"), "fragment analysis_ids")
    if any(ID_RE.fullmatch(value) is None for value in receipt_ids + fragment_ids):
        raise FinalizationError(
            "receipt and fragment analysis_ids must match ^[A-Za-z][A-Za-z0-9_.-]*$"
        )
    if receipt_ids != fragment_ids:
        raise FinalizationError("receipt and fragment analysis_ids must be identical and ordered alike")
    return receipt_ids


def _validated_supersedes(execution_id: str, values: list[str]) -> list[str]:
    if len(values) != len(set(values)):
        raise FinalizationError("supersedes execution ids must be unique")
    for value in values:
        if not ID_RE.fullmatch(value):
            raise FinalizationError(
                "supersedes execution id must match ^[A-Za-z][A-Za-z0-9_.-]*$"
            )
        if value == execution_id:
            raise FinalizationError("an execution cannot supersede itself")
    return values


def _finalize_locked(
    args: argparse.Namespace, root: Path, run_dir: Path
) -> dict[str, Any]:
    receipt_path = run_dir / "execution_receipt.json"
    fragment_path = run_dir / "execution_record.fragment.json"
    receipt = _load_json(receipt_path, "execution receipt")
    fragment = _load_json(fragment_path, "execution record fragment")
    if not isinstance(receipt, dict) or not isinstance(fragment, dict):
        raise FinalizationError("receipt and fragment must be JSON objects")

    _validate_existing_receipt_link(root, run_dir, receipt_path, fragment)
    _validate_receipt_metadata(receipt)
    analysis_ids = _validate_ids(args.execution_id, receipt, fragment)
    _validate_receipt_fragment_mirror(receipt, fragment)
    _validate_seed_command_binding(receipt)
    dependency_environment, _ = normalized_python_child_environment()
    _, _, dependency_errors = verify_python_dependency_versions(
        receipt.get("command_argv"),
        receipt.get("entrypoint"),
        receipt.get("dependencies"),
        root,
        dependency_environment,
    )
    if dependency_errors:
        raise FinalizationError("; ".join(dependency_errors))
    process_status, missing_outputs = _validate_receipt_process(receipt)
    if "seed" not in receipt or "seed" not in fragment:
        raise FinalizationError("receipt and fragment must both contain a top-level seed")
    if (
        receipt.get("adjudication_status") != "pending_checks"
        or fragment.get("attempt_status") != "pending_checks"
        or fragment.get("adjudication_status") != "pending_checks"
    ):
        raise FinalizationError(
            "execution is already adjudicated; preserve it and use a new execution id for another attempt"
        )
    input_paths = _validate_recorded_inputs(root, receipt)
    entrypoint = _validate_entrypoint_snapshot(root, receipt)
    _validate_code_file_closure(root, entrypoint, receipt)
    allowed_evidence_paths, output_owners = _validate_execution_artifacts(
        root, receipt, fragment, analysis_ids, missing_outputs
    )
    overlap = input_paths & allowed_evidence_paths
    if overlap:
        raise FinalizationError(
            "input and output/log artifact roles must be path-disjoint: "
            + ", ".join(sorted(path.relative_to(root).as_posix() for path in overlap))
        )

    checks, covered_output_owners = _validate_checks(
        root,
        _load_json(args.checks_json, "checks JSON"),
        set(analysis_ids),
        allowed_evidence_paths,
        output_owners,
    )
    observed_raw: Any = []
    if args.observed_parameters_json is not None:
        observed_raw = _load_json(args.observed_parameters_json, "observed parameters JSON")
    observed_parameters = _validate_observed_parameters(
        root, observed_raw, allowed_evidence_paths, receipt["seed"]
    )
    supersedes = _validated_supersedes(
        args.execution_id, list(args.supersedes_execution_id or [])
    )
    required_output_owners = {
        (path, analysis_id)
        for path, owners in output_owners.items()
        for analysis_id in owners
    }

    succeeded = (
        process_status == "succeeded"
        and missing_outputs == []
        and bool(checks)
        and all(check["passed"] for check in checks)
        and required_output_owners.issubset(covered_output_owners)
    )
    adjudication_status = "succeeded" if succeeded else "failed"
    adjudicated_at = _utc_now()
    checks_sha256 = _canonical_sha256(checks)
    observed_parameters_sha256 = _canonical_sha256(observed_parameters)

    receipt.update(
        {
            "checks": checks,
            "observed_parameters": observed_parameters,
            "checks_sha256": checks_sha256,
            "observed_parameters_sha256": observed_parameters_sha256,
            "adjudication_status": adjudication_status,
            "adjudicated_at_utc": adjudicated_at,
            "supersedes_execution_ids": supersedes,
        }
    )
    fragment.update(
        {
            "attempt_status": adjudication_status,
            "adjudication_status": adjudication_status,
            "checks": checks,
            "observed_parameters": observed_parameters,
            "checks_sha256": checks_sha256,
            "observed_parameters_sha256": observed_parameters_sha256,
            "adjudicated_at_utc": adjudicated_at,
            "supersedes_execution_ids": supersedes,
        }
    )

    _atomic_write_json(receipt_path, receipt)
    receipt_sha256 = _sha256(receipt_path)
    fragment["receipt_sha256"] = receipt_sha256
    _atomic_write_json(fragment_path, fragment)
    return {
        "execution_id": args.execution_id,
        "attempt_status": adjudication_status,
        "adjudicated_at_utc": adjudicated_at,
        "checks_sha256": checks_sha256,
        "observed_parameters_sha256": observed_parameters_sha256,
        "receipt_path": receipt_path.relative_to(root).as_posix(),
        "receipt_sha256": receipt_sha256,
        "execution_record_fragment": fragment_path.relative_to(root).as_posix(),
    }


def _finalize(args: argparse.Namespace) -> dict[str, Any]:
    if not ID_RE.fullmatch(args.execution_id):
        raise FinalizationError("execution id must match ^[A-Za-z][A-Za-z0-9_.-]*$")
    root = args.project_dir.resolve(strict=True)
    if not root.is_dir():
        raise FinalizationError(f"project directory is not a directory: {root}")

    runs_dir = root / "runs"
    run_dir = runs_dir / args.execution_id
    if not runs_dir.is_dir() or not run_dir.is_dir():
        raise FinalizationError(f"run directory does not exist: runs/{args.execution_id}")
    expected_run_dir = run_dir.absolute()
    resolved_run_dir = run_dir.resolve(strict=True)
    if resolved_run_dir != expected_run_dir or runs_dir.is_symlink() or run_dir.is_symlink():
        raise FinalizationError(
            f"run directory must be the physical project path runs/{args.execution_id}"
        )

    with _exclusive_run_lock(run_dir / LOCK_FILENAME, args.execution_id):
        return _finalize_locked(args, root, run_dir)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project-dir", type=Path, required=True)
    parser.add_argument("--execution-id", required=True)
    parser.add_argument("--checks-json", type=Path, required=True)
    parser.add_argument("--observed-parameters-json", type=Path)
    parser.add_argument("--supersedes-execution-id", action="append", default=[])
    return parser


def main() -> int:
    args = _parser().parse_args()
    try:
        result = _finalize(args)
    except (FinalizationError, OSError) as exc:
        print(f"finalization error: {exc}", file=sys.stderr)
        return 2
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
