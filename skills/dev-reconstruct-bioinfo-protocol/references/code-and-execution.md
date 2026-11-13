# Code guidance and execution contract

## 1. Code provenance labels

Label every delivered code block or file:

- `source_exact`: copied or minimally wrapped active source code from a cited
  snapshot and locator; disclose wrappers and path/config changes.
- `source_adapted`: based on cited source code but changed for available inputs,
  API versions, orchestration, or output isolation; list every material change.
- `generated_guidance`: newly written from explicit Methods plus documented
  assumptions; it is not the authors' code.
- `pseudocode_only`: structure is useful but missing parameters, data semantics,
  dependencies, or algorithms prevent safe executable guidance.

Do not label plotting-only code as a full reproduction pipeline. Commented-out,
dead, or import-only code cannot support `source_exact` method attribution.

## 2. Minimum code delivery

An executable guidance package states:

- language and runtime version;
- dependency names and compatible or observed versions;
- random seed(s) and which libraries/stages consume them;
- input files/objects, formats, required fields, units, and validation checks;
- output files/objects, schemas, checkpoints, and overwrite policy;
- every recovered parameter with evidence ref;
- every unknown parameter as a required option or explicit blocker;
- resource expectations and known platform constraints;
- one minimal run command;
- provenance label and source/adaptation notes.

Structured guidance is `ready` only when every method parameter used by the
minimal command is reported or directly implemented. Any `unreported` or
`inferred` method parameter keeps guidance `blocked`, is named under
`unresolved_parameters`, and points to a blocker issue. Never place a suggested
numeric value into an `unreported` parameter record or ready command.

Ready guidance also names an existing project-relative `entrypoint`. Its input
and output arrays exactly preserve the analysis artifact ids, paths, semantic
types, and fingerprints; changing an artifact's meaning creates a new analysis
contract, not a convenience edit. Every configurable path flag occurs in the
minimal command. `pseudocode_only` is always `blocked`.

For a Python entrypoint, recursively inventory statically reachable
project-local imports from the entrypoint directory. Every
file in that closure must have exactly one fingerprint-consistent
`active_call`, `active_config`, or `active_import_only` code record. The latter
binds the code bundle but cannot support method attribution. Statically inventory
`argparse`/Click registrations across the closure:
the minimal run includes every required option, each supplied method-parameter
value agrees with the recorded Methods/code value, and every statically
identified third-party import has a named concrete dependency version. Bounded
literal strings, safe module-level aliases/concatenation, explicit `dest`, and
safe direct registration aliases may be resolved. Dynamic targets, f-strings,
star expansion, callable shadowing, indirect registration, parser-level or
computed defaults, positional-only contracts, and unsupported non-Python CLI
inventories keep guidance `blocked`. Dynamic imports/dotted-name or plugin resolvers,
runtime/native/archive/serialized-object code loaders, Python import-state mutation, subprocess
code dispatch, and local compiled/bytecode modules also fail closed because the
local code closure cannot be proven. Non-Python entrypoints may still receive
bounded guidance, but cannot qualify an execution until a language-specific
recursive closure implementation exists.

Paths must be CLI options, config fields, or paths resolved relative to a
project root. Do not embed local drive letters, usernames, temporary folders,
credentials, concrete/private endpoints, or fixed ports. Endpoint, port, and
secret inputs are configuration placeholders or environment-variable names,
not literal command values.

Minimal Python structure:

```python
# generated_guidance — not paper source code
from argparse import ArgumentParser
from pathlib import Path

parser = ArgumentParser()
parser.add_argument("--input", type=Path, required=True)
parser.add_argument("--output-dir", type=Path, required=True)
parser.add_argument("--seed", type=int, required=True)
# Add unreported consequential parameters as required arguments.
args = parser.parse_args()

args.output_dir.mkdir(parents=True, exist_ok=False)
# Validate input semantics before analysis; write outputs only under output-dir.
```

The example is a delivery pattern, not evidence that Python or any particular
parameter was used in a paper.

## 3. Preflight before execution

Execution is allowed only after the evidence alignment and reproducibility
audit for the target analysis.

Check and record:

1. user/request authorization and exact scope;
2. source snapshot and immutable input fingerprints;
3. entrypoint and command arguments;
4. runtime, package, system tool, reference-data, model-weight, and hardware
   availability;
5. version compatibility with source code and paper date;
6. all consequential parameters and seed handling;
7. input schema, sample/design metadata, species/build/identifier namespace;
8. isolated output directory with no overwrite of source or prior run;
9. expected intermediate/output artifacts and acceptance checks;
10. network, credential, license, storage, memory, or compute requirements.

Do not silently install packages, download large/private data, accept licenses,
change the method, reduce data, or substitute a backend to make a run succeed.
Record such needs as blockers or ask for the missing authority.

