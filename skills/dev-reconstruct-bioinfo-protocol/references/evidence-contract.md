# Evidence and traceability contract

## 1. Evidence lanes

Classify by semantic role before file type. One source may occupy several
roles, but every evidence item has exactly one lane for the claim it supports.

| Lane | What it can establish |
| --- | --- |
| `paper_claim` | What Results, Discussion, or another explicitly identified paper section claims. |
| `figure` | What a visible panel, caption, legend, axis, or table directly displays. |
| `method` | What Methods, STAR Methods, protocol text, or supplement declares was done. |
| `code` | What active source code, notebook cells, workflow rules, or config implements. |
| `input` | Identity and semantics of data, metadata, references, and upstream objects. |
| `output` | Generated tables, models, logs, figures, serialized objects, and checks. |
| `runtime` | What an observed command actually executed in a recorded environment. |
| `interpretation` | A biological or methodological interpretation, never a substitute for a source lane. |

Keep Results and Methods separate even when they appear in one PDF. Keep a
caption separate from a visual observation. Keep plotting code separate from
upstream analytical code.

## 2. Source and locator rules

Assign stable source IDs (`SRC001`, `SRC002`, …) once. Record:

- semantic roles;
- original path or stable remote identifier;
- availability: `available`, `missing`, or `unreadable`;
- SHA-256 for every locally captured evidence file or deterministic repository
  snapshot; preserve Git commit, DOI/URL, and retrieval time as provenance
  metadata rather than replacing the content fingerprint;
- an extraction limitation when content is scanned, encrypted, truncated,
  corrupted, or otherwise incomplete.

Every direct evidence item needs a locator appropriate to its source:

- PDF page and, when useful, figure or bounding-region label;
- Markdown/TXT/code line range;
- DOCX heading and paragraph index;
- spreadsheet sheet and cell/range;
- notebook cell index and cell id when available;
- HTML heading/anchor;
- figure/panel id, caption segment, axis, or legend;
- runtime log line, output artifact, or check id.

`path` alone is not a sufficient locator for a long document or code file.
A remote identifier without a locally inspectable, fingerprinted capture is a
retrieval lead, not direct content evidence. Record it as missing/unverifiable
until the captured bytes are inventoried.

## 3. Evidence classes

Each evidence-linked statement is labeled with exactly one of:

- `直接证据`: the cited source directly contains or demonstrates the
  statement. A direct paper statement is direct evidence of what the authors
  wrote, not automatic proof that the statement is true. It qualifies for a
  direct-observation lane only when the cited source/artifact is locally
  inspectable and fingerprint-consistent, or when a blocked preflight record is
  structurally verifiable as operational evidence of that blocker. An expected
  but nonexistent output is not an observation. A blocked runtime is never a
  general-purpose direct reference: it may appear alone only with the packaged
  validator's canonical preflight-blocked statement and an empty quantitative
  claim list. It does not count as a reconstructed-support lane and is otherwise
  confined to `unverified` or a structured conflict/gap.
- `合理推断`: the statement follows from identified evidence plus a stated
  assumption or domain rule. Record the inference rationale and the evidence
  that would confirm it.
- `无法验证`: the required source, locator, object, parameter, or execution
  evidence is unavailable or insufficient.

Generated code guidance is labeled `generated_guidance`; it is never promoted
to source evidence. A conventional default may appear only as an optional,
clearly labeled suggestion and never as a recovered paper parameter.

## 4. Evidence authority without silent merging

There is no single authority that overwrites every lane:

- runtime evidence is authoritative for what the recorded command actually did;
- active code/config is authoritative for implemented behavior in that snapshot;
- Methods/supplements are authoritative for the declared analytical method;
- figures/captions are authoritative for the displayed artifact and legend;
- Results/Discussion are authoritative for the authors' stated claim.

