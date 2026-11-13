from __future__ import annotations

import importlib.util
import tempfile
import unittest
from pathlib import Path
from typing import Callable


SKILL_ROOT = Path(__file__).resolve().parents[1]
VALIDATOR_PATH = SKILL_ROOT / "scripts" / "validate_reconstruction.py"
CONTRACT_TEST_PATH = Path(__file__).with_name("test_contract_scenarios.py")


def _load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


VALIDATOR = _load_module("static_parameter_validator", VALIDATOR_PATH)
CONTRACT = _load_module("static_parameter_contract_helpers", CONTRACT_TEST_PATH)


def _install_code(root: Path, manifest: dict, code: str) -> None:
    code_path = root / "code/analysis.py"
    code_path.write_text(code, encoding="utf-8")
    fingerprint = f"sha256:{CONTRACT._sha256(code_path)}"
    source = next(item for item in manifest["sources"] if item["source_id"] == "SRC004")
    source["fingerprint"] = fingerprint
    manifest["analyses"][0]["code_locations"][0]["snapshot"] = fingerprint
    source_fingerprint = VALIDATOR._source_set_fingerprint(manifest["sources"])
    for stage in manifest["stage_state"]:
        stage["input_fingerprint"] = source_fingerprint


def _validate(
    manifest: dict,
    setup: Callable[[Path, dict], None] | None = None,
) -> dict:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        CONTRACT._materialize_sources(root, manifest)
        if setup:
            setup(root, manifest)
        rows = [
            CONTRACT.trace_row(manifest, index)
            for index in range(len(manifest["analyses"]))
        ]
        CONTRACT._write_project(
            root,
            manifest,
            rows,
            CONTRACT._canonical_report(manifest),
        )
        return VALIDATOR.validate_project(root, write_report=True)


