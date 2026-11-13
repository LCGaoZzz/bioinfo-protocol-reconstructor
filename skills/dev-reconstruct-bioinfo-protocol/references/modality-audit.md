# Modality-aware scientific audit

Read the universal section plus only the sections matching the active analyses.
The checklist controls questions and claim ceilings; it does not supply missing
paper parameters.

## Universal checks

### Measurement and preprocessing

- What was physically measured, at what resolution, and in which units?
- Which object is raw, normalized, transformed, scaled, residualized,
  integrated, imputed, batch-corrected, or model-derived?
- Are filtering, normalization, feature selection, transformation, and missing
  data handling applied in the same order in Methods and code?
- Was information from the test/comparison set used during feature selection,
  normalization, tuning, imputation, or model fitting?
- Are thresholds data-dependent, manually selected, or pre-specified?

Never infer matrix semantics from a filename, layer name, or object slot alone.

### Statistical unit, replication, and dependence

- Name the observation unit, experimental unit, sampling unit, and statistical
  unit separately.
- Count independent biological replicates per group. Cells, spots, reads,
  spectra, peaks, technical wells, image tiles, and repeated measurements are
  not automatically biological replicates.
- Identify pairing, repeated measures, nesting, longitudinal structure,
  multiplexing, and technical replicates.
- Check whether aggregation, mixed models, clustered standard errors, blocking,
  or another dependence-aware method is needed.
- Flag cell-/spot-/read-level tests used to make subject-level claims without a
  defensible dependence model as pseudoreplication.

### Batch, confounding, and design

- Build the sample × condition × batch × subject coverage table.
- Check whether condition is completely or nearly confounded with batch,
  library, center, platform, sex, age, tissue region, time, or processing date.
- Distinguish correction for visualization from covariate control in inference.
- Confirm the same sample identity and contrast direction are used across
  metadata, code, tables, and captions.

Complete confounding is a stop for the affected causal/comparative claim; a
batch-correction algorithm does not create missing design information.

### Statistical inference

- Match the test/model to outcome distribution, design, pairing, and unit.
- Record effect size, uncertainty/CI, exact p value when available, and the
  family over which multiple testing was controlled.
- Check covariates, offsets, contrasts, reference levels, filtering before
  testing, independent filtering, and post-selection inference.
- Distinguish exploratory thresholds from confirmatory decision rules.
- A plot or nominal p value alone does not establish a robust effect.

### Species, reference, and identifiers

- Record species, strain when relevant, genome/transcriptome build, annotation
  release, coordinate convention, and feature namespace.
- Preserve original gene/feature ids. Record version stripping, symbol mapping,
  orthology mapping, one-to-many mappings, duplicates, unmapped features, and
  aggregation rules.
- Do not silently mix human/mouse symbols, Ensembl releases, gene/transcript
  ids, or coordinate builds.

### Parameter consistency

For each consequential parameter, compare:

`Methods | supplement/table | config | active code | runtime log | observed output`

Include defaults only when the installed version and call signature establish
that the default applied. A current-library default is not evidence for an old
paper's run.

### Conclusion strength

Use the lowest ceiling imposed by design, measurement, and execution evidence:

- descriptive observation;
- association/correlation;
- predictive performance;
- temporal ordering;
- perturbation-supported effect;
- `not_assessable` when required design/evidence is absent.

`perturbation_supported` is the highest reconstruction ceiling in this local
contract. Even when a paper reports intervention, temporal order, controls, or
direct flux measurement, retain causal, mechanistic, and measured-flux wording
as paper-attributed or unverified and record the design basis separately; the
validator does not automatically certify those claim levels.

## Bulk RNA-seq and other sample-level expression

- Confirm raw counts versus TPM/FPKM/CPM/log expression and the method's input
  requirement.
- Check library-size normalization, low-count filtering, design matrix,
  contrasts, paired/repeated structure, batch covariates, dispersion estimation,
  and independent sample count.
- For gene-set analysis, record gene universe, ranking statistic, direction,
  database/version, identifier mapping, permutation unit, and FDR family.
- Do not interpret enrichment as activation, necessity, or mechanism without
  orthogonal evidence.

## Single-cell and single-nucleus omics

- Record assay, count source, cell/nucleus QC, ambient correction, doublet
  handling, normalization, HVG selection, integration, graph, clustering,
  annotation, and random seeds.
- Cells are nested within donors/samples. For condition inference, audit donor-
  or sample-level replication and pseudobulk/mixed-model strategy.
- Integration coordinates are generally not count-scale inputs for DE.
- Check cell-type abundance, unequal cells per donor, composition effects,
  sample coverage, and whether labels were transferred or manually curated.
- A trajectory/pseudotime is an ordering under a model. It is not observed time,
  lineage, direction, or fate without independent directional evidence.

## Spatial transcriptomics and imaging-derived omics

- Record platform, spatial unit (spot/cell/bin/ROI), segmentation, coordinate
  system, image registration, tissue/sample identity, and neighborhood scale.
- Spatial units within a section are not independent biological replicates.
  Audit subject/section nesting and spatial autocorrelation.
- Check deconvolution reference, gene overlap, normalization compatibility,
  priors, batch/platform effects, and validation against known anatomy or
  orthogonal measurements.
- A spatial co-location or ligand/receptor score is association, not proof of
  communication or mechanism.

## Proteomics and metabolomics

- Record acquisition mode, feature identification confidence, normalization,
  batch/QC samples, drift correction, missingness mechanism, imputation,
  transformation, and multiple-testing universe.
- Distinguish peptide from protein inference and annotated metabolite from
  ambiguous feature/isomer.
- Pathway scores or inferred enzyme activities are not measured reaction rates.
- Expression or abundance alone cannot establish true metabolic flux. Flux
  claims require appropriate tracer/flux measurements or a clearly stated,
  validated constraint-based inference with its assumptions.

## Epigenomics and genomics

- Record genome build, read processing, duplicate handling, blacklist/filtering,
  peak/variant calling, coverage, normalization, and annotation release.
- Check sample-level replication, paired inputs/controls, peak universe,
  differential model, CNV/ploidy where relevant, and multiple testing.
- Coordinate conversion must record chain/reference and unmapped or duplicated
  loci.
- Accessibility, binding motif, or methylation association alone does not prove
  regulation or functional mechanism.

## Microbiome and compositional measurements

- Record extraction/primer/platform, denoising or OTU method, taxonomy database,
  contaminant controls, library filtering, and repeated sampling.
- Audit compositionality, zero handling, normalization/transform, subject-level
  replication, batch, antibiotic/diet covariates, and multiple testing.
- Relative abundance changes do not necessarily imply absolute abundance
  changes.

## Multi-omics, time course, and cross-species analysis

- Verify sample pairing across modalities, missing-modality handling, feature
  mapping, scale normalization, and whether integration was supervised by the
  outcome.
- For time courses, separate repeated measurements from independent samples;
  audit time × condition interactions and temporal resolution.
- For cross-species work, record orthology type, one-to-many resolution,
  reference releases, and losses introduced by mapping.
- A shared latent factor is not by itself a regulatory mechanism.

## Interpretation handoff

For each audit issue, record:

- observed evidence and locator;
- affected analysis and claim;
- whether it is a conflict, blocking gap, nonblocking limitation, or reasonable
  inference;
- the maximum defensible claim;
- the additional data or experiment needed to raise that ceiling.