When lanes disagree, show both values and their locators. Runtime success may
explain code behavior, but it may not replace the Methods value or rewrite the
paper claim. Resolve a conflict only with additional evidence; never resolve it
by averaging, choosing the more plausible value, or silently adopting the code.

For code-tool attribution, rank positive evidence as follows:

1. active panel- or analysis-generation call;
2. active config or workflow rule connected to the output;
3. active upstream analysis call connected by a concrete artifact;
4. active import with no call;
5. caption/visual resemblance;
6. commented-out or dead code.

Levels 4–6 do not prove use. Preserve them as weak or rejected evidence.

## 5. Analysis record

Use one stable `analysis_id` per computational analysis or independently
auditable panel. Split rows when panels use different methods, inputs,
statistical units, or code paths. Do not split merely to hide a conflict.

Each `analyses[]` object in `reconstruction_manifest.json` contains:

- paper-claim summary and linked evidence;
- figure/panel ids, display summary, and linked evidence;
- method summary, explicit parameters, and linked evidence;
- code locations and evidence status;
- inputs and outputs with semantics and fingerprints when available;
- execution record ids;
- scientific-audit findings;
- interpretation separated by evidence class, with every statement carrying
  explicit evidence refs and a `quantitative_claims` array (empty when the
  statement makes no quantitative expression);
- conflicts and gaps;
- declared reproduction status.

Parameter records preserve provenance rather than normalizing disagreements
away. `reported`, `implemented`, `observed_runtime`, `inferred`, and
`unreported` are distinct. An `unreported` value is JSON `null`; an inferred
value needs a rationale and remains unresolved for ready code guidance. An
implemented value cites active code evidence and records an exact
`implementation_literal` that must occur outside ordinary comments in the
fingerprinted code snapshot. The cited code source location and code-location
path must identify the same local file. An `observed_runtime` value must match a
structured name/value observation in a qualifying execution record and cite the
output/log path whose UTF-8 content exposes that exact pair; linking an
arbitrary successful run is not enough. When parameter consistency is marked
`passed` or `warning`, every reported parameter also has a registered
`implemented` or `observed_runtime` counterpart. Simple active-code assignments
and literal Python `argparse`/Click defaults that contradict a reported value
must become an explicit side-by-side conflict even if the implementer omitted
the parameter record. Static Python CLI inspection resolves bounded literal
strings, safe module-level string aliases and concatenation, explicit `dest`,
and safe direct registration aliases. Dynamic targets, f-strings, star
expansion, callable shadowing, indirect `getattr`, computed or parser-level
defaults, and other unresolved registration paths fail closed rather than
proving agreement. Runtime parameter names
match `^[A-Za-z][A-Za-z0-9_.-]*$` and are unique ignoring ASCII case; normalized
`seed` strictly equals the execution's top-level seed. These observations are
run-global, so every analysis linked to a shared execution mirrors each one with
that execution id. A cited output/log set containing a second, different value
for the same ASCII-case-insensitive name is ambiguous and cannot qualify.

IDs referenced in an analysis must exist in the project manifest. Empty arrays
are allowed only when the absence is also represented as a gap.

Every required scientific-audit topic cites the material actually checked.
`passed` and `warning` require directly available, fingerprint-consistent
evidence in these minimum lanes: preprocessing = Methods + active code + input;
statistical unit, replication/pseudoreplication, batch/confounding, and
species/gene ids = Methods + input; multiple testing and parameter consistency
= Methods + active code; claim strength = paper claim + figure/caption +
Methods. `blocked`/`not_applicable` must still cite at least one relevant
searched lane. Artifact and execution ids may serve as structured input/output
or runtime references; they do not turn inferred or missing source content into
direct evidence.