class StaticParameterHardeningTests(unittest.TestCase):
    def test_literal_annassign_and_finite_alias_resolve(self) -> None:
        source = """\
ALPHA: float = 0.05
DEFAULT_ALPHA = ALPHA
FINAL_ALPHA = DEFAULT_ALPHA
parser.add_argument("--alpha", default=FINAL_ALPHA)
"""
        values, gaps = VALIDATOR._python_cli_default_inspections(source, "alpha")
        self.assertEqual(values, [0.05])
        self.assertEqual(gaps, [])

        set_default_values, set_default_gaps = VALIDATOR._python_cli_default_inspections(
            "ALPHA: float = 0.05\nparser.set_defaults(alpha=ALPHA)\n",
            "alpha",
        )
        self.assertEqual(set_default_values, [0.05])
        self.assertEqual(set_default_gaps, [])

    def test_click_module_alias_resolves(self) -> None:
        source = """\
DEFAULT_ALPHA: float = 0.05
@click.option("--alpha", default=DEFAULT_ALPHA)
def cli(alpha):
    return alpha
"""
        values, gaps = VALIDATOR._python_cli_default_inspections(source, "alpha")
        self.assertEqual(values, [0.05])
        self.assertEqual(gaps, [])

    def test_registration_callable_alias_resolves_and_drift_conflicts(self) -> None:
        source = """\
DEFAULT_ALPHA = 0.10
add_alpha = parser.add_argument
add_alpha("--alpha", type=float, default=DEFAULT_ALPHA)
"""
        values, gaps = VALIDATOR._python_cli_default_inspections(source, "alpha")
        self.assertEqual(values, [0.10])
        self.assertEqual(gaps, [])

        manifest = CONTRACT.base_manifest()

        def setup(root: Path, value: dict) -> None:
            code = CONTRACT.SOURCE_CONTENT["code/analysis.py"].replace(
                'parser.add_argument("--alpha", type=float, default=ALPHA)',
                'DEFAULT_ALPHA = 0.10\nadd_alpha = parser.add_argument\n'
                'add_alpha("--alpha", type=float, default=DEFAULT_ALPHA)',
            )
            _install_code(root, value, code)

        result = _validate(manifest, setup)
        self.assertFalse(result["valid"])
        self.assertEqual(result["derived_statuses"]["A001"]["derived"], "材料冲突")
        self.assertIn(
            "undeclared_parameter_conflict",
            {item["code"] for item in result["errors"]},
        )

    def test_unresolved_cli_wrapper_and_implicit_default_fail_closed(self) -> None:
        cases = {
            "getattr wrapper": (
                'DEFAULT_ALPHA = 0.10\n'
                'getattr(parser, "add_argument")("--alpha", default=DEFAULT_ALPHA)\n'
            ),
            "parser-level default": (
                'DEFAULT_ALPHA = 0.10\n'
                'parser = argparse.ArgumentParser(argument_default=DEFAULT_ALPHA)\n'
                'parser.add_argument("--alpha", type=float)\n'
            ),
        }
        for label, source in cases.items():
            with self.subTest(label=label):
                _, gaps = VALIDATOR._python_cli_default_inspections(source, "alpha")
                self.assertTrue(gaps, source)

    def test_static_option_and_dest_expressions_are_resolved(self) -> None:
        cases = {
            "option alias": 'OPT = "--alpha"\nparser.add_argument(OPT, default=0.10)\n',
            "option concatenation": 'parser.add_argument("--" + "alpha", default=0.10)\n',
            "dest alias": (
                'NAME = "al" + "pha"\n'
                'parser.add_argument("--threshold", dest=NAME, default=0.10)\n'
            ),
        }
        for label, source in cases.items():
            with self.subTest(label=label):
                values, gaps = VALIDATOR._python_cli_default_inspections(source, "alpha")
                self.assertEqual(values, [0.10])
                self.assertEqual(gaps, [])

    def test_dynamic_cli_targets_and_callable_shadowing_fail_closed(self) -> None:
        cases = {
            "static f-string is conservatively dynamic": (
                'NAME = "alpha"\nparser.add_argument(f"--{NAME}", default=0.10)\n'
            ),
            "custom wrapper": (
                'OPT = "--" + "alpha"\nregister(OPT, default=0.10)\n'
            ),
            "dynamic option": (
                'OPT = os.getenv("OPTION")\nparser.add_argument(OPT, default=0.10)\n'
            ),
            "shadowed callable alias": (
                'ADD = parser.add_argument\n'
                'def configure(ADD):\n'
                '    ADD("--alpha", default=0.10)\n'
            ),
        }
        for label, source in cases.items():
            with self.subTest(label=label):
                _, gaps = VALIDATOR._python_cli_default_inspections(source, "alpha")
                self.assertTrue(gaps, source)

        values, gaps = VALIDATOR._python_cli_default_inspections(
            'OPT = "--beta"\nparser.add_argument(OPT, default=0.10)\n',
            "alpha",
        )
        self.assertEqual(values, [])
        self.assertEqual(gaps, [])

    def test_dynamic_target_cannot_hide_default_drift(self) -> None:
        replacements = {
            "concatenated option": 'parser.add_argument("--" + "alpha", default=0.10)',
            "aliased option": (
                'OPT = "--" + "alpha"\nparser.add_argument(OPT, default=0.10)'
            ),
            "aliased dest": (
                'NAME = "al" + "pha"\n'
                'parser.add_argument("--threshold", dest=NAME, default=0.10)'
            ),
            "getattr": (
                'OPT = "--" + "alpha"\n'
                'getattr(parser, "add_argument")(OPT, default=0.10)'
            ),
            "wrapper": (
                'OPT = "--" + "alpha"\nregister(OPT, default=0.10)'
            ),
            "f-string": (
                'NAME = "alpha"\nparser.add_argument(f"--{NAME}", default=0.10)'
            ),
        }
        for label, replacement in replacements.items():
            with self.subTest(label=label):
                manifest = CONTRACT.base_manifest()

                def setup(root: Path, value: dict, replacement: str = replacement) -> None:
                    code = CONTRACT.SOURCE_CONTENT["code/analysis.py"].replace(
                        'parser.add_argument("--alpha", type=float, default=ALPHA)',
                        replacement,
                    )
                    _install_code(root, value, code)

                result = _validate(manifest, setup)
                self.assertFalse(result["valid"])
                self.assertIn(
                    result["derived_statuses"]["A001"]["derived"],
                    {"材料冲突", "受阻"},
                )
                self.assertTrue(
                    {"undeclared_parameter_conflict", "undeclared_static_parameter_gap"}
                    & {item["code"] for item in result["errors"]}
                )

    def test_module_alias_default_drift_is_material_conflict(self) -> None:
        manifest = CONTRACT.base_manifest()

        def setup(root: Path, value: dict) -> None:
            code = CONTRACT.SOURCE_CONTENT["code/analysis.py"].replace(
                "ALPHA = 0.05",
                "ALPHA = 0.05\nDEFAULT_ALPHA = 0.10",
            ).replace("default=ALPHA", "default=DEFAULT_ALPHA")
            _install_code(root, value, code)

        result = _validate(manifest, setup)
        self.assertFalse(result["valid"])
        self.assertEqual(result["derived_statuses"]["A001"]["derived"], "材料冲突")
        self.assertIn(
            "undeclared_parameter_conflict",
            {item["code"] for item in result["errors"]},
        )

    def test_dynamic_conditional_and_reassigned_defaults_fail_closed(self) -> None:
        replacements = {
            "dynamic": 'default=os.getenv("ALPHA", "0.05")',
            "conditional": "default=(0.05 if USE_REPORTED else 0.10)",
            "reassigned": "default=DEFAULT_ALPHA",
        }
        prefixes = {
            "dynamic": "",
            "conditional": "USE_REPORTED = True\n",
            "reassigned": "DEFAULT_ALPHA = 0.05\nDEFAULT_ALPHA = 0.10\n",
        }
        for label, replacement in replacements.items():
            with self.subTest(label=label):
                manifest = CONTRACT.base_manifest()

                def setup(root: Path, value: dict, *, label: str = label) -> None:
                    code = prefixes[label] + CONTRACT.SOURCE_CONTENT["code/analysis.py"]
                    code = code.replace("default=ALPHA", replacements[label])
                    _install_code(root, value, code)

                result = _validate(manifest, setup)
                self.assertFalse(result["valid"])
                self.assertEqual(result["derived_statuses"]["A001"]["derived"], "受阻")
                self.assertIn(
                    "undeclared_static_parameter_gap",
                    {item["code"] for item in result["errors"]},
                )

    def test_conditionally_defined_cli_default_fails_closed(self) -> None:
        values, gaps = VALIDATOR._python_cli_default_inspections(
            "if enabled:\n    parser.add_argument('--alpha', default=0.05)\n",
            "alpha",
        )
        self.assertEqual(values, [0.05])
        self.assertTrue(any("conditionally" in gap for gap in gaps), gaps)

    def test_local_shadow_alias_cycle_and_short_circuit_fail_closed(self) -> None:
        cases = {
            "local shadow": (
                "DEFAULT_ALPHA = 0.05\n"
                "def main():\n"
                "    DEFAULT_ALPHA = 0.10\n"
                "    parser.add_argument('--alpha', default=DEFAULT_ALPHA)\n"
            ),
            "alias cycle": (
                "FIRST_ALPHA = SECOND_ALPHA\n"
                "SECOND_ALPHA = FIRST_ALPHA\n"
                "parser.add_argument('--alpha', default=FIRST_ALPHA)\n"
            ),
            "short circuit": (
                "enabled and parser.add_argument('--alpha', default=0.05)\n"
            ),
        }
        for label, source in cases.items():
            with self.subTest(label=label):
                _, gaps = VALIDATOR._python_cli_default_inspections(source, "alpha")
                self.assertTrue(gaps)

    def test_assignment_literals_reject_duplicate_keys_nan_and_overflow(self) -> None:
        for literal in (
            '{"value": 1, "value": 2}',
            "NaN",
            "1e400",
            "{'value': 1, 'value': 2}",
        ):
            with self.subTest(literal=literal):
                self.assertIs(VALIDATOR._parse_simple_literal(literal), VALIDATOR._NO_LITERAL)

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            code_path = root / "analysis.py"
            code_path.write_text(
                'alpha = {"value": 1, "value": 2}\n', encoding="utf-8"
            )
            analysis = {
                "code_locations": [
                    {
                        "evidence_id": "E_CODE",
                        "path": "analysis.py",
                        "evidence_status": "active_config",
                    }
                ]
            }
            values, gaps = VALIDATOR._active_code_parameter_inspection(
                analysis, root, "alpha"
            )
        self.assertEqual(values, [])
        self.assertTrue(gaps)
        self.assertIn("dynamic", gaps[0]["reason"])

        for payload in ('{"alpha": 0.05, "alpha": 0.10}\n', '{"alpha": NaN}\n'):
            with self.subTest(active_json=payload), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                config_path = root / "config.json"
                config_path.write_text(payload, encoding="utf-8")
                analysis = {
                    "code_locations": [
                        {
                            "evidence_id": "E_CONFIG",
                            "path": "config.json",
                            "evidence_status": "active_config",
                        }
                    ]
                }
                values, gaps = VALIDATOR._active_code_parameter_inspection(
                    analysis, root, "alpha"
                )
                self.assertEqual(values, [])
                self.assertTrue(any("not strict JSON" in item["reason"] for item in gaps))

    def test_non_ascii_parameter_and_assignment_names_are_blocked(self) -> None:
        self.assertFalse(VALIDATOR._is_ascii_parameter_name("ſeed"))
        manifest = CONTRACT.base_manifest()
        manifest["analyses"][0]["method_parameters"]["parameters"][0]["name"] = "ſeed"
        result = _validate(manifest)
        self.assertFalse(result["valid"])
        self.assertIn(
            "parameter_name_not_ascii",
            {item["code"] for item in result["errors"]},
        )

        values, gaps = VALIDATOR._python_cli_default_inspections(
            "ſeed = 999\nparser.add_argument('--seed', default=ſeed)\n",
            "seed",
        )
        self.assertEqual(values, [999])
        self.assertTrue(gaps)
        self.assertTrue(any("non-ASCII confusable" in gap for gap in gaps), gaps)


if __name__ == "__main__":
    unittest.main()
