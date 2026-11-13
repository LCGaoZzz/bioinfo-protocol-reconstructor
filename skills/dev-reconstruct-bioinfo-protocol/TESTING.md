# Development verification

These tests validate the local Skill contract. They are synthetic contract
tests, not evidence that any scientific paper has been reproduced.

## Static and scenario tests

From the workspace root:

```powershell
py -3 -B -m unittest discover `
  -s skills/dev-reconstruct-bioinfo-protocol/tests `
  -p "test_*.py" -v
```

The suite covers:

- complete, mutually consistent materials without execution →
  `材料完整但未执行`;
- missing source code → `受阻`;
- Methods/code parameter conflict backed by an actual differing literal in the
  fingerprinted fixture code → `材料冲突`;
- unavailable execution environment → `受阻`;
- rejection of `已执行验证` without runtime evidence;
- acceptance of `已执行验证` only after the fixture really launches a local
  standard-library command through the packaged fresh-directory wrapper and the
  wrapper first emits `pending_checks`, the packaged adjudicator binds
  structured TSV/JSON/text/hash checks to recorded outputs/logs, mechanically
  recomputes `observed`/`passed`, and the validator reopens inputs, outputs, logs, and
  receipt, recomputes SHA-256, verifies execution authorization/preflight, and
  follows analysis-linked evidence-backed passed checks;
- rejection of nonexistent runtime artifacts, hash mismatches, one-way
  analysis/execution links, shared input/output/log paths, missing code
  snapshot links and unsupported completion language;
- preservation of a failed attempt followed by a qualifying successful run;
- preservation of an exit-zero attempt whose scientific check failed, followed
  by a superseding qualifying success;
- resolved conflicts requiring additional resolution evidence;
- all eight scientific-audit topics and the executable code-guidance contract;
- rejection of fabricated unreported parameters, machine paths, concrete
  endpoints/ports, secret arguments, pseudocode marked ready, I/O semantic
  drift, wrong evidence lanes, missing input fingerprints, receipt tampering,
  echo masquerading as entrypoint execution, and causal/mechanistic
  overclaiming;
- rejection of unsafe execution ids, launcher-option entrypoint bypass,
  unadjudicated success, tampered check hashes, unavailable evidence marked
  passed, undeclared same-parameter conflicts, unbound runtime parameter values,
  code/source path substitution, orphan execution artifacts, report-level
  causal overclaim, and blocked states without stage-linked blockers;
- rejection of same-byte execution through an unlinked code path, unregistered
  active-code assignment conflicts, runtime parameter/check values absent from
  cited logs, mixed paper-attribution/reconstruction causal language, self-
  declared high claim ceilings, untraceable interpretation statements, and
  downstream stages started after a partial upstream gate;
- one finalized execution shared by two analyses with an exact compatible I/O
  union, checks covering both analyses, and run-global parameters mirrored into
  both analyses;
- strict finalizer/validator parity for JSON objects/lists, duplicate JSON keys,
  RFC6901 escapes and array indices; rejection when a log check merely lists but
  does not select the declared output;
- stable, unique result-check ids plus explicit metric/unit; rejection when a
  quantitative runtime statement points to another check, mismatches the
  check's strict observed value/metric/unit/selected evidence path, or collides
  only with a seed, exit code, parameter, dependency, receipt, or unrelated
  number in the same file;
- required per-statement `quantitative_claims` arrays, including exact
  source-excerpt and structured-parameter bindings for non-runtime quantities;
  source numeric-token boundaries reject `5`, `0`, `0.0`, `05`, and numeric
  strings as substitutes for source value `0.05`, while inferred parameter
  bindings remain confined to inference/unverified lanes;
- source excerpts require exactly one direct metric-to-selected-value relation
  and a value-adjacent unit; a selected quantitative `evidence_ref` cannot
  borrow direct status from another statement ref. Narrow figure/biomedical
  identifiers remain qualitative, while accompanying HR/AUC/TPM/log2FC-style
  quantities still require structured bindings;
- rejection of unregistered digits, scientific notation, ranges, percentages,
  and quantities written in words in free interpretation prose, with exact
  values rendered only from typed bindings;
- nonempty analysis ownership for every execution output and per-owner check
  coverage, including a shared output where one analysis has only a log check;
- rejection of duplicate logical artifacts resolving to one physical path,
  receipt expected-output/owner drift, and boolean process ids;
- exact seed binding only through a case-sensitive canonical long option after
  the entrypoint and before argv `--`; rejection of bare equal-valued tokens,
  prefixes/abbreviations, case variants, short aliases, terminator-hidden
  options, mismatched values, and `seed=not_applicable` with any canonical or
  ambiguous seed-like option;
- rejection of an executed active default drifting from Methods, and rejection
  of free report prose (including a fabricated numerical result) not present in
  structured manifest statements;
- rejection of a literal `argparse` default drifting before execution, an
  unstructured interpretation quantity, ambiguous
  same-name runtime values, receipt/record JSON type drift, and failed/blocked
  adjudication-status contradictions;
