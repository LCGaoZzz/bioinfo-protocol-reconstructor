# Dependency-gated workflow

## Project initialization and resume

Create a new project directory unless the user explicitly selected an existing
reconstruction project. Never write into the source bundle.

For a new project:

1. normalize the request into task mode, target claims/figures, desired output,
   and execution scope (`none`, authorized `execute_now`, or read-only
   `audit_supplied_record`);
2. initialize `working_state.json` with all six stages `not_started`;
3. record the source roots/files without reading every file deeply;
4. compute an inventory fingerprint from normalized source identifiers and
   file hashes.

For a resumed project, parse the existing state and artifacts first. Reuse a
completed stage only when:

- its required artifacts exist and parse;
- recorded source fingerprints still match;
- no upstream stage was invalidated;
- the user's target has not changed in a way that changes the stage output.

When an input changes, invalidate the earliest affected stage and all dependent
downstream stages. Preserve old artifacts under a prior run/revision; do not
silently overwrite their provenance.

Allowed stage states are `not_started`, `in_progress`, `completed`, `partial`,
and `blocked`. Update `working_state.json` after each material decision.

## Stage 1 — evidence inventory

Purpose: discover and classify evidence without prematurely interpreting it.

Required input: at least one user-provided source path, file, identifier, or an
explicit code-only/method-only triage request.

Actions:

- inventory files recursively while excluding generated caches and dependency
  trees unless explicitly relevant;
- assign source roles: main/results text, Methods, supplement, figure visual,
  caption, table/metadata, raw-data manifest, code, config/environment, output,
  or unknown;
- record format, size, fingerprint, locator strategy, availability, extraction
  limitations, and user-pinned role overrides;
- snapshot code by Git commit when possible, otherwise by archive hash or a
  deterministic file-list hash;
- record missing evidence lanes explicitly.

Outputs: `source_inventory.json`, input fingerprint, extraction plan inside
`working_state.json`.

Gate: main/results material is required for faithful paper-claim reconstruction.
Code-only or Methods-only triage may continue only when the reduced scope is
explicitly recorded. A missing figure visual may continue in caption-only mode.

## Stage 2 — cross-material alignment

Purpose: create stable analysis rows and connect source lanes without deciding
that the analysis is reproducible yet.

Required input: valid Stage 1 inventory.

Actions:

1. Build compact section/source maps; retrieve raw leaves only for the current
   target.
2. Extract Results/Discussion claims separately from Methods details.
3. Inventory figures and panels, distinguishing visible evidence, caption-only,
   code-only, and absent evidence.
4. Index code beyond README: entrypoints, active calls, configs, environments,
   notebooks, workflow rules, outputs, commented-out/dead code, and line/cell
   locators.
5. Assign stable `analysis_id` values and connect claim ↔ panel ↔ method ↔ code
   ↔ input/output using evidence refs.
6. Initialize one row per analysis in `traceability.tsv`; missing lanes stay
   visible.

For large Methods or code bundles, shard by section/file and retain only compact
maps plus the active evidence leaves. Do not reread completed shards unless an
alignment conflict points back to them.

Outputs: draft `reconstruction_manifest.json` and `traceability.tsv`.

Gate: every target must have an analysis row. If a required lane is missing,
mark a gap and stop that target before reproducibility claims.

## Stage 3 — reproducibility audit

Purpose: decide whether the declared and implemented analysis is coherent and
what is needed to reproduce it.

Required input: Stage 2 analysis records with source locators.

Actions per `analysis_id`:

- compare Methods, supplements, active code/config, figures, inputs, and prior
  outputs parameter by parameter;
- audit preprocessing semantics, independent statistical unit, replication and
  pseudoreplication, batch/confounding, repeated measures, test assumptions,
  multiple testing, species/build/feature ids, and conclusion strength;
- for every passed/warning finding, cite the required directly available
  Methods/code/input/figure lanes; a searched but missing/unverifiable lane can
  justify `blocked`, not `passed`;
- distinguish upstream analytical code, panel-generation code, plot-only code,
  and figure assembly;
