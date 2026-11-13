---
id: dev-reconstruct-bioinfo-protocol
name: dev-reconstruct-bioinfo-protocol
description: "Reconstruct and audit a bioinformatics protocol by linking paper claims, figures and captions, Methods and supplements, active code and parameters, runtime evidence, and biological interpretation into a validated traceability package."
tier: community
category: paper_audit
category_order: 49
summary: "Traceable paper-to-figure-to-code bioinformatics reconstruction with conservative execution and interpretation."
use_when: "Use when a paper-linked analysis, figure, method, repository, notebook, or result must be reproduced, audited, explained, or converted into executable guidance without inventing missing evidence."
boot_load: false
---

# Bioinformatics Protocol Reconstruction

## Purpose

Build a defensible, resumable reconstruction of one or more paper-linked
analyses. The durable result is an evidence package, not a prose summary. Every
`analysis_id` must connect the paper claim, figure or panel, method and explicit
parameters, active code location, inputs and outputs, reproduction state, and
conflicts or gaps.

This Skill supports six request modes that may share one project:

- full reconstruction;
- figure or panel explanation;
- paper–code–Methods audit;
- execution or empirical verification;
- executable code guidance;
- follow-up biological interpretation.

## Required project artifacts

Write new artifacts under a user-selected or runtime-provided project directory.
Treat all source materials as read-only. A project may be partial, but it must
make that partial state explicit.

Required:

- `source_inventory.json` — schema/project ids plus source roles, locators,
  availability, and stable fingerprints; its source records mirror the
  manifest exactly;
- `working_state.json` — schema/project ids, source-set input fingerprint,
  stage state, completed artifacts, blockers, and invalidations;
- `reconstruction_manifest.json` — structured evidence, analyses, execution
  records, interpretations, and derived status;
- `traceability.tsv` — exactly this header and order:

  `analysis_id | 正文主张 | figure/panel | method与参数 | code位置 | 输入/输出 | 复现状态 | 冲突或缺口`

- `REPORT.md` — a human-readable report generated from the manifest and table;
- `validation_report.json` — validator result, including failures and warnings.

Use tab characters in `traceability.tsv`; the pipes above only show column
boundaries. One row represents one stable `analysis_id`. Never hide an absent
lane by omitting the row.

## Mandatory dependency order

Run the stages in this order:

1. evidence inventory;
2. cross-material alignment;
3. reproducibility audit;
4. execution or code guidance;
5. biological interpretation;
6. validation and handoff.

Do not start a content-producing stage before its required upstream artifacts
exist and parse. If a prerequisite is missing, preserve all valid partial
artifacts, mark the current stage `partial` or `blocked`, list the exact missing
input, and stop forward scientific work. Stage 6 may still validate and hand
off a blocked partial project; that is closeout, not permission to skip a gate.

Read `references/workflow.md` for stage inputs, outputs, resume rules, and stop
conditions. Read it once for a new project, or reload only the active stage
section for a resumed project.

## Evidence and status contract

Before authoring the first analysis row, read
`references/evidence-contract.md`. It defines source roles, evidence classes,
locators, conflict handling, the exact traceability cells, and deterministic
status derivation.

The only legal reproduction states are:

- `已执行验证`;
- `材料完整但未执行`;
- `受阻`;
- `材料冲突`.

`已执行验证` requires actual successful execution evidence. A notebook, script,
plan, plausible result, or validator fixture is not execution evidence. If
Methods and code conflict, preserve both and use `材料冲突` even when the code
runs; the run establishes actual code behavior, not agreement with the paper.

## Progressive resource policy

Load only the resources needed for the active decision:

- `references/evidence-contract.md`: mandatory before creating analysis rows or
  assigning status;
- `references/workflow.md`: mandatory for a new project and stage transitions;
- `references/modality-audit.md`: stage 3 and stage 5, limited to the relevant
  modality sections;
- `references/code-and-execution.md`: stage 4 only;
- `references/reuse-routing.md`: only when choosing an optional Omicos Skill;
- `schemas/reconstruction_manifest.schema.json`: immediately before writing or
  validating `reconstruction_manifest.json`;
- `scripts/validate_reconstruction.py`: validation implementation; run the
  local resource rather than rewriting it when it is executable;
- `scripts/run_reconstruction.py`: stage-4 process wrapper; use it for a new
  local execution attempt so the attempt receives a fresh run directory,
  captured streams, fingerprints, and a validator-linked receipt;
- `scripts/finalize_execution.py`: stage-4 adjudicator; load it only after
  claim-specific checks (and any runtime-observed parameters) have been written,
  then bind them to output/log evidence before a run can become `succeeded`;
- `scripts/execution_contract.py`: internal shared runner/finalizer/validator
  helpers for exact seed binding, normalized dependency identity and child-runtime
  version observation, and recursive local-code import closure; it is not a
  standalone entrypoint, so use it only through the packaged scripts;
- `TESTING.md` and `tests/`: development verification only, never normal task
  context.

