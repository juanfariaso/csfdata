# Catalogue Workflow

This page records design for importing validated simulation grids into a
long-lived catalogue. It is a design reference. Some parts are already
implemented, while copying and catalogue creation remain planned work.

This page idea is to familiarize with the design, plan future features and 
keep decisions consistent as this repository builds.

## Goals

- Keep raw source data unchanged.
- Import only simulations approved by validation.
- Give every managed simulation a stable catalogue identity.
- Keep collections separate by grid or campaign.
- Make every managed simulation expose a predictable `config.yaml` for later
  metadata extraction and queries.
- Keep validation, import, and later indexing as separate steps.

## Terms

A **source grid** is the existing directory tree that contains simulations.

A **collection** is one coherent imported grid or campaign in the catalogue.
For example, `dcaf-tff-grid-v1` is a D-CAF collection. Future MHD grids will
be separate collections.

A **validation report** is the YAML file written by `csfdata validate`. It
records the source hostname and root, lists simulations approved for transfer,
and records simulations with validation issues.

During an import, `csfdata` creates an in-memory mapping from approved source
paths to local simulation IDs such as `0001`. The imported simulations' metadata
records this permanent association; users do not manage a separate manifest file.

## Validation Report

Validation scans a source grid, checks each D-CAF simulation, and writes a
portable report. Its approved paths are relative to the source root so the
root is recorded only once.

```yaml
schema_version: 1
source:
  hostname: superdupercomputer
  root: /path_to_the_grid_we_want_to_import/

summary:
  total_simulations: 1900
  valid_simulations: 1858
  simulations_with_issues: 42

valid_simulations:
  - M1000/tff0.5_sfe0.05/01

simulations_with_issues:
  M1000/tff0.5_sfe0.05/00:
    - Segment 0: background_gas.dat has 25 time records but dcaf_output has 72 stellar snapshots.
```

Only `valid_simulations` may be imported. Simulations with issues remain in the
report for later inspection, repair, or rerunning.

## Catalogue Layout

Raw data are not stored in Git. The Git repository contains only the Python
code and documentation. A shared catalogue root stores imported data.

```text
catalogue-root/
  registry.sqlite
  collections/
    dcaf-tff-grid-v1/
      collection.yaml
      simulations/
        dcaf-tff-grid-v1-0001/
          metadata.yaml
          config.yaml
          raw/
            config.yaml
            code.out
            background_gas.dat
            dcaf_output/
          derived/
```

Each collection has its own `simulations/` directory. We do not place all
simulation codes and campaigns into one global simulations folder.

## Two Configuration Layers

Every managed simulation must contain a top-level `config.yaml`. This is the
required, catalogue-facing scientific configuration. It gives all future tools
one predictable place to find the parameters of a simulation.

The `raw/` directory preserves source files without changing their meaning. In
a D-CAF import, the original D-CAF `config.yaml` is copied to
`raw/config.yaml`. The importer reads it and creates the separate top-level
catalogue `config.yaml`.

```text
config.yaml       Canonical catalogue configuration for this simulation.
raw/config.yaml   Original D-CAF configuration copied without modification.
```

For a future code that uses a namelist, HDF5 header, or another input format,
its collection adapter constructs the top-level `config.yaml` from those
sources. The raw files retain their original names and formats.

## Collection Configuration

`collection.yaml` describes choices shared by all simulations in one
collection. In particular, it selects the importer and declares the standard
parameters that every simulation in the collection must provide. At present,
these may use the selected code's original parameter names. A shared
cross-code vocabulary will be designed later.

```yaml
schema_version: 1
id: dcaf-tff-grid-v1
importer: dcaf
config_schema_version: 1

required_parameters:
  - seed_index
  - tff
  - Mstars
  - sfe

optional_parameters:
  - Fmax
  - tge_over_tff
```

The final shared catalogue vocabulary will be agreed explicitly. Until then,
the D-CAF adapter preserves every scalar source field as a code-specific
parameter. Its collection may require D-CAF names directly, but those names
are not yet guaranteed to be comparable across collections.