Each interpretation item has `statement`, nonempty `evidence_refs`, and a
`quantitative_claims` array.
`paper_claim` items cite paper-claim evidence; direct observations cite
inspected direct-class material, qualifying runtime, or a structurally verified
blocked preflight; reconstructed support spans at least two directly available
lanes. `合理推断` and `无法验证` evidence cannot by themselves support a direct
observation.
The local schema deliberately excludes `causal`, `mechanistic`, and
`measured_flux` ceilings because the validator cannot independently establish
those designs or measurements. Preserve such wording only as a paper-attributed
or unverified statement; `claim_basis` may document the reported design but
cannot automatically promote the reconstruction's claim ceiling.

Interpretation `statement` prose stays qualitative. Do not type exact counts,
percentages, ranges, thresholds, p values, effect sizes, scientific notation,
or quantities written in words into that free text. Put each quantity only in a
`quantitative_claims[]` item; canonical report rendering inserts the structured
value, so prose cannot disagree with its binding. Each item records `metric`, the exact JSON `value`,
an explicit `unit` (use `dimensionless` or `count` where appropriate), one
specific `evidence_ref`, and one typed `binding`:

Figure/table labels and the validator's narrow biomedical-identifier patterns
may remain qualitative identifiers: hyphenated `IL-6`/`PD-1`/`CTLA-4`/`HPV-16`
forms, `SARS-CoV-2`, optionally species-qualified `miR`/`let` names with an
optional arm, `3'`/`5' UTR`, and 5-methylcytosine/hydroxymethylcytosine forms.
This is a syntax exception, not quantitative evidence. Labels such as HR, OR,
RR, FC, FDR, AUC, SD, SE, mean, p-value, TPM, CPM, FPKM, RPKM, NES, log2FC, and
UMI do not exempt an accompanying number from the structured-claim requirement.

- `result_check`: `execution_id` plus stable run-local `check_id`. This is the
  only binding allowed for a runtime number presented as direct observation or
  reconstructed support. The referenced check must be unique, passed, name the
  current analysis, and match the claim's metric, unit, and value by strict JSON
  equality to `observed`. `evidence_ref` must be the selected execution output's
  `artifact_id`; that output must own the current analysis and its path must
  equal the check's `verification.evidence_path`. The selector, not another
  occurrence in the same file, determines the observed value.
- `source_excerpt`: `source_id`, the evidence item's exact locator, and the
  shortest exact excerpt that contains the quantity. `evidence_ref` is that
  evidence item's `evidence_id`; source id, locator, and excerpt must agree with
  its fingerprinted source and recorded summary/content. A numeric value must
  match one complete numeric token with compatible numeric type/semantics; a
  substring such as `5`, `0`, or `05` cannot borrow characters from `0.05`, and
  a numeric-looking string matches only an explicitly quoted string token. The
  excerpt must contain exactly one direct relation from the declared metric to
  the selected value, and an explicit unit must be adjacent to that value;
  `dimensionless` or `not_recorded` is valid only when no source unit is
  present. This binding is deliberately machine-checkable only against a
  fingerprinted UTF-8, line-addressable text capture and its locator must contain exactly one
  one-based `L<n>` or `L<n>-L<m>` range. A PDF page, DOCX paragraph, sheet cell,
  or remote page must first be extracted to an inventoried text capture that
  preserves the original locator; otherwise omit the quantity and record the
  source as blocked/unverified.
- `parameter`: parameter `name` plus `value_status`. The current analysis must
  contain exactly one matching structured parameter whose value strictly
  equals the claim value, and `evidence_ref` must be one of that parameter's
  evidence refs. The claim unit must equal the parameter's structured `unit`;
  use `not_recorded` when the parameter has no unit. `unreported` is not a
  quantitative binding. An `inferred` parameter binding may appear only under
  `reasonable_inference` or `unverified`, never as direct observation or
  reconstructed support.

For a quantitative item in `direct_observation` or `reconstructed_support`, the
selected `evidence_ref` must itself be eligible direct material for that
statement. Another eligible reference elsewhere in the statement cannot lend
direct status to a selected inferred, unavailable, or unverifiable reference.

