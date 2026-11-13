#!/usr/bin/env python3
"""Run one reconstruction attempt in a fresh directory and emit a receipt.

The wrapper is intentionally small and standard-library-only.  It never invokes
a shell, never reuses an existing run directory, fingerprints declared inputs,
captures both output streams, and fingerprints declared outputs after the child
process exits.  The resulting receipt is evidence of a locally observed process;
it is not a scientific-validity certificate or a cryptographic attestation.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shlex
import shutil
import subprocess
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from execution_contract import (
    argv_seed_bindings,
    dependency_contract_errors,
    normalized_python_child_environment,
    python_local_import_closure,
    verify_python_dependency_versions,
)


PRODUCER = "dev-reconstruct-bioinfo-protocol/run_reconstruction.py"
PRODUCER_VERSION = "1.0.0"
ID_RE = re.compile(r"^[A-Za-z][A-Za-z0-9_.-]*$")
UNKNOWN_VERSIONS = {"", "unknown", "unreported", "missing", "latest", "any", "*"}
def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _relative_file(root: Path, value: str, *, must_exist: bool) -> Path:
    candidate = Path(value)
    if candidate.is_absolute():
        raise ValueError(f"path must be project-relative: {value}")
    resolved = (root / candidate).resolve()
    try:
        resolved.relative_to(root)
    except ValueError as exc:
        raise ValueError(f"path escapes project directory: {value}") from exc
    if must_exist and not resolved.is_file():
        raise ValueError(f"required file does not exist: {value}")
    return resolved


def _artifact_spec(raw: str) -> dict[str, Any]:
    try:
        value = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise argparse.ArgumentTypeError(f"artifact spec is not JSON: {exc}") from exc
    if not isinstance(value, dict):
        raise argparse.ArgumentTypeError("artifact spec must be a JSON object")
    required = ("artifact_id", "path", "semantic_type")
    result: dict[str, Any] = {
        key: str(value.get(key, "")).strip() for key in required
    }
    if any(not result[key] for key in required):
        raise argparse.ArgumentTypeError(
            "artifact spec requires non-empty artifact_id, path, and semantic_type"
        )
    if "analysis_ids" in value:
        analysis_ids = value["analysis_ids"]
        if (
            not isinstance(analysis_ids, list)
            or not analysis_ids
            or any(not isinstance(item, str) or not item.strip() for item in analysis_ids)
            or len(analysis_ids) != len(set(analysis_ids))
        ):
            raise argparse.ArgumentTypeError(
                "artifact spec analysis_ids must be a non-empty array of unique strings"
            )
        result["analysis_ids"] = analysis_ids
    return result


def _dependency(raw: str) -> dict[str, str]:
    name, separator, version = raw.partition("=")
    name = name.strip()
    version = version.strip()
    if not separator or not name or version.lower() in UNKNOWN_VERSIONS:
        raise argparse.ArgumentTypeError("dependency must be NAME=CONCRETE_VERSION")
    dependency = {"name": name, "version": version}
    errors = dependency_contract_errors([dependency])
    if errors:
        raise argparse.ArgumentTypeError(errors[0])
    return dependency


def _seed(raw: str) -> int | str:
    if raw == "not_applicable":
        return raw
    try:
        return int(raw)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("seed must be an integer or not_applicable") from exc


def _command_display(argv: list[str]) -> str:
    return subprocess.list2cmdline(argv) if os.name == "nt" else shlex.join(argv)


def _canonical_sha256(value: Any) -> str:
    payload = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _argv_executes_entrypoint(argv: list[str], entrypoint: str) -> bool:
    """Reject launcher options that can consume or bypass the entrypoint token."""
    if entrypoint not in argv:
        return False
    index = argv.index(entrypoint)
    suffix = Path(entrypoint).suffix.lower()
    launcher = Path(argv[0]).name.lower() if argv else ""
    launchers = {
        ".py": {"python", "python.exe", "python3", "python3.exe", "py", "py.exe"},
        ".r": {"r", "r.exe", "rscript", "rscript.exe"},
        ".jl": {"julia", "julia.exe"},
        ".sh": {"sh", "bash", "zsh"},
        ".ipynb": {"jupyter", "jupyter.exe", "jupyter-nbconvert", "jupyter-nbconvert.exe"},
    }
    allowed = launchers.get(suffix)
    if allowed is None:
        return index == 0
    if launcher not in allowed or index < 1:
        return False
    prefix_options = argv[1:index]
    if suffix == ".py":
        safe_flags = {"-B", "-E", "-O", "-OO", "-q", "-s", "-S", "-u", "-v"}
        if launcher in {"py", "py.exe"}:
            return all(re.fullmatch(r"-[1-9](?:\.\d+)?(?:-\d+)?", token) or token in safe_flags for token in prefix_options)
        return all(token in safe_flags for token in prefix_options)
    return not prefix_options


def _write_json(path: Path, value: Any) -> None:
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project-dir", type=Path, required=True)
    parser.add_argument("--execution-id", required=True)
    parser.add_argument("--analysis-id", action="append", required=True)
    parser.add_argument("--entrypoint", required=True)
    parser.add_argument("--code-evidence-ref", action="append", required=True)
    parser.add_argument("--input-spec", action="append", type=_artifact_spec, required=True)
    parser.add_argument("--output-spec", action="append", type=_artifact_spec, required=True)
    parser.add_argument("--dependency", action="append", type=_dependency, required=True)
    parser.add_argument("--seed", type=_seed, required=True)
    parser.add_argument("--seed-reason")
    parser.add_argument(
        "--authorization-basis",
        choices=("explicit_execution_request",),
        default="explicit_execution_request",
    )
    parser.add_argument("--environment", choices=("existing", "isolated"), default="existing")
    parser.add_argument("--network-used", action="store_true")
    parser.add_argument(
        "--code-provenance",
        choices=("source_exact", "source_adapted", "generated_guidance"),
        default="source_exact",
    )
    parser.add_argument("command", nargs=argparse.REMAINDER)
    return parser


def main() -> int:
    args = _parser().parse_args()
    root = args.project_dir.resolve()
    if not root.is_dir():
        raise SystemExit(f"project directory does not exist: {root}")
    if not ID_RE.fullmatch(args.execution_id):
        raise SystemExit("execution id must match ^[A-Za-z][A-Za-z0-9_.-]*$")
    if any(ID_RE.fullmatch(value) is None for value in args.analysis_id):
        raise SystemExit("analysis ids must match ^[A-Za-z][A-Za-z0-9_.-]*$")
    if len(args.analysis_id) != len(set(args.analysis_id)):
        raise SystemExit("analysis ids must be unique")
    if len(args.code_evidence_ref) != len(set(args.code_evidence_ref)):
        raise SystemExit("code evidence refs must be unique")
    if args.seed == "not_applicable" and not str(args.seed_reason or "").strip():
        raise SystemExit("not_applicable seed requires --seed-reason")

    command = list(args.command)
    if command and command[0] == "--":
        command.pop(0)
    if len(command) < 2 or any(not str(token) for token in command):
        raise SystemExit("a non-shell command with at least two argv tokens is required after --")
    launcher = command[0]
    if Path(launcher).is_absolute() or any(separator in launcher for separator in ("/", "\\")):
        if not Path(launcher).is_file():
            raise SystemExit(f"command launcher does not exist: {launcher}")
    elif shutil.which(launcher) is None:
        raise SystemExit(f"command launcher is not available on PATH: {launcher}")

    entrypoint = _relative_file(root, args.entrypoint, must_exist=True)
    if not _argv_executes_entrypoint(command, args.entrypoint):
        raise SystemExit(
            "command argv must execute the declared entrypoint with a compatible launcher"
        )
    code_closure, code_closure_gaps = python_local_import_closure(root, entrypoint)
    if code_closure_gaps:
        raise SystemExit(
            "local code import closure cannot be fingerprinted: "
            + "; ".join(code_closure_gaps)
        )
    code_files = [
        {
            "path": path.relative_to(root).as_posix(),
            "sha256": _sha256(path),
        }
        for path in code_closure
    ]

    dependency_errors = dependency_contract_errors(args.dependency)
    if dependency_errors:
        raise SystemExit("; ".join(dependency_errors))
    child_environment, normalized_python_environment = (
        normalized_python_child_environment()
    )
    verified_dependencies, python_runtime, dependency_probe_errors = (
        verify_python_dependency_versions(
            command,
            args.entrypoint,
            args.dependency,
            root,
            child_environment,
        )
    )
    if dependency_probe_errors:
        raise SystemExit("; ".join(dependency_probe_errors))

    run_relative = Path("runs") / args.execution_id
    run_dir = (root / run_relative).resolve()
    if run_dir.exists():
        raise SystemExit(f"refusing to reuse existing run directory: {run_relative.as_posix()}")
    run_dir.parent.mkdir(parents=True, exist_ok=True)
    run_dir.mkdir()

    try:
        inputs: list[dict[str, Any]] = []
        artifact_ids: set[str] = set()
        artifact_paths: set[str] = set()
        for spec in args.input_spec:
            if "analysis_ids" in spec:
                raise ValueError("input artifact specs must not contain analysis_ids")
            if spec["artifact_id"] in artifact_ids or spec["path"] in artifact_paths:
                raise ValueError("input artifact ids and paths must be unique")
            artifact_ids.add(spec["artifact_id"])
            artifact_paths.add(spec["path"])
            path = _relative_file(root, spec["path"], must_exist=True)
            try:
                path.relative_to(run_dir)
            except ValueError:
                pass
            else:
                raise ValueError(f"input must remain outside the new run directory: {spec['path']}")
            if spec["path"] not in command:
                raise ValueError(f"command argv does not name declared input: {spec['path']}")
            inputs.append({**spec, "sha256": _sha256(path)})

        expected_outputs: list[dict[str, Any]] = []
        record_analysis_ids = set(args.analysis_id)
        owned_analysis_ids: set[str] = set()
        for spec in args.output_spec:
            if spec["artifact_id"] in artifact_ids or spec["path"] in artifact_paths:
                raise ValueError("input/output artifact ids and paths must be globally unique")
            artifact_ids.add(spec["artifact_id"])
            artifact_paths.add(spec["path"])
            path = _relative_file(root, spec["path"], must_exist=False)
            try:
                path.relative_to(run_dir)
            except ValueError as exc:
                raise ValueError(f"output must be inside {run_relative.as_posix()}: {spec['path']}") from exc
            if "analysis_ids" not in spec:
                if len(args.analysis_id) != 1:
                    raise ValueError(
                        "multi-analysis output specs must contain non-empty analysis_ids ownership"
                    )
                owners = list(args.analysis_id)
            else:
                owners = list(spec["analysis_ids"])
            unknown_owners = set(owners) - record_analysis_ids
            if unknown_owners:
                raise ValueError(
                    "output artifact analysis_ids must be a subset of the execution analysis ids: "
                    + ", ".join(sorted(unknown_owners))
                )
            owned_analysis_ids.update(owners)
            expected_outputs.append({**spec, "analysis_ids": owners})

        unowned_analysis_ids = record_analysis_ids - owned_analysis_ids
        if unowned_analysis_ids:
            raise ValueError(
                "every execution analysis id must own at least one declared output: "
                + ", ".join(sorted(unowned_analysis_ids))
            )

        output_tokens = {spec["path"] for spec in expected_outputs}
        output_tokens.add(run_relative.as_posix())
        output_tokens.add(str(run_relative))
        if not any(token in command for token in output_tokens):
            raise ValueError("command argv must name the run directory or a declared output path")
        command_seed_values, malformed_seed_option = argv_seed_bindings(
            command, args.entrypoint
        )
        if malformed_seed_option:
            raise ValueError("command argv contains an invalid or ambiguous seed-like option")
        if args.seed == "not_applicable" and command_seed_values:
            raise ValueError(
                "not_applicable seed conflicts with an explicit seed option in command argv"
            )
        if isinstance(args.seed, int):
            if not command_seed_values:
                raise ValueError(
                    "command argv must bind the declared random seed through a canonical long option"
                )
            if any(value != str(args.seed) for value in command_seed_values):
                raise ValueError("explicit command argv seed option conflicts with declared seed")
    except ValueError as exc:
        try:
            run_dir.rmdir()
        except OSError:
            pass
        raise SystemExit(str(exc)) from exc

    stdout_path = run_dir / "stdout.log"
    stderr_path = run_dir / "stderr.log"
    started = _utc_now()
    nonce = uuid.uuid4().hex
    process = subprocess.Popen(
        command,
        cwd=root,
        env=child_environment,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        shell=False,
    )
    stdout_bytes, stderr_bytes = process.communicate()
    finished = _utc_now()
    stdout_path.write_text(stdout_bytes.decode("utf-8", errors="replace"), encoding="utf-8")
    stderr_path.write_text(stderr_bytes.decode("utf-8", errors="replace"), encoding="utf-8")

    outputs: list[dict[str, Any]] = []
    missing_outputs: list[str] = []
    for spec in expected_outputs:
        path = _relative_file(root, spec["path"], must_exist=False)
        if path.is_file():
            outputs.append({**spec, "sha256": _sha256(path)})
        else:
            missing_outputs.append(spec["path"])
    process_status = "succeeded" if process.returncode == 0 and not missing_outputs else "failed"
    attempt_status = "pending_checks" if process_status == "succeeded" else "failed"
    checks: list[dict[str, Any]] = []
    observed_parameters: list[dict[str, Any]] = []
    preflight = {
        "authorization_basis": args.authorization_basis,
        "status": "passed",
        "source_read_only": True,
        "output_directory": run_relative.as_posix(),
        "environment": args.environment,
        "network_used": bool(args.network_used),
        "notes": [
            "Fresh run directory created by the reconstruction execution wrapper.",
            *(
                [
                    "Removed import-affecting Python environment variables from the child process: "
                    + ", ".join(normalized_python_environment)
                ]
                if normalized_python_environment
                else []
            ),
            "Observed dependency versions through the exact child Python launcher before execution: "
            + ", ".join(
                f"{item['name']}={item['version']}" for item in verified_dependencies
            )
            + f" ({python_runtime['implementation']} {python_runtime['python_version']}).",
        ],
    }
    receipt = {
        "receipt_schema_version": "1.0.0",
        "producer": PRODUCER,
        "producer_version": PRODUCER_VERSION,
        "execution_id": args.execution_id,
        "nonce": nonce,
        "process_id": process.pid,
        "analysis_ids": args.analysis_id,
        "command": _command_display(command),
        "command_argv": command,
        "entrypoint": args.entrypoint,
        "code_evidence_refs": args.code_evidence_ref,
        "code_snapshot_sha256": _sha256(entrypoint),
        "code_files": code_files,
        "working_directory": ".",
        "started_at_utc": started,
        "finished_at_utc": finished,
        "exit_code": process.returncode,
        "process_status": process_status,
        "dependencies": verified_dependencies,
        "seed": args.seed,
        "inputs": inputs,
        "expected_outputs": expected_outputs,
        "outputs": outputs,
        "missing_outputs": missing_outputs,
        "stdout_log": (run_relative / "stdout.log").as_posix(),
        "stderr_log": (run_relative / "stderr.log").as_posix(),
        "stdout_sha256": _sha256(stdout_path),
        "stderr_sha256": _sha256(stderr_path),
        "checks": checks,
        "checks_sha256": _canonical_sha256(checks),
        "observed_parameters": observed_parameters,
        "observed_parameters_sha256": _canonical_sha256(observed_parameters),
        "adjudication_status": attempt_status,
        "adjudicated_at_utc": finished if attempt_status == "failed" else None,
        "supersedes_execution_ids": [],
        "preflight": preflight,
        "code_provenance": args.code_provenance,
    }
    if args.seed_reason:
        receipt["seed_reason"] = args.seed_reason
    receipt_path = run_dir / "execution_receipt.json"
    _write_json(receipt_path, receipt)
    receipt_sha256 = _sha256(receipt_path)

    fragment = {
        key: receipt[key]
        for key in (
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
            "inputs",
            "outputs",
            "stdout_log",
            "stderr_log",
            "preflight",
            "code_provenance",
        )
    }
    if args.seed_reason:
        fragment["seed_reason"] = args.seed_reason
    fragment.update(
        {
            "attempt_status": attempt_status,
            "checks": checks,
            "checks_sha256": receipt["checks_sha256"],
            "observed_parameters": observed_parameters,
            "observed_parameters_sha256": receipt["observed_parameters_sha256"],
            "adjudication_status": attempt_status,
            "adjudicated_at_utc": receipt["adjudicated_at_utc"],
            "receipt_path": (run_relative / "execution_receipt.json").as_posix(),
            "receipt_sha256": receipt_sha256,
            "supersedes_execution_ids": [],
        }
    )
    fragment_path = run_dir / "execution_record.fragment.json"
    _write_json(fragment_path, fragment)
    print(
        json.dumps(
            {
                "attempt_status": attempt_status,
                "execution_record_fragment": fragment_path.relative_to(root).as_posix(),
                "receipt_path": receipt_path.relative_to(root).as_posix(),
                "receipt_sha256": receipt_sha256,
            },
            ensure_ascii=False,
        )
    )
    return 0 if process_status == "succeeded" else (process.returncode or 2)


if __name__ == "__main__":
    raise SystemExit(main())
