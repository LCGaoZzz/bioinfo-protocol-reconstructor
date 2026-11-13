from __future__ import annotations

import hashlib
import json
import os
import platform
import py_compile
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from typing import Any, Callable


SKILL_ROOT = Path(__file__).resolve().parents[1]
RUNNER_PATH = SKILL_ROOT / "scripts" / "run_reconstruction.py"
FINALIZER_PATH = SKILL_ROOT / "scripts" / "finalize_execution.py"


def _write_json(path: Path, value: Any) -> None:
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )


def _read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


class FinalizerParityHardeningTests(unittest.TestCase):
    def _prepare_project(self, root: Path) -> None:
        (root / "code").mkdir(parents=True)
        (root / "data").mkdir(parents=True)
        (root / "data/input.tsv").write_text("sample\tvalue\ns1\t1\n", encoding="utf-8")
        (root / "code/analysis.py").write_text(
            """from pathlib import Path
import sys

seed_index = next(
    index for index, value in enumerate(sys.argv) if "--seed".startswith(value)
)
seed = sys.argv[seed_index + 1]
for output in sys.argv[seed_index + 2:]:
    path = Path(output)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("key\\tvalue\\tunit\\nrow\\t1\\tunitless\\n", encoding="utf-8")
print(f"seed={seed}")
""",
            encoding="utf-8",
        )

    def _run_runner(
        self,
        root: Path,
        execution_id: str,
        analysis_ids: list[str],
        output_specs: list[dict[str, Any]],
        child_seed_option: str = "--seed",
        launcher_flags: list[str] | None = None,
        wrapper_flags: list[str] | None = None,
        runner_environment: dict[str, str] | None = None,
        dependencies: list[str] | None = None,
    ) -> subprocess.CompletedProcess[str]:
        command = [
            sys.executable,
            *(wrapper_flags or []),
            str(RUNNER_PATH),
            "--project-dir",
            str(root),
            "--execution-id",
            execution_id,
        ]
        for analysis_id in analysis_ids:
            command.extend(["--analysis-id", analysis_id])
        command.extend(
            [
                "--entrypoint",
                "code/analysis.py",
                "--code-evidence-ref",
                "CODE1",
                "--input-spec",
                json.dumps(
                    {
                        "artifact_id": "INPUT1",
                        "path": "data/input.tsv",
                        "semantic_type": "test input",
                    }
                ),
            ]
        )
        for spec in output_specs:
            command.extend(["--output-spec", json.dumps(spec)])
        for dependency in dependencies or [f"python={platform.python_version()}"]:
            command.extend(["--dependency", dependency])
        command.extend(
            [
                "--seed",
                "7",
                "--",
                sys.executable,
                *(launcher_flags or []),
                "code/analysis.py",
                "data/input.tsv",
                child_seed_option,
                "7",
                *[str(spec["path"]) for spec in output_specs],
            ]
        )
        return subprocess.run(
            command,
            cwd=root,
            capture_output=True,
            text=True,
            check=False,
            env=runner_environment,
        )

    def _output_spec(
        self,
        execution_id: str,
        artifact_id: str = "OUTPUT1",
        owners: list[str] | None = None,
    ) -> dict[str, Any]:
        spec: dict[str, Any] = {
            "artifact_id": artifact_id,
            "path": f"runs/{execution_id}/{artifact_id.lower()}.tsv",
            "semantic_type": "test result table",
        }
        if owners is not None:
            spec["analysis_ids"] = owners
        return spec

    def _output_check(
        self,
        execution_id: str,
        artifact_id: str,
        analysis_ids: list[str],
        check_id: str,
    ) -> dict[str, Any]:
        path = f"runs/{execution_id}/{artifact_id.lower()}.tsv"
        return {
            "check_id": check_id,
            "check": f"verify {artifact_id}",
            "metric": "row",
            "unit": "unitless",
            "observed": "1",
            "passed": True,
            "analysis_ids": analysis_ids,
            "evidence_paths": [path],
            "verification": {
                "kind": "tsv_cell_equals",
                "evidence_path": path,
                "selector": {
                    "key_column": "key",
                    "key_value": "row",
                    "value_column": "value",
                    "unit_column": "unit",
                },
                "expected": "1",
            },
        }

    def _log_check(
        self, execution_id: str, analysis_ids: list[str], check_id: str
    ) -> dict[str, Any]:
        path = f"runs/{execution_id}/stdout.log"
        return {
            "check_id": check_id,
            "check": "verify process seed echo",
            "metric": "seed_echo",
            "unit": "not_applicable",
            "observed": True,
            "passed": True,
            "analysis_ids": analysis_ids,
            "evidence_paths": [path],
            "verification": {
                "kind": "text_contains",
                "evidence_path": path,
                "selector": None,
                "expected": "seed=7",
            },
        }

    def _finalize(
        self, root: Path, execution_id: str, checks: list[dict[str, Any]]
    ) -> subprocess.CompletedProcess[str]:
        checks_path = root / f"checks.{execution_id}.json"
        _write_json(checks_path, checks)
        return subprocess.run(
            [
                sys.executable,
                str(FINALIZER_PATH),
                "--project-dir",
                str(root),
                "--execution-id",
                execution_id,
                "--checks-json",
                str(checks_path),
            ],
            cwd=root,
            capture_output=True,
            text=True,
            check=False,
        )

    def _mutate_pending(
        self,
        root: Path,
        execution_id: str,
        receipt_mutator: Callable[[dict[str, Any]], None] | None = None,
        fragment_mutator: Callable[[dict[str, Any]], None] | None = None,
    ) -> None:
        run_dir = root / "runs" / execution_id
        receipt_path = run_dir / "execution_receipt.json"
        fragment_path = run_dir / "execution_record.fragment.json"
        receipt = _read_json(receipt_path)
        fragment = _read_json(fragment_path)
        if receipt_mutator is not None:
            receipt_mutator(receipt)
        if fragment_mutator is not None:
            fragment_mutator(fragment)
        _write_json(receipt_path, receipt)
        fragment["receipt_sha256"] = _sha256(receipt_path)
        _write_json(fragment_path, fragment)

    def test_runner_enforces_and_carries_output_ownership(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            self._prepare_project(root)
            execution_id = "RUN_SINGLE"
            completed = self._run_runner(
                root, execution_id, ["A1"], [self._output_spec(execution_id)]
            )
            self.assertEqual(completed.returncode, 0, completed.stderr)
            receipt = _read_json(root / f"runs/{execution_id}/execution_receipt.json")
            fragment = _read_json(
                root / f"runs/{execution_id}/execution_record.fragment.json"
            )
            self.assertEqual(receipt["expected_outputs"][0]["analysis_ids"], ["A1"])
            self.assertEqual(receipt["outputs"][0]["analysis_ids"], ["A1"])
            self.assertEqual(fragment["outputs"][0]["analysis_ids"], ["A1"])

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            self._prepare_project(root)
            completed = self._run_runner(
                root, "RUN_MISSING", ["A1", "A2"], [self._output_spec("RUN_MISSING")]
            )
            self.assertNotEqual(completed.returncode, 0)
            self.assertIn("multi-analysis output specs", completed.stderr)

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            self._prepare_project(root)
            completed = self._run_runner(
                root,
                "RUN_UNOWNED",
                ["A1", "A2"],
                [self._output_spec("RUN_UNOWNED", owners=["A1"])],
            )
            self.assertNotEqual(completed.returncode, 0)
            self.assertIn("must own at least one declared output", completed.stderr)

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            self._prepare_project(root)
            execution_id = "RUN_SHARED"
            completed = self._run_runner(
                root,
                execution_id,
                ["A1", "A2"],
                [self._output_spec(execution_id, owners=["A1", "A2"])],
            )
            self.assertEqual(completed.returncode, 0, completed.stderr)
            receipt = _read_json(root / f"runs/{execution_id}/execution_receipt.json")
            self.assertEqual(receipt["outputs"][0]["analysis_ids"], ["A1", "A2"])

    def test_runner_binds_unique_dependencies_to_the_child_runtime(self) -> None:
        cases = {
            "observed version mismatch": ["python=0.0.0-fake"],
            "normalized duplicate": [
                f"python={platform.python_version()}",
                f"PYTHON={platform.python_version()}",
            ],
        }
        for label, dependencies in cases.items():
            with self.subTest(label=label), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                self._prepare_project(root)
                execution_id = "RUN_DEPENDENCY_REJECT"
                runner = self._run_runner(
                    root,
                    execution_id,
                    ["A1"],
                    [self._output_spec(execution_id)],
                    dependencies=dependencies,
                )
                self.assertNotEqual(runner.returncode, 0)
                self.assertIn("dependenc", runner.stderr.casefold())
                self.assertFalse((root / "runs" / execution_id).exists())

    def test_finalizer_rechecks_dependency_versions_before_adjudication(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            self._prepare_project(root)
            execution_id = "RUN_DEPENDENCY_TAMPER"
            runner = self._run_runner(
                root,
                execution_id,
                ["A1"],
                [self._output_spec(execution_id)],
            )
            self.assertEqual(runner.returncode, 0, runner.stderr)

            def replace_dependencies(value: dict[str, Any]) -> None:
                value["dependencies"] = [{"name": "python", "version": "0.0.0-fake"}]

            self._mutate_pending(
                root,
                execution_id,
                receipt_mutator=replace_dependencies,
                fragment_mutator=replace_dependencies,
            )
            check = self._output_check(execution_id, "OUTPUT1", ["A1"], "CHECK1")
            finalizer = self._finalize(root, execution_id, [check])
            self.assertNotEqual(finalizer.returncode, 0)
            self.assertIn("dependency version mismatch", finalizer.stderr.casefold())

    def test_finalizer_requires_path_owner_coverage(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            self._prepare_project(root)
            execution_id = "RUN_SWAP"
            specs = [
                self._output_spec(execution_id, "OUT_A1", ["A1"]),
                self._output_spec(execution_id, "OUT_A2", ["A2"]),
            ]
            runner = self._run_runner(root, execution_id, ["A1", "A2"], specs)
            self.assertEqual(runner.returncode, 0, runner.stderr)
            swapped = [
                self._output_check(execution_id, "OUT_A1", ["A2"], "CHECK_A2"),
                self._output_check(execution_id, "OUT_A2", ["A1"], "CHECK_A1"),
            ]
            finalizer = self._finalize(root, execution_id, swapped)
            self.assertNotEqual(finalizer.returncode, 0)
            self.assertIn("does not own it", finalizer.stderr)

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            self._prepare_project(root)
            execution_id = "RUN_LOG_GAP"
            spec = self._output_spec(execution_id, owners=["A1", "A2"])
            runner = self._run_runner(root, execution_id, ["A1", "A2"], [spec])
            self.assertEqual(runner.returncode, 0, runner.stderr)
            checks = [
                self._output_check(execution_id, "OUTPUT1", ["A1"], "CHECK_A1"),
                self._log_check(execution_id, ["A2"], "CHECK_A2_LOG"),
            ]
            finalizer = self._finalize(root, execution_id, checks)
            self.assertEqual(finalizer.returncode, 0, finalizer.stderr)
            self.assertEqual(json.loads(finalizer.stdout)["attempt_status"], "failed")

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            self._prepare_project(root)
            execution_id = "RUN_SHARED_OK"
            spec = self._output_spec(execution_id, owners=["A1", "A2"])
            runner = self._run_runner(root, execution_id, ["A1", "A2"], [spec])
            self.assertEqual(runner.returncode, 0, runner.stderr)
            check = self._output_check(
                execution_id, "OUTPUT1", ["A1", "A2"], "CHECK_SHARED"
            )
            finalizer = self._finalize(root, execution_id, [check])
            self.assertEqual(finalizer.returncode, 0, finalizer.stderr)
            self.assertEqual(json.loads(finalizer.stdout)["attempt_status"], "succeeded")

    def test_finalizer_rejects_mirror_input_and_code_drift(self) -> None:
        cases = {
            "fragment mirror": lambda root, execution_id: self._mutate_pending(
                root,
                execution_id,
                fragment_mutator=lambda fragment: fragment.__setitem__(
                    "command", "tampered command display"
                ),
            ),
            "input hash": lambda root, _execution_id: (root / "data/input.tsv").write_text(
                "sample\tvalue\ns1\t999\n", encoding="utf-8"
            ),
            "entrypoint hash": lambda root, _execution_id: (
                root / "code/analysis.py"
            ).write_text("raise SystemExit('tampered')\n", encoding="utf-8"),
        }
        for label, mutate in cases.items():
            with self.subTest(label=label), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                self._prepare_project(root)
                execution_id = "RUN_DRIFT"
                runner = self._run_runner(
                    root,
                    execution_id,
                    ["A1"],
                    [self._output_spec(execution_id)],
                )
                self.assertEqual(runner.returncode, 0, runner.stderr)
                mutate(root, execution_id)
                check = self._output_check(
                    execution_id, "OUTPUT1", ["A1"], "CHECK_OUTPUT"
                )
                finalizer = self._finalize(root, execution_id, [check])
                self.assertNotEqual(finalizer.returncode, 0)

    def test_finalizer_infers_legacy_single_analysis_output_owner(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            self._prepare_project(root)
            execution_id = "RUN_LEGACY"
            runner = self._run_runner(
                root, execution_id, ["A1"], [self._output_spec(execution_id)]
            )
            self.assertEqual(runner.returncode, 0, runner.stderr)

            def strip_receipt_owners(receipt: dict[str, Any]) -> None:
                receipt["expected_outputs"][0].pop("analysis_ids")
                receipt["outputs"][0].pop("analysis_ids")

            def strip_fragment_owners(fragment: dict[str, Any]) -> None:
                fragment["outputs"][0].pop("analysis_ids")

            self._mutate_pending(
                root, execution_id, strip_receipt_owners, strip_fragment_owners
            )
            check = self._output_check(
                execution_id, "OUTPUT1", ["A1"], "CHECK_LEGACY"
            )
            finalizer = self._finalize(root, execution_id, [check])
            self.assertEqual(finalizer.returncode, 0, finalizer.stderr)
            self.assertEqual(json.loads(finalizer.stdout)["attempt_status"], "succeeded")
            receipt = _read_json(root / f"runs/{execution_id}/execution_receipt.json")
            fragment = _read_json(
                root / f"runs/{execution_id}/execution_record.fragment.json"
            )
            self.assertEqual(receipt["expected_outputs"][0]["analysis_ids"], ["A1"])
            self.assertEqual(receipt["outputs"][0]["analysis_ids"], ["A1"])
            self.assertEqual(fragment["outputs"][0]["analysis_ids"], ["A1"])

    def test_finalizer_enforces_new_result_check_identity_contract(self) -> None:
        variants: dict[str, Callable[[list[dict[str, Any]]], None]] = {
            "missing check_id": lambda checks: checks[0].pop("check_id"),
            "invalid check_id": lambda checks: checks[0].__setitem__(
                "check_id", "not a valid id"
            ),
            "blank metric": lambda checks: checks[0].__setitem__("metric", " "),
            "blank unit": lambda checks: checks[0].__setitem__("unit", ""),
            "duplicate check_id": lambda checks: checks.append(dict(checks[0])),
        }
        for label, mutate in variants.items():
            with self.subTest(label=label), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                self._prepare_project(root)
                execution_id = "RUN_CHECK_CONTRACT"
                runner = self._run_runner(
                    root,
                    execution_id,
                    ["A1"],
                    [self._output_spec(execution_id)],
                )
                self.assertEqual(runner.returncode, 0, runner.stderr)
                checks = [
                    self._output_check(
                        execution_id, "OUTPUT1", ["A1"], "CHECK_OUTPUT"
                    )
                ]
                mutate(checks)
                finalizer = self._finalize(root, execution_id, checks)
                self.assertNotEqual(finalizer.returncode, 0)

    def test_finalizer_rejects_seed_metadata_that_contradicts_command(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            self._prepare_project(root)
            execution_id = "RUN_SEED_CONFLICT"
            runner = self._run_runner(
                root,
                execution_id,
                ["A1"],
                [self._output_spec(execution_id)],
            )
            self.assertEqual(runner.returncode, 0, runner.stderr)

            def contradict_seed(value: dict[str, Any]) -> None:
                value["seed"] = "not_applicable"
                value["seed_reason"] = "claimed deterministic path"

            self._mutate_pending(
                root,
                execution_id,
                receipt_mutator=contradict_seed,
                fragment_mutator=contradict_seed,
            )
            check = self._output_check(
                execution_id, "OUTPUT1", ["A1"], "CHECK_OUTPUT"
            )
            finalizer = self._finalize(root, execution_id, [check])
            self.assertNotEqual(finalizer.returncode, 0)
            self.assertIn("conflicts with an explicit seed option", finalizer.stderr)

    def test_runner_requires_an_exact_entrypoint_seed_binding(self) -> None:
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
            with self.subTest(option=option), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                self._prepare_project(root)
                execution_id = "RUN_SEED_UNBOUND"
                runner = self._run_runner(
                    root,
                    execution_id,
                    ["A1"],
                    [self._output_spec(execution_id)],
                    child_seed_option=option,
                )
                self.assertNotEqual(runner.returncode, 0)
                self.assertIn("seed", runner.stderr.casefold())

    def test_runner_rejects_unbound_dynamic_code_loaders(self) -> None:
        variants = {
            "runpy callable alias": (
                "import runpy\nloader = runpy.run_path\nloader('code/helper.py')\n"
            ),
            "import_module alias": (
                "from importlib import import_module\nimport_module('helper')\n"
            ),
            "builtin import alias": (
                "loader = __import__\nloader('helper')\n"
            ),
            "builtins import": (
                "import builtins\nbuiltins.__import__('helper')\n"
            ),
            "getattr builtins import": (
                "import builtins\ngetattr(builtins, '__import__')('helper')\n"
            ),
            "builtins dictionary import": (
                "import builtins\nbuiltins.__dict__['__import__']('helper')\n"
            ),
            "pkgutil dotted resolver": (
                "import pkgutil\npkgutil.resolve_name('helper.value')\n"
            ),
            "pydoc dotted resolver": "import pydoc\npydoc.locate('helper.value')\n",
            "mock dotted resolver": (
                "from unittest.mock import patch\n"
                "with patch('helper.value', 'patched'):\n    pass\n"
            ),
            "find spec": (
                "import importlib.util\nimportlib.util.find_spec('helper')\n"
            ),
            "metadata entry point": (
                "from importlib.metadata import EntryPoint\n"
                "ep = EntryPoint(name='x', value='helper:value', group='x')\n"
                "ep.load()\n"
            ),
            "metadata entry point load alias": (
                "from importlib.metadata import EntryPoint\n"
                "ep = EntryPoint(name='x', value='helper:value', group='x')\n"
                "loader = ep.load\nloader()\n"
            ),
            "metadata entry point loop": (
                "from importlib.metadata import entry_points\n"
                "for ep in entry_points().select(group='x'):\n    ep.load()\n"
            ),
            "metadata entry point comprehension": (
                "from importlib.metadata import entry_points\n"
                "[ep.load() for ep in entry_points().select(group='x')]\n"
            ),
            "metadata entry point next": (
                "from importlib.metadata import entry_points\n"
                "ep = next(iter(entry_points().select(group='x')))\n"
                "ep.load()\n"
            ),
            "pickle loader": "import pickle\npickle.loads(b'fixture')\n",
            "numpy pickle loader": (
                "import numpy\nnumpy.load('fixture.npy', allow_pickle=True)\n"
            ),
            "builtins exec": (
                "import builtins\nfrom pathlib import Path\n"
                "builtins.exec(Path('code/helper.py').read_text())\n"
            ),
            "getattr builtins exec": (
                "import builtins\nfrom pathlib import Path\n"
                "getattr(builtins, 'exec')(Path('code/helper.py').read_text())\n"
            ),
            "builtins dictionary exec": (
                "import builtins\nfrom pathlib import Path\n"
                "builtins.__dict__['exec'](Path('code/helper.py').read_text())\n"
            ),
            "process loader": "import os\nos.popen('echo helper')\n",
            "getattr process loader": "import os\ngetattr(os, 'popen')('echo helper')\n",
            "ctypes native loader": "import ctypes\nctypes.CDLL('code/helper.dll')\n",
            "zip import loader": (
                "import zipimport\n"
                "zipimport.zipimporter('code/plugins.zip').load_module('helper')\n"
            ),
        }
        for label, snippet in variants.items():
            with self.subTest(label=label), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                self._prepare_project(root)
                (root / "code/helper.py").write_text(
                    "value = 'helper'\n", encoding="utf-8"
                )
                entrypoint = root / "code/analysis.py"
                entrypoint.write_text(
                    entrypoint.read_text(encoding="utf-8") + "\n" + snippet,
                    encoding="utf-8",
                )
                execution_id = "RUN_DYNAMIC_CODE"
                runner = self._run_runner(
                    root,
                    execution_id,
                    ["A1"],
                    [self._output_spec(execution_id)],
                )
                self.assertNotEqual(runner.returncode, 0)
                self.assertIn("code", runner.stderr.casefold())

    def test_import_api_presence_does_not_taint_unrelated_json_load(self) -> None:
        variants = {
            "metadata import": (
                "import importlib.metadata\nimport json\n"
                "importlib.metadata.version('pip')\n"
            ),
            "entrypoint declaration": (
                "from importlib.metadata import EntryPoint\nimport json\n"
                "EntryPoint(name='x', value='helper:value', group='x')\n"
            ),
            "pickle import": "import pickle\nimport json\npickle.dumps({'x': 1})\n",
        }
        for label, prefix in variants.items():
            with self.subTest(label=label), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                self._prepare_project(root)
                config_path = root / "data/config.json"
                config_path.write_text('{"x": 1}\n', encoding="utf-8")
                entrypoint = root / "code/analysis.py"
                entrypoint.write_text(
                    prefix
                    + "with open('data/config.json', encoding='utf-8') as handle:\n"
                    + "    json.load(handle)\n"
                    + entrypoint.read_text(encoding="utf-8"),
                    encoding="utf-8",
                )
                execution_id = "RUN_SAFE_JSON_LOAD"
                runner = self._run_runner(
                    root,
                    execution_id,
                    ["A1"],
                    [self._output_spec(execution_id)],
                )
                self.assertEqual(runner.returncode, 0, runner.stderr)

    def test_runner_records_nested_relative_from_import_closure(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            self._prepare_project(root)
            package = root / "code/pkg"
            helper_package = package / "sub"
            helper_package.mkdir(parents=True)
            (package / "__init__.py").write_text("", encoding="utf-8")
            (package / "main.py").write_text(
                "from .sub import helper\nvalue = helper.value\n", encoding="utf-8"
            )
            (helper_package / "__init__.py").write_text("", encoding="utf-8")
            (helper_package / "helper.py").write_text("value = 1\n", encoding="utf-8")
            entrypoint = root / "code/analysis.py"
            entrypoint.write_text(
                "from pkg import main\n" + entrypoint.read_text(encoding="utf-8"),
                encoding="utf-8",
            )
            execution_id = "RUN_RELATIVE_IMPORT"
            runner = self._run_runner(
                root,
                execution_id,
                ["A1"],
                [self._output_spec(execution_id)],
            )
            self.assertEqual(runner.returncode, 0, runner.stderr)
            receipt = _read_json(root / f"runs/{execution_id}/execution_receipt.json")
            code_paths = {item["path"] for item in receipt["code_files"]}
            self.assertIn("code/pkg/sub/helper.py", code_paths)

    def test_runner_resolves_absolute_imports_from_entrypoint_directory(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            self._prepare_project(root)
            package = root / "code/pkg"
            package.mkdir(parents=True)
            (package / "__init__.py").write_text("", encoding="utf-8")
            (package / "main.py").write_text("import helper\n", encoding="utf-8")
            (package / "helper.py").write_text("value = 'decoy'\n", encoding="utf-8")
            (root / "code/helper.py").write_text("value = 'executed'\n", encoding="utf-8")
            entrypoint = root / "code/analysis.py"
            entrypoint.write_text(
                "from pkg import main\n" + entrypoint.read_text(encoding="utf-8"),
                encoding="utf-8",
            )
            execution_id = "RUN_ABSOLUTE_IMPORT"
            runner = self._run_runner(
                root,
                execution_id,
                ["A1"],
                [self._output_spec(execution_id)],
            )
            self.assertEqual(runner.returncode, 0, runner.stderr)
            receipt = _read_json(root / f"runs/{execution_id}/execution_receipt.json")
            code_paths = {item["path"] for item in receipt["code_files"]}
            self.assertIn("code/helper.py", code_paths)
            self.assertNotIn("code/pkg/helper.py", code_paths)

    def test_runner_does_not_bind_project_root_decoy_as_absolute_import(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            self._prepare_project(root)
            (root / "random.py").write_text(
                "raise RuntimeError('project-root decoy executed')\n", encoding="utf-8"
            )
            entrypoint = root / "code/analysis.py"
            entrypoint.write_text(
                "import random\n" + entrypoint.read_text(encoding="utf-8"),
                encoding="utf-8",
            )
            execution_id = "RUN_ROOT_DECOY"
            runner = self._run_runner(
                root,
                execution_id,
                ["A1"],
                [self._output_spec(execution_id)],
            )
            self.assertEqual(runner.returncode, 0, runner.stderr)
            receipt = _read_json(root / f"runs/{execution_id}/execution_receipt.json")
            code_paths = {item["path"] for item in receipt["code_files"]}
            self.assertNotIn("random.py", code_paths)

    def test_runner_rejects_python_flags_that_change_import_search_path(self) -> None:
        for flag in ("-P", "-I"):
            with self.subTest(flag=flag), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                self._prepare_project(root)
                execution_id = "RUN_UNSUPPORTED_IMPORT_PATH"
                runner = self._run_runner(
                    root,
                    execution_id,
                    ["A1"],
                    [self._output_spec(execution_id)],
                    launcher_flags=[flag],
                )
                self.assertNotEqual(runner.returncode, 0)
                self.assertIn("entrypoint", runner.stderr.casefold())

    def test_runner_normalizes_python_import_environment_for_child(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            self._prepare_project(root)
            (root / "code/random.py").write_text(
                "raise RuntimeError('local module proves script-dir import semantics')\n",
                encoding="utf-8",
            )
            entrypoint = root / "code/analysis.py"
            entrypoint.write_text(
                "import random\n" + entrypoint.read_text(encoding="utf-8"),
                encoding="utf-8",
            )
            execution_id = "RUN_SAFE_PATH_ENV"
            runner_environment = os.environ.copy()
            runner_environment["PYTHONSAFEPATH"] = "1"
            runner = self._run_runner(
                root,
                execution_id,
                ["A1"],
                [self._output_spec(execution_id)],
                wrapper_flags=["-E"],
                runner_environment=runner_environment,
            )
            self.assertNotEqual(runner.returncode, 0)
            receipt = _read_json(root / f"runs/{execution_id}/execution_receipt.json")
            self.assertEqual(receipt["process_status"], "failed")
            self.assertTrue(
                any("PYTHONSAFEPATH" in note for note in receipt["preflight"]["notes"])
            )

    def test_runner_removes_environment_selected_breakpoint_hook(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            self._prepare_project(root)
            (root / "code/helper.py").write_text(
                "def hook(*args, **kwargs):\n    print('environment hook ran')\n",
                encoding="utf-8",
            )
            entrypoint = root / "code/analysis.py"
            entrypoint.write_text(
                "breakpoint()\n" + entrypoint.read_text(encoding="utf-8"),
                encoding="utf-8",
            )
            execution_id = "RUN_BREAKPOINT_ENV"
            runner_environment = os.environ.copy()
            runner_environment["PYTHONBREAKPOINT"] = "helper.hook"
            runner = self._run_runner(
                root,
                execution_id,
                ["A1"],
                [self._output_spec(execution_id)],
                wrapper_flags=["-E"],
                runner_environment=runner_environment,
            )
            self.assertNotEqual(runner.returncode, 0)
            receipt = _read_json(root / f"runs/{execution_id}/execution_receipt.json")
            self.assertEqual(receipt["process_status"], "failed")
            self.assertTrue(
                any("PYTHONBREAKPOINT" in note for note in receipt["preflight"]["notes"])
            )

    def test_runner_rejects_import_path_mutations_and_aliases(self) -> None:
        variants = {
            "augmented assignment": "import sys\nsys.path += ['.']\n",
            "slice assignment": "import sys\nsys.path[:] = ['.'] + sys.path\n",
            "module alias": "import sys as s\ns.path.insert(0, '.')\n",
            "imported path alias": "from sys import path as p\np.insert(0, '.')\n",
            "local path alias": "import sys\np = sys.path\np.append('.')\n",
            "site directory": "import site\nsite.addsitedir('.')\n",
            "setattr path": "import sys\nsetattr(sys, 'path', ['.'])\n",
            "meta path": "import sys\nsys.meta_path.clear()\n",
            "modules assignment": "import sys\nsys.modules['helper'] = object()\n",
            "modules alias": "from sys import modules as m\nm['helper'] = object()\n",
            "builtin importer": "import builtins\nbuiltins.__import__ = lambda *a: None\n",
        }
        for label, snippet in variants.items():
            with self.subTest(label=label), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                self._prepare_project(root)
                entrypoint = root / "code/analysis.py"
                entrypoint.write_text(
                    snippet + entrypoint.read_text(encoding="utf-8"), encoding="utf-8"
                )
                execution_id = "RUN_PATH_MUTATION"
                runner = self._run_runner(
                    root,
                    execution_id,
                    ["A1"],
                    [self._output_spec(execution_id)],
                )
                self.assertNotEqual(runner.returncode, 0)
                self.assertIn("import", runner.stderr.casefold())

    def test_runner_rejects_local_bytecode_without_auditable_source(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            self._prepare_project(root)
            helper_source = root / "code/helper.py"
            helper_bytecode = root / "code/helper.pyc"
            helper_source.write_text("value = 'bytecode helper'\n", encoding="utf-8")
            py_compile.compile(
                str(helper_source), cfile=str(helper_bytecode), doraise=True
            )
            helper_source.unlink()
            entrypoint = root / "code/analysis.py"
            entrypoint.write_text(
                "import helper\n" + entrypoint.read_text(encoding="utf-8"),
                encoding="utf-8",
            )
            execution_id = "RUN_BYTECODE_IMPORT"
            runner = self._run_runner(
                root,
                execution_id,
                ["A1"],
                [self._output_spec(execution_id)],
            )
            self.assertNotEqual(runner.returncode, 0)
            self.assertIn("bytecode", runner.stderr.casefold())

    def test_finalizer_rejects_unbound_or_ambiguous_integer_seed(self) -> None:
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
            with self.subTest(option=option), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                self._prepare_project(root)
                execution_id = "RUN_SEED_TAMPER"
                runner = self._run_runner(
                    root,
                    execution_id,
                    ["A1"],
                    [self._output_spec(execution_id)],
                )
                self.assertEqual(runner.returncode, 0, runner.stderr)

                def replace_seed_option(value: dict[str, Any]) -> None:
                    argv = list(value["command_argv"])
                    argv[argv.index("--seed")] = option
                    value["command_argv"] = argv
                    value["command"] = subprocess.list2cmdline(argv)

                self._mutate_pending(
                    root,
                    execution_id,
                    receipt_mutator=replace_seed_option,
                    fragment_mutator=replace_seed_option,
                )
                check = self._output_check(
                    execution_id, "OUTPUT1", ["A1"], "CHECK_OUTPUT"
                )
                finalizer = self._finalize(root, execution_id, [check])
                self.assertNotEqual(finalizer.returncode, 0)
                self.assertIn("seed", finalizer.stderr.casefold())


if __name__ == "__main__":
    unittest.main()