Set the manifest task's execution scope explicitly:

- `none`: no runtime record is being introduced;
- `execute_now`: the user authorized this project to run, so
  `execution_requested` is `true`;
- `audit_supplied_record`: existing runtime evidence is being audited without
  authorizing a new command, so `execution_requested` remains `false`.

Each attempt also records a preflight object: authorization basis, `passed` or
`blocked` state, read-only treatment of sources, isolated project-relative
output directory, environment state, network use, and notes. A blocked
preflight cannot qualify as a successful execution. A complete, structurally
verified blocked record may be cited only as direct operational evidence that
the preflight was blocked; it supplies no output or scientific-result evidence.
Use the validator-exported canonical blocked-preflight statement, cite only that
record, and leave `quantitative_claims` empty so the runtime id cannot be reused
as generic support for a scientific assertion.

## 4. Execution record

Each attempt gets a unique `execution_id`. Preserve failed attempts; a later
success does not rewrite them. Use `attempt_status` as follows: `pending_checks`
when a process exited zero and produced its declared outputs but scientific
checks have not been adjudicated; `succeeded` only after the process, outputs,
and every linked scientific check pass; `failed` when a process ran but exited
nonzero, missed an output, or failed a check; and `blocked` when preflight
prevented execution. A later successful attempt may list earlier non-successful
ids in `supersedes_execution_ids`, but both records remain intact and must cover
the same analyses in chronological, acyclic order.

For a new local attempt, invoke the packaged wrapper rather than assembling a
runtime record by hand:

```text
python <skill-root>/scripts/run_reconstruction.py \
  --project-dir <project-dir> --execution-id <run-id> \
  --analysis-id <analysis-id> --entrypoint <relative-entrypoint> \
  --code-evidence-ref <evidence-id> \
  --input-spec <artifact-json> --output-spec <artifact-json> \
  --dependency <name=version> --seed <integer> -- <command argv...>
```

Each artifact JSON has `artifact_id`, `path`, and `semantic_type`. The wrapper
creates exactly `runs/<execution_id>` and refuses to reuse it. It fingerprints
declared inputs and the validator-computed local Python import closure before launch,
requires dependency names to be unique after case-insensitive PEP 503-style
normalization, and probes the exact child Python launcher in a non-project
temporary directory. The inventory must include Python itself; every declared
interpreter/distribution version must be observable and match exactly. A version
mismatch, missing distribution, duplicate normalized name, or ambiguous name
blocks before a run directory is created. The wrapper then invokes argv without
a shell, captures stdout and stderr, fingerprints declared
outputs, and writes `execution_receipt.json` plus
`execution_record.fragment.json`. Receipt and fragment mirror command, code
bundle, I/O, seed, environment, process outcome, and later adjudication fields;
the receipt also carries wrapper provenance and expected-output declarations,
while the fragment is the manifest-shaped execution record. The wrapper accepts
only an explicit new-run authorization basis; never invoke it while merely
auditing supplied evidence.
For Python, direct-script launch semantics are part of the contract: `-P` and
`-I` are rejected, and import-affecting `PYTHON*` variables (including path,
home, safe-path, user-base, case, breakpoint, warning, startup, and inspect
controls) are removed from the child environment and noted in preflight.
It emits `pending_checks` after a clean process exit. Do not edit that state by
hand. Logical input/output artifacts must resolve to distinct physical paths.
The receipt's `expected_outputs` must exactly mirror each recorded output's id,
path, semantic type, and owner set before hashes are added.

Write result checks as a JSON array, then adjudicate them with:

```text
python <skill-root>/scripts/finalize_execution.py \
  --project-dir <project-dir> --execution-id <run-id> \
  --checks-json <checks.json> \
  [--observed-parameters-json <observed-parameters.json>] \
  [--supersedes-execution-id <prior-run-id>]
```

Each check contains exactly a stable run-local `check_id`, `metric`, `unit`,
`check`, `observed`, boolean `passed`, covered `analysis_ids`, `evidence_paths`,
and `verification`. Check ids are unique inside an execution and remain stable
in the receipt, record, report bindings, and any superseding audit. Use an
explicit unit such as `count`, `%`, or `dimensionless`; for nonquantitative
text/hash checks use `not_applicable`. The verification contains exactly `kind`,
`evidence_path`, `selector`, and `expected`; its evidence path must be one of
that check's recorded output/log paths. The adjudicator ignores
self-asserted truth and mechanically recomputes `observed` and `passed`:

- `tsv_cell_equals`: selector has nonempty `key_column`, `key_value`, and
  `value_column`; the unique matching TSV cell is compared as a string;
