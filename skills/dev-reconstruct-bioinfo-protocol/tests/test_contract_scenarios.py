from __future__ import annotations

import csv
import copy
import hashlib
import importlib.util
import json
import subprocess
import sys
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable


SKILL_ROOT = Path(__file__).resolve().parents[1]
VALIDATOR_PATH = SKILL_ROOT / "scripts" / "validate_reconstruction.py"
RUNNER_PATH = SKILL_ROOT / "scripts" / "run_reconstruction.py"
FINALIZER_PATH = SKILL_ROOT / "scripts" / "finalize_execution.py"
SPEC = importlib.util.spec_from_file_location("reconstruction_validator", VALIDATOR_PATH)
assert SPEC and SPEC.loader
VALIDATOR = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(VALIDATOR)
FINALIZER_SPEC = importlib.util.spec_from_file_location("reconstruction_finalizer", FINALIZER_PATH)
assert FINALIZER_SPEC and FINALIZER_SPEC.loader
FINALIZER = importlib.util.module_from_spec(FINALIZER_SPEC)
FINALIZER_SPEC.loader.exec_module(FINALIZER)

HASH_PLACEHOLDER = "0" * 64


SOURCE_CONTENT = {
    "paper.md": (
        "# Results\n\nFigure 1A reports a difference between the two measured groups.\n"
    ),
    "figure1.txt": "Fig1A caption: group A and group B sample-level summaries.\n",
    "methods.md": (
        "# Methods\n\nUse independent samples as the statistical unit and alpha=0.05.\n"
    ),
    "code/analysis.py": """from __future__ import annotations

import argparse
import csv
from pathlib import Path

ALPHA = 0.05

parser = argparse.ArgumentParser()
parser.add_argument("--input", type=Path, required=True)
parser.add_argument("--output-dir", type=Path, required=True)
parser.add_argument("--seed", type=int, required=True)
parser.add_argument("--alpha", type=float, default=ALPHA)
args = parser.parse_args()

with args.input.open(encoding="utf-8", newline="") as handle:
    rows = list(csv.DictReader(handle, delimiter="\\t"))
means = {}
for group in sorted({row["group"] for row in rows}):
    values = [float(row["value"]) for row in rows if row["group"] == group]
    means[group] = sum(values) / len(values)
difference = means["B"] - means["A"]
args.output_dir.mkdir(parents=True, exist_ok=True)
output = args.output_dir / "group_test.tsv"
output.write_text(
    f"metric\\tvalue\\tunit\\nmean_difference_B_minus_A\\t{difference:.1f}\\tdimensionless\\n",
    encoding="utf-8",
)
print(f"seed={args.seed}; alpha={args.alpha}; output={output}; difference={difference:.1f}")
print('{"json_seed": 7}')
print("check_passed=True")
""",
    "code/pkg/__init__.py": "",
    "code/pkg/main.py": "import helper\nvalue = helper.value\n",
    "code/helper.py": "value = 'local helper'\n",
    "data/input.tsv": "sample\tgroup\tvalue\nS1\tA\t1\nS2\tA\t2\nS3\tB\t4\nS4\tB\t5\n",
}


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _rewrite_receipt(
    root: Path, record: dict, mutate: Callable[[dict], None]
) -> dict:
    receipt_path = root / record["receipt_path"]
    receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    mutate(receipt)
    receipt_path.write_text(
        json.dumps(receipt, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    record["receipt_sha256"] = _sha256(receipt_path)
    return receipt


def _source(source_id: str, roles: list[str], location: str) -> dict:
    return {
        "source_id": source_id,
        "roles": roles,
        "location": location,
        "availability": "available",
        "fingerprint": f"sha256:{HASH_PLACEHOLDER}",
        "locator_type": "mixed",
        "limitations": [],
    }


def _evidence(evidence_id: str, lane: str, source_id: str, locator: str, summary: str) -> dict:
    return {
        "evidence_id": evidence_id,
        "lane": lane,
        "source_id": source_id,
        "locator": locator,
        "evidence_class": "直接证据",
        "summary": summary,
    }


def _stages() -> list[dict]:
    return [
        {
            "stage": name,
            "status": "completed",
            "input_fingerprint": f"sha256:{HASH_PLACEHOLDER}",
            "artifacts": ["contract-fixture"],
            "blockers": [],
        }
        for name in VALIDATOR.STAGE_ORDER
    ]


def _audit(evidence_refs: list[str] | None = None) -> list[dict]:
    refs_by_topic = {
        "preprocessing": ["E_METHOD", "E_CODE", "IN001"],
        "statistical_unit": ["E_METHOD", "IN001"],
        "replication_pseudoreplication": ["E_METHOD", "IN001"],
        "batch_confounding": ["E_METHOD", "IN001"],
        "multiple_testing": ["E_METHOD", "E_CODE"],
        "species_gene_ids": ["E_METHOD", "IN001"],
        "parameter_consistency": evidence_refs or ["E_METHOD", "E_CODE"],
        "claim_strength": ["E_CLAIM", "E_FIG", "E_METHOD"],
    }
    return [
        {
            "topic": topic,
            "status": "passed",
            "finding": f"Synthetic contract fixture records {topic} explicitly.",
            "evidence_refs": refs_by_topic[topic],
            "claim_ceiling": "association",
        }
        for topic in sorted(VALIDATOR.CORE_AUDIT_TOPICS)
    ]


def _statement(
    text: str,
    *evidence_refs: str,
    quantitative_claims: list[dict] | None = None,
) -> dict:
    return {
        "statement": text,
        "evidence_refs": list(evidence_refs),
        "quantitative_claims": copy.deepcopy(quantitative_claims or []),
    }


def _quantitative_claim_text(claim: dict) -> str:
    binding = claim["binding"]
    kind = binding["kind"]
    if kind == "result_check":
        binding_text = f"result_check:{binding['execution_id']}/{binding['check_id']}"
    elif kind == "source_excerpt":
        binding_text = f"source_excerpt:{binding['source_id']}@{binding['locator']}"
    else:
        binding_text = f"parameter:{binding['name']}@{binding['value_status']}"
    value_text = json.dumps(
        claim["value"], ensure_ascii=False, sort_keys=True, separators=(",", ":")
    )
    return (
        f"{claim['metric']}={value_text} {claim['unit']} "
        f"[evidence: {claim['evidence_ref']}; binding: {binding_text}]"
    )


def _group_result_verification(execution_id: str = "RUN_OK", expected: str = "3.0") -> dict:
    return {
        "kind": "tsv_cell_equals",
        "evidence_path": f"runs/{execution_id}/group_test.tsv",
        "selector": {
            "key_column": "metric",
            "key_value": "mean_difference_B_minus_A",
            "value_column": "value",
            "unit_column": "unit",
        },
        "expected": expected,
    }


def _canonical_report(manifest: dict) -> str:
    lines = ["# Reconstruction report", "", "## Status"]
    lines.extend(
        f"- {analysis['analysis_id']}: {analysis['reproduction_status']}"
        for analysis in manifest["analyses"]
    )
    sections = (
        ("Direct evidence/observation", "direct_observation"),
        ("Paper claim", "paper_claim"),
        ("Reconstructed support", "reconstructed_support"),
        ("Reasonable inference", "reasonable_inference"),
        ("Unverified", "unverified"),
    )
    for heading, key in sections:
        lines.extend(["", f"## {heading}"])
        section_lines = []
        for analysis in manifest["analyses"]:
            analysis_id = analysis["analysis_id"]
            for statement in analysis["interpretation"][key]:
                references = ", ".join(statement["evidence_refs"])
                quantitative = statement.get("quantitative_claims", [])
                quantitative_text = ""
                if quantitative:
                    quantitative_text = " [quantitative: " + " | ".join(
                        _quantitative_claim_text(claim) for claim in quantitative
                    ) + "]"
                section_lines.append(
                    f"- {analysis_id}: {statement['statement']}{quantitative_text} "
                    f"[evidence: {references}]"
                )
        lines.extend(section_lines or ["- none"])
    lines.extend(["", "## Conflicts or gaps"])
    issue_lines = []
    for analysis in manifest["analyses"]:
        analysis_id = analysis["analysis_id"]
        for issue in analysis["conflicts_gaps"]:
            references = ", ".join(issue["evidence_refs"])
            issue_lines.append(
                f"- {analysis_id}/{issue['issue_id']} ({issue['kind']}): "
                f"{issue['description']} [evidence: {references}]"
            )
    lines.extend(issue_lines or ["- none"])
    return "\n".join(lines) + "\n"


def base_manifest() -> dict:
    sources = [
        _source("SRC001", ["main_text", "results_text"], "paper.md"),
        _source("SRC002", ["figure_visual", "figure_caption"], "figure1.txt"),
        _source("SRC003", ["methods_text", "supplement_text"], "methods.md"),
        _source("SRC004", ["code", "environment"], "code/analysis.py"),
        _source("SRC005", ["input_data"], "data/input.tsv"),
    ]
    analysis = {
        "analysis_id": "A001",
        "modality": "synthetic_expression",
        "paper_claim": {
            "summary": "The reported groups differ in the measured feature.",
            "evidence": [
                _evidence(
                    "E_CLAIM",
                    "paper_claim",
                    "SRC001",
                    "Results:L3",
                    "Reported group difference",
                )
            ],
        },
        "figure_panel": {
            "ids": ["Fig1A"],
            "source_mode": "visual_plus_caption",
            "display_summary": "Two group summaries are displayed.",
            "evidence": [
                _evidence(
                    "E_FIG",
                    "figure",
                    "SRC002",
                    "Fig1A:caption+panel",
                    "Displayed group summaries",
                )
            ],
        },
        "method_parameters": {
            "summary": "A sample-level two-group comparison uses alpha 0.05.",
            "evidence": [
                _evidence(
                    "E_METHOD",
                    "method",
                    "SRC003",
                    "Methods:L3",
                    "Declared unit and alpha",
                )
            ],
            "parameters": [
                {
                    "name": "alpha",
                    "value": 0.05,
                    "value_status": "reported",
                    "evidence_refs": ["E_METHOD"],
                },
                {
                    "name": "alpha",
                    "value": 0.05,
                    "value_status": "implemented",
                    "evidence_refs": ["E_CODE"],
                    "implementation_literal": "ALPHA = 0.05",
                }
            ],
        },
        "code_locations": [
            {
                "evidence_id": "E_CODE",
                "source_id": "SRC004",
                "snapshot": f"sha256:{HASH_PLACEHOLDER}",
                "path": "code/analysis.py",
                "locator": "L1-L24",
                "scope": "upstream_analysis",
                "evidence_status": "active_call",
            }
        ],
        "code_guidance": None,
        "inputs_outputs": {
            "inputs": [
                {
                    "artifact_id": "IN001",
                    "path": "data/input.tsv",
                    "semantic_type": "sample-level measurements",
                    "fingerprint": f"sha256:{HASH_PLACEHOLDER}",
                }
            ],
            "outputs": [
                {
                    "artifact_id": "OUT001",
                    "path": "results/group_test.tsv",
                    "semantic_type": "expected group comparison table",
                    "fingerprint": None,
                }
            ],
        },
        "execution_record_ids": [],
        "scientific_audit": _audit(),
        "interpretation": {
            "direct_observation": [
                _statement("The synthetic panel displays the group summaries.", "E_FIG")
            ],
            "paper_claim": [
                _statement("The fixture paper claims a group difference.", "E_CLAIM")
            ],
            "reconstructed_support": [
                _statement(
                    "Methods and active code specify compatible sample-level group calculations.",
                    "E_METHOD",
                    "E_CODE",
                )
            ],
            "reasonable_inference": [],
            "unverified": [
                _statement(
                    "No qualifying execution record is linked; active-code behavior remains unverified.",
                    "E_CODE",
                )
            ],
        },
        "conflicts_gaps": [],
        "reproduction_status": "材料完整但未执行",
    }
    return {
        "schema_version": "1.0.0",
        "project_id": "contract-fixture",
        "task": {
            "mode": "reproduction_audit",
            "request": "Validate the reconstruction contract fixture.",
            "execution_requested": False,
            "execution_scope": "none",
            "target_ids": ["Fig1A"],
        },
        "sources": sources,
        "stage_state": _stages(),
        "analyses": [analysis],
        "execution_records": [],
        "overall_status": "材料完整但未执行",
    }


def _materialize_sources(root: Path, manifest: dict) -> None:
    for source in manifest["sources"]:
        if source["availability"] != "available":
            continue
        relative = source["location"]
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(SOURCE_CONTENT[relative], encoding="utf-8")
        source["fingerprint"] = f"sha256:{_sha256(path)}"

    analysis = manifest["analyses"][0]
    input_path = root / "data/input.tsv"
    if input_path.is_file():
        analysis["inputs_outputs"]["inputs"][0]["fingerprint"] = f"sha256:{_sha256(input_path)}"
    code_path = root / "code/analysis.py"
    if code_path.is_file() and analysis["code_locations"]:
        analysis["code_locations"][0]["snapshot"] = f"sha256:{_sha256(code_path)}"
    source_fingerprint = VALIDATOR._source_set_fingerprint(manifest["sources"])
    for stage in manifest["stage_state"]:
        stage["input_fingerprint"] = source_fingerprint


def trace_row(manifest: dict, analysis_index: int = 0) -> dict:
    analysis = manifest["analyses"][analysis_index]
    paper_tokens = [analysis["paper_claim"]["summary"]]
    for item in analysis["paper_claim"]["evidence"]:
        paper_tokens.extend([item["evidence_id"], item["locator"]])

    figure_tokens = list(analysis["figure_panel"]["ids"])
    figure_tokens.append(analysis["figure_panel"]["display_summary"])
    for item in analysis["figure_panel"]["evidence"]:
        figure_tokens.extend([item["evidence_id"], item["locator"]])

    method_tokens = [analysis["method_parameters"]["summary"]]
    for item in analysis["method_parameters"]["evidence"]:
        method_tokens.extend([item["evidence_id"], item["locator"]])
    for parameter in analysis["method_parameters"]["parameters"]:
        text = (
            f"{parameter['name']}={parameter['value']} ({parameter['value_status']}; "
            f"evidence={','.join(parameter['evidence_refs'])})"
        )
        if parameter.get("implementation_literal"):
            text += f" literal={parameter['implementation_literal']}"
        if parameter.get("execution_record_refs"):
            text += " execution=" + ",".join(parameter["execution_record_refs"])
        method_tokens.append(text)

    if analysis["code_locations"]:
        code_tokens = [
            " ".join(
                str(value)
                for value in (
                    item["evidence_id"],
                    item["snapshot"],
                    item["path"],
                    item["locator"],
                    item["scope"],
                    item["evidence_status"],
                )
            )
            for item in analysis["code_locations"]
        ]
    else:
        code_tokens = ["未提供/未找到代码"]

    io_tokens = []
    for direction in ("inputs", "outputs"):
        for artifact in analysis["inputs_outputs"][direction]:
            fingerprint = artifact.get("fingerprint") or "fingerprint=missing"
            io_tokens.append(
                f"{artifact['artifact_id']} {artifact['path']} ({artifact['semantic_type']}) {fingerprint}"
            )

    if analysis["conflicts_gaps"]:
        issue_tokens = []
        for issue in analysis["conflicts_gaps"]:
            text = (
                f"{issue['issue_id']}: {issue['description']} | impact={issue['impact']} | evidence="
                + ",".join(issue["evidence_refs"])
            )
            if issue.get("resolved"):
                text += " | resolution=" + str(issue.get("resolution"))
                text += " | resolution_evidence=" + ",".join(issue.get("resolution_evidence_refs", []))
            issue_tokens.append(text)
    else:
        issue_tokens = ["无已知冲突或阻塞缺口"]

    return {
        "analysis_id": analysis["analysis_id"],
        "正文主张": "; ".join(paper_tokens),
        "figure/panel": "; ".join(figure_tokens),
        "method与参数": "; ".join(method_tokens),
        "code位置": "; ".join(code_tokens),
        "输入/输出": " -> ".join(io_tokens),
        "复现状态": analysis["reproduction_status"],
        "冲突或缺口": "; ".join(issue_tokens),
    }


def _write_project(root: Path, manifest: dict, row: dict | list[dict], report: str) -> None:
    (root / "reconstruction_manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    (root / "source_inventory.json").write_text(
        json.dumps(
            {
                "schema_version": "1.0.0",
                "project_id": manifest["project_id"],
                "sources": manifest["sources"],
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    blockers = sorted(
        {
            blocker
            for stage in manifest["stage_state"]
            for blocker in stage.get("blockers", [])
        }
    )
    (root / "working_state.json").write_text(
        json.dumps(
            {
                "schema_version": "1.0.0",
                "project_id": manifest["project_id"],
                "input_fingerprint": VALIDATOR._source_set_fingerprint(manifest["sources"]),
                "stages": manifest["stage_state"],
                "completed_artifacts": [
                    "source_inventory.json",
                    "working_state.json",
                    "reconstruction_manifest.json",
                    "traceability.tsv",
                    "REPORT.md",
                ],
                "invalidations": [],
                "blockers": blockers,
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    with (root / "traceability.tsv").open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=VALIDATOR.TRACE_HEADER,
            delimiter="\t",
            lineterminator="\n",
        )
        writer.writeheader()
        writer.writerows(row if isinstance(row, list) else [row])
    (root / "REPORT.md").write_text(report, encoding="utf-8")


def _run_successful_fixture(
    root: Path,
    manifest: dict,
    supersedes: list[str] | None = None,
    execution_analysis_ids: list[str] | None = None,
    execution_code_refs: list[str] | None = None,
    observed_parameters: list[dict] | None = None,
    entrypoint: str = "code/analysis.py",
    check_observed: object | None = None,
    check_name: str = "output table records the expected synthetic mean difference",
    check_verification: dict | None = None,
    additional_checks: list[dict] | None = None,
) -> None:
    analysis = manifest["analyses"][0]
    execution_analysis_ids = execution_analysis_ids or ["A001"]
    execution_code_refs = execution_code_refs or ["E_CODE"]
    runtime_observations = copy.deepcopy(observed_parameters or [])
    if not any(str(item.get("name", "")).casefold() == "alpha" for item in runtime_observations):
        runtime_observations.append(
            {
                "name": "alpha",
                "value": 0.05,
                "evidence_paths": ["runs/RUN_OK/stdout.log"],
            }
        )
    manifest["task"].update(
        {"mode": "execution", "execution_requested": True, "execution_scope": "execute_now"}
    )
    analysis["inputs_outputs"]["outputs"] = [
        {
            "artifact_id": "OUT001",
            "path": "runs/RUN_OK/group_test.tsv",
            "semantic_type": "group comparison table",
            "fingerprint": None,
        }
    ]
    child_command = [
        sys.executable,
        entrypoint,
        "--input",
        "data/input.tsv",
        "--output-dir",
        "runs/RUN_OK",
        "--seed",
        "7",
    ]
    runner_command = [
        sys.executable,
        str(RUNNER_PATH),
        "--project-dir",
        str(root),
        "--execution-id",
        "RUN_OK",
        "--entrypoint",
        entrypoint,
    ]
    for analysis_id in execution_analysis_ids:
        runner_command.extend(["--analysis-id", analysis_id])
    for evidence_id in execution_code_refs:
        runner_command.extend(["--code-evidence-ref", evidence_id])
    runner_command.extend(
        [
        "--input-spec",
        json.dumps(
            {
                "artifact_id": "IN001",
                "path": "data/input.tsv",
                "semantic_type": "sample-level measurements",
            }
        ),
        "--output-spec",
        json.dumps(
            {
                "artifact_id": "OUT001",
                "path": "runs/RUN_OK/group_test.tsv",
                "semantic_type": "group comparison table",
                "analysis_ids": execution_analysis_ids,
            }
        ),
        "--dependency",
        f"python={sys.version.split()[0]}",
        "--seed",
        "7",
        "--",
        *child_command,
        ]
    )
    wrapper = subprocess.run(runner_command, cwd=root, capture_output=True, text=True, check=False)
    if wrapper.returncode != 0:
        raise AssertionError(f"runner failed: {wrapper.stdout}\n{wrapper.stderr}")
    run_dir = root / "runs/RUN_OK"
    output_path = run_dir / "group_test.tsv"
    observed = output_path.read_text(encoding="utf-8") if output_path.is_file() else "missing"
    pending_record = json.loads(
        (run_dir / "execution_record.fragment.json").read_text(encoding="utf-8")
    )
    if pending_record.get("attempt_status") != "pending_checks":
        raise AssertionError(f"runner skipped pending_checks: {pending_record}")
    primary_verification = check_verification or _group_result_verification()
    primary_unit = (
        "not_applicable"
        if primary_verification.get("kind") in {"text_contains", "sha256_equals"}
        else "dimensionless"
    )
    checks = [
        {
            "check_id": "CHK_MEAN_DIFF",
            "metric": "mean_difference_B_minus_A",
            "unit": primary_unit,
            "check": check_name,
            "observed": check_observed
            if check_observed is not None
            else ("3.0" if "\t3.0" in observed else observed),
            "passed": wrapper.returncode == 0 and "\t3.0" in observed,
            "analysis_ids": execution_analysis_ids,
            "evidence_paths": ["runs/RUN_OK/group_test.tsv", "runs/RUN_OK/stdout.log"],
            "verification": primary_verification,
        }
    ]
    checks.extend(copy.deepcopy(additional_checks or []))
    for check_index, check in enumerate(checks, start=1):
        check.setdefault("check_id", f"CHK_EXTRA_{check_index}")
        check.setdefault("metric", f"fixture_metric_{check_index}")
        kind = check.get("verification", {}).get("kind")
        check.setdefault(
            "unit",
            "not_applicable"
            if kind in {"text_contains", "sha256_equals"}
            else "not_recorded",
        )
    checks_path = root / "checks.RUN_OK.json"
    checks_path.write_text(json.dumps(checks, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    finalizer_command = [
            sys.executable,
            str(FINALIZER_PATH),
            "--project-dir",
            str(root),
            "--execution-id",
            "RUN_OK",
            "--checks-json",
            str(checks_path),
        ]
    observed_path = root / "observed.RUN_OK.json"
    observed_path.write_text(
        json.dumps(runtime_observations, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    finalizer_command.extend(["--observed-parameters-json", str(observed_path)])
    for execution_id in supersedes or []:
        finalizer_command.extend(["--supersedes-execution-id", execution_id])
    finalizer = subprocess.run(
        finalizer_command,
        cwd=root,
        capture_output=True,
        text=True,
        check=False,
    )
    if finalizer.returncode != 0:
        raise AssertionError(f"finalizer failed: {finalizer.stdout}\n{finalizer.stderr}")
    record = json.loads((run_dir / "execution_record.fragment.json").read_text(encoding="utf-8"))
    if record.get("attempt_status") != "succeeded":
        raise AssertionError(f"finalizer did not adjudicate success: {record}")
    manifest["execution_records"] = [record]
    analysis["execution_record_ids"] = ["RUN_OK"]
    analyses_by_id = {item["analysis_id"]: item for item in manifest["analyses"]}
    for analysis_id in execution_analysis_ids:
        target_analysis = analyses_by_id[analysis_id]
        linked_code_ref = next(
            (
                item["evidence_id"]
                for item in target_analysis["code_locations"]
                if item["evidence_id"] in execution_code_refs
            ),
            execution_code_refs[0],
        )
        for observation in runtime_observations:
            if not any(
                parameter.get("value_status") == "observed_runtime"
                and str(parameter.get("name", "")).casefold()
                == str(observation.get("name", "")).casefold()
                and parameter.get("value") == observation.get("value")
                and "RUN_OK" in parameter.get("execution_record_refs", [])
                for parameter in target_analysis["method_parameters"]["parameters"]
            ):
                target_analysis["method_parameters"]["parameters"].append(
                    {
                        "name": observation["name"],
                        "value": observation["value"],
                        "value_status": "observed_runtime",
                        "evidence_refs": [linked_code_ref],
                        "execution_record_refs": ["RUN_OK"],
                    }
                )
    analysis["inputs_outputs"]["outputs"][0]["fingerprint"] = f"sha256:{_sha256(output_path)}"
    analysis["interpretation"] = {
        "direct_observation": [
            _statement(
                "The successful run records the selected synthetic mean-difference result.",
                "RUN_OK",
                "OUT001",
                quantitative_claims=[
                    {
                        "metric": "mean_difference_B_minus_A",
                        "value": "3.0",
                        "unit": "dimensionless",
                        "evidence_ref": "OUT001",
                        "binding": {
                            "kind": "result_check",
                            "execution_id": "RUN_OK",
                            "check_id": "CHK_MEAN_DIFF",
                        },
                    }
                ],
            )
        ],
        "paper_claim": [
            _statement("The fixture paper claims a group difference.", "E_CLAIM")
        ],
        "reconstructed_support": [
            _statement(
                "The recorded command executed source_exact fixture code successfully and passed the output check.",
                "E_CODE",
                "RUN_OK",
                "OUT001",
            )
        ],
        "reasonable_inference": [],
        "unverified": [
            _statement("This synthetic run is not evidence for any external publication.", "E_CLAIM")
        ],
    }
    analysis["reproduction_status"] = "已执行验证"
    manifest["overall_status"] = "已执行验证"


def _add_failed_environment_record(root: Path, manifest: dict) -> None:
    analysis = manifest["analyses"][0]
    manifest["task"].update(
        {"mode": "execution", "execution_requested": True, "execution_scope": "execute_now"}
    )
    started = _utc_now()
    run_dir = root / "runs/RUN_FAILED"
    run_dir.mkdir(parents=True)
    (run_dir / "stdout.log").write_text("", encoding="utf-8")
    (run_dir / "stderr.log").write_text(
        "ModuleNotFoundError: required-example-package is unavailable\n", encoding="utf-8"
    )
    finished = _utc_now()
    command_argv = [
        sys.executable,
        "code/analysis.py",
        "--input",
        "data/input.tsv",
        "--output-dir",
        "runs/RUN_FAILED",
        "--seed",
        "7",
    ]
    manifest["execution_records"] = [
        {
            "execution_id": "RUN_FAILED",
            "analysis_ids": ["A001"],
            "command": subprocess.list2cmdline(command_argv),
            "command_argv": command_argv,
            "attempt_status": "blocked",
            "entrypoint": "code/analysis.py",
            "code_evidence_refs": ["E_CODE"],
            "code_snapshot_sha256": _sha256(root / "code/analysis.py"),
            "code_files": [
                {
                    "path": "code/analysis.py",
                    "sha256": _sha256(root / "code/analysis.py"),
                }
            ],
            "working_directory": ".",
            "started_at_utc": started,
            "finished_at_utc": finished,
            "exit_code": -1,
            "dependencies": [{"name": "required-example-package", "version": "missing"}],
            "seed": 7,
            "inputs": [
                {
                    "artifact_id": "IN001",
                    "path": "data/input.tsv",
                    "sha256": _sha256(root / "data/input.tsv"),
                    "semantic_type": "sample-level measurements",
                }
            ],
            "outputs": [],
            "stdout_log": "runs/RUN_FAILED/stdout.log",
            "stderr_log": "runs/RUN_FAILED/stderr.log",
            "checks": [
                {
                    "check_id": "CHK_BLOCKED_OUTPUT",
                    "metric": "result_table_created",
                    "unit": "not_applicable",
                    "check": "result table created",
                    "observed": False,
                    "passed": False,
                    "analysis_ids": ["A001"],
                    "evidence_paths": ["runs/RUN_FAILED/stderr.log"],
                    "verification": {
                        "kind": "text_contains",
                        "evidence_path": "runs/RUN_FAILED/stderr.log",
                        "selector": None,
                        "expected": "result table created",
                    },
                }
            ],
            "checks_sha256": VALIDATOR._canonical_sha256(
                [
                    {
                        "check_id": "CHK_BLOCKED_OUTPUT",
                        "metric": "result_table_created",
                        "unit": "not_applicable",
                        "check": "result table created",
                        "observed": False,
                        "passed": False,
                        "analysis_ids": ["A001"],
                        "evidence_paths": ["runs/RUN_FAILED/stderr.log"],
                        "verification": {
                            "kind": "text_contains",
                            "evidence_path": "runs/RUN_FAILED/stderr.log",
                            "selector": None,
                            "expected": "result table created",
                        },
                    }
                ]
            ),
            "observed_parameters": [],
            "observed_parameters_sha256": VALIDATOR._canonical_sha256([]),
            "adjudication_status": "blocked",
            "adjudicated_at_utc": None,
            "preflight": {
                "authorization_basis": "explicit_execution_request",
                "status": "blocked",
                "source_read_only": True,
                "output_directory": "runs/RUN_FAILED",
                "environment": "unavailable",
                "network_used": False,
                "notes": ["Dependency preflight failed; no substitution or install was attempted."],
            },
            "code_provenance": "source_exact",
            "receipt_path": None,
            "receipt_sha256": None,
            "supersedes_execution_ids": [],
        }
    ]
    analysis["execution_record_ids"] = ["RUN_FAILED"]
    analysis["conflicts_gaps"] = [
        {
            "issue_id": "G_ENV",
            "kind": "gap",
            "topic": "execution environment",
            "description": "Required dependency is unavailable in the test environment.",
            "impact": "The requested command cannot produce the result table.",
            "evidence_refs": ["E_CODE"],
            "blocking": True,
            "resolved": False,
        }
    ]
    analysis["interpretation"] = {
        "direct_observation": [
            _statement(VALIDATOR.BLOCKED_RUNTIME_OBSERVATION_STATEMENT, "RUN_FAILED")
        ],
        "paper_claim": [
            _statement("The fixture paper claims a group difference.", "E_CLAIM")
        ],
        "reconstructed_support": [
            _statement(
                "The source materials remain aligned, but execution was not completed.",
                "E_METHOD",
                "E_CODE",
            )
        ],
        "reasonable_inference": [],
        "unverified": [
            _statement(
                "The numerical result remains unverified because the environment is unavailable.",
                "E_CODE",
            )
        ],
    }
    analysis["reproduction_status"] = "受阻"
    manifest["overall_status"] = "受阻"
    manifest["stage_state"][3]["status"] = "blocked"
    manifest["stage_state"][3]["blockers"] = ["G_ENV"]
    manifest["stage_state"][4]["status"] = "not_started"


class ReconstructionContractScenarios(unittest.TestCase):
    def validate(
        self,
        manifest: dict,
        setup: Callable[[Path, dict], None] | None = None,
        report: str | None = None,
        row_mutator: Callable[[dict], None] | None = None,
    ) -> dict:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _materialize_sources(root, manifest)
            if setup:
                setup(root, manifest)
            if report is None:
                report = _canonical_report(manifest)
            rows = [trace_row(manifest, index) for index in range(len(manifest["analyses"]))]
            if row_mutator:
                row_mutator(rows[0])
            _write_project(root, manifest, rows, report)
            return VALIDATOR.validate_project(root, write_report=True)

    def test_complete_materials_remain_unexecuted(self) -> None:
        manifest = base_manifest()
        result = self.validate(manifest)
        self.assertTrue(result["valid"], result["errors"])
        self.assertEqual(result["derived_overall_status"], "材料完整但未执行")

    def test_missing_code_is_blocked_without_claiming_alignment(self) -> None:
        manifest = base_manifest()
        analysis = manifest["analyses"][0]
        analysis["code_locations"] = []
        analysis["method_parameters"]["parameters"] = [
            parameter
            for parameter in analysis["method_parameters"]["parameters"]
            if parameter["value_status"] != "implemented"
        ]
        manifest["sources"][3].update(
            {"availability": "missing", "fingerprint": None, "locator_type": "unavailable"}
        )
        analysis["conflicts_gaps"] = [
            {
                "issue_id": "G_CODE",
                "kind": "gap",
                "topic": "source code",
                "description": "No source code was provided or found.",
                "impact": "Implemented parameters and faithful execution cannot be verified.",
                "evidence_refs": ["E_METHOD"],
                "blocking": True,
                "resolved": False,
            }
        ]
        analysis["scientific_audit"] = _audit(["E_METHOD"])
        for audit in analysis["scientific_audit"]:
            if audit["topic"] in {"preprocessing", "multiple_testing", "parameter_consistency"}:
                audit.update(
                    {
                        "status": "blocked",
                        "finding": f"{audit['topic']} cannot be checked against active code because code is missing.",
                        "evidence_refs": [
                            ref for ref in audit["evidence_refs"] if ref != "E_CODE"
                        ],
                        "claim_ceiling": "not_assessable",
                    }
                )
        analysis["interpretation"] = {
            "direct_observation": [
                _statement("The paper and figure materials are readable.", "E_CLAIM", "E_FIG")
            ],
            "paper_claim": [
                _statement("The fixture paper claims a group difference.", "E_CLAIM")
            ],
            "reconstructed_support": [
                _statement(
                    "The paper claim and Methods parameters were inventoried directly.",
                    "E_CLAIM",
                    "E_METHOD",
                )
            ],
            "reasonable_inference": [],
            "unverified": [
                _statement(
                    "Implementation behavior is unverified because source code is missing.",
                    "E_METHOD",
                )
            ],
        }
        analysis["reproduction_status"] = "受阻"
        manifest["overall_status"] = "受阻"
        manifest["stage_state"][3]["status"] = "blocked"
        manifest["stage_state"][3]["blockers"] = ["G_CODE"]
        manifest["stage_state"][4]["status"] = "not_started"
        result = self.validate(manifest)
        self.assertTrue(result["valid"], result["errors"])
        self.assertEqual(result["derived_statuses"]["A001"]["derived"], "受阻")

    def test_methods_code_conflict_is_preserved_side_by_side(self) -> None:
        manifest = base_manifest()
        analysis = manifest["analyses"][0]
        analysis["method_parameters"]["parameters"].append(
            {
                "name": "alpha",
                "value": 0.10,
                "value_status": "implemented",
                "evidence_refs": ["E_CODE"],
                "implementation_literal": "ALPHA = 0.10",
            }
        )
        analysis["conflicts_gaps"] = [
            {
                "issue_id": "C_ALPHA",
                "kind": "conflict",
                "topic": "alpha threshold",
                "description": "Methods alpha=0.05 conflicts with active code alpha=0.10.",
                "impact": "Significance decisions may differ.",
                "evidence_refs": ["E_METHOD", "E_CODE"],
                "blocking": True,
                "resolved": False,
            }
        ]
        for audit in analysis["scientific_audit"]:
            if audit["topic"] == "parameter_consistency":
                audit.update(
                    {
                        "status": "warning",
                        "finding": "Methods alpha=0.05 and active code alpha=0.10 conflict.",
                    }
                )
        analysis["interpretation"] = {
            "direct_observation": [
                _statement("Methods and code expose different alpha values.", "E_METHOD", "E_CODE")
            ],
            "paper_claim": [
                _statement("The fixture paper claims a group difference.", "E_CLAIM")
            ],
            "reconstructed_support": [
                _statement(
                    "Both alpha values are preserved without silently selecting either value.",
                    "E_METHOD",
                    "E_CODE",
                )
            ],
            "reasonable_inference": [],
            "unverified": [
                _statement(
                    "Significance decisions cannot be reconciled until the conflict is resolved.",
                    "E_METHOD",
                    "E_CODE",
                )
            ],
        }
        analysis["reproduction_status"] = "材料冲突"
        manifest["overall_status"] = "材料冲突"

        def expose_real_code_conflict(root: Path, value: dict) -> None:
            code_path = root / "code/analysis.py"
            code_path.write_text(
                code_path.read_text(encoding="utf-8") + "\n# Paper/code conflict fixture\nALPHA = 0.10\n",
                encoding="utf-8",
            )
            fingerprint = f"sha256:{_sha256(code_path)}"
            value["sources"][3]["fingerprint"] = fingerprint
            value["analyses"][0]["code_locations"][0]["snapshot"] = fingerprint
            value["analyses"][0]["code_locations"][0]["locator"] = "L27: ALPHA = 0.10"
            source_fingerprint = VALIDATOR._source_set_fingerprint(value["sources"])
            for stage in value["stage_state"]:
                stage["input_fingerprint"] = source_fingerprint

        result = self.validate(manifest, setup=expose_real_code_conflict)
        self.assertTrue(result["valid"], result["errors"])
        self.assertEqual(result["derived_statuses"]["A001"]["derived"], "材料冲突")

    def test_unexecutable_environment_is_blocked(self) -> None:
        manifest = base_manifest()
        result = self.validate(manifest, setup=_add_failed_environment_record)
        self.assertTrue(result["valid"], result["errors"])
        self.assertEqual(result["derived_statuses"]["A001"]["derived"], "受阻")

    def test_blocked_runtime_cannot_lend_direct_support_to_scientific_claims(self) -> None:
        for false_statement in (
            "The blocked run directly shows robust group separation.",
            "The blocked run confirms successful normalization and batch correction.",
        ):
            with self.subTest(false_statement=false_statement):
                manifest = base_manifest()

                def overclaim(root: Path, value: dict) -> None:
                    _add_failed_environment_record(root, value)
                    value["analyses"][0]["interpretation"]["direct_observation"][0][
                        "statement"
                    ] = false_statement

                result = self.validate(manifest, setup=overclaim)
                self.assertFalse(result["valid"])
                self.assertIn(
                    "blocked_runtime_observation_not_canonical",
                    {item["code"] for item in result["errors"]},
                )

        manifest = base_manifest()

        def reconstruct_from_blocked(root: Path, value: dict) -> None:
            _add_failed_environment_record(root, value)
            value["analyses"][0]["interpretation"]["reconstructed_support"] = [
                _statement(
                    "The blocked run and Methods support robust group separation.",
                    "RUN_FAILED",
                    "E_METHOD",
                )
            ]

        result = self.validate(manifest, setup=reconstruct_from_blocked)
        self.assertFalse(result["valid"])
        self.assertIn(
            "blocked_runtime_ref_wrong_interpretation_lane",
            {item["code"] for item in result["errors"]},
        )

        manifest = base_manifest()

        def add_undeclared_output(root: Path, value: dict) -> None:
            _add_failed_environment_record(root, value)
            (root / "runs/RUN_FAILED/result.tsv").write_text(
                "metric\tvalue\nmean_difference\t99\n", encoding="utf-8"
            )

        result = self.validate(manifest, setup=add_undeclared_output)
        self.assertFalse(result["valid"])
        self.assertIn(
            "interpretation_observation_without_direct_material",
            {item["code"] for item in result["errors"]},
        )
        self.assertTrue(any(item["code"] == "execution_not_qualifying" for item in result["warnings"]))

    def test_executed_status_without_runtime_evidence_is_rejected(self) -> None:
        manifest = base_manifest()
        manifest["analyses"][0]["reproduction_status"] = "已执行验证"
        manifest["overall_status"] = "已执行验证"
        result = self.validate(
            manifest,
            report=(
                "# Contract fixture\n\nA001: 已执行验证；复现完成。\n\n"
                "## Direct observation\nDeclared status only.\n\n"
                "## Reasonable inference\nNone.\n\n"
                "## Unverified\nExecution evidence is unverified.\n"
            ),
        )
        self.assertFalse(result["valid"])
        codes = {item["code"] for item in result["errors"]}
        self.assertIn("status_mismatch", codes)
        self.assertIn("unsupported_completion_language", codes)

    def test_real_fixture_execution_with_files_hashes_logs_and_checks_qualifies(self) -> None:
        manifest = base_manifest()
        result = self.validate(
            manifest,
            setup=_run_successful_fixture,
        )
        self.assertTrue(result["valid"], result["errors"])
        self.assertEqual(result["derived_overall_status"], "已执行验证")

    def test_nonexistent_runtime_artifacts_cannot_qualify(self) -> None:
        manifest = base_manifest()

        def forge(_root: Path, value: dict) -> None:
            analysis = value["analyses"][0]
            value["task"].update(
                {"mode": "execution", "execution_requested": True, "execution_scope": "execute_now"}
            )
            value["execution_records"] = [
                {
                    "execution_id": "RUN_FAKE",
                    "analysis_ids": ["A001"],
                    "command": "never-ran",
                    "command_argv": ["never-ran", "code/analysis.py"],
                    "attempt_status": "succeeded",
                    "entrypoint": "code/analysis.py",
                    "code_evidence_refs": ["E_CODE"],
                    "code_snapshot_sha256": _sha256(_root / "code/analysis.py"),
                    "code_files": [
                        {
                            "path": "code/analysis.py",
                            "sha256": _sha256(_root / "code/analysis.py"),
                        }
                    ],
                    "working_directory": ".",
                    "started_at_utc": "2026-07-28T01:00:00Z",
                    "finished_at_utc": "2026-07-28T01:00:01Z",
                    "exit_code": 0,
                    "dependencies": [{"name": "python", "version": "3.11.9"}],
                    "seed": 7,
                    "inputs": [
                        {
                            "artifact_id": "IN001",
                            "path": "missing/input.tsv",
                            "sha256": "a" * 64,
                            "semantic_type": "sample-level measurements",
                        }
                    ],
                    "outputs": [
                        {
                            "artifact_id": "OUT001",
                            "path": "missing/output.tsv",
                            "sha256": "b" * 64,
                            "semantic_type": "group comparison table",
                            "analysis_ids": ["A001"],
                        }
                    ],
                    "stdout_log": "missing/stdout.log",
                    "stderr_log": "missing/stderr.log",
                    "checks": [
                        {
                            "check_id": "CHK_FABRICATED",
                            "metric": "fabricated_check",
                            "unit": "not_applicable",
                            "check": "fabricated check",
                            "observed": "ok",
                            "passed": True,
                            "analysis_ids": ["A001"],
                            "evidence_paths": ["missing/output.tsv"],
                            "verification": {
                                "kind": "text_contains",
                                "evidence_path": "missing/output.tsv",
                                "selector": None,
                                "expected": "ok",
                            },
                        }
                    ],
                    "preflight": {
                        "authorization_basis": "explicit_execution_request",
                        "status": "passed",
                        "source_read_only": True,
                        "output_directory": "missing",
                        "environment": "existing",
                        "network_used": False,
                        "notes": [],
                    },
                    "code_provenance": "source_exact",
                    "receipt_path": "runs/RUN_FAKE/execution_receipt.json",
                    "receipt_sha256": "c" * 64,
                    "supersedes_execution_ids": [],
                }
            ]
            analysis["execution_record_ids"] = ["RUN_FAKE"]
            analysis["reproduction_status"] = "已执行验证"
            value["overall_status"] = "已执行验证"

        result = self.validate(manifest, setup=forge)
        self.assertFalse(result["valid"])
        self.assertEqual(result["derived_statuses"]["A001"]["derived"], "受阻")
        self.assertIn("status_mismatch", {item["code"] for item in result["errors"]})

    def test_runtime_hash_mismatch_is_rejected(self) -> None:
        manifest = base_manifest()

        def run_then_corrupt(root: Path, value: dict) -> None:
            _run_successful_fixture(root, value)
            value["execution_records"][0]["outputs"][0]["sha256"] = "f" * 64

        result = self.validate(manifest, setup=run_then_corrupt)
        self.assertFalse(result["valid"])
        self.assertEqual(result["derived_statuses"]["A001"]["derived"], "受阻")

    def test_execution_analysis_links_must_be_bidirectional(self) -> None:
        manifest = base_manifest()

        def break_backlink(root: Path, value: dict) -> None:
            _run_successful_fixture(root, value)
            value["execution_records"][0]["analysis_ids"] = ["A999"]

        result = self.validate(manifest, setup=break_backlink)
        self.assertFalse(result["valid"])
        codes = {item["code"] for item in result["errors"]}
        self.assertIn("analysis_execution_link_mismatch", codes)
        self.assertIn("unknown_analysis_ref", codes)

    def test_resolved_conflict_requires_additional_evidence(self) -> None:
        manifest = base_manifest()
        analysis = manifest["analyses"][0]
        analysis["conflicts_gaps"] = [
            {
                "issue_id": "C_ALPHA",
                "kind": "conflict",
                "topic": "alpha threshold",
                "description": "Methods and code initially differed.",
                "impact": "Significance decisions could differ.",
                "evidence_refs": ["E_METHOD", "E_CODE"],
                "blocking": True,
                "resolved": True,
                "resolution_evidence_refs": ["E_METHOD"],
                "resolution": "The boolean was flipped without additional evidence.",
            }
        ]
        result = self.validate(manifest)
        self.assertFalse(result["valid"])
        self.assertIn(
            "resolved_issue_without_new_evidence",
            {item["code"] for item in result["errors"]},
        )

    def test_all_eight_scientific_audit_topics_are_required(self) -> None:
        manifest = base_manifest()
        manifest["analyses"][0]["scientific_audit"].pop()
        result = self.validate(manifest)
        self.assertFalse(result["valid"])
        self.assertIn("scientific_audit_incomplete", {item["code"] for item in result["errors"]})

    def test_ready_code_guidance_contract_is_validated(self) -> None:
        manifest = base_manifest()
        analysis = manifest["analyses"][0]
        manifest["task"]["mode"] = "code_guidance"
        analysis["code_guidance"] = {
            "status": "ready",
            "provenance": "source_adapted",
            "entrypoint": "code/analysis.py",
            "dependencies": [{"name": "python", "version": sys.version.split()[0]}],
            "seed": 7,
            "inputs": analysis["inputs_outputs"]["inputs"],
            "outputs": analysis["inputs_outputs"]["outputs"],
            "configurable_paths": ["--input", "--output-dir"],
            "minimal_run": (
                "python code/analysis.py --input <input.tsv> --output-dir <new-output-dir> --seed 7"
            ),
            "unresolved_parameters": [],
            "blocker_ids": [],
        }
        result = self.validate(manifest)
        self.assertTrue(result["valid"], result["errors"])

    def test_code_guidance_mode_missing_or_invalid_guidance_derives_blocked(self) -> None:
        cases = (
            ("absent", "missing_code_guidance"),
            ("none", "missing_code_guidance"),
            ("non_dict", "invalid_code_guidance"),
            ("empty", "invalid_guidance_status"),
        )
        for variant, expected_code in cases:
            with self.subTest(variant=variant):
                manifest = base_manifest()
                manifest["task"]["mode"] = "code_guidance"
                analysis = manifest["analyses"][0]
                if variant == "absent":
                    analysis.pop("code_guidance")
                elif variant == "none":
                    analysis["code_guidance"] = None
                elif variant == "non_dict":
                    analysis["code_guidance"] = []
                else:
                    analysis["code_guidance"] = {}

                result = self.validate(manifest)
                self.assertFalse(result["valid"])
                self.assertIn(
                    expected_code,
                    {item["code"] for item in result["errors"]},
                )
                self.assertEqual(
                    result["derived_statuses"]["A001"]["derived"],
                    "受阻",
                )
                self.assertEqual(result["derived_overall_status"], "受阻")
                self.assertTrue(
                    any(
                        expected_code in reason
                        for reason in result["derived_statuses"]["A001"]["reasons"]
                    )
                )

    def test_ready_guidance_covers_required_and_consistent_cli_parameters(self) -> None:
        def install_code(root: Path, value: dict, code: str) -> None:
            code_path = root / "code/analysis.py"
            code_path.write_text(code, encoding="utf-8")
            fingerprint = f"sha256:{_sha256(code_path)}"
            value["sources"][3]["fingerprint"] = fingerprint
            value["analyses"][0]["code_locations"][0]["snapshot"] = fingerprint
            source_fingerprint = VALIDATOR._source_set_fingerprint(value["sources"])
            for stage in value["stage_state"]:
                stage["input_fingerprint"] = source_fingerprint

        def ready_manifest(minimal_run: str) -> dict:
            value = base_manifest()
            analysis = value["analyses"][0]
            value["task"]["mode"] = "code_guidance"
            analysis["code_guidance"] = {
                "status": "ready",
                "provenance": "source_adapted",
                "entrypoint": "code/analysis.py",
                "dependencies": [{"name": "python", "version": sys.version.split()[0]}],
                "seed": 7,
                "inputs": analysis["inputs_outputs"]["inputs"],
                "outputs": analysis["inputs_outputs"]["outputs"],
                "configurable_paths": ["--input", "--output-dir"],
                "minimal_run": minimal_run,
                "unresolved_parameters": [],
                "blocker_ids": [],
            }
            return value

        missing = ready_manifest(
            "python code/analysis.py --input <input.tsv> --output-dir <output> --seed 7"
        )

        def require_alpha(root: Path, value: dict) -> None:
            code = SOURCE_CONTENT["code/analysis.py"].replace(
                'parser.add_argument("--alpha", type=float, default=ALPHA)',
                'parser.add_argument("--alpha", type=float, required=True)',
            )
            install_code(root, value, code)

        result = self.validate(missing, setup=require_alpha)
        self.assertFalse(result["valid"])
        self.assertIn(
            "guidance_required_cli_argument_missing",
            {item["code"] for item in result["errors"]},
        )
        self.assertEqual(result["derived_statuses"]["A001"]["derived"], "受阻")
        self.assertEqual(result["derived_overall_status"], "受阻")

        wrong = ready_manifest(
            "python code/analysis.py --input <input.tsv> --output-dir <output> "
            "--seed 7 --alpha 0.10"
        )
        result = self.validate(wrong)
        self.assertFalse(result["valid"])
        self.assertIn(
            "guidance_parameter_value_mismatch",
            {item["code"] for item in result["errors"]},
        )

        correct = ready_manifest(
            "python code/analysis.py --input <input.tsv> --output-dir <output> "
            "--seed 7 --alpha 0.05"
        )
        result = self.validate(correct)
        self.assertTrue(result["valid"], result["errors"])

        swallowed = ready_manifest(
            "python code/analysis.py --input --output-dir <output> --seed 7"
        )
        result = self.validate(swallowed)
        self.assertFalse(result["valid"])
        self.assertIn(
            "guidance_cli_argument_malformed",
            {item["code"] for item in result["errors"]},
        )

    def test_ready_guidance_dependencies_cover_active_python_imports(self) -> None:
        manifest = base_manifest()
        analysis = manifest["analyses"][0]
        manifest["task"]["mode"] = "code_guidance"
        analysis["code_guidance"] = {
            "status": "ready",
            "provenance": "source_adapted",
            "entrypoint": "code/analysis.py",
            "dependencies": [{"name": "python", "version": sys.version.split()[0]}],
            "seed": 7,
            "inputs": analysis["inputs_outputs"]["inputs"],
            "outputs": analysis["inputs_outputs"]["outputs"],
            "configurable_paths": ["--input", "--output-dir"],
            "minimal_run": (
                "python code/analysis.py --input <input.tsv> --output-dir <output> --seed 7"
            ),
            "unresolved_parameters": [],
            "blocker_ids": [],
        }

        def add_numpy_import(root: Path, value: dict) -> None:
            code = SOURCE_CONTENT["code/analysis.py"].replace(
                "from __future__ import annotations\n",
                "from __future__ import annotations\n\nimport numpy\n",
            )
            code_path = root / "code/analysis.py"
            code_path.write_text(code, encoding="utf-8")
            fingerprint = f"sha256:{_sha256(code_path)}"
            value["sources"][3]["fingerprint"] = fingerprint
            value["analyses"][0]["code_locations"][0]["snapshot"] = fingerprint
            source_fingerprint = VALIDATOR._source_set_fingerprint(value["sources"])
            for stage in value["stage_state"]:
                stage["input_fingerprint"] = source_fingerprint

        result = self.validate(copy.deepcopy(manifest), setup=add_numpy_import)
        self.assertFalse(result["valid"])
        self.assertIn(
            "guidance_missing_import_dependencies",
            {item["code"] for item in result["errors"]},
        )
        self.assertEqual(result["derived_statuses"]["A001"]["derived"], "受阻")
        self.assertEqual(result["derived_overall_status"], "受阻")

        manifest["analyses"][0]["code_guidance"]["dependencies"].append(
            {"name": "numpy", "version": "fixture-pinned"}
        )
        result = self.validate(manifest, setup=add_numpy_import)
        self.assertTrue(result["valid"], result["errors"])

    def test_ready_guidance_dependency_identities_are_unique_and_use_distribution_aliases(self) -> None:
        def ready_manifest() -> dict:
            value = base_manifest()
            analysis = value["analyses"][0]
            value["task"]["mode"] = "code_guidance"
            analysis["code_guidance"] = {
                "status": "ready",
                "provenance": "source_adapted",
                "entrypoint": "code/analysis.py",
                "dependencies": [
                    {"name": "python", "version": sys.version.split()[0]}
                ],
                "seed": 7,
                "inputs": analysis["inputs_outputs"]["inputs"],
                "outputs": analysis["inputs_outputs"]["outputs"],
                "configurable_paths": ["--input", "--output-dir"],
                "minimal_run": (
                    "python code/analysis.py --input <input.tsv> "
                    "--output-dir <output> --seed 7"
                ),
                "unresolved_parameters": [],
                "blocker_ids": [],
            }
            return value

        for duplicate in ("PYTHON", "python", "python..."):
            with self.subTest(duplicate=duplicate):
                manifest = ready_manifest()
                manifest["analyses"][0]["code_guidance"]["dependencies"].append(
                    {"name": duplicate, "version": sys.version.split()[0]}
                )
                result = self.validate(manifest)
                self.assertFalse(result["valid"])
                self.assertIn(
                    "guidance_invalid_dependency_contract",
                    {item["code"] for item in result["errors"]},
                )

        manifest = ready_manifest()
        manifest["analyses"][0]["code_guidance"]["dependencies"].append(
            {"name": "   ", "version": "1.0"}
        )
        result = self.validate(manifest)
        self.assertFalse(result["valid"])

        alias_manifest = ready_manifest()
        alias_manifest["analyses"][0]["code_guidance"]["dependencies"].extend(
            [
                {"name": "umap-learn", "version": "fixture-pinned"},
                {"name": "scikit-image", "version": "fixture-pinned"},
            ]
        )

        def add_aliased_imports(root: Path, value: dict) -> None:
            code = SOURCE_CONTENT["code/analysis.py"].replace(
                "from __future__ import annotations\n",
                "from __future__ import annotations\n\nimport skimage\nimport umap\n",
            )
            code_path = root / "code/analysis.py"
            code_path.write_text(code, encoding="utf-8")
            fingerprint = f"sha256:{_sha256(code_path)}"
            value["sources"][3]["fingerprint"] = fingerprint
            value["analyses"][0]["code_locations"][0]["snapshot"] = fingerprint
            source_fingerprint = VALIDATOR._source_set_fingerprint(value["sources"])
            for stage in value["stage_state"]:
                stage["input_fingerprint"] = source_fingerprint

        result = self.validate(alias_manifest, setup=add_aliased_imports)
        self.assertTrue(result["valid"], result["errors"])

    def test_ready_guidance_treats_recursive_entrypoint_root_import_as_local(self) -> None:
        manifest = base_manifest()
        analysis = manifest["analyses"][0]
        manifest["task"]["mode"] = "code_guidance"
        analysis["code_guidance"] = {
            "status": "ready",
            "provenance": "source_adapted",
            "entrypoint": "code/analysis.py",
            "dependencies": [{"name": "python", "version": sys.version.split()[0]}],
            "seed": 7,
            "inputs": analysis["inputs_outputs"]["inputs"],
            "outputs": analysis["inputs_outputs"]["outputs"],
            "configurable_paths": ["--input", "--output-dir"],
            "minimal_run": (
                "python code/analysis.py --input <input.tsv> --output-dir <output> --seed 7"
            ),
            "unresolved_parameters": [],
            "blocker_ids": [],
        }
        additions = (
            ("SRC006", "E_PKG_INIT", "code/pkg/__init__.py"),
            ("SRC007", "E_PKG_MAIN", "code/pkg/main.py"),
            ("SRC008", "E_HELPER", "code/helper.py"),
        )
        for source_id, evidence_id, path in additions:
            manifest["sources"].append(_source(source_id, ["code"], path))
            analysis["code_locations"].append(
                {
                    "evidence_id": evidence_id,
                    "source_id": source_id,
                    "snapshot": f"sha256:{HASH_PLACEHOLDER}",
                    "path": path,
                    "locator": "L1",
                    "scope": "upstream_analysis",
                    "evidence_status": "active_import_only",
                }
            )

        def install_nested_import(root: Path, value: dict) -> None:
            code_path = root / "code/analysis.py"
            code_path.write_text(
                "from pkg import main\n" + code_path.read_text(encoding="utf-8"),
                encoding="utf-8",
            )
            value["sources"][3]["fingerprint"] = f"sha256:{_sha256(code_path)}"
            value["analyses"][0]["code_locations"][0]["snapshot"] = (
                f"sha256:{_sha256(code_path)}"
            )
            by_path = {source["location"]: source for source in value["sources"]}
            for item in value["analyses"][0]["code_locations"][1:]:
                item["snapshot"] = by_path[item["path"]]["fingerprint"]
            source_fingerprint = VALIDATOR._source_set_fingerprint(value["sources"])
            for stage in value["stage_state"]:
                stage["input_fingerprint"] = source_fingerprint

        result = self.validate(manifest, setup=install_nested_import)
        self.assertTrue(result["valid"], result["errors"])

    def test_ready_guidance_rejects_unregistered_local_import_code(self) -> None:
        manifest = base_manifest()
        analysis = manifest["analyses"][0]
        manifest["task"]["mode"] = "code_guidance"
        analysis["code_guidance"] = {
            "status": "ready",
            "provenance": "source_adapted",
            "entrypoint": "code/analysis.py",
            "dependencies": [{"name": "python", "version": sys.version.split()[0]}],
            "seed": 7,
            "inputs": analysis["inputs_outputs"]["inputs"],
            "outputs": analysis["inputs_outputs"]["outputs"],
            "configurable_paths": ["--input", "--output-dir"],
            "minimal_run": (
                "python code/analysis.py --input <input.tsv> --output-dir <output> --seed 7"
            ),
            "unresolved_parameters": [],
            "blocker_ids": [],
        }

        def install_unregistered_helper(root: Path, value: dict) -> None:
            helper = root / "code/cli_helper.py"
            helper.write_text(
                "def build(parser):\n"
                "    parser.add_argument('--alpha', type=float, required=True)\n",
                encoding="utf-8",
            )
            code = SOURCE_CONTENT["code/analysis.py"].replace(
                'parser.add_argument("--alpha", type=float, default=ALPHA)',
                "from cli_helper import build\nbuild(parser)",
            )
            code_path = root / "code/analysis.py"
            code_path.write_text(code, encoding="utf-8")
            fingerprint = f"sha256:{_sha256(code_path)}"
            value["sources"][3]["fingerprint"] = fingerprint
            value["analyses"][0]["code_locations"][0]["snapshot"] = fingerprint
            source_fingerprint = VALIDATOR._source_set_fingerprint(value["sources"])
            for stage in value["stage_state"]:
                stage["input_fingerprint"] = source_fingerprint

        result = self.validate(manifest, setup=install_unregistered_helper)
        self.assertFalse(result["valid"])
        codes = {item["code"] for item in result["errors"]}
        self.assertIn("guidance_unbound_local_code", codes)
        self.assertIn("guidance_required_cli_argument_missing", codes)

    def test_ready_guidance_dynamic_closure_gap_derives_blocked(self) -> None:
        manifest = base_manifest()
        analysis = manifest["analyses"][0]
        manifest["task"]["mode"] = "code_guidance"
        analysis["code_guidance"] = {
            "status": "ready",
            "provenance": "source_adapted",
            "entrypoint": "code/analysis.py",
            "dependencies": [{"name": "python", "version": sys.version.split()[0]}],
            "seed": 7,
            "inputs": analysis["inputs_outputs"]["inputs"],
            "outputs": analysis["inputs_outputs"]["outputs"],
            "configurable_paths": ["--input", "--output-dir"],
            "minimal_run": (
                "python code/analysis.py --input <input.tsv> --output-dir <output> --seed 7"
            ),
            "unresolved_parameters": [],
            "blocker_ids": [],
        }

        def install_dynamic_loader(root: Path, value: dict) -> None:
            code_path = root / "code/analysis.py"
            code_path.write_text(
                "__import__('runtime_helper')\n" + code_path.read_text(encoding="utf-8"),
                encoding="utf-8",
            )
            fingerprint = f"sha256:{_sha256(code_path)}"
            value["sources"][3]["fingerprint"] = fingerprint
            value["analyses"][0]["code_locations"][0]["snapshot"] = fingerprint
            source_fingerprint = VALIDATOR._source_set_fingerprint(value["sources"])
            for stage in value["stage_state"]:
                stage["input_fingerprint"] = source_fingerprint

        result = self.validate(manifest, setup=install_dynamic_loader)
        self.assertFalse(result["valid"])
        self.assertIn(
            "guidance_code_closure_gap",
            {item["code"] for item in result["errors"]},
        )
        self.assertEqual(result["derived_statuses"]["A001"]["derived"], "受阻")
        self.assertEqual(result["derived_overall_status"], "受阻")
        self.assertTrue(
            any(
                "guidance_code_closure_gap" in reason
                for reason in result["derived_statuses"]["A001"]["reasons"]
            )
        )

    def test_ready_guidance_blocker_does_not_override_material_conflict(self) -> None:
        manifest = base_manifest()
        analysis = manifest["analyses"][0]
        manifest["task"]["mode"] = "code_guidance"
        analysis["code_guidance"] = {
            "status": "ready",
            "provenance": "source_adapted",
            "entrypoint": "code/analysis.py",
            "dependencies": [],
            "seed": 7,
            "inputs": analysis["inputs_outputs"]["inputs"],
            "outputs": analysis["inputs_outputs"]["outputs"],
            "configurable_paths": ["--input", "--output-dir"],
            "minimal_run": (
                "python code/analysis.py --input <input.tsv> --output-dir <output> --seed 7"
            ),
            "unresolved_parameters": [],
            "blocker_ids": [],
        }
        analysis["conflicts_gaps"] = [
            {
                "issue_id": "C_GUIDANCE_PRIORITY",
                "kind": "conflict",
                "topic": "parameter consistency",
                "description": "Methods and active code expose unresolved alternatives.",
                "impact": "The analysis choice remains ambiguous.",
                "evidence_refs": ["E_METHOD", "E_CODE"],
                "blocking": True,
                "resolved": False,
            }
        ]
        analysis["reproduction_status"] = "材料冲突"
        manifest["overall_status"] = "材料冲突"

        result = self.validate(manifest)
        self.assertFalse(result["valid"])
        self.assertIn(
            "guidance_missing_dependencies",
            {item["code"] for item in result["errors"]},
        )
        self.assertEqual(result["derived_statuses"]["A001"]["derived"], "材料冲突")
        self.assertEqual(result["derived_overall_status"], "材料冲突")

    def test_execution_code_bundle_detects_imported_helper_drift(self) -> None:
        manifest = base_manifest()

        def run_then_drift_helper(root: Path, value: dict) -> None:
            value["sources"].append(
                _source("SRC006", ["code"], "code/helper.py")
            )
            value["analyses"][0]["code_locations"].append(
                {
                    "evidence_id": "E_HELPER",
                    "source_id": "SRC006",
                    "snapshot": f"sha256:{HASH_PLACEHOLDER}",
                    "path": "code/helper.py",
                    "locator": "L1-L2",
                    "scope": "upstream_analysis",
                    "evidence_status": "active_call",
                }
            )
            helper = root / "code/helper.py"
            helper.write_text(
                "def passthrough(value):\n    return value\n", encoding="utf-8"
            )
            code = SOURCE_CONTENT["code/analysis.py"].replace(
                "import csv\n", "import csv\nfrom helper import passthrough\n"
            ).replace(
                'difference = means["B"] - means["A"]',
                'difference = passthrough(means["B"] - means["A"])',
            )
            code_path = root / "code/analysis.py"
            code_path.write_text(code, encoding="utf-8")
            code_hash = f"sha256:{_sha256(code_path)}"
            helper_hash = f"sha256:{_sha256(helper)}"
            value["sources"][3]["fingerprint"] = code_hash
            value["sources"][-1]["fingerprint"] = helper_hash
            value["analyses"][0]["code_locations"][0]["snapshot"] = code_hash
            value["analyses"][0]["code_locations"][1]["snapshot"] = helper_hash
            source_fingerprint = VALIDATOR._source_set_fingerprint(value["sources"])
            for stage in value["stage_state"]:
                stage["input_fingerprint"] = source_fingerprint

            _run_successful_fixture(
                root,
                value,
                execution_code_refs=["E_CODE", "E_HELPER"],
            )

            helper.write_text(
                "def passthrough(value):\n    return value + 100\n",
                encoding="utf-8",
            )
            drift_hash = f"sha256:{_sha256(helper)}"
            value["sources"][-1]["fingerprint"] = drift_hash
            value["analyses"][0]["code_locations"][1]["snapshot"] = drift_hash
            source_fingerprint = VALIDATOR._source_set_fingerprint(value["sources"])
            for stage in value["stage_state"]:
                stage["input_fingerprint"] = source_fingerprint

        result = self.validate(manifest, setup=run_then_drift_helper)
        self.assertFalse(result["valid"])
        self.assertEqual(result["derived_statuses"]["A001"]["derived"], "受阻")
        self.assertIn(
            "successful_record_not_qualifying",
            {item["code"] for item in result["errors"]},
        )

    def test_ready_guidance_cannot_hide_unknown_version(self) -> None:
        manifest = base_manifest()
        analysis = manifest["analyses"][0]
        manifest["task"]["mode"] = "code_guidance"
        analysis["code_guidance"] = {
            "status": "ready",
            "provenance": "generated_guidance",
            "entrypoint": "run.py",
            "dependencies": [{"name": "unknown-library", "version": "unknown"}],
            "seed": 7,
            "inputs": analysis["inputs_outputs"]["inputs"],
            "outputs": analysis["inputs_outputs"]["outputs"],
            "configurable_paths": ["--input", "--output-dir"],
            "minimal_run": "python run.py --input <input> --output-dir <output>",
            "unresolved_parameters": [],
            "blocker_ids": [],
        }
        result = self.validate(manifest)
        self.assertFalse(result["valid"])
        self.assertIn(
            "guidance_unknown_dependency_version",
            {item["code"] for item in result["errors"]},
        )

    def test_unreported_parameter_cannot_be_fabricated_into_ready_guidance(self) -> None:
        manifest = base_manifest()
        analysis = manifest["analyses"][0]
        manifest["task"]["mode"] = "code_guidance"
        analysis["method_parameters"]["parameters"].append(
            {
                "name": "mystery",
                "value": 42,
                "value_status": "unreported",
                "evidence_refs": ["E_METHOD"],
            }
        )
        analysis["code_guidance"] = {
            "status": "ready",
            "provenance": "generated_guidance",
            "entrypoint": "run.py",
            "dependencies": [{"name": "python", "version": sys.version.split()[0]}],
            "seed": 7,
            "inputs": analysis["inputs_outputs"]["inputs"],
            "outputs": analysis["inputs_outputs"]["outputs"],
            "configurable_paths": ["--input", "--output-dir"],
            "minimal_run": (
                "python run.py --input <input> --output-dir <output> --mystery 42 --seed 7"
            ),
            "unresolved_parameters": [],
            "blocker_ids": [],
        }
        result = self.validate(manifest)
        self.assertFalse(result["valid"])
        codes = {item["code"] for item in result["errors"]}
        self.assertIn("fabricated_unreported_parameter", codes)
        self.assertIn("guidance_unresolved_method_parameters", codes)

    def test_ready_guidance_rejects_machine_endpoint_port_and_secret_arguments(self) -> None:
        manifest = base_manifest()
        analysis = manifest["analyses"][0]
        manifest["task"]["mode"] = "code_guidance"
        analysis["code_guidance"] = {
            "status": "ready",
            "provenance": "generated_guidance",
            "entrypoint": "C:/Users/example/run.py",
            "dependencies": [{"name": "python", "version": sys.version.split()[0]}],
            "seed": 7,
            "inputs": analysis["inputs_outputs"]["inputs"],
            "outputs": analysis["inputs_outputs"]["outputs"],
            "configurable_paths": ["--input", "--output-dir"],
            "minimal_run": (
                "python C:/Users/example/run.py --endpoint https://private.invalid/v1 "
                "--port 5055 --api-key literal-secret"
            ),
            "unresolved_parameters": [],
            "blocker_ids": [],
        }
        result = self.validate(manifest)
        self.assertFalse(result["valid"])
        self.assertIn("guidance_hardcoded_environment", {item["code"] for item in result["errors"]})

    def test_claim_language_cannot_exceed_recorded_ceiling(self) -> None:
        manifest = base_manifest()
        manifest["analyses"][0]["interpretation"]["reasonable_inference"] = [
            _statement(
                "The expression change drives disease and establishes a mechanism.",
                "E_CLAIM",
                "E_FIG",
            )
        ]
        result = self.validate(manifest)
        self.assertFalse(result["valid"])
        codes = {item["code"] for item in result["errors"]}
        self.assertIn("claim_exceeds_causal_evidence", codes)
        self.assertIn("claim_exceeds_mechanistic_evidence", codes)

    def test_subject_first_flux_and_definitive_mechanism_language_is_bounded(self) -> None:
        cases = (
            ("Metabolic flux increased in group B.", "claim_exceeds_flux_evidence"),
            ("The analysis shows increased metabolic flux.", "claim_exceeds_flux_evidence"),
            ("\u4ee3\u8c22\u901a\u91cf\u5347\u9ad8\u3002", "claim_exceeds_flux_evidence"),
            (
                "Gene X is responsible for disease progression.",
                "claim_exceeds_causal_evidence",
            ),
            ("Gene X mediates drug resistance.", "claim_exceeds_mechanistic_evidence"),
            ("Gene X controls cell fate.", "claim_exceeds_mechanistic_evidence"),
            ("Gene X controls gene expression.", "claim_exceeds_mechanistic_evidence"),
            ("Gene X regulates Y expression.", "claim_exceeds_mechanistic_evidence"),
            ("Gene X is required for survival.", "claim_exceeds_causal_evidence"),
            ("Gene X determines treatment response.", "claim_exceeds_causal_evidence"),
            ("Gene X determines Y expression.", "claim_exceeds_causal_evidence"),
            ("\u57fa\u56e0X\u4ecb\u5bfc\u8010\u836f\u3002", "claim_exceeds_mechanistic_evidence"),
            ("\u57fa\u56e0X\u8c03\u63a7\u57fa\u56e0Y\u8868\u8fbe\u3002", "claim_exceeds_mechanistic_evidence"),
            ("\u57fa\u56e0X\u51b3\u5b9a\u57fa\u56e0Y\u8868\u8fbe\u3002", "claim_exceeds_causal_evidence"),
            (
                "Gene X may be expressed, but it mediates drug resistance.",
                "claim_exceeds_mechanistic_evidence",
            ),
            (
                "Gene X might correlate with response, while gene Y determines treatment response.",
                "claim_exceeds_causal_evidence",
            ),
            (
                "Whether X matters is unclear, but Y is responsible for progression.",
                "claim_exceeds_causal_evidence",
            ),
        )
        for statement, expected_code in cases:
            with self.subTest(statement=statement):
                manifest = base_manifest()
                manifest["analyses"][0]["interpretation"]["direct_observation"][0][
                    "statement"
                ] = statement
                result = self.validate(manifest)
                self.assertFalse(result["valid"])
                self.assertIn(expected_code, {item["code"] for item in result["errors"]})

        controls = (
            ("paper_claim", "The paper reports that metabolic flux increased in group B."),
            ("unverified", "Whether metabolic flux increased remains unverified."),
            ("reasonable_inference", "Gene X may mediate drug resistance."),
            ("reasonable_inference", "Gene X may regulate gene Y expression."),
            ("direct_observation", "A higher metabolic flux score was observed in group B."),
            ("direct_observation", "The metabolic flux score increased in group B."),
            ("direct_observation", "Batch metadata were required for covariate adjustment."),
            ("direct_observation", "The input matrix is required for this analysis."),
            ("direct_observation", "Samples were sufficient for the descriptive summary."),
            ("direct_observation", "Expression features were sufficient for classification."),
            ("direct_observation", "Methods metadata are necessary for reproducibility."),
            ("direct_observation", "The model controls for batch effects."),
            ("direct_observation", "The workflow controls false discovery rate."),
            ("direct_observation", "The analysis controls technical covariates."),
            ("direct_observation", "Normalization determines gene expression levels."),
            ("direct_observation", "The assay controls transcription measurement."),
            ("direct_observation", "The model controls protein abundance estimates."),
            ("direct_observation", "The workflow regulates expression output formatting."),
        )
        for lane, statement in controls:
            with self.subTest(control_lane=lane):
                manifest = base_manifest()
                manifest["analyses"][0]["interpretation"][lane] = [
                    _statement(
                        statement,
                        "E_FIG" if lane == "direct_observation" else "E_CLAIM",
                    )
                ]
                result = self.validate(manifest)
                self.assertTrue(result["valid"], result["errors"])

    def test_execution_scope_without_linked_record_derives_blocked(self) -> None:
        manifest = base_manifest()
        manifest["task"].update(
            {"mode": "execution", "execution_requested": True, "execution_scope": "execute_now"}
        )
        result = self.validate(manifest)
        self.assertFalse(result["valid"])
        self.assertEqual(result["derived_statuses"]["A001"]["derived"], "受阻")
        self.assertTrue(
            any("links none" in reason for reason in result["derived_statuses"]["A001"]["reasons"])
        )

    def test_missing_input_fingerprint_derives_blocked(self) -> None:
        manifest = base_manifest()

        def erase_input_fingerprint(_root: Path, value: dict) -> None:
            value["analyses"][0]["inputs_outputs"]["inputs"][0]["fingerprint"] = None

        result = self.validate(manifest, setup=erase_input_fingerprint)
        self.assertFalse(result["valid"])
        self.assertEqual(result["derived_statuses"]["A001"]["derived"], "受阻")

    def test_unreported_parameter_derives_blocked_even_without_manual_gap(self) -> None:
        manifest = base_manifest()
        manifest["analyses"][0]["method_parameters"]["parameters"].append(
            {
                "name": "normalization_method",
                "value": None,
                "value_status": "unreported",
                "evidence_refs": ["E_METHOD"],
            }
        )
        result = self.validate(manifest)
        self.assertFalse(result["valid"])
        self.assertEqual(result["derived_statuses"]["A001"]["derived"], "受阻")

    def test_direct_evidence_requires_matching_lane_role_and_available_source(self) -> None:
        manifest = base_manifest()
        evidence = manifest["analyses"][0]["paper_claim"]["evidence"][0]
        evidence["lane"] = "figure"
        manifest["sources"][0]["availability"] = "missing"
        manifest["sources"][0]["fingerprint"] = None
        result = self.validate(manifest)
        self.assertFalse(result["valid"])
        codes = {item["code"] for item in result["errors"]}
        self.assertIn("evidence_lane_mismatch", codes)
        self.assertIn("direct_evidence_source_unavailable", codes)
        self.assertEqual(result["derived_statuses"]["A001"]["derived"], "受阻")

    def test_claim_strength_audit_requires_paper_figure_and_method_lanes(self) -> None:
        manifest = base_manifest()
        claim_audit = next(
            item
            for item in manifest["analyses"][0]["scientific_audit"]
            if item["topic"] == "claim_strength"
        )
        claim_audit["evidence_refs"] = ["E_METHOD"]
        result = self.validate(manifest)
        self.assertFalse(result["valid"])
        self.assertIn(
            "scientific_audit_wrong_evidence_lane",
            {item["code"] for item in result["errors"]},
        )

    def test_ready_guidance_rejects_pseudocode_and_io_drift(self) -> None:
        manifest = base_manifest()
        analysis = manifest["analyses"][0]
        manifest["task"]["mode"] = "code_guidance"
        drifted_inputs = [dict(item) for item in analysis["inputs_outputs"]["inputs"]]
        drifted_inputs[0]["semantic_type"] = "silently changed input meaning"
        analysis["code_guidance"] = {
            "status": "ready",
            "provenance": "pseudocode_only",
            "entrypoint": "code/analysis.py",
            "dependencies": [{"name": "python", "version": sys.version.split()[0]}],
            "seed": 7,
            "inputs": drifted_inputs,
            "outputs": analysis["inputs_outputs"]["outputs"],
            "configurable_paths": ["--input", "--output-dir"],
            "minimal_run": (
                "python code/analysis.py --input <input.tsv> --output-dir <new-output-dir> --seed 7"
            ),
            "unresolved_parameters": [],
            "blocker_ids": [],
        }
        result = self.validate(manifest)
        self.assertFalse(result["valid"])
        codes = {item["code"] for item in result["errors"]}
        self.assertIn("guidance_pseudocode_not_ready", codes)
        self.assertIn("guidance_input_contract_mismatch", codes)

    def test_ready_guidance_rejects_bare_endpoint_listen_port_and_credential(self) -> None:
        manifest = base_manifest()
        analysis = manifest["analyses"][0]
        manifest["task"]["mode"] = "code_guidance"
        analysis["code_guidance"] = {
            "status": "ready",
            "provenance": "generated_guidance",
            "entrypoint": "code/analysis.py",
            "dependencies": [{"name": "python", "version": sys.version.split()[0]}],
            "seed": 7,
            "inputs": analysis["inputs_outputs"]["inputs"],
            "outputs": analysis["inputs_outputs"]["outputs"],
            "configurable_paths": ["--input", "--output-dir"],
            "minimal_run": (
                "python code/analysis.py --input <input> --output-dir <output> --seed 7 "
                "--endpoint api.internal:5055 --listen-port 5055 --credential literal"
            ),
            "unresolved_parameters": [],
            "blocker_ids": [],
        }
        result = self.validate(manifest)
        self.assertFalse(result["valid"])
        self.assertIn("guidance_hardcoded_environment", {item["code"] for item in result["errors"]})

    def test_ready_guidance_command_must_execute_entrypoint_and_seed(self) -> None:
        manifest = base_manifest()
        analysis = manifest["analyses"][0]
        manifest["task"]["mode"] = "code_guidance"
        analysis["code_guidance"] = {
            "status": "ready",
            "provenance": "generated_guidance",
            "entrypoint": "code/analysis.py",
            "dependencies": [{"name": "python", "version": sys.version.split()[0]}],
            "seed": 7,
            "inputs": analysis["inputs_outputs"]["inputs"],
            "outputs": analysis["inputs_outputs"]["outputs"],
            "configurable_paths": ["--input", "--output-dir"],
            "minimal_run": "echo code/analysis.py --input <input> --output-dir <output>",
            "unresolved_parameters": [],
            "blocker_ids": [],
        }
        result = self.validate(manifest)
        self.assertFalse(result["valid"])
        codes = {item["code"] for item in result["errors"]}
        self.assertIn("guidance_command_does_not_execute_entrypoint", codes)
        self.assertIn("guidance_seed_not_in_command", codes)

    def test_analysis_fingerprint_must_match_qualifying_execution(self) -> None:
        manifest = base_manifest()

        def corrupt_analysis_fingerprint(root: Path, value: dict) -> None:
            _run_successful_fixture(root, value)
            value["analyses"][0]["inputs_outputs"]["outputs"][0]["fingerprint"] = "f" * 64

        result = self.validate(manifest, setup=corrupt_analysis_fingerprint)
        self.assertFalse(result["valid"])
        self.assertIn("successful_record_not_qualifying", {item["code"] for item in result["errors"]})
        self.assertEqual(result["derived_statuses"]["A001"]["derived"], "受阻")

    def test_passed_check_must_name_analysis_and_cover_output(self) -> None:
        manifest = base_manifest()

        def detach_check(root: Path, value: dict) -> None:
            _run_successful_fixture(root, value)
            value["execution_records"][0]["checks"][0]["analysis_ids"] = ["A999"]
            value["execution_records"][0]["checks"][0]["evidence_paths"] = [
                "runs/RUN_OK/stdout.log"
            ]

        result = self.validate(manifest, setup=detach_check)
        self.assertFalse(result["valid"])
        self.assertIn("successful_record_not_qualifying", {item["code"] for item in result["errors"]})

    def test_execution_receipt_hash_is_verified(self) -> None:
        manifest = base_manifest()

        def alter_receipt(root: Path, value: dict) -> None:
            _run_successful_fixture(root, value)
            receipt_path = root / value["execution_records"][0]["receipt_path"]
            receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
            receipt["nonce"] = "0" * 32
            receipt_path.write_text(json.dumps(receipt, indent=2) + "\n", encoding="utf-8")

        result = self.validate(manifest, setup=alter_receipt)
        self.assertFalse(result["valid"])
        self.assertIn("successful_record_not_qualifying", {item["code"] for item in result["errors"]})

    def test_echo_command_cannot_masquerade_as_entrypoint_execution(self) -> None:
        manifest = base_manifest()

        def forge_echo(root: Path, value: dict) -> None:
            _run_successful_fixture(root, value)
            record = value["execution_records"][0]
            argv = ["echo", "code/analysis.py", "data/input.tsv", "runs/RUN_OK", "7"]
            record["command_argv"] = argv
            record["command"] = subprocess.list2cmdline(argv)
            receipt_path = root / record["receipt_path"]
            receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
            receipt["command_argv"] = argv
            receipt["command"] = record["command"]
            receipt_path.write_text(json.dumps(receipt, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
            record["receipt_sha256"] = _sha256(receipt_path)

        result = self.validate(manifest, setup=forge_echo)
        self.assertFalse(result["valid"])
        self.assertIn("successful_record_not_qualifying", {item["code"] for item in result["errors"]})
        gaps = " ".join(item["message"] for item in result["errors"])
        self.assertIn("compatible launcher", gaps)

    def test_duplicate_analysis_artifact_ids_are_rejected(self) -> None:
        manifest = base_manifest()
        manifest["analyses"][0]["inputs_outputs"]["outputs"][0]["artifact_id"] = "IN001"
        result = self.validate(manifest)
        self.assertFalse(result["valid"])
        self.assertIn("duplicate_analysis_artifact_id", {item["code"] for item in result["errors"]})

    def test_empty_report_is_rejected(self) -> None:
        manifest = base_manifest()
        result = self.validate(manifest, report="")
        self.assertFalse(result["valid"])
        codes = {item["code"] for item in result["errors"]}
        self.assertIn("report_too_short", codes)
        self.assertIn("report_missing_analysis", codes)

    def test_blocked_guidance_preserves_unknown_parameter(self) -> None:
        manifest = base_manifest()
        analysis = manifest["analyses"][0]
        manifest["task"]["mode"] = "code_guidance"
        analysis["method_parameters"]["parameters"].append(
            {
                "name": "normalization_method",
                "value": None,
                "value_status": "unreported",
                "evidence_refs": ["E_METHOD"],
            }
        )
        analysis["conflicts_gaps"] = [
            {
                "issue_id": "G_NORMALIZATION",
                "kind": "gap",
                "topic": "normalization parameter",
                "description": "The normalization method is not reported in the supplied materials.",
                "impact": "An executable faithful command cannot be specified.",
                "evidence_refs": ["E_METHOD"],
                "blocking": True,
                "resolved": False,
            }
        ]
        analysis["code_guidance"] = {
            "status": "blocked",
            "provenance": "pseudocode_only",
            "entrypoint": None,
            "dependencies": [{"name": "python", "version": sys.version.split()[0]}],
            "seed": "unknown",
            "inputs": analysis["inputs_outputs"]["inputs"],
            "outputs": analysis["inputs_outputs"]["outputs"],
            "configurable_paths": ["--input", "--output-dir"],
            "minimal_run": None,
            "unresolved_parameters": ["normalization_method"],
            "blocker_ids": ["G_NORMALIZATION"],
        }
        for audit in analysis["scientific_audit"]:
            if audit["topic"] in {"preprocessing", "parameter_consistency"}:
                audit.update(
                    {
                        "status": "blocked",
                        "finding": (
                            f"{audit['topic']} is blocked because normalization is unreported; "
                            "no value was fabricated."
                        ),
                        "claim_ceiling": "not_assessable",
                    }
                )
        analysis["interpretation"] = {
            "direct_observation": [
                _statement("The supplied Methods omit normalization details.", "E_METHOD")
            ],
            "paper_claim": [
                _statement("The fixture paper claims a group difference.", "E_CLAIM")
            ],
            "reconstructed_support": [
                _statement(
                    "Only paper-scoped Methods evidence and generated guidance structure can be supplied safely.",
                    "E_CLAIM",
                    "E_METHOD",
                )
            ],
            "reasonable_inference": [],
            "unverified": [
                _statement(
                    "The faithful executable preprocessing step is not verifiable.",
                    "E_METHOD",
                )
            ],
        }
        analysis["reproduction_status"] = "受阻"
        manifest["overall_status"] = "受阻"
        manifest["stage_state"][3]["status"] = "blocked"
        manifest["stage_state"][3]["blockers"] = ["G_NORMALIZATION"]
        manifest["stage_state"][4]["status"] = "not_started"
        result = self.validate(manifest)
        self.assertTrue(result["valid"], result["errors"])
        self.assertEqual(result["derived_statuses"]["A001"]["derived"], "受阻")

    def test_input_output_and_log_roles_cannot_share_one_file(self) -> None:
        manifest = base_manifest()

        def forge_roles(root: Path, value: dict) -> None:
            analysis = value["analyses"][0]
            value["task"].update(
                {"mode": "execution", "execution_requested": True, "execution_scope": "execute_now"}
            )
            started = _utc_now()
            run_dir = root / "runs/RUN_ROLE"
            run_dir.mkdir(parents=True)
            shared = run_dir / "shared.txt"
            shared.write_text("pre-existing content\n", encoding="utf-8")
            finished = _utc_now()
            digest = _sha256(shared)
            analysis["inputs_outputs"] = {
                "inputs": [
                    {
                        "artifact_id": "IN_SHARED",
                        "path": "runs/RUN_ROLE/shared.txt",
                        "semantic_type": "forged shared input",
                        "fingerprint": f"sha256:{digest}",
                    }
                ],
                "outputs": [
                    {
                        "artifact_id": "OUT_SHARED",
                        "path": "runs/RUN_ROLE/shared.txt",
                        "semantic_type": "forged shared output",
                        "fingerprint": f"sha256:{digest}",
                    }
                ],
            }
            value["execution_records"] = [
                {
                    "execution_id": "RUN_ROLE",
                    "analysis_ids": ["A001"],
                    "command": "python code/analysis.py --input runs/RUN_ROLE/shared.txt",
                    "command_argv": ["python", "code/analysis.py", "--input", "runs/RUN_ROLE/shared.txt"],
                    "attempt_status": "succeeded",
                    "entrypoint": "code/analysis.py",
                    "code_evidence_refs": ["E_CODE"],
                    "code_snapshot_sha256": _sha256(root / "code/analysis.py"),
                    "code_files": [
                        {
                            "path": "code/analysis.py",
                            "sha256": _sha256(root / "code/analysis.py"),
                        }
                    ],
                    "working_directory": ".",
                    "started_at_utc": started,
                    "finished_at_utc": finished,
                    "exit_code": 0,
                    "dependencies": [{"name": "python", "version": sys.version.split()[0]}],
                    "seed": 7,
                    "inputs": [
                        {
                            "artifact_id": "IN_SHARED",
                            "path": "runs/RUN_ROLE/shared.txt",
                            "sha256": digest,
                            "semantic_type": "forged shared input",
                        }
                    ],
                    "outputs": [
                        {
                            "artifact_id": "OUT_SHARED",
                            "path": "runs/RUN_ROLE/shared.txt",
                            "sha256": digest,
                            "semantic_type": "forged shared output",
                            "analysis_ids": ["A001"],
                        }
                    ],
                    "stdout_log": "runs/RUN_ROLE/shared.txt",
                    "stderr_log": "runs/RUN_ROLE/shared.txt",
                    "checks": [
                        {
                            "check_id": "CHK_ROLE_SHARING",
                            "metric": "role_sharing",
                            "unit": "not_applicable",
                            "check": "forged role-sharing check",
                            "observed": "same file",
                            "passed": True,
                            "analysis_ids": ["A001"],
                            "evidence_paths": ["runs/RUN_ROLE/shared.txt"],
                            "verification": {
                                "kind": "text_contains",
                                "evidence_path": "runs/RUN_ROLE/shared.txt",
                                "selector": None,
                                "expected": "pre-existing content",
                            },
                        }
                    ],
                    "preflight": {
                        "authorization_basis": "explicit_execution_request",
                        "status": "passed",
                        "source_read_only": True,
                        "output_directory": "runs/RUN_ROLE",
                        "environment": "existing",
                        "network_used": False,
                        "notes": [],
                    },
                    "code_provenance": "source_exact",
                    "receipt_path": "runs/RUN_ROLE/execution_receipt.json",
                    "receipt_sha256": "c" * 64,
                    "supersedes_execution_ids": [],
                }
            ]
            analysis["execution_record_ids"] = ["RUN_ROLE"]
            analysis["reproduction_status"] = "已执行验证"
            value["overall_status"] = "已执行验证"

        result = self.validate(manifest, setup=forge_roles)
        self.assertFalse(result["valid"])
        self.assertEqual(result["derived_statuses"]["A001"]["derived"], "受阻")
        self.assertIn("successful_record_not_qualifying", {item["code"] for item in result["errors"]})

    def test_failed_attempt_before_qualifying_success_does_not_force_blocked(self) -> None:
        manifest = base_manifest()

        def fail_then_succeed(root: Path, value: dict) -> None:
            child_command = [
                sys.executable,
                "code/analysis.py",
                "--input",
                "data/input.tsv",
                "--output-dir",
                "runs/RUN_FAILED_FIRST",
                "--seed",
                "7",
            ]
            runner_command = [
                sys.executable,
                str(RUNNER_PATH),
                "--project-dir",
                str(root),
                "--execution-id",
                "RUN_FAILED_FIRST",
                "--analysis-id",
                "A001",
                "--entrypoint",
                "code/analysis.py",
                "--code-evidence-ref",
                "E_CODE",
                "--input-spec",
                json.dumps(
                    {
                        "artifact_id": "IN001",
                        "path": "data/input.tsv",
                        "semantic_type": "sample-level measurements",
                    }
                ),
                "--output-spec",
                json.dumps(
                    {
                        "artifact_id": "OUT001",
                        "path": "runs/RUN_FAILED_FIRST/group_test.tsv",
                        "semantic_type": "group comparison table",
                    }
                ),
                "--dependency",
                f"python={sys.version.split()[0]}",
                "--seed",
                "7",
                "--",
                *child_command,
            ]
            wrapper = subprocess.run(
                runner_command, cwd=root, capture_output=True, text=True, check=False
            )
            if wrapper.returncode != 0:
                raise AssertionError(f"first runner failed: {wrapper.stdout}\n{wrapper.stderr}")
            failed_dir = root / "runs/RUN_FAILED_FIRST"
            failed_checks = [
                {
                    "check_id": "CHK_FAILED_MEAN_DIFF",
                    "metric": "mean_difference_B_minus_A",
                    "unit": "dimensionless",
                    "check": "first attempt scientific assertion intentionally fails",
                    "observed": "3.0",
                    "passed": False,
                    "analysis_ids": ["A001"],
                    "evidence_paths": ["runs/RUN_FAILED_FIRST/group_test.tsv"],
                    "verification": _group_result_verification(
                        "RUN_FAILED_FIRST", expected="999.0"
                    ),
                }
            ]
            failed_checks_path = root / "checks.RUN_FAILED_FIRST.json"
            failed_checks_path.write_text(
                json.dumps(failed_checks, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )
            adjudication = subprocess.run(
                [
                    sys.executable,
                    str(FINALIZER_PATH),
                    "--project-dir",
                    str(root),
                    "--execution-id",
                    "RUN_FAILED_FIRST",
                    "--checks-json",
                    str(failed_checks_path),
                ],
                cwd=root,
                capture_output=True,
                text=True,
                check=False,
            )
            if adjudication.returncode != 0:
                raise AssertionError(
                    f"first finalizer failed: {adjudication.stdout}\n{adjudication.stderr}"
                )
            failed = json.loads(
                (failed_dir / "execution_record.fragment.json").read_text(encoding="utf-8")
            )
            if failed.get("attempt_status") != "failed":
                raise AssertionError(f"first attempt was not adjudicated failed: {failed}")
            _run_successful_fixture(root, value, supersedes=["RUN_FAILED_FIRST"])
            analysis = value["analyses"][0]
            value["execution_records"].insert(0, failed)
            analysis["execution_record_ids"] = ["RUN_FAILED_FIRST", "RUN_OK"]

        result = self.validate(
            manifest,
            setup=fail_then_succeed,
        )
        self.assertTrue(result["valid"], result["errors"])
        self.assertEqual(result["derived_statuses"]["A001"]["derived"], "已执行验证")
        self.assertTrue(any(item["code"] == "execution_not_qualifying" for item in result["warnings"]))

    def test_trace_cells_must_link_back_to_manifest(self) -> None:
        manifest = base_manifest()

        def remove_method_link(row: dict) -> None:
            row["method与参数"] = "generic method description"

        result = self.validate(manifest, row_mutator=remove_method_link)
        self.assertFalse(result["valid"])
        self.assertIn("trace_lane_mismatch", {item["code"] for item in result["errors"]})

    def test_execution_id_path_traversal_is_rejected(self) -> None:
        manifest = base_manifest()

        def forge_id(root: Path, value: dict) -> None:
            _add_failed_environment_record(root, value)
            value["execution_records"][0]["execution_id"] = "../agents"
            value["analyses"][0]["execution_record_ids"] = ["../agents"]

        result = self.validate(manifest, setup=forge_id)
        self.assertFalse(result["valid"])
        self.assertIn("invalid_execution_id", {item["code"] for item in result["errors"]})

    def test_pending_checks_cannot_qualify_as_executed(self) -> None:
        manifest = base_manifest()

        def revert_to_pending(root: Path, value: dict) -> None:
            _run_successful_fixture(root, value)
            record = value["execution_records"][0]
            record.update(
                {
                    "attempt_status": "pending_checks",
                    "checks": [],
                    "checks_sha256": VALIDATOR._canonical_sha256([]),
                    "adjudication_status": "pending_checks",
                    "adjudicated_at_utc": None,
                }
            )

            def mutate(receipt: dict) -> None:
                receipt.update(
                    {
                        "checks": [],
                        "checks_sha256": VALIDATOR._canonical_sha256([]),
                        "adjudication_status": "pending_checks",
                        "adjudicated_at_utc": None,
                    }
                )

            _rewrite_receipt(root, record, mutate)

        result = self.validate(manifest, setup=revert_to_pending)
        self.assertFalse(result["valid"])
        self.assertEqual(result["derived_statuses"]["A001"]["derived"], "受阻")
        self.assertIn("status_mismatch", {item["code"] for item in result["errors"]})

    def test_receipt_checks_hash_is_bound_to_adjudication(self) -> None:
        manifest = base_manifest()

        def forge_checks_hash(root: Path, value: dict) -> None:
            _run_successful_fixture(root, value)
            record = value["execution_records"][0]
            _rewrite_receipt(
                root,
                record,
                lambda receipt: receipt.__setitem__("checks_sha256", "0" * 64),
            )

        result = self.validate(manifest, setup=forge_checks_hash)
        self.assertFalse(result["valid"])
        qualifying = [
            item for item in result["errors"] if item["code"] == "successful_record_not_qualifying"
        ]
        self.assertTrue(qualifying)
        self.assertIn("receipt checks SHA-256 mismatch", qualifying[0]["message"])

    def test_finalized_attempt_cannot_be_readjudicated_in_place(self) -> None:
        manifest = base_manifest()

        def try_rewrite(root: Path, value: dict) -> None:
            _run_successful_fixture(root, value)
            completed = subprocess.run(
                [
                    sys.executable,
                    str(FINALIZER_PATH),
                    "--project-dir",
                    str(root),
                    "--execution-id",
                    "RUN_OK",
                    "--checks-json",
                    str(root / "checks.RUN_OK.json"),
                ],
                cwd=root,
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertNotEqual(completed.returncode, 0)
            self.assertIn("already adjudicated", completed.stderr)

        result = self.validate(manifest, setup=try_rewrite)
        self.assertTrue(result["valid"], result["errors"])

    def test_passed_audit_cannot_cite_unavailable_direct_material(self) -> None:
        manifest = base_manifest()
        manifest["sources"][2].update(
            {"availability": "missing", "fingerprint": None, "locator_type": "unavailable"}
        )
        result = self.validate(manifest)
        self.assertFalse(result["valid"])
        self.assertIn(
            "scientific_audit_unavailable_evidence",
            {item["code"] for item in result["errors"]},
        )

    def test_undeclared_methods_code_parameter_conflict_is_detected(self) -> None:
        manifest = base_manifest()
        analysis = manifest["analyses"][0]
        analysis["method_parameters"]["parameters"].append(
            {
                "name": "ALPHA",
                "value": 0.10,
                "value_status": "implemented",
                "evidence_refs": ["E_CODE"],
                "implementation_literal": "ALPHA = 0.10",
            }
        )
        analysis["reproduction_status"] = "材料冲突"
        manifest["overall_status"] = "材料冲突"

        def expose_conflict(root: Path, value: dict) -> None:
            code_path = root / "code/analysis.py"
            code_path.write_text(
                code_path.read_text(encoding="utf-8") + "\nALPHA = 0.10\n",
                encoding="utf-8",
            )
            fingerprint = f"sha256:{_sha256(code_path)}"
            value["sources"][3]["fingerprint"] = fingerprint
            value["analyses"][0]["code_locations"][0]["snapshot"] = fingerprint
            source_fingerprint = VALIDATOR._source_set_fingerprint(value["sources"])
            for stage in value["stage_state"]:
                stage["input_fingerprint"] = source_fingerprint

        result = self.validate(manifest, setup=expose_conflict)
        self.assertFalse(result["valid"])
        self.assertEqual(result["derived_statuses"]["A001"]["derived"], "材料冲突")
        self.assertIn("undeclared_parameter_conflict", {item["code"] for item in result["errors"]})

    def test_observed_runtime_parameter_must_match_bound_observation(self) -> None:
        manifest = base_manifest()

        def bind_seed_then_misstate(root: Path, value: dict) -> None:
            _run_successful_fixture(
                root,
                value,
                observed_parameters=[
                    {
                        "name": "seed",
                        "value": 7,
                        "evidence_paths": ["runs/RUN_OK/stdout.log"],
                    }
                ],
            )
            value["analyses"][0]["method_parameters"]["parameters"].append(
                {
                    "name": "seed",
                    "value": 999,
                    "value_status": "observed_runtime",
                    "evidence_refs": ["E_CODE"],
                    "execution_record_refs": ["RUN_OK"],
                }
            )

        result = self.validate(manifest, setup=bind_seed_then_misstate)
        self.assertFalse(result["valid"])
        self.assertIn("observed_runtime_value_mismatch", {item["code"] for item in result["errors"]})

    def test_finalizer_validator_binding_round_trip_variants(self) -> None:
        manifest = base_manifest()

        def bind_variants(root: Path, value: dict) -> None:
            output_value = str(Path("runs/RUN_OK/group_test.tsv"))
            observations = [
                {
                    "name": "output",
                    "value": output_value,
                    "evidence_paths": ["runs/RUN_OK/stdout.log"],
                },
                {
                    "name": "json_seed",
                    "value": 7,
                    "evidence_paths": ["runs/RUN_OK/stdout.log"],
                },
            ]
            _run_successful_fixture(
                root,
                value,
                observed_parameters=observations,
                additional_checks=[
                    {
                        "check": "fixture emitted the boolean check_passed marker",
                        "observed": True,
                        "passed": True,
                        "analysis_ids": ["A001"],
                        "evidence_paths": ["runs/RUN_OK/stdout.log"],
                        "verification": {
                            "kind": "text_contains",
                            "evidence_path": "runs/RUN_OK/stdout.log",
                            "selector": None,
                            "expected": "check_passed=True",
                        },
                    }
                ],
            )

        result = self.validate(manifest, setup=bind_variants)
        self.assertTrue(result["valid"], result["errors"])
        self.assertEqual(result["derived_statuses"]["A001"]["derived"], "已执行验证")

    def test_active_code_source_must_identify_same_file(self) -> None:
        manifest = base_manifest()

        def point_to_other_file(root: Path, value: dict) -> None:
            alternate = root / "code/alternate.py"
            alternate.write_text(
                (root / "code/analysis.py").read_text(encoding="utf-8"), encoding="utf-8"
            )
            code_item = value["analyses"][0]["code_locations"][0]
            code_item["path"] = "code/alternate.py"
            code_item["snapshot"] = f"sha256:{_sha256(alternate)}"

        result = self.validate(manifest, setup=point_to_other_file)
        self.assertFalse(result["valid"])
        self.assertIn("active_code_source_path_mismatch", {item["code"] for item in result["errors"]})

    def test_report_cannot_overstate_causal_support(self) -> None:
        manifest = base_manifest()
        report = (
            "# Contract fixture\n\n- A001: 材料完整但未执行\n\n"
            "## Direct observation\nThe paper claims X causes Y; that claim remains attributed.\n\n"
            "## Reasonable inference\nOur reconstruction proves treatment X causes disease Y.\n\n"
            "## Unverified\nExecution remains unverified.\n"
        )
        result = self.validate(manifest, report=report)
        self.assertFalse(result["valid"])
        self.assertIn("claim_exceeds_causal_evidence", {item["code"] for item in result["errors"]})

    def test_blocked_status_requires_stage_linked_blocker(self) -> None:
        manifest = base_manifest()
        analysis = manifest["analyses"][0]
        analysis["conflicts_gaps"] = [
            {
                "issue_id": "G_UNTRACKED",
                "kind": "gap",
                "topic": "untracked prerequisite",
                "description": "A required prerequisite remains unavailable for this analysis.",
                "impact": "The analysis cannot proceed to faithful execution.",
                "evidence_refs": ["E_METHOD"],
                "blocking": True,
                "resolved": False,
            }
        ]
        analysis["reproduction_status"] = "受阻"
        manifest["overall_status"] = "受阻"
        result = self.validate(manifest)
        self.assertFalse(result["valid"])
        self.assertIn("blocked_without_stage_blocker", {item["code"] for item in result["errors"]})

    def test_one_execution_can_qualify_two_linked_analyses(self) -> None:
        manifest = base_manifest()
        second = copy.deepcopy(manifest["analyses"][0])
        second["analysis_id"] = "A002"
        evidence_mapping = {
            "E_CLAIM": "E_CLAIM2",
            "E_FIG": "E_FIG2",
            "E_METHOD": "E_METHOD2",
            "E_CODE": "E_CODE2",
        }
        for group in ("paper_claim", "figure_panel", "method_parameters"):
            for evidence in second[group]["evidence"]:
                evidence["evidence_id"] = evidence_mapping[evidence["evidence_id"]]
        second["figure_panel"]["ids"] = ["Fig1A-secondary-audit"]
        second["code_locations"][0]["evidence_id"] = "E_CODE2"
        for parameter in second["method_parameters"]["parameters"]:
            parameter["evidence_refs"] = [
                evidence_mapping.get(ref, ref) for ref in parameter["evidence_refs"]
            ]
        for audit in second["scientific_audit"]:
            audit["evidence_refs"] = [
                evidence_mapping.get(ref, ref) for ref in audit["evidence_refs"]
            ]
        for statements in second["interpretation"].values():
            for statement in statements:
                statement["evidence_refs"] = [
                    evidence_mapping.get(ref, ref) for ref in statement["evidence_refs"]
                ]
        manifest["analyses"].append(second)

        def execute_both(root: Path, value: dict) -> None:
            value["analyses"][1]["code_locations"][0]["snapshot"] = value["analyses"][0][
                "code_locations"
            ][0]["snapshot"]
            _run_successful_fixture(
                root,
                value,
                execution_analysis_ids=["A001", "A002"],
                execution_code_refs=["E_CODE", "E_CODE2"],
            )
            first = value["analyses"][0]
            second_analysis = value["analyses"][1]
            second_analysis["inputs_outputs"] = copy.deepcopy(first["inputs_outputs"])
            second_analysis["execution_record_ids"] = ["RUN_OK"]
            second_analysis["interpretation"] = copy.deepcopy(first["interpretation"])
            for statements in second_analysis["interpretation"].values():
                for statement in statements:
                    statement["evidence_refs"] = [
                        evidence_mapping.get(ref, ref) for ref in statement["evidence_refs"]
                    ]
            second_analysis["reproduction_status"] = "已执行验证"

        result = self.validate(manifest, setup=execute_both)
        self.assertTrue(result["valid"], result["errors"])
        self.assertEqual(result["derived_statuses"]["A001"]["derived"], "已执行验证")
        self.assertEqual(result["derived_statuses"]["A002"]["derived"], "已执行验证")

    def test_execution_orphan_output_is_rejected(self) -> None:
        manifest = base_manifest()

        def append_orphan(root: Path, value: dict) -> None:
            _run_successful_fixture(root, value)
            orphan_path = root / "runs/RUN_OK/orphan.tsv"
            orphan_path.write_text("orphan\tvalue\n", encoding="utf-8")
            artifact = {
                "artifact_id": "ORPHAN",
                "path": "runs/RUN_OK/orphan.tsv",
                "sha256": _sha256(orphan_path),
                "semantic_type": "undeclared extra result",
            }
            record = value["execution_records"][0]
            record["outputs"].append(artifact)
            _rewrite_receipt(
                root,
                record,
                lambda receipt: receipt["outputs"].append(copy.deepcopy(artifact)),
            )

        result = self.validate(manifest, setup=append_orphan)
        self.assertFalse(result["valid"])
        self.assertIn("execution_orphan_artifact", {item["code"] for item in result["errors"]})

    def test_unregistered_active_code_assignment_conflict_is_detected(self) -> None:
        manifest = base_manifest()

        def expose_unregistered_conflict(root: Path, value: dict) -> None:
            code_path = root / "code/analysis.py"
            code_path.write_text(
                code_path.read_text(encoding="utf-8") + "\nALPHA = 0.10\n",
                encoding="utf-8",
            )
            fingerprint = f"sha256:{_sha256(code_path)}"
            value["sources"][3]["fingerprint"] = fingerprint
            value["analyses"][0]["code_locations"][0]["snapshot"] = fingerprint
            source_fingerprint = VALIDATOR._source_set_fingerprint(value["sources"])
            for stage in value["stage_state"]:
                stage["input_fingerprint"] = source_fingerprint

        result = self.validate(manifest, setup=expose_unregistered_conflict)
        self.assertFalse(result["valid"])
        self.assertEqual(result["derived_statuses"]["A001"]["derived"], "材料冲突")
        self.assertIn("undeclared_parameter_conflict", {item["code"] for item in result["errors"]})

    def test_finalizer_rejects_runtime_parameter_not_present_in_log(self) -> None:
        manifest = base_manifest()
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _materialize_sources(root, manifest)
            with self.assertRaisesRegex(AssertionError, "must strictly equal"):
                _run_successful_fixture(
                    root,
                    manifest,
                    observed_parameters=[
                        {
                            "name": "seed",
                            "value": 999,
                            "evidence_paths": ["runs/RUN_OK/stdout.log"],
                        }
                    ],
                )

    def test_finalizer_rejects_passed_check_observation_absent_from_evidence(self) -> None:
        manifest = base_manifest()
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _materialize_sources(root, manifest)
            with self.assertRaisesRegex(AssertionError, "mechanically recomputed"):
                _run_successful_fixture(
                    root,
                    manifest,
                    check_observed="mean_difference_B_minus_A\t999.0",
                )

    def test_identical_bytes_at_unlinked_entrypoint_path_do_not_qualify(self) -> None:
        manifest = base_manifest()

        def execute_alternate(root: Path, value: dict) -> None:
            alternate = root / "code/alternate.py"
            alternate.write_bytes((root / "code/analysis.py").read_bytes())
            _run_successful_fixture(root, value, entrypoint="code/alternate.py")

        result = self.validate(manifest, setup=execute_alternate)
        self.assertFalse(result["valid"])
        errors = [
            item for item in result["errors"] if item["code"] == "successful_record_not_qualifying"
        ]
        self.assertTrue(errors)
        self.assertIn("entrypoint path does not equal", errors[0]["message"])

    def test_mixed_attribution_does_not_hide_reconstruction_causal_overclaim(self) -> None:
        manifest = base_manifest()
        report = (
            "# Contract fixture\n\nA001: 材料完整但未执行。\n\n"
            "The paper claims X correlates with Y, and our reconstruction proves X causes disease Y.\n\n"
            "## Direct observation\nRecorded source evidence only.\n\n"
            "## Reasonable inference\nAssociation only.\n\n"
            "## Unverified\nNo execution was performed.\n"
        )
        result = self.validate(manifest, report=report)
        self.assertFalse(result["valid"])
        self.assertIn("claim_exceeds_causal_evidence", {item["code"] for item in result["errors"]})

    def test_automatic_high_claim_ceiling_is_rejected(self) -> None:
        manifest = base_manifest()
        for audit in manifest["analyses"][0]["scientific_audit"]:
            audit["claim_ceiling"] = "mechanistic"
        result = self.validate(manifest)
        self.assertFalse(result["valid"])
        self.assertIn(
            "unsupported_automatic_high_claim_ceiling",
            {item["code"] for item in result["errors"]},
        )

    def test_partial_upstream_gate_blocks_downstream_completion(self) -> None:
        manifest = base_manifest()
        manifest["stage_state"][0]["status"] = "partial"
        result = self.validate(manifest)
        self.assertFalse(result["valid"])
        self.assertIn("stage_dependency_violation", {item["code"] for item in result["errors"]})

    def test_interpretation_statement_requires_evidence_refs(self) -> None:
        manifest = base_manifest()
        manifest["analyses"][0]["interpretation"]["direct_observation"][0][
            "evidence_refs"
        ] = []
        result = self.validate(manifest)
        self.assertFalse(result["valid"])
        self.assertIn("interpretation_statement_untraceable", {item["code"] for item in result["errors"]})

    def test_runner_rejects_python_option_that_consumes_entrypoint(self) -> None:
        manifest = base_manifest()
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _materialize_sources(root, manifest)
            child = [
                sys.executable,
                "-W",
                "code/analysis.py",
                "-c",
                "print('unrelated')",
                "data/input.tsv",
                "runs/RUN_BYPASS",
                "7",
            ]
            command = [
                sys.executable,
                str(RUNNER_PATH),
                "--project-dir",
                str(root),
                "--execution-id",
                "RUN_BYPASS",
                "--analysis-id",
                "A001",
                "--entrypoint",
                "code/analysis.py",
                "--code-evidence-ref",
                "E_CODE",
                "--input-spec",
                json.dumps(
                    {
                        "artifact_id": "IN001",
                        "path": "data/input.tsv",
                        "semantic_type": "sample-level measurements",
                    }
                ),
                "--output-spec",
                json.dumps(
                    {
                        "artifact_id": "OUT001",
                        "path": "runs/RUN_BYPASS/output.tsv",
                        "semantic_type": "unrelated output",
                    }
                ),
                "--dependency",
                f"python={sys.version.split()[0]}",
                "--seed",
                "7",
                "--",
                *child,
            ]
            completed = subprocess.run(
                command, cwd=root, capture_output=True, text=True, check=False
            )
            self.assertNotEqual(completed.returncode, 0)
            self.assertIn("compatible launcher", completed.stderr)
            self.assertFalse((root / "runs/RUN_BYPASS").exists())

    def test_runner_rejects_nonexecuting_python_version_flags(self) -> None:
        manifest = base_manifest()
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _materialize_sources(root, manifest)

            def invoke(execution_id: str, child: list[str]) -> subprocess.CompletedProcess[str]:
                command = [
                    sys.executable,
                    str(RUNNER_PATH),
                    "--project-dir",
                    str(root),
                    "--execution-id",
                    execution_id,
                    "--analysis-id",
                    "A001",
                    "--entrypoint",
                    "code/analysis.py",
                    "--code-evidence-ref",
                    "E_CODE",
                    "--input-spec",
                    json.dumps(
                        {
                            "artifact_id": "IN001",
                            "path": "data/input.tsv",
                            "semantic_type": "sample-level measurements",
                        }
                    ),
                    "--output-spec",
                    json.dumps(
                        {
                            "artifact_id": "OUT001",
                            "path": f"runs/{execution_id}/output.tsv",
                            "semantic_type": "group comparison table",
                        }
                    ),
                    "--dependency",
                    f"python={sys.version.split()[0]}",
                    "--seed",
                    "7",
                    "--",
                    *child,
                ]
                return subprocess.run(
                    command, cwd=root, capture_output=True, text=True, check=False
                )

            cases = {
                "RUN_VERSION": [sys.executable, "-V", "code/analysis.py"],
                "RUN_PYLIST": ["py", "-0", "code/analysis.py"],
            }
            for execution_id, child in cases.items():
                with self.subTest(execution_id=execution_id):
                    completed = invoke(execution_id, child)
                    self.assertNotEqual(completed.returncode, 0)
                    self.assertIn("compatible launcher", completed.stderr)
                    self.assertFalse((root / f"runs/{execution_id}").exists())

    def test_json_pointer_object_and_list_verification_has_finalizer_validator_parity(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            evidence = root / "result.json"
            evidence.write_text(
                '{"result":{"items":[{"value":3},{"value":4}]}}\n', encoding="utf-8"
            )
            expected = {"items": [{"value": 3}, {"value": 4}]}
            verification = {
                "kind": "json_pointer_equals",
                "evidence_path": "result.json",
                "selector": "/result",
                "expected": expected,
            }
            final_observed, final_passed = FINALIZER._recompute_check(
                root, verification, [evidence.resolve()], "checks[0]"
            )
            audit_observed, audit_passed, audit_error = VALIDATOR._evaluate_check_verification(
                root,
                verification,
                {evidence.resolve()},
                {evidence.resolve()},
            )
        self.assertEqual(final_observed, expected)
        self.assertTrue(final_passed)
        self.assertEqual(audit_observed, expected)
        self.assertTrue(audit_passed)
        self.assertIsNone(audit_error)

    def test_invalid_strict_json_and_pointer_are_rejected_by_both_adjudicators(self) -> None:
        cases = (
            ('{"value":1,"value":2}\n', "/value", "duplicate"),
            ('{"items":[1,2]}\n', "/items/01", "array index"),
            ('{"a~b":1}\n', "/a~2b", "RFC6901"),
        )
        for payload, selector, marker in cases:
            with self.subTest(marker=marker), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                evidence = root / "result.json"
                evidence.write_text(payload, encoding="utf-8")
                verification = {
                    "kind": "json_pointer_equals",
                    "evidence_path": "result.json",
                    "selector": selector,
                    "expected": 1,
                }
                with self.assertRaises(FINALIZER.FinalizationError):
                    FINALIZER._recompute_check(
                        root, verification, [evidence.resolve()], "checks[0]"
                    )
                _, _, audit_error = VALIDATOR._evaluate_check_verification(
                    root,
                    verification,
                    {evidence.resolve()},
                    {evidence.resolve()},
                )
                self.assertIsNotNone(audit_error)
                self.assertIn(marker, audit_error)

    def test_result_check_must_verify_the_declared_output_it_claims_to_cover(self) -> None:
        manifest = base_manifest()

        def redirect_check_to_log(root: Path, value: dict) -> None:
            _run_successful_fixture(root, value)
            record = value["execution_records"][0]
            check = record["checks"][0]
            check.update(
                {
                    "observed": True,
                    "passed": True,
                    "verification": {
                        "kind": "text_contains",
                        "evidence_path": "runs/RUN_OK/stdout.log",
                        "selector": None,
                        "expected": "seed=7",
                    },
                }
            )
            record["checks_sha256"] = VALIDATOR._canonical_sha256(record["checks"])
            _rewrite_receipt(
                root,
                record,
                lambda receipt: receipt.update(
                    {
                        "checks": copy.deepcopy(record["checks"]),
                        "checks_sha256": record["checks_sha256"],
                    }
                ),
            )

        result = self.validate(manifest, setup=redirect_check_to_log)
        self.assertFalse(result["valid"])
        messages = "\n".join(item["message"] for item in result["errors"])
        self.assertIn("lacks a passed linked result check", messages)

    def test_executed_active_default_drift_is_derived_as_material_conflict(self) -> None:
        manifest = base_manifest()

        def execute_drifted_default(root: Path, value: dict) -> None:
            code_path = root / "code/analysis.py"
            code_path.write_text(
                code_path.read_text(encoding="utf-8").replace(
                    'parser.add_argument("--alpha", type=float, default=ALPHA)',
                    'parser.add_argument("--alpha", type=float, default=0.10)',
                ),
                encoding="utf-8",
            )
            fingerprint = f"sha256:{_sha256(code_path)}"
            value["sources"][3]["fingerprint"] = fingerprint
            value["analyses"][0]["code_locations"][0]["snapshot"] = fingerprint
            source_fingerprint = VALIDATOR._source_set_fingerprint(value["sources"])
            for stage in value["stage_state"]:
                stage["input_fingerprint"] = source_fingerprint
            _run_successful_fixture(
                root,
                value,
                observed_parameters=[
                    {
                        "name": "alpha",
                        "value": 0.10,
                        "evidence_paths": ["runs/RUN_OK/stdout.log"],
                    }
                ],
            )

        result = self.validate(manifest, setup=execute_drifted_default)
        self.assertFalse(result["valid"])
        self.assertEqual(result["derived_statuses"]["A001"]["derived"], "材料冲突")
        self.assertIn("undeclared_parameter_conflict", {item["code"] for item in result["errors"]})

    def test_report_rejects_free_numerical_claim_not_present_in_manifest(self) -> None:
        manifest = base_manifest()
        report = _canonical_report(manifest)
        report += "- A001: The reconstructed result is exactly 9.0. [evidence: E_METHOD, E_CODE]\n"
        result = self.validate(manifest, report=report)
        self.assertFalse(result["valid"])
        self.assertIn("report_unstructured_claim", {item["code"] for item in result["errors"]})

    def test_structured_interpretation_rejects_number_absent_from_cited_evidence(self) -> None:
        manifest = base_manifest()

        def inject_false_number(root: Path, value: dict) -> None:
            _run_successful_fixture(root, value)
            value["analyses"][0]["interpretation"]["direct_observation"][0] = _statement(
                "RUN_OK output records a synthetic mean difference of 9999.0.",
                "RUN_OK",
                "OUT001",
            )

        result = self.validate(manifest, setup=inject_false_number)
        self.assertFalse(result["valid"])
        self.assertIn(
            "interpretation_quantity_must_be_structured",
            {item["code"] for item in result["errors"]},
        )

    def test_unexecuted_argparse_default_drift_is_material_conflict(self) -> None:
        manifest = base_manifest()

        def drift_default(root: Path, value: dict) -> None:
            code_path = root / "code/analysis.py"
            code_path.write_text(
                code_path.read_text(encoding="utf-8").replace(
                    'parser.add_argument("--alpha", type=float, default=ALPHA)',
                    'parser.add_argument("--alpha", type=float, default=0.10)',
                ),
                encoding="utf-8",
            )
            fingerprint = f"sha256:{_sha256(code_path)}"
            value["sources"][3]["fingerprint"] = fingerprint
            value["analyses"][0]["code_locations"][0]["snapshot"] = fingerprint
            source_fingerprint = VALIDATOR._source_set_fingerprint(value["sources"])
            for stage in value["stage_state"]:
                stage["input_fingerprint"] = source_fingerprint

        result = self.validate(manifest, setup=drift_default)
        self.assertFalse(result["valid"])
        self.assertEqual(result["derived_statuses"]["A001"]["derived"], "材料冲突")
        self.assertIn("undeclared_parameter_conflict", {item["code"] for item in result["errors"]})

    def test_finalizer_rejects_conflicting_same_name_runtime_values(self) -> None:
        manifest = base_manifest()
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _materialize_sources(root, manifest)
            code_path = root / "code/analysis.py"
            code_path.write_text(
                code_path.read_text(encoding="utf-8") + '\nprint("alpha=0.10")\n',
                encoding="utf-8",
            )
            manifest["analyses"][0]["code_locations"][0]["snapshot"] = (
                f"sha256:{_sha256(code_path)}"
            )
            with self.assertRaisesRegex(AssertionError, "conflicting same-name value"):
                _run_successful_fixture(root, manifest)

    def test_finalizer_does_not_succeed_when_check_selects_only_a_log(self) -> None:
        manifest = base_manifest()
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _materialize_sources(root, manifest)
            with self.assertRaisesRegex(AssertionError, "did not adjudicate success"):
                _run_successful_fixture(
                    root,
                    manifest,
                    check_observed=True,
                    check_verification={
                        "kind": "text_contains",
                        "evidence_path": "runs/RUN_OK/stdout.log",
                        "selector": None,
                        "expected": "seed=7",
                    },
                )
            record = json.loads(
                (root / "runs/RUN_OK/execution_record.fragment.json").read_text(encoding="utf-8")
            )
            self.assertEqual(record["attempt_status"], "failed")

    def test_receipt_record_mirror_uses_strict_json_types(self) -> None:
        manifest = base_manifest()

        def mutate_seed_type(root: Path, value: dict) -> None:
            _run_successful_fixture(root, value)
            record = value["execution_records"][0]
            _rewrite_receipt(root, record, lambda receipt: receipt.update({"seed": 7.0}))

        result = self.validate(manifest, setup=mutate_seed_type)
        self.assertFalse(result["valid"])
        messages = "\n".join(item["message"] for item in result["errors"])
        self.assertIn("receipt/record mismatch: seed", messages)

    def test_ascii_parameter_names_preserve_punctuation_during_matching(self) -> None:
        manifest = base_manifest()

        def observe_distinct_names(root: Path, value: dict) -> None:
            code_path = root / "code/analysis.py"
            code_path.write_text(
                code_path.read_text(encoding="utf-8") + '\nprint("a-b=1; ab=2")\n',
                encoding="utf-8",
            )
            fingerprint = f"sha256:{_sha256(code_path)}"
            value["sources"][3]["fingerprint"] = fingerprint
            value["analyses"][0]["code_locations"][0]["snapshot"] = fingerprint
            source_fingerprint = VALIDATOR._source_set_fingerprint(value["sources"])
            for stage in value["stage_state"]:
                stage["input_fingerprint"] = source_fingerprint
            _run_successful_fixture(
                root,
                value,
                observed_parameters=[
                    {"name": "a-b", "value": 1, "evidence_paths": ["runs/RUN_OK/stdout.log"]},
                    {"name": "ab", "value": 2, "evidence_paths": ["runs/RUN_OK/stdout.log"]},
                ],
            )

        result = self.validate(manifest, setup=observe_distinct_names)
        self.assertTrue(result["valid"], result["errors"])

    def test_failed_or_blocked_adjudication_status_must_match_attempt(self) -> None:
        manifest = base_manifest()

        def contradict_status(root: Path, value: dict) -> None:
            _add_failed_environment_record(root, value)
            value["execution_records"][0]["adjudication_status"] = "succeeded"

        result = self.validate(manifest, setup=contradict_status)
        self.assertFalse(result["valid"])
        self.assertIn("execution_attempt_status_mismatch", {item["code"] for item in result["errors"]})

    def test_duplicate_logical_artifacts_cannot_share_one_physical_path(self) -> None:
        manifest = base_manifest()
        duplicate = copy.deepcopy(manifest["analyses"][0]["inputs_outputs"]["outputs"][0])
        duplicate["artifact_id"] = "OUT002"
        duplicate["semantic_type"] = "second logical result"
        manifest["analyses"][0]["inputs_outputs"]["outputs"].append(duplicate)
        result = self.validate(manifest)
        self.assertFalse(result["valid"])
        self.assertIn(
            "duplicate_analysis_artifact_path",
            {item["code"] for item in result["errors"]},
        )

    def test_seed_not_applicable_cannot_contradict_explicit_seed_argv(self) -> None:
        for option in ("--seed", "--se", "--see"):
            with self.subTest(option=option):
                manifest = base_manifest()

                def contradict_seed(root: Path, value: dict) -> None:
                    _run_successful_fixture(root, value)
                    record = value["execution_records"][0]
                    record["command_argv"] = [
                        option if token == "--seed" else token
                        for token in record["command_argv"]
                    ]
                    record["command"] = subprocess.list2cmdline(record["command_argv"])
                    record["seed"] = "not_applicable"
                    record["seed_reason"] = "claimed deterministic path"

                    def mutate_receipt(receipt: dict) -> None:
                        receipt.update(
                            {
                                "command_argv": copy.deepcopy(record["command_argv"]),
                                "command": record["command"],
                                "seed": "not_applicable",
                                "seed_reason": "claimed deterministic path",
                            }
                        )

                    _rewrite_receipt(root, record, mutate_receipt)

                result = self.validate(manifest, setup=contradict_seed)
                self.assertFalse(result["valid"])
                messages = "\n".join(item["message"] for item in result["errors"])
                self.assertIn("seed", messages.casefold())

    def test_integer_seed_requires_exact_entrypoint_option_binding(self) -> None:
        for option in (
            "--replicates",
            "-s",
            "-s7",
            "-s=7",
            "--se",
            "--SEED",
            "--bootstrap-seed",
            "--torch-seed",
            "--seed-value",
            "--rng-state",
            "--random-generator-seed",
            "--",
        ):
            with self.subTest(option=option):
                manifest = base_manifest()

                def detach_seed(root: Path, value: dict) -> None:
                    _run_successful_fixture(root, value)
                    record = value["execution_records"][0]
                    argv = list(record["command_argv"])
                    argv[argv.index("--seed")] = option
                    record["command_argv"] = argv
                    record["command"] = subprocess.list2cmdline(argv)

                    def mutate_receipt(receipt: dict) -> None:
                        receipt["command_argv"] = copy.deepcopy(argv)
                        receipt["command"] = record["command"]

                    _rewrite_receipt(root, record, mutate_receipt)

                result = self.validate(manifest, setup=detach_seed)
                self.assertFalse(result["valid"])
                messages = "\n".join(item["message"] for item in result["errors"])
                self.assertIn("seed", messages.casefold())

    def test_receipt_expected_outputs_and_process_id_are_semantically_checked(self) -> None:
        variants = {
            "empty expected outputs": lambda receipt: receipt.update({"expected_outputs": []}),
            "false output owner": lambda receipt: receipt["expected_outputs"][0].update(
                {"analysis_ids": ["A_FAKE"]}
            ),
            "boolean process id": lambda receipt: receipt.update({"process_id": True}),
        }
        for label, mutate_receipt in variants.items():
            with self.subTest(label=label):
                manifest = base_manifest()

                def mutate(root: Path, value: dict) -> None:
                    _run_successful_fixture(root, value)
                    _rewrite_receipt(root, value["execution_records"][0], mutate_receipt)

                result = self.validate(manifest, setup=mutate)
                self.assertFalse(result["valid"])
                messages = "\n".join(item["message"] for item in result["errors"])
                if label == "boolean process id":
                    self.assertIn("receipt process_id", messages)
                else:
                    self.assertIn("receipt expected_outputs must exactly mirror", messages)

    def test_exact_trace_header_is_enforced(self) -> None:
        manifest = base_manifest()
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _materialize_sources(root, manifest)
            _write_project(
                root,
                manifest,
                trace_row(manifest),
                "# Contract fixture\n\nA001: 材料完整但未执行。No scientific reproduction is claimed.\n",
            )
            text = (root / "traceability.tsv").read_text(encoding="utf-8")
            (root / "traceability.tsv").write_text(
                text.replace("figure/panel", "figure"), encoding="utf-8"
            )
            result = VALIDATOR.validate_project(root)
        self.assertFalse(result["valid"])
        self.assertIn("trace_header_mismatch", {item["code"] for item in result["errors"]})


if __name__ == "__main__":
    unittest.main()