## Metadata

`metadata.yaml` records catalogue identity and provenance rather than replacing
scientific configuration. Its minimum fields include:

- Stable simulation ID and collection ID.
- Selected importer or code family.
- Source hostname, root, and relative source path.
- Import time.
- A checksum linking the catalogue configuration to its source inputs.

The top-level `config.yaml` holds scientific parameters. `registry.sqlite` is
rebuilt from these configuration files and metadata records for fast selection;
the YAML files remain the human-readable source of truth.

## Indexing And Coverage

After importing a collection, build the catalogue-wide SQLite index:

```bash
csfdata index-catalogue /path/to/catalogue
```

The index discovers all collection directories. It stores universal catalogue
facts in database columns and scientific parameters as indexed rows, so future
collections can introduce additional parameters without changing the database
schema.

Use the global summary to discover the collections and their available
parameters:

```bash
csfdata catalogue-summary /path/to/catalogue
```

A collection may declare `grid_axes` in its `collection.yaml` when it is
intended to contain every combination of independently varied values:

```yaml
grid_axes:
  tff: [0.5, 1.0, 3.0]
  sfe: [0.05, 0.1, 0.3]
  seed_index: [0, 1, 2, 3]
```

The collection summary then reports expected, indexed, and missing grid
combinations. The exact missing combinations can be written as CSV for later
inspection or scheduler submission:

```bash
csfdata missing-combinations /path/to/catalogue \
  --collection dcaf-grid-v1 \
  --output missing-combinations.csv
```

`grid_axes` describes a full Cartesian product only. It must be declared
before the collection's first import because `collection.yaml` is treated as a
stable reviewed collection definition.

## Import Workflow

The intended workflow is:

```text
source grid
    |
    v
csfdata validate -> validation report
    |
    v
csfdata import
    - select a collection configuration
    - assign collection-local simulation IDs
    - call the selected adapter to read each approved simulation configuration
    - confirm required parameters are understood
    - copy into a staging directory
    |
    v
validate the staged copy and write config.yaml / metadata.yaml
    |
    v
promote the complete staging directory into the collection
    |
    v
csfdata index-catalogue -> registry.sqlite
    |
    v
csfdata catalogue-summary -> available parameters and grid coverage
```

Import preflight is a second validation layer. A simulation must be both
filesystem-valid and understandable by the selected collection adapter before
it is copied into the catalogue.

## Responsibilities

The generic local importer performs staging, copying, verification, and final
promotion. It does not know D-CAF filenames or parameter names.

Each code-specific simulation adapter knows how to:

- Recognize and validate one simulation folder.
- Select the raw files to preserve.
- Read the source configuration format.
- Produce the required top-level catalogue `config.yaml`.
- Preserve code-specific parameters and, once agreed, map shared query
  parameters with their provenance.

D-CAF uses its existing `config.yaml`. A future adapter may use completely
different source files while producing the same catalogue-facing structure.

## Safety Rules

- Validation reports are reviewed records; importing does not rescan the
  source grid.
- Only report-approved paths are eligible for copying.
- Source files are never modified or deleted.
- Copy into staging first, never directly into a final simulation directory.
- Verify the staged copy before promotion.
- Never overwrite an existing imported simulation.
- Keep invalid simulations in the validation report for later work instead of
  silently repairing or importing them.

## Current Status

Implemented now:

- D-CAF validation and YAML validation reports.
- Importer validation-report reader.
- In-memory import mapping and deterministic ID assignment.
- Collection configuration model and required-parameter checks.
- D-CAF canonical configuration extraction and raw-payload selection.
- Version-1 simulation metadata.
- Staged local import with raw-file size verification and no overwrites.
- SQLite registry indexing and global catalogue summaries.
- Optional declared-grid coverage and missing-combination CSV reports.

Planned next:

- Query functions and scheduler support.
- Remote transfer support.