- `json_pointer_equals`: selector is a strict RFC6901 JSON Pointer; the selected
  strict-JSON value is compared with exact JSON types, including objects/lists;
- `text_contains`: selector is `null`; expected is a nonempty needle and the
  recomputed observed value is boolean;
- `sha256_equals`: selector is `null`; expected is a SHA-256 and the recomputed
  observed value is the file digest.

For example, a TSV check uses this minimal shape:

```json
{
  "check_id": "CHK_TARGET_METRIC",
  "metric": "target_metric",
  "unit": "dimensionless",
  "check": "declared metric equals the expected value",
  "observed": "3.0",
  "passed": true,
  "analysis_ids": ["A001"],
  "evidence_paths": ["runs/RUN001/result.tsv"],
  "verification": {
    "kind": "tsv_cell_equals",
    "evidence_path": "runs/RUN001/result.tsv",
    "selector": {
      "key_column": "metric",
      "key_value": "target_metric",
      "value_column": "value"
    },
    "expected": "3.0"
  }
}
```

Every execution output also contains a nonempty `analysis_ids` ownership set.
Every owner needs a passing linked check whose own
`verification.evidence_path` is that output and whose `analysis_ids` names that
owner; merely listing the output beside a log-based check does not cover it.
For a shared output, list all analyses whose declared output contract it
satisfies, and cover every owner (one multi-analysis check or separate checks
may do so). Do not assign an output to an unrelated analysis merely to satisfy
coverage. Inputs do not carry per-analysis ownership. These controls prevent
an unbound assertion,
but do not decide whether the expected value, tolerance, or scientific predicate
is appropriate. The adjudicator mirrors checks and their canonical SHA-256 into
receipt and fragment; only a process-success record with nonempty all-passed
checks covering every linked analysis becomes `succeeded`.
Adjudication holds an exclusive `runs/<execution_id>` lock across read/check/
write and is one-shot. A pre-existing lock is not silently reclaimed. If a
check was wrong or new evidence arrives, preserve
the finalized attempt and use a new `execution_id`; never rewrite a failed or
successful record in place.
Before finalization writes either file, it requires receipt/fragment parity,
recomputes the current supported local import closure and every `code_files` SHA-256, and
rejects code drift or an unprovable dynamic closure. It also repeats dependency
observation through the recorded child launcher, so an edited or no-longer-matching
dependency inventory cannot be adjudicated as successful.

A runtime quantitative statement in `direct_observation` or
`reconstructed_support` binds to one of these checks by
`{kind: result_check, execution_id, check_id}`. Its metric and unit match the
check exactly, its value is strictly JSON-equal to the recomputed `observed`,
and the metric also equals the TSV selector's `key_value` or the strict JSON
Pointer selector, respectively,
and its `evidence_ref` is the selected output's artifact id. That artifact's
path must equal the check's own `verification.evidence_path` and its ownership
must include the current analysis. Do not search all numbers in that file or in
the execution receipt. Seed, exit code,
parameter values, dependency versions, unrelated cells/keys, and other checks
cannot satisfy the binding merely because they contain the same number.

A qualifying successful record contains:

- linked `analysis_ids`;
- exact display command and `command_argv`, project-relative entrypoint and
  working directory;
- `code_evidence_refs` plus a nonempty `code_files` array of exact
  `{path, sha256}` objects that fingerprints the supported, statically computed local Python import
  closure; every member maps to exactly one referenced active code record whose
  path and snapshot match, and the entrypoint
  resolves to its exact cited path rather than merely sharing bytes;
- UTC start and end timestamps;
- exit code `0`;
- runtime and dependency versions observed through the recorded child Python
  launcher, with one unique normalized identity per dependency;
- an integer seed bound after the declared entrypoint and before the first argv
  `--` by an exact, case-sensitive canonical long option: `--seed`,
  `--random-seed`, `--random_seed`, `--random-state`, `--random_state`,
  `--rng-seed`, or `--rng_seed`. Both `--option value` and `--option=value` are
  accepted. A bare equal-valued token, option prefix/abbreviation, case variant,
  short/single-dash alias, or token after the terminator is not a binding;
  ambiguous seed-like options invalidate qualification. `not_applicable`
  requires a reason and no canonical or ambiguous seed-like option;
- input and output artifact ids, paths, semantic types, and SHA-256
  fingerprints, exactly matching the linked analysis contract;
- stdout and stderr log paths, even when one is empty;
- one or more mechanically recomputed result checks with observed values,
  `passed: true`, unique stable `check_id`, explicit `metric` and `unit`, linked
  `analysis_ids`, recorded evidence paths, and one structured verification
  selector per check;
- canonical hashes binding the exact checks and runtime-observed parameter
  arrays, plus matching final adjudication status and timestamp;
