# Minimal Omicos reuse routing

The main reconstruction Skill owns dependency order, evidence classes, the
traceability table, four-state semantics, and final completion language. Reused
Skills contribute a bounded capability; their output must be translated into
the main contract rather than replacing it.

Load an optional Skill only when its trigger is present and the active stage
needs it. Load at most one optional Skill for one bounded subtask at a time.

| Trigger | Reuse | Boundary |
| --- | --- | --- |
| Only DOI/PMID/PMCID or missing legal full text | `fulltext-free` | Retrieval/extraction only; inventory the returned source and limitations. |
| DOCX/XLSX/PPTX or extraction not handled by native readers | `office-tools` | Format extraction/creation only; preserve paragraph/sheet/cell locators. |
| Need to locate public datasets/supplements | `dataset-linkout` | Discovery only; accessions and URLs are not proof that the exact input was used. |
| Paper claims must be mapped to repository code | `paper-code-audit` | Reuse file/function/config/runtime mapping; ignore its legacy status/output schema. |
| Sources disagree or terminology differs | `source-comparison` | Reuse side-by-side comparison; do not collapse into consensus or use its status enum. |
| Statistical tests or inferential claims need review | `statistics-check` | Add general checks; still apply this Skill's unit/pseudoreplication/modality audit. |
| Claim strength, alternatives, or causality needs review | `scientific-critical-thinking` | Use for reasoning; evidence class and claim ceiling remain controlled here. |
| Final workspace traceability review requested or useful | `evidence-traceability-review` | It checks visible links, not scientific correctness or reproduction completion. |
| Omics data must be loaded for execution | `data-io-loading` | Use only for supported formats and record actual runtime signatures/versions. |
| Sample identifiers/design need reconciliation | `sample-metadata-alignment` | Preserve proposed versus verified mappings and biological unit. |
| Gene/feature ids require conversion | `gene-id-conversion` | Record species, release, one-to-many/unmapped handling, and original ids. |
| Executed notebook must be exported | `notebook-export` | Export only actual executed cells/outputs; it cannot create runtime evidence retroactively. |

For a specialized assay execution, select the most specific installed Omicos
analysis Skill that matches the observed modality and requested method. If it
is unavailable or not authorized for the active Agent, stop execution and give
a handoff or code-guidance plan. Do not substitute a familiar workflow.

Avoid these common over-selection errors:

- do not load literature search for fully supplied local materials;
- do not load statistics review for a purely descriptive code-location query;
- do not load plotting Skills when only upstream computation is being audited;
- do not load report/rendering Skills unless the user requests those formats;
- do not reload a Skill or resource after its bounded output has been captured;
- do not let a reused Skill's legacy slash command, team name, status enum, or
  output path override the Omicos local project contract.