- identify missing data, metadata, reference resources, weights, manual steps,
  environment locks, and expected intermediate artifacts;
- create conflict/gap objects and derive a provisional status using the evidence
  contract.

Read only relevant sections of `references/modality-audit.md`. An installed
specialized Omicos Skill can supply method-specific checks, but its output must
still be translated into this project's evidence and status contract.

Outputs: completed audit blocks, conflicts/gaps, execution feasibility, and
updated table rows.

Gate: an unresolved conflict prevents a faithful status other than
`材料冲突`. A blocking gap prevents execution from being presented as faithful
reproduction.

## Stage 4 — execution or code guidance

Purpose: either run the smallest justified reproduction/validation or provide
safe, executable guidance without claiming it ran.

Required input: completed Stage 3 audit and an execution decision. If Stage 3
is partial or blocked, record the blocker and go only to Stage 6 closeout; do
not begin execution/guidance as though the audit were complete.

Read `references/code-and-execution.md`.

Execution route:

- confirm execution is authorized and inputs are immutable;
- preflight dependencies, versions, resources, data access, required parameters,
  output isolation, and seeds;
- run the smallest command that tests the target claim or analysis dependency
  through `scripts/run_reconstruction.py`, which creates a fresh
  `runs/<execution_id>` directory and a `pending_checks` process receipt;
- capture commands, logs, environment, input/output fingerprints, exit code,
  artifact ids and semantics, evidence-backed result checks linked to analysis
  ids, receipt hash, preflight state, and `code_files` in the wrapper receipt
  and record fragment. `code_files` is the validator-computed supported local
  Python import closure, with one pre-run SHA-256 per file;
- write checks (and structured runtime-observed parameters when applicable) to
  JSON, then run `scripts/finalize_execution.py`; only its all-passed,
  all-analysis-covered adjudication may change `pending_checks` to `succeeded`;
- copy the adjudicated record fragment into the manifest rather than rebuilding
  its mirrored receipt, code, I/O, seed, check, or hash fields by hand;
- assign each check a stable run-local `check_id`, `metric`, and `unit`, then
  mechanically recompute it from its declared TSV/JSON/text/hash selector;
- give every output a nonempty `analysis_ids` ownership set. For shared output,
  list every analysis whose result contract owns it; require the output to be
  selected evidence of a passed check naming each owner. Inputs do not require
  and must not carry per-analysis ownership;
- bind each runtime parameter name/value to a cited UTF-8 output/log;
  preserve the limitation that this verifies evidence binding rather than the
  scientific choice of predicate or tolerance;
- reopen every local runtime artifact, recompute its SHA-256, and maintain
  bidirectional links between the execution record and each analysis;
- require every `code_files` member to map to exactly one id in
  `code_evidence_refs`, whose `active_call`, `active_config`, or
  `active_import_only` record has the same path and SHA-256. Do not use
  import-only evidence for method attribution.
  Dynamic imports/dotted-name or plugin resolvers, runtime/native/archive or serialized-object loaders, Python
  import-state mutation, subprocess code dispatch, local compiled/bytecode
  modules, and non-Python entrypoints without a language-specific closure block
  execution qualification. Reject Python `-P`/`-I`; normalize and record
  import-affecting `PYTHON*` child variables;
- never change methods silently after failure. Record any fallback as a new
  attempt linked to the failed one.

Guidance route:

- provide dependency/version requirements, configurable inputs/outputs, seed,
  parameter provenance, minimal run command, and checkpoints;
- label code as source-exact, adapted, or newly generated guidance;
- represent missing paper parameters as required configuration fields or
  blockers, not guessed values;
- state that the guidance was not executed.
- store a structured `code_guidance` record: use `ready` only when dependency
  versions, seed handling, existing entrypoint, exact analysis I/O contract,
  configurable paths, and minimal run are all known. For Python, every local
  import-closure file must have exactly one active fingerprinted evidence
  record; the static CLI inventory must succeed; every required option must be
  present; supplied method-parameter values must match recorded evidence; and
  every third-party import must have a named concrete dependency version.
  Dynamic/unsupported inventories remain `blocked` with unresolved parameters
  and unresolved blocking issue ids.