Do not list or read every resource merely because it exists. Do not reload a
resource already used in the same stage unless an input changed or a conflict
requires returning to raw evidence.

## Scientific audit floor

For every analysis, audit the relevant parts of:

- preprocessing and the semantic meaning of each matrix or measurement;
- biological/statistical unit and independent replicate count;
- repeated measures and pseudoreplication;
- batch, pairing, covariates, and complete confounding;
- test assumptions, effect sizes, uncertainty, and multiple testing;
- species, genome build, feature namespace, and gene-identifier mapping;
- parameter agreement across Methods, supplement, config, code, and run logs;
- whether the conclusion strength exceeds the design and evidence.

The modality reference supplies focused checks, but it does not authorize
inventing a design choice or substituting a generic workflow for the paper's
declared method.

## Code and execution floor

Code guidance must state dependencies and versions, random seed handling,
inputs, outputs, configurable paths, and a minimal run command. Preserve unknown
parameters as required options or explicit gaps; do not choose convenient
values and attribute them to the paper.

Represent guidance in each analysis as either `code_guidance: null`, a `ready`
record satisfying the full executable contract, or a `blocked` record naming
both unresolved parameters and issue ids. A `ready` record cannot carry unknown
versions, an unknown seed, unreported/inferred method parameters, hidden
blockers, machine-absolute paths, concrete endpoints/ports, or credential
arguments. It must name an existing project-relative entrypoint and preserve the
analysis input/output artifact ids, paths, semantic types, and fingerprints
exactly. For a Python entrypoint, every statically reachable local code file
must have one fingerprint-consistent active code record. The minimal command
must include every statically resolvable required CLI option; supplied method
parameter values must agree with recorded Methods/code values; and every
statically identified third-party import needs a concrete dependency version.
Dynamic or unsupported CLI/code-loading paths keep guidance blocked.

Execution must record command, environment and dependency versions, seed,
fingerprinted inputs and outputs, exit code, logs, and explicit result checks.
For supported Python execution, dependency names are unique after PEP 503-style
normalization, the interpreter itself is listed, and every recorded version is
observed through the exact child launcher rather than accepted as a declaration.
It must also declare `none`, `execute_now`, or `audit_supplied_record` scope and
an authorization/preflight record. A local run uses a never-reused
`runs/<execution_id>` directory and `scripts/run_reconstruction.py`. A clean
process exit produces `pending_checks`, never immediate success. Write checks to
a separate JSON array, then run `scripts/finalize_execution.py`; copy only the
adjudicated record fragment into the manifest. Each passed check has a stable
run-local `check_id`, explicit `metric` and `unit`, names the analysis ids it
verifies, and includes a structured `verification` selecting one recorded
output/log. The adjudicator mechanically recomputes `observed` and `passed` with
`tsv_cell_equals`, `json_pointer_equals`, `text_contains`, or `sha256_equals`.
Every execution output declares a nonempty `analysis_ids` ownership set, and
each owner must be covered by a passing check whose selected evidence is that
output. Logical artifacts use distinct resolved paths; receipt
`expected_outputs` exactly mirrors output id/path/type/owners. A recorded
`not_applicable` seed cannot coexist with a canonical or ambiguous seed-like
option in the child argv. An integer seed qualifies only through an exact,
case-sensitive canonical long seed option after the entrypoint and before an
argv `--` terminator; a bare equal-valued token, abbreviation, or unproved short
alias is not a binding. The wrapper receipt and record fragment mirror
`code_files`; the manifest record copies the adjudicated fragment. That array
lists the validator-computed local Python import closure with each file's pre-run
SHA-256, and each file maps to exactly one id in `code_evidence_refs` whose
`active_call`, `active_config`, or `active_import_only` record has the same path
and snapshot. Import-only code can fingerprint the execution bundle but cannot
support source-exact method attribution. Dynamic
imports or dotted-name/plugin resolvers, runtime/native/archive/serialized-object code loaders, Python
import-state mutation, subprocess code dispatch, local compiled/bytecode
modules, and unsupported non-Python execution entrypoints fail closed for this
local contract. Python `-P`/`-I` launch modes are rejected; import-affecting
`PYTHON*` variables are removed from the child environment and recorded. A
verified blocked preflight may evidence only the operational blocker, never a
scientific result. Runtime-observed
parameter name/value pairs must likewise be present unambiguously as assignments
or JSON pairs in their named output/log paths; any different value for the same
ASCII-case-insensitive name blocks qualification. Parameter names use
`^[A-Za-z][A-Za-z0-9_.-]*$`, are unique ignoring ASCII case, and a normalized
`seed` must strictly equal the run's top-level seed. A multi-analysis run treats
observed parameters as run-global, so every linked analysis mirrors them as
`observed_runtime`. These are provenance bindings, not proof that the chosen
scientific predicate or tolerance is correct. Adjudication uses a per-run
exclusive lock and is one-shot. Validator-qualified
runtime files must
exist in role-disjoint paths, match recomputed SHA-256 values and recorded run
times, carry matching artifact ids and semantic types, link the entrypoint to
the exact active-code evidence path and snapshot (equal bytes at another path
do not qualify), and link to analyses in both directions. The
record must point to the wrapper-generated `execution_receipt.json` and its
SHA-256; canonical hashes bind checks and observed parameters to both receipt
and record. Static receipt validation detects broken or inconsistent evidence but
is not cryptographic attestation and cannot defeat deliberate manual forgery.
Read `references/code-and-execution.md` before preflight or code delivery.