- static CLI inventory resolves safe aliases, literal concatenation, and
  explicit `dest`, but fails closed on dynamic targets, shadowing, wrappers, or
  implicit defaults. Ready guidance must include required options, preserve
  recorded method/code values, reject cross-option value swallowing, and name
  concrete versions for statically imported third-party dependencies. Dependency
  identities are normalized and unique, common import/distribution aliases such
  as `umap`/`umap-learn` and `skimage`/`scikit-image` are covered, and the runner
  plus finalizer reject a Python/distribution version that differs from the exact
  child runtime;
- the supported static local Python import closure is persisted as receipt/fragment
  `code_files`; every closure file needs exactly one loadable fingerprinted code
  record, and imported-helper drift is rejected. Relative/absolute import roots,
  root decoys, helper dependency inventory, and code drift are covered. Dynamic
  imports/dotted-name or plugin resolvers, runtime/native/archive/serialized-object loaders, Python
  import-state mutation, subprocess dispatch, local compiled/bytecode modules,
  import-changing flags/environment, and unsupported non-Python execution fail closed;
- acceptance of punctuation-distinct ASCII parameter names while still
  enforcing case-insensitive uniqueness;
- direct observations require materialized direct-class evidence; nonexistent
  output specifications and `无法验证` evidence do not qualify, while a fully
  checked blocked preflight may directly evidence only its operational blocker;
- exact traceability-table header and manifest-linked lane content.

The validator intentionally fails closed if Python `jsonschema` 4.x is not
available. Do not install it silently; use an already authorized environment or
record validation as blocked.

These checks prove contract and text-evidence binding only. They do not
automatically decide whether a scientific predicate, tolerance, or biological
interpretation is correct, and the local receipts are not signed attestations.

Validate a real reconstruction project with:

```powershell
py -3 skills/dev-reconstruct-bioinfo-protocol/scripts/validate_reconstruction.py `
  --project-dir <project-dir> --write-report
```

## Omicos discovery smoke

Start the local core using the workspace development procedure, then check:

```powershell
$agents = Invoke-RestMethod http://127.0.0.1:5055/api/agents
$skills = Invoke-RestMethod http://127.0.0.1:5055/api/skills

$agents.agents | Where-Object id -eq 'dev_reconstruct_bioinfo_protocol'
$skills.skills | Where-Object id -eq 'dev-reconstruct-bioinfo-protocol'

Invoke-RestMethod `
  http://127.0.0.1:5055/api/agents/dev_reconstruct_bioinfo_protocol/tools
```

The resolved tools must include the model-facing `skill` and `skill_resource`
operations. Load the Skill body through the runtime `skill` provider and read
one referenced file through `skill_resource`; filesystem parsing alone does not
prove model-facing loading.

### Workspace-gate compatibility check

First test the documented workspace-extension start path. Some current core
checkouts gate visible `agents/` and `skills/` overlays only by account plan and
do not implement `OMICOS_ENABLE_WORKSPACE_EXTENSIONS`; on a non-lab account the
documented flag can therefore leave both drafts undiscoverable. Treat that as a
core/runtime blocker, not as permission to copy drafts into cloud/admin caches.

To test this Skill's parsing and tool plumbing without changing core or account
state, a strictly local, test-only process may use these explicit overrides:

```powershell
$env:OMICOS_TEMPLATES_DIR = '<workspace-root>'
$env:OMICOS_SKILL_ROOTS = 'skills'
```

On Windows keep `OMICOS_SKILL_ROOTS` workspace-relative; the current root-list
parser can split a drive-letter colon. Run the process with the workspace root
as its working directory and an isolated temporary `--data-dir`. Passing this
override smoke proves discovery/loading of the artifacts, but does not prove
that the documented account/flag gate works; report both results separately.

For an offline deterministic end-to-end smoke, run
`tests/fake_openai_skill_probe.py` on a loopback port, configure the local core's
`custom_openai` provider to that `/v1` endpoint, and send one read-only chat turn
with this Agent. The capture must show three requests: the first observes the
selected Agent body and its declared tools, the second observes the loaded Skill
body, the third observes `references/evidence-contract.md`, and the final SSE
contains `MODEL_LOAD_PROBE_OK`. The fixture forces tool calls; it
tests wiring and resource loading, not model judgment or scientific behavior.

The packaged isolated runner performs that whole check, including refresh and
PID-scoped cleanup, without reading or changing the normal Omicos data dir:

```powershell
py -3 -B skills/dev-reconstruct-bioinfo-protocol/tests/run_local_discovery_smoke.py `
  --workspace . --core omicos-core/target/debug/omicos.exe
```

Probe the documented flag without test-only overrides separately:

```powershell
py -3 -B skills/dev-reconstruct-bioinfo-protocol/tests/run_local_discovery_smoke.py `
  --workspace . --core omicos-core/target/debug/omicos.exe --mode workspace-gate
```

This mode performs discovery, refresh, and repeat discovery. It exits nonzero
unless both drafts are present before and after refresh; it does not reinterpret
an undiscoverable draft as a passing result.

After discovery, call both refresh endpoints and repeat the GET checks:

```powershell
Invoke-RestMethod -Method Post http://127.0.0.1:5055/api/agents/refresh
Invoke-RestMethod -Method Post http://127.0.0.1:5055/api/skills/refresh
```

An offline refresh may report `skipped: true`. The acceptance criterion is
that both local entries remain discoverable afterward.