Outputs: optional `code/` and `runs/` artifacts, execution records, updated
status and table rows.

Gate: only a complete successful execution record can support
`已执行验证`. A failed import, preflight, command, or check is `受阻` unless an
unresolved source conflict already requires `材料冲突`.

## Stage 5 — biological interpretation

Purpose: explain results at the strongest level supported by design and
evidence.

Required input: completed Stages 2–4. If Stage 4 is partial or blocked, record
partial interpretation needs and go to Stage 6 closeout instead of marking
Stage 5 started or completed.

For each analysis, write separately:

- direct figure/output observation;
- paper claim;
- declared method and implemented behavior;
- runtime observation, if any;
- reasonable biological interpretation with assumptions;
- unverifiable content and the evidence needed to verify it.

Store every item as `{statement, evidence_refs, quantitative_claims}`; keep
`quantitative_claims` present and empty when the statement has no quantity.
Reconstructed support must cite at least two evidence lanes. Represent every
quantitative expression with metric, exact value, unit, one evidence ref, and a
typed result-check, source-excerpt, or parameter binding. Runtime quantities in
direct observation or reconstructed support bind only to the exact passed
check's execution id, stable check id, metric, unit, observed value, evidence
output artifact id, owner set, path, and selector. Never accept a same-valued number found elsewhere in a
whole source, output, log, receipt, seed, exit code, parameter, or dependency
record. If an exact binding is unavailable, omit the quantity from supported
language and record it as unverified. This local contract never assigns
`causal`, `mechanistic`, or `measured_flux` as a reconstruction ceiling. Preserve
those only as paper-attributed or unverified claims and document the direct
design/measurement that would be needed.

Apply the claim ceilings in `references/modality-audit.md`. Revisit raw evidence
only for a disputed parameter or claim; otherwise synthesize from the manifest.

Output: interpretation blocks and `REPORT.md` derived from structured records.

Gate: interpretation cannot upgrade reproduction status or evidence class.

## Stage 6 — validation and handoff

Purpose: verify contract integrity and close out complete or partial work.

Required input: all artifacts produced by reached stages. A blocked Stage 1–5
is allowed, but its blocker must be represented in the manifest and table.

Actions:

- validate JSON structure, exact TSV header, and manifest-linked lane tokens;
- validate unique/resolving ids and source refs;
- independently derive analysis and overall statuses;
- reject `已执行验证` without authorized preflight, existing local artifacts,
  recomputed matching hashes, a wrapper receipt, logs, analysis-linked
  machine-recomputed checks with unique stable ids and metric/unit that select
  every declared output for each output owner, matching
  adjudication/check hashes, exact compatible multi-analysis artifact union,
  and bidirectional run links;
- require the executed entrypoint to be the same resolved path as linked active
  code evidence, recompute checks from strict TSV/JSON/text/hash selectors, and
  bind runtime parameters to cited text;
- verify every analysis row is represented once in the table;
- check that conflicts, blocking gaps, rejected code evidence, and unverified
  statements remain visible;
- resolve every quantitative statement through its typed binding and reject
  whole-file or whole-record number-pool matches;
- require every derived `受阻` state to appear in a partial/blocked stage with a
  blocker id tied to an unresolved blocking issue;
- require all eight scientific-audit topics and check structured guidance
  against the code-guidance contract;
- report scientific checks not mechanically decidable as warnings or blockers,
  never as automatically passed.

Run the packaged validator when locally executable and save
`validation_report.json`. If it cannot run, record the environment error; manual
inspection alone must not be described as validator success.

Handoff summary:

- project files created;
- stages completed, partial, or blocked;
- optional Skills/resources actually loaded;
- analysis and overall statuses;
- commands actually executed and their results, or “not executed”;
- conflicts, gaps, and unresolved risks.

## Minimal dependency graph

```text
inventory -> alignment -> audit -> execution/guidance -> interpretation -> validation/handoff
blocked Stage 1-5 -----------------------------------------------------> validation/handoff
```

Validation may close a partial project, but no downstream scientific stage may
bypass a missing upstream gate.