- source snapshot and code provenance label;
- receipt path `runs/<execution_id>/execution_receipt.json`, its SHA-256,
  wrapper producer/version, nonce, process id, exact argv, timestamps, process
  outcome, `code_files`, input/output fingerprints, and log fingerprints. The
  adjudicated fragment mirrors the receipt-bound execution fields and is copied
  into the manifest without manual reconstruction.

For validator-qualified evidence, working directory, inputs, outputs, logs,
check evidence, and preflight output directory must exist on disk. Runtime
paths are project-relative, output files stay under the declared output
directory, and that dedicated directory is exactly `runs/<execution_id>`.
Inputs stay
outside it; input, output, stdout and stderr paths are role-disjoint; outputs
and logs from `execute_now` fall inside the recorded time window. Recorded
input/output SHA-256 values must match bytes reopened by the validator, and
execution I/O must cover the analysis I/O specification. Analysis-to-execution
links must agree in both directions. For a multi-analysis record, its I/O is the
exact compatible union of the linked analysis contracts: no orphan artifact is
allowed, and no two logical artifacts may collapse onto one resolved physical
path. Each output's ownership is the nonempty subset of run analyses whose
contracts contain that artifact. A shared output lists all such owners; an
analysis-specific output lists only its owner. Every owner/output pair must be
covered by a passed check naming that analysis and selecting that output.

For every Methods-reported parameter whose consistency audit is `passed` or
`warning`, register an `implemented` or `observed_runtime` counterpart. Do not
rely on omission from the manifest: the validator also scans conservative,
simple active-code assignments and literal Python `argparse`/Click option
defaults for undeclared reported-versus-code conflicts. The scan can resolve
bounded static string aliases/concatenation, explicit destinations, and safe
direct callable aliases; dynamic targets, shadowed aliases, computed defaults,
and unresolved parser-level behavior fail closed. This remains a conservative
static check, not complete program analysis.
Each runtime-observed parameter contains exactly `name`, `value`, and
`evidence_paths`; its name matches `^[A-Za-z][A-Za-z0-9_.-]*$`, names are unique
ignoring ASCII case, and the pair must appear as an assignment or JSON pair in a
cited recorded output/log. All cited text is considered together: if the same
case-insensitive name also appears with a different value, the observation is
ambiguous and the run cannot qualify. A normalized `seed` value must strictly equal the
receipt/fragment top-level seed. Observed parameters are run-global: every
analysis linked to a shared execution mirrors every one as `observed_runtime`
with that execution id. A runtime value differing from Methods or active-code
records is preserved as `材料冲突`, even when the process and checks succeeded.

The receipt is a consistency and provenance control, not a signed attestation.
The validator recomputes its hash and cross-checks its content, but a person
with write access to the whole project can still fabricate files and metadata.
Therefore preserve OS/job-scheduler logs or independently signed provenance
when adversarial tamper resistance matters; never describe static validation
alone as proof that a process caused an artifact.

An exit code alone is insufficient. Import success, notebook creation, or file
existence alone is not scientific verification. Checks should address the
target claim at the appropriate tolerance, for example exact metadata/config,
structural figure agreement, deterministic table equality, or documented
tolerance for stochastic metrics.

## 5. Failure and environment blocking

When preflight or execution fails:

- capture the exact failing command/check, exit code, error class, relevant log
  locator, environment/version state, and partial outputs;
- mark partial outputs as nonfinal and do not cite them as successful results;
- identify whether the blocker is missing code/data/parameter, dependency,
  incompatibility, hardware/resource, permission, or implementation failure;
- provide the smallest concrete resolution path without claiming it was tried;
- set `受阻` unless an unresolved source conflict requires `材料冲突`.

Do not call a failed or interrupted run “partially reproduced.” The legal
project status is `受阻`; details belong in the gap and execution attempt.

## 6. Fallbacks and adaptations

A fallback is a new attempt with its own id, command, environment, and outputs.
Link it to the failed attempt and state whether it answers the same scientific
question. A near-equivalent library, test, dataset, or visualization is an
adaptation, not faithful execution, unless equivalence is established.

Never use a current package default for an unreported historical parameter and
present it as recovered. When a demonstration default is useful, label it
`合理推断`, explain sensitivity, and keep faithful reproduction blocked if the
parameter is consequential.

## 7. No-run language

When guidance was not executed, say all of the following where relevant:

- “代码指导已生成，但未在本项目中执行。”
- “以下参数来自 Methods/代码：…”
- “以下参数未报告，必须由用户提供或通过敏感性分析确定：…”
- “预期检查点是建议的验收标准，不是已观察结果。”

Never use “运行成功”, “结果一致”, “验证通过”, or “完成复现” without a
qualifying execution record.
