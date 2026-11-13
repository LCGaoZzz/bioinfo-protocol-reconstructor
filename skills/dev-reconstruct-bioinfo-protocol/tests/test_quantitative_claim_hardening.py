from __future__ import annotations

import copy
import sys
import unittest
from pathlib import Path

TEST_DIR = Path(__file__).resolve().parent
if str(TEST_DIR) not in sys.path:
    sys.path.insert(0, str(TEST_DIR))

import test_contract_scenarios as contract


class QuantitativeClaimHardeningTests(unittest.TestCase):
    def validate(self, manifest: dict, setup=None) -> dict:
        harness = contract.ReconstructionContractScenarios(methodName="runTest")
        return harness.validate(manifest, setup=setup)

    @staticmethod
    def _executed_claim(root: Path, manifest: dict) -> dict:
        contract._run_successful_fixture(root, manifest)
        return manifest["analyses"][0]["interpretation"]["direct_observation"][0][
            "quantitative_claims"
        ][0]

    @staticmethod
    def _source_claim_manifest(
        *, metric: str, value: int | float, unit: str, excerpt: str
    ) -> dict:
        manifest = contract.base_manifest()
        manifest["analyses"][0]["interpretation"]["direct_observation"] = [
            contract._statement(
                f"The inspected Methods text reports the selected {metric}.",
                "E_METHOD",
                quantitative_claims=[
                    {
                        "metric": metric,
                        "value": value,
                        "unit": unit,
                        "evidence_ref": "E_METHOD",
                        "binding": {
                            "kind": "source_excerpt",
                            "source_id": "SRC003",
                            "locator": "Methods:L3",
                            "exact_excerpt": excerpt,
                        },
                    }
                ],
            )
        ]
        return manifest

    @staticmethod
    def _install_method_excerpt(excerpt: str):
        def install(root: Path, value: dict) -> None:
            methods = root / "methods.md"
            methods.write_text(f"# Methods\n\n{excerpt}\n", encoding="utf-8")
            value["sources"][2]["fingerprint"] = f"sha256:{contract._sha256(methods)}"
            fingerprint = contract.VALIDATOR._source_set_fingerprint(value["sources"])
            for stage in value["stage_state"]:
                stage["input_fingerprint"] = fingerprint

        return install

    def test_unrelated_seed_exit_and_parameter_values_cannot_satisfy_result_claim(self) -> None:
        for false_value in ("7", "0", "0.05"):
            with self.subTest(false_value=false_value):
                manifest = contract.base_manifest()

                def mutate(root: Path, value: dict, candidate: str = false_value) -> None:
                    claim = self._executed_claim(root, value)
                    claim["value"] = candidate

                result = self.validate(manifest, setup=mutate)
                self.assertFalse(result["valid"])
                self.assertIn(
                    "quantitative_result_value_mismatch",
                    {item["code"] for item in result["errors"]},
                )

    def test_quantity_word_cannot_bypass_structured_binding(self) -> None:
        for prose in (
            "The selected mean difference is seven.",
            "选定的均值差是七。",
            "选定的均值差是百分之七。",
            "选定的均值差约七倍。",
        ):
            with self.subTest(prose=prose):
                manifest = contract.base_manifest()

                def mutate(root: Path, value: dict, candidate: str = prose) -> None:
                    self._executed_claim(root, value)
                    value["analyses"][0]["interpretation"]["direct_observation"][0][
                        "statement"
                    ] = candidate

                result = self.validate(manifest, setup=mutate)
                self.assertFalse(result["valid"])
                self.assertIn(
                    "interpretation_quantity_must_be_structured",
                    {item["code"] for item in result["errors"]},
                )

    def test_domain_modality_and_component_identifiers_are_not_quantities(self) -> None:
        for prose in (
            "The single-cell panel displays the annotated populations.",
            "The single-nucleus assay preserves the annotated populations.",
            "The first principal component separates the annotated populations.",
            "第一主成分显示样本分离。",
        ):
            with self.subTest(prose=prose):
                manifest = contract.base_manifest()
                manifest["analyses"][0]["interpretation"]["direct_observation"][0][
                    "statement"
                ] = prose
                result = self.validate(manifest)
                self.assertTrue(result["valid"], result["errors"])

    def test_result_claim_unit_and_metric_must_match_selected_check(self) -> None:
        cases = (
            ("unit", "percent", "quantitative_result_unit_mismatch"),
            ("metric", "seed", "quantitative_result_metric_mismatch"),
        )
        for field, candidate, expected_code in cases:
            with self.subTest(field=field):
                manifest = contract.base_manifest()

                def mutate(root: Path, value: dict) -> None:
                    claim = self._executed_claim(root, value)
                    claim[field] = candidate

                result = self.validate(manifest, setup=mutate)
                self.assertFalse(result["valid"])
                self.assertIn(expected_code, {item["code"] for item in result["errors"]})

    def test_result_claim_must_name_selected_analysis_owned_output(self) -> None:
        manifest = contract.base_manifest()

        def mutate(root: Path, value: dict) -> None:
            claim = self._executed_claim(root, value)
            claim["evidence_ref"] = "RUN_OK"

        result = self.validate(manifest, setup=mutate)
        self.assertFalse(result["valid"])
        self.assertIn(
            "quantitative_result_output_unbound",
            {item["code"] for item in result["errors"]},
        )

    def test_source_excerpt_binding_is_exact_and_metric_scoped(self) -> None:
        manifest = contract.base_manifest()
        analysis = manifest["analyses"][0]
        analysis["interpretation"]["direct_observation"] = [
            contract._statement(
                "The inspected Methods text records the alpha threshold.",
                "E_METHOD",
                quantitative_claims=[
                    {
                        "metric": "alpha",
                        "value": 0.05,
                        "unit": "dimensionless",
                        "evidence_ref": "E_METHOD",
                        "binding": {
                            "kind": "source_excerpt",
                            "source_id": "SRC003",
                            "locator": "Methods:L3",
                            "exact_excerpt": "alpha=0.05",
                        },
                    }
                ],
            )
        ]
        result = self.validate(copy.deepcopy(manifest))
        self.assertTrue(result["valid"], result["errors"])

        for false_value in (5, 0, 0.0, "5", "0", "0.0", "05", "0.05"):
            with self.subTest(false_value=false_value):
                value_variant = copy.deepcopy(manifest)
                value_variant["analyses"][0]["interpretation"]["direct_observation"][0][
                    "quantitative_claims"
                ][0]["value"] = false_value
                result = self.validate(value_variant)
                self.assertFalse(result["valid"])
                self.assertIn(
                    "quantitative_source_value_absent",
                    {item["code"] for item in result["errors"]},
                )

        unit_variant = copy.deepcopy(manifest)
        unit_variant["analyses"][0]["interpretation"]["direct_observation"][0][
            "quantitative_claims"
        ][0]["unit"] = "percent"
        result = self.validate(unit_variant)
        self.assertFalse(result["valid"])
        self.assertIn(
            "quantitative_source_unit_absent",
            {item["code"] for item in result["errors"]},
        )

        for false_metric in ("mean difference", "p"):
            metric_variant = copy.deepcopy(manifest)
            metric_variant["analyses"][0]["interpretation"]["direct_observation"][0][
                "quantitative_claims"
            ][0]["metric"] = false_metric
            result = self.validate(metric_variant)
            self.assertFalse(result["valid"])
            self.assertIn(
                "quantitative_source_metric_absent",
                {item["code"] for item in result["errors"]},
            )

        locator_variant = copy.deepcopy(manifest)

        def move_excerpt_outside_locator(root: Path, value: dict) -> None:
            methods = root / "methods.md"
            methods.write_text(
                "# Methods\n\nNo alpha threshold is reported here.\n\n"
                "# Unrelated appendix\nalpha=0.05\n",
                encoding="utf-8",
            )
            value["sources"][2]["fingerprint"] = f"sha256:{contract._sha256(methods)}"
            fingerprint = contract.VALIDATOR._source_set_fingerprint(value["sources"])
            for stage in value["stage_state"]:
                stage["input_fingerprint"] = fingerprint

        result = self.validate(locator_variant, setup=move_excerpt_outside_locator)
        self.assertFalse(result["valid"])
        self.assertIn(
            "quantitative_source_excerpt_not_found",
            {item["code"] for item in result["errors"]},
        )

    def test_source_metric_conflicting_values_fail_closed_but_duplicates_pass(self) -> None:
        conflicting_excerpt = "alpha=0.05; alpha=0.1"
        for selected_value in (0.05, 0.1):
            with self.subTest(case="conflict", selected_value=selected_value):
                manifest = self._source_claim_manifest(
                    metric="alpha",
                    value=selected_value,
                    unit="dimensionless",
                    excerpt=conflicting_excerpt,
                )
                result = self.validate(
                    manifest,
                    setup=self._install_method_excerpt(conflicting_excerpt),
                )
                self.assertFalse(result["valid"])
                self.assertIn(
                    "quantitative_source_metric_values_conflict",
                    {item["code"] for item in result["errors"]},
                )

        duplicate_excerpt = "alpha=0.05; alpha=0.05"
        manifest = self._source_claim_manifest(
            metric="alpha",
            value=0.05,
            unit="dimensionless",
            excerpt=duplicate_excerpt,
        )
        result = self.validate(
            manifest,
            setup=self._install_method_excerpt(duplicate_excerpt),
        )
        self.assertTrue(result["valid"], result["errors"])

    def test_parameter_binding_uses_exact_structured_parameter_value(self) -> None:
        manifest = contract.base_manifest()
        analysis = manifest["analyses"][0]
        analysis["interpretation"]["reconstructed_support"] = [
            contract._statement(
                "Methods and active code register the same alpha setting.",
                "E_METHOD",
                "E_CODE",
                quantitative_claims=[
                    {
                        "metric": "alpha",
                        "value": 0.05,
                        "unit": "not_recorded",
                        "evidence_ref": "E_METHOD",
                        "binding": {
                            "kind": "parameter",
                            "name": "alpha",
                            "value_status": "reported",
                        },
                    }
                ],
            )
        ]
        result = self.validate(copy.deepcopy(manifest))
        self.assertTrue(result["valid"], result["errors"])

        manifest["analyses"][0]["interpretation"]["reconstructed_support"][0][
            "quantitative_claims"
        ][0]["value"] = 0.10
        result = self.validate(manifest)
        self.assertFalse(result["valid"])
        self.assertIn(
            "quantitative_parameter_value_mismatch",
            {item["code"] for item in result["errors"]},
        )

    def test_source_percentage_unit_is_bound_to_the_selected_value(self) -> None:
        manifest = contract.base_manifest()
        analysis = manifest["analyses"][0]
        analysis["interpretation"]["direct_observation"] = [
            contract._statement(
                "The inspected Methods text reports the response.",
                "E_METHOD",
                quantitative_claims=[
                    {
                        "metric": "response",
                        "value": 5,
                        "unit": "%",
                        "evidence_ref": "E_METHOD",
                        "binding": {
                            "kind": "source_excerpt",
                            "source_id": "SRC003",
                            "locator": "Methods:L3",
                            "exact_excerpt": "response=5%",
                        },
                    }
                ],
            )
        ]

        def install_percentage_source(root: Path, value: dict) -> None:
            methods = root / "methods.md"
            methods.write_text("# Methods\n\nresponse=5%\n", encoding="utf-8")
            value["sources"][2]["fingerprint"] = f"sha256:{contract._sha256(methods)}"
            fingerprint = contract.VALIDATOR._source_set_fingerprint(value["sources"])
            for stage in value["stage_state"]:
                stage["input_fingerprint"] = fingerprint

        for correct_unit in ("%", "percent"):
            with self.subTest(correct_unit=correct_unit):
                variant = copy.deepcopy(manifest)
                variant["analyses"][0]["interpretation"]["direct_observation"][0][
                    "quantitative_claims"
                ][0]["unit"] = correct_unit
                result = self.validate(variant, setup=install_percentage_source)
                self.assertTrue(result["valid"], result["errors"])

        for false_unit in ("dimensionless", "not_recorded"):
            with self.subTest(false_unit=false_unit):
                variant = copy.deepcopy(manifest)
                variant["analyses"][0]["interpretation"]["direct_observation"][0][
                    "quantitative_claims"
                ][0]["unit"] = false_unit
                result = self.validate(variant, setup=install_percentage_source)
                self.assertFalse(result["valid"])
                self.assertIn(
                    "quantitative_source_unit_absent",
                    {item["code"] for item in result["errors"]},
                )

        attack = copy.deepcopy(manifest)
        attack_claim = attack["analyses"][0]["interpretation"]["direct_observation"][0][
            "quantitative_claims"
        ][0]
        attack_claim["binding"]["exact_excerpt"] = (
            "response was assessed; dropout=5%"
        )

        def install_cross_metric_source(root: Path, value: dict) -> None:
            methods = root / "methods.md"
            methods.write_text(
                "# Methods\n\nresponse was assessed; dropout=5%\n",
                encoding="utf-8",
            )
            value["sources"][2]["fingerprint"] = f"sha256:{contract._sha256(methods)}"
            fingerprint = contract.VALIDATOR._source_set_fingerprint(value["sources"])
            for stage in value["stage_state"]:
                stage["input_fingerprint"] = fingerprint

        result = self.validate(attack, setup=install_cross_metric_source)
        self.assertFalse(result["valid"])
        self.assertIn(
            "quantitative_source_metric_value_unbound",
            {item["code"] for item in result["errors"]},
        )

        attack_claim["metric"] = "dropout"
        result = self.validate(attack, setup=install_cross_metric_source)
        self.assertTrue(result["valid"], result["errors"])

    def test_source_nonpercentage_unit_requires_the_complete_adjacent_token(self) -> None:
        manifest = contract.base_manifest()
        analysis = manifest["analyses"][0]
        analysis["interpretation"]["direct_observation"] = [
            contract._statement(
                "The inspected Methods text reports the concentration.",
                "E_METHOD",
                quantitative_claims=[
                    {
                        "metric": "concentration",
                        "value": 5,
                        "unit": "mg/mL",
                        "evidence_ref": "E_METHOD",
                        "binding": {
                            "kind": "source_excerpt",
                            "source_id": "SRC003",
                            "locator": "Methods:L3",
                            "exact_excerpt": "concentration = 5 mg/mL",
                        },
                    }
                ],
            )
        ]

        def install_concentration_source(root: Path, value: dict) -> None:
            methods = root / "methods.md"
            methods.write_text(
                "# Methods\n\nconcentration = 5 mg/mL\n",
                encoding="utf-8",
            )
            value["sources"][2]["fingerprint"] = f"sha256:{contract._sha256(methods)}"
            fingerprint = contract.VALIDATOR._source_set_fingerprint(value["sources"])
            for stage in value["stage_state"]:
                stage["input_fingerprint"] = fingerprint

        result = self.validate(copy.deepcopy(manifest), setup=install_concentration_source)
        self.assertTrue(result["valid"], result["errors"])

        for false_unit in ("dimensionless", "not_recorded", "mg"):
            with self.subTest(false_unit=false_unit):
                variant = copy.deepcopy(manifest)
                variant["analyses"][0]["interpretation"]["direct_observation"][0][
                    "quantitative_claims"
                ][0]["unit"] = false_unit
                result = self.validate(variant, setup=install_concentration_source)
                self.assertFalse(result["valid"])
                self.assertIn(
                    "quantitative_source_unit_absent",
                    {item["code"] for item in result["errors"]},
                )

    def test_source_without_unit_allows_placeholder_before_narrative_text(self) -> None:
        manifest = contract.base_manifest()
        analysis = manifest["analyses"][0]
        analysis["interpretation"]["direct_observation"] = [
            contract._statement(
                "The inspected Methods text reports the selected threshold.",
                "E_METHOD",
                quantitative_claims=[
                    {
                        "metric": "threshold",
                        "value": 5,
                        "unit": "dimensionless",
                        "evidence_ref": "E_METHOD",
                        "binding": {
                            "kind": "source_excerpt",
                            "source_id": "SRC003",
                            "locator": "Methods:L3",
                            "exact_excerpt": "threshold = 5 was used for filtering",
                        },
                    }
                ],
            )
        ]

        def install_dimensionless_source(root: Path, value: dict) -> None:
            methods = root / "methods.md"
            methods.write_text(
                "# Methods\n\nthreshold = 5 was used for filtering\n",
                encoding="utf-8",
            )
            value["sources"][2]["fingerprint"] = f"sha256:{contract._sha256(methods)}"
            fingerprint = contract.VALIDATOR._source_set_fingerprint(value["sources"])
            for stage in value["stage_state"]:
                stage["input_fingerprint"] = fingerprint

        for placeholder in ("dimensionless", "not_recorded"):
            with self.subTest(placeholder=placeholder):
                variant = copy.deepcopy(manifest)
                variant["analyses"][0]["interpretation"]["direct_observation"][0][
                    "quantitative_claims"
                ][0]["unit"] = placeholder
                result = self.validate(variant, setup=install_dimensionless_source)
                self.assertTrue(result["valid"], result["errors"])

    def test_source_scientific_power_is_one_typed_value_with_adjacent_unit(self) -> None:
        cases = (
            ("count = 10^6 cells", 1_000_000, 10),
            ("count = 2 × 10^6 cells", 2_000_000, 2),
            ("count = 2*10^6 cells", 2_000_000, 2),
        )
        for excerpt, complete_value, truncated_value in cases:
            with self.subTest(excerpt=excerpt, case="complete"):
                manifest = self._source_claim_manifest(
                    metric="count",
                    value=complete_value,
                    unit="cells",
                    excerpt=excerpt,
                )
                result = self.validate(
                    manifest,
                    setup=self._install_method_excerpt(excerpt),
                )
                self.assertTrue(result["valid"], result["errors"])

            with self.subTest(excerpt=excerpt, case="truncated"):
                manifest = self._source_claim_manifest(
                    metric="count",
                    value=truncated_value,
                    unit="dimensionless",
                    excerpt=excerpt,
                )
                result = self.validate(
                    manifest,
                    setup=self._install_method_excerpt(excerpt),
                )
                self.assertFalse(result["valid"])
                self.assertIn(
                    "quantitative_source_value_absent",
                    {item["code"] for item in result["errors"]},
                )

            with self.subTest(excerpt=excerpt, case="unit"):
                manifest = self._source_claim_manifest(
                    metric="count",
                    value=complete_value,
                    unit="dimensionless",
                    excerpt=excerpt,
                )
                result = self.validate(
                    manifest,
                    setup=self._install_method_excerpt(excerpt),
                )
                self.assertFalse(result["valid"])
                self.assertIn(
                    "quantitative_source_unit_absent",
                    {item["code"] for item in result["errors"]},
                )

    def test_source_unsupported_composite_numbers_fail_closed(self) -> None:
        cases = (
            ("count", "count = 1,000 cells", 1),
            ("count", "count = 1 000 cells", 1),
            ("p", "p = 0,05", 0),
            ("range", "range = 5-10 mg", 5),
            ("range", "range = 5–10 mg", 5),
            ("ratio", "ratio = 1/2", 1),
            ("ratio", "ratio = 1:2", 1),
            ("mean", "mean = 5 ± 2 mg", 5),
        )
        for metric, excerpt, truncated_value in cases:
            with self.subTest(excerpt=excerpt):
                manifest = self._source_claim_manifest(
                    metric=metric,
                    value=truncated_value,
                    unit="dimensionless",
                    excerpt=excerpt,
                )
                result = self.validate(
                    manifest,
                    setup=self._install_method_excerpt(excerpt),
                )
                self.assertFalse(result["valid"])
                self.assertIn(
                    "quantitative_source_value_absent",
                    {item["code"] for item in result["errors"]},
                )

    def test_source_unicode_and_delimited_units_are_explicit(self) -> None:
        cases = (
            ("浓度", "浓度 = 5 毫克/毫升", "毫克/毫升"),
            ("weight", "weight = 5 (kg)", "kg"),
            ("weight", "weight = 5 [kg]", "kg"),
            ("weight", "weight = 5, kg", "kg"),
        )
        for metric, excerpt, expected_unit in cases:
            with self.subTest(excerpt=excerpt, case="complete"):
                manifest = self._source_claim_manifest(
                    metric=metric,
                    value=5,
                    unit=expected_unit,
                    excerpt=excerpt,
                )
                result = self.validate(
                    manifest,
                    setup=self._install_method_excerpt(excerpt),
                )
                self.assertTrue(result["valid"], result["errors"])

            for false_unit in ("dimensionless", "not_recorded"):
                with self.subTest(excerpt=excerpt, false_unit=false_unit):
                    manifest = self._source_claim_manifest(
                        metric=metric,
                        value=5,
                        unit=false_unit,
                        excerpt=excerpt,
                    )
                    result = self.validate(
                        manifest,
                        setup=self._install_method_excerpt(excerpt),
                    )
                    self.assertFalse(result["valid"])
                    self.assertIn(
                        "quantitative_source_unit_absent",
                        {item["code"] for item in result["errors"]},
                    )

    def test_source_compound_word_and_inverse_units_require_complete_match(self) -> None:
        cases = (
            ("concentration", "concentration = 5 mg per mL", "mg per mL", "mg"),
            ("density", "density = 5 cells per mL", "cells per mL", "cells"),
            ("rate", "rate = 5 reads s-1", "reads s-1", "reads"),
        )
        for metric, excerpt, complete_unit, prefix_unit in cases:
            with self.subTest(excerpt=excerpt, case="complete"):
                manifest = self._source_claim_manifest(
                    metric=metric,
                    value=5,
                    unit=complete_unit,
                    excerpt=excerpt,
                )
                result = self.validate(
                    manifest,
                    setup=self._install_method_excerpt(excerpt),
                )
                self.assertTrue(result["valid"], result["errors"])

            for false_unit in (prefix_unit, "dimensionless", "not_recorded"):
                with self.subTest(excerpt=excerpt, false_unit=false_unit):
                    manifest = self._source_claim_manifest(
                        metric=metric,
                        value=5,
                        unit=false_unit,
                        excerpt=excerpt,
                    )
                    result = self.validate(
                        manifest,
                        setup=self._install_method_excerpt(excerpt),
                    )
                    self.assertFalse(result["valid"])
                    self.assertIn(
                        "quantitative_source_unit_absent",
                        {item["code"] for item in result["errors"]},
                    )

    def test_biomedical_hyphenated_identifiers_are_not_quantities(self) -> None:
        manifest = contract.base_manifest()
        analysis = manifest["analyses"][0]
        analysis["interpretation"]["direct_observation"] = [
            contract._statement(
                "IL-6, PD-1, CTLA-4, SARS-CoV-2, miR-21, let-7, miR-155, "
                "hsa-miR-21-5p, mmu-miR-122-5p, 3' UTR, 5′ UTR, and "
                "5-methylcytosine identifiers occur in the inspected material.",
                "E_METHOD",
            )
        ]
        result = self.validate(copy.deepcopy(manifest))
        self.assertTrue(result["valid"], result["errors"])

        quantitative_tokens = (
            "day-7",
            "HR-2",
            "OR-3",
            "RR-4",
            "FC-7",
            "FDR-5",
            "AUC-8",
            "SD-2",
            "SE-3",
            "MEAN-7",
            "PVAL-5",
            "TPM-10",
            "CPM-20",
            "FPKM-3",
            "RPKM-4",
            "NES-2",
            "log2FC-2",
            "UMI-100",
        )
        for token in quantitative_tokens:
            with self.subTest(token=token):
                variant = copy.deepcopy(manifest)
                variant["analyses"][0]["interpretation"]["direct_observation"][0][
                    "statement"
                ] = f"The result reports {token}."
                result = self.validate(variant)
                self.assertFalse(result["valid"])
                self.assertIn(
                    "interpretation_quantity_must_be_structured",
                    {item["code"] for item in result["errors"]},
                )

    def test_quantitative_claim_cannot_borrow_another_direct_statement_ref(self) -> None:
        manifest = contract.base_manifest()
        analysis = manifest["analyses"][0]
        unverified = copy.deepcopy(analysis["method_parameters"]["evidence"][0])
        unverified["evidence_id"] = "E_UNV_METHOD"
        unverified["evidence_class"] = "无法验证"
        analysis["method_parameters"]["evidence"].append(unverified)
        analysis["interpretation"]["direct_observation"] = [
            contract._statement(
                "The Methods material contains an inspected and an unverifiable record.",
                "E_METHOD",
                "E_UNV_METHOD",
                quantitative_claims=[
                    {
                        "metric": "alpha",
                        "value": 0.05,
                        "unit": "dimensionless",
                        "evidence_ref": "E_UNV_METHOD",
                        "binding": {
                            "kind": "source_excerpt",
                            "source_id": "SRC003",
                            "locator": "Methods:L3",
                            "exact_excerpt": "alpha=0.05",
                        },
                    }
                ],
            )
        ]
        result = self.validate(manifest)
        self.assertFalse(result["valid"])
        self.assertIn(
            "quantitative_claim_evidence_not_directly_available",
            {item["code"] for item in result["errors"]},
        )

    def test_direct_observation_requires_materialized_direct_evidence(self) -> None:
        output_variant = contract.base_manifest()
        output_variant["analyses"][0]["interpretation"]["direct_observation"] = [
            contract._statement("The expected output is described.", "OUT001")
        ]
        result = self.validate(output_variant)
        self.assertFalse(result["valid"])
        self.assertIn(
            "interpretation_observation_without_direct_material",
            {item["code"] for item in result["errors"]},
        )

        class_variant = contract.base_manifest()
        class_variant["analyses"][0]["figure_panel"]["evidence"][0][
            "evidence_class"
        ] = "无法验证"
        result = self.validate(class_variant)
        self.assertFalse(result["valid"])
        self.assertIn(
            "interpretation_observation_without_direct_material",
            {item["code"] for item in result["errors"]},
        )

    def test_inferred_parameter_binding_is_limited_to_inference_lanes(self) -> None:
        manifest = contract.base_manifest()
        analysis = manifest["analyses"][0]
        analysis["method_parameters"]["parameters"].append(
            {
                "name": "provisional_threshold",
                "value": 0.2,
                "value_status": "inferred",
                "evidence_refs": ["E_METHOD"],
                "inference_rationale": "Used only to demonstrate explicit inference routing.",
            }
        )
        inferred_statement = contract._statement(
            "A provisional threshold is recorded as an inference.",
            "E_METHOD",
            quantitative_claims=[
                {
                    "metric": "provisional_threshold",
                    "value": 0.2,
                    "unit": "not_recorded",
                    "evidence_ref": "E_METHOD",
                    "binding": {
                        "kind": "parameter",
                        "name": "provisional_threshold",
                        "value_status": "inferred",
                    },
                }
            ],
        )
        analysis["interpretation"]["direct_observation"] = [
            copy.deepcopy(inferred_statement)
        ]
        result = self.validate(copy.deepcopy(manifest))
        self.assertFalse(result["valid"])
        self.assertIn(
            "inferred_parameter_wrong_interpretation_lane",
            {item["code"] for item in result["errors"]},
        )

        analysis["interpretation"]["direct_observation"] = [
            contract._statement("The synthetic panel displays the group summaries.", "E_FIG")
        ]
        analysis["interpretation"]["reasonable_inference"] = [inferred_statement]
        result = self.validate(manifest)
        self.assertNotIn(
            "inferred_parameter_wrong_interpretation_lane",
            {item["code"] for item in result["errors"]},
        )


if __name__ == "__main__":
    unittest.main()