## Interpretation and claim ceiling

Describe separately:

1. what the figure or output directly shows;
2. what the paper claims it means;
3. what the reconstructed or executed analysis supports;
4. reasonable biological interpretation;
5. what cannot be verified.

Every interpretation entry is a structured `statement`, `evidence_refs`, and
`quantitative_claims` array; the array is present even when empty. A
reconstructed-support statement must span at least two material lanes; do not
create an untraceable narrative after the evidence audit. Direct observation
requires locally inspectable, fingerprint-consistent direct-class material,
qualifying runtime, or a structurally verified blocked preflight; inferred,
unverifiable, or merely expected outputs do not qualify. Keep the free
`statement` qualitative: exact counts, percentages, thresholds, effect sizes,
scientific notation, and quantities written in words appear only in structured
claims and are inserted by canonical report rendering. Every structured claim
contains `metric`, exact JSON `value`, `unit`, `evidence_ref`, and one typed
binding: a concrete passed
`result_check`, an exact source excerpt, or a structured parameter. Runtime
numbers in direct observation or reconstructed support may use only a
`result_check` binding whose `execution_id` and `check_id` resolve uniquely and
whose `metric`, `unit`, and `observed` match the claim exactly; its selected
output artifact must match `evidence_ref`, own the analysis, and have the
check's `verification.evidence_path`. A number appearing somewhere else in an output, log, receipt,
seed, exit code, parameter, dependency version, or cited source is not a
binding. Omit an unbound value from the statement and record the missing
quantitative evidence under `unverified`; do not preserve an unbound number in
prose. Source-excerpt numbers match complete typed numeric tokens, never a
substring. The excerpt must contain exactly one direct metric-to-value relation
and the declared unit must be adjacent to that value; another metric elsewhere
in the excerpt cannot lend its name to the selected number. Each quantitative
claim in a direct/reconstructed lane selects an `evidence_ref` that is itself
eligible direct material rather than borrowing another statement ref. Inferred
parameter bindings are confined to
`reasonable_inference` or `unverified`. This local contract never
assigns `causal`, `mechanistic`, or
`measured_flux` as an automatic reconstruction ceiling. Preserve those as
paper-attributed or unverified claims, record any study-design basis separately,
and state the direct experiment or measurement needed to support them.

Do not convert correlation into causation, differential expression into a
mechanism, pathway enrichment or activity score into biochemical activity,
trajectory ordering into proven temporal development, or expression-derived
metabolic scores into measured flux. State the experiment or evidence that
would be needed for a stronger claim.

## Validation and delivery

Validate structure and semantic status with:

```text
python skills/dev-reconstruct-bioinfo-protocol/scripts/validate_reconstruction.py --project-dir <project_dir> --write-report
```

The path is workspace-relative and illustrative; resolve the current workspace
and Skill resource location at runtime. Do not hardcode this machine's absolute
path in delivered project code.

The validator checks contracts and evidence completeness; it cannot certify
biological correctness or prove process-to-artifact causality. It fails closed
if `jsonschema` 4.x is unavailable. A project is ready for handoff only when:

- all produced JSON and TSV artifacts parse;
- source and analysis IDs resolve;
- statuses equal the validator-derived statuses;
- every trace-table lane links back to manifest ids/locators and every
  conflict/gap remains visible;
- all eight required scientific-audit topics are answered or explicitly
  blocked, and a passed/warning audit cites directly available evidence from
  every required Methods/code/input/figure lane;
- code guidance satisfies its delivery contract when present;
- no completion claim exceeds recorded runtime evidence;
- result-check ids are unique within each execution; quantitative statements
  resolve through their typed bindings rather than a whole-file or whole-record
  number search; every execution output has explicit analysis ownership and is
  selected by a passed check for each owner;
- `REPORT.md` uses only the fixed headings and verbatim manifest-derived status,
  interpretation (including canonical quantitative-binding suffixes), and
  conflict/gap lines defined in
  `references/evidence-contract.md`; free narrative is rejected. It explicitly
  separates direct evidence/observation, paper claim, reconstructed support,
  reasonable inference, and unverifiable content, using `- none` when empty.

Finish by reporting created files, stages completed or blocked, optional Omicos
capabilities actually used, validator result, execution actually performed,
and remaining risks. Never say “reproduced” when the strongest state is
`材料完整但未执行`, `受阻`, or `材料冲突`.