Never validate a quantitative claim by collecting all numbers from an entire
source, output, log, receipt, execution record, parameter list, dependency
list, seed, or exit code. Mere same-value occurrence is not provenance. If the
binding cannot be resolved exactly, omit the quantity and record a
non-quantified `unverified` statement plus the gap; do not retain an unbound
number even under `unverified`.

## 6. Required traceability table

`traceability.tsv` has exactly eight tab-separated columns in this exact order:

| Column | Cell contract |
| --- | --- |
| `analysis_id` | Stable id matching one manifest analysis. |
| `正文主张` | Concise claim plus evidence ids/locators; say `未找到` if absent. |
| `figure/panel` | Figure/panel ids, what is shown, and evidence ids/locators; distinguish caption-only. |
| `method与参数` | Declared tool/version/test/parameters and method evidence locators; unknown values remain `未报告`. |
| `code位置` | Snapshot plus file:line/notebook-cell/workflow locator and code scope; say `未提供/未找到` when absent. |
| `输入/输出` | Named inputs and outputs, their semantics, and fingerprints or explicit missing state. |
| `复现状态` | One legal Chinese status, exactly matching the manifest and validator derivation. |
| `冲突或缺口` | Side-by-side conflicting values and locators, or precise gaps and their effect; use `无已知冲突或阻塞缺口` only after checking. |

Do not put raw multiline text into TSV cells. Use concise semicolon-separated
items and keep full evidence in the manifest.

## 7. Deterministic status derivation

Derive status for each analysis in this order:

1. `材料冲突` when any unresolved `conflict` entry exists, or when differing
   values for the same normalized reported/implemented/runtime parameter were
   not yet represented by an explicit conflict. This remains true even if one
   implementation executed successfully.
2. `受阻` when a blocking gap exists, required evidence is absent, an attempted
   execution has no complete successful record, requested execution has no
   linked record, code guidance is blocked, any consequential parameter remains
   `unreported`/`inferred`, or the environment/fingerprinted input cannot support
   the requested reproduction.
3. `已执行验证` when there is no unresolved conflict or blocking gap and at
   least one linked execution record contains all required runtime evidence:
   command, working directory, start/end time, exit code 0, dependency versions,
   integer seed bound after the entrypoint and before the first argv `--` by an
   exact case-sensitive canonical long option, or justified `not_applicable`
   with no canonical or ambiguous seed-like option in `command_argv`,
   fingerprinted inputs and outputs with matching artifact ids, semantics, and
   explicit nonempty analysis ownership, logs, mechanically recomputed passed result checks with
   unique stable ids and explicit metric/unit, naming the analysis and selecting
   every output owned by that analysis through that check's own
   `verification.evidence_path`, an authorized passed
   preflight, matching receipt/record adjudication and output declarations
   (including expected-output ownership), canonical hashes of checks
   and runtime-observed parameters, and bidirectional analysis/run links.
   Receipt, record fragment, and manifest execution record must agree on a
   nonempty `code_files` array of exact `{path, sha256}` objects that fingerprints
   the supported, statically computed local Python import closure. Every closure file maps to exactly
   one id in `code_evidence_refs`, whose `active_call`, `active_config`, or
   `active_import_only` code record has the same path and SHA-256 snapshot.
   Import-only evidence binds the bundle but cannot establish method attribution.
   Dynamic imports/dotted-name or plugin resolvers, runtime/native/archive/serialized-object
   loaders, Python import-state mutation, subprocess code dispatch, local
   compiled/bytecode modules, and unsupported language entrypoints that prevent
   a static closure block qualification.
   Referenced local files must exist and their SHA-256 values must be recomputed
   successfully. The entrypoint must resolve to the same path as linked active
   code evidence, not merely share its bytes. Each check recomputes its
   observation from a strict TSV cell, JSON Pointer, text needle, or SHA-256;
   every runtime parameter pair must be locatable in cited textual output/log
   evidence. These bindings do not certify that the chosen expected value,
   tolerance, or scientific predicate is correct.
4. `材料完整但未执行` when the required paper, figure/caption, Methods,
   active code/config, and input/output specifications are present and mutually
   consistent, but no qualifying successful execution record exists.

Project overall status uses the most conservative unresolved state:

1. any `材料冲突` → `材料冲突`;
2. otherwise any `受阻` → `受阻`;
3. otherwise all analyses `已执行验证` → `已执行验证`;
4. otherwise → `材料完整但未执行`.

Do not use status as a confidence score. A successfully executed pipeline can
still have a weak biological interpretation; record that separately.

## 8. Conflict and gap objects

Every conflict or gap records:

- `kind`: `conflict` or `gap`;
- `topic`;
- description and impact;
- evidence refs checked;
- `blocking` boolean;
- resolution status and, if resolved, new evidence supporting the resolution.

`resolved: true` requires a written resolution and at least one entry in
`resolution_evidence_refs` that was not already in the issue's original evidence
set. The issue row remains in the manifest and trace table; changing only the
boolean is invalid.

Examples of conflicts include Methods versus code parameter values, figure
caption versus plotted labels, reported sample count versus data manifest, or
output numbers versus runtime logs. Examples of gaps include missing code,
unavailable raw data, unspecified seed, ambiguous sample unit, and an
uninstallable dependency.

Never delete a resolved conflict. Mark it resolved and preserve the evidence
history.

## 9. Figure and panel rules

- Interpret each panel before rolling up to the figure.
- Separate `display` (what is shown) from `generation` (how it was made).
- Caption-only evidence can support a caption-grounded description but not an
  exact visual claim.
- Map panel-specific claims and code only when the evidence is panel-specific;
  otherwise label it figure-shared or section-shared.
- Plotting or figure-assembly code does not prove the upstream computation.
- A follow-up figure answer must retrieve the linked claim, method, and code
  records before giving reproduction guidance.

## 10. Report language

`REPORT.md` is rendered from the structured manifest, not written as free
narrative. Use these headings exactly:

```text
# Reconstruction report
## Status
## Direct evidence/observation
## Paper claim
## Reconstructed support
## Reasonable inference
## Unverified
## Conflicts or gaps
```

Under Status, render `- <analysis_id>: <derived Chinese status>`. Under each
interpretation section, render every item verbatim as
`- <analysis_id>: <statement> [evidence: <ref1>, <ref2>]` when it has no
quantitative claim. When claims are present, insert immediately before the
final evidence suffix:

`[quantitative: <metric>=<canonical JSON value> <unit> [evidence: <evidence_ref>; binding: <kind-specific binding>] | ...]`

Render a result-check binding as
`result_check:<execution_id>/<check_id>`, a source excerpt as
`source_excerpt:<source_id>@<locator>`, and a parameter as
`parameter:<name>@<value_status>`. Preserve manifest array order and use compact,
sorted-key JSON for each value. Under conflicts or gaps, render
`- <analysis_id>/<issue_id> (<kind>): <description> [evidence: <refs>]`. Write
`- none` for an empty section. The validator rejects omitted manifest lines and
every nonempty line that is neither a fixed heading nor one of these exact
manifest-derived lines; add scientific content to the structured manifest first
instead of appending report prose. Every rendered quantitative expression comes
from a structured claim with a typed binding that resolves exactly as
defined above; canonical rendering and same-value occurrence elsewhere cannot
legitimize an invented number. The rendered binding is an audit aid;
`reconstruction_manifest.json` remains authoritative.

Use explicit phrases:

- `论文正文声称…`
- `图/图注直接显示…`
- `Methods 声明…`
- `活动代码实现…`
- `本次运行观察到…`
- `合理推断（依据与假设）…`
- `目前无法验证…`

Do not use “证明了”, “机制是”, “导致”, “真实通量”, or similar stronger language
as a reconstruction-owned conclusion. Preserve it only as explicitly
paper-attributed or unverified wording, followed by the direct design or
measurement needed to assess it.
