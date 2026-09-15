# Command Line

## Index Catalogue

Build the SQLite search index for every collection in a catalogue:

```bash
csfdata index-catalogue /path/to/catalogue
```

Update only a newly imported or changed collection:

```bash
csfdata index-catalogue /path/to/catalogue --collection dcaf-grid-v1
```

The command writes `registry.sqlite` at the catalogue root. It indexes each
simulation's canonical `metadata.yaml` and `config.yaml`; those YAML files
remain the source of truth and the SQLite file can always be rebuilt.

## Catalogue Summary

Print available indexed parameters, their units, availability, and value
ranges without rescanning the catalogue YAML files:

```bash
csfdata catalogue-summary /path/to/catalogue
csfdata catalogue-summary /path/to/catalogue --collection dcaf-grid-v1
```

Run `index-catalogue` first. The summary reads `registry.sqlite` and the
selected collection configuration only.

## Missing Combinations

For a collection that declares `grid_axes`, write the expected parameter
combinations that are absent from the indexed catalogue:

```bash
csfdata missing-combinations /path/to/catalogue \
  --collection dcaf-grid-v1 \
  --output missing-combinations.csv
```

The output CSV uses the declared axis names as headers and can later feed a
scheduler or a manual restart workflow.

## Analysis Add-on

Install `csfdata_analysis` in the same Python environment as `csfdata` to
make its diagnostics available through the main command:

```bash
csfdata analysis diagnostics
csfdata analysis compute lagrangian_radii \
  --catalogue /path/to/catalogue \
  --filter collection=dcaf-grid-v1 \
  --workers 12 \
  --dry-run
```

`csfdata` forwards everything after `analysis` to the add-on. The backbone
does not import AMUSE itself; AMUSE is required only by the separately
installed analysis package. Use `compute-simulation` instead of `compute`
when developing or inspecting one imported simulation directly.

`csfdata` validates local D-CAF simulation grids and imports approved
simulations into a separate local catalogue. It never modifies the source grid.

## Export Lite Collection

Create a lightweight working copy of one collection before using a worker node
that cannot write to the full catalogue:

```bash
csfdata export-lite \
  --catalogue /path/to/source-catalogue \
  --collection dcaf-grid-v1
```

The lite catalogue copies only `collection.yaml`, `metadata.yaml`, and
canonical `config.yaml`, then creates its own `registry.sqlite`. It does not
copy raw snapshots or prior derived files. Its `lite.yaml` records the full
source catalogue and collection identity so the analysis add-on can read raw
snapshots from the original catalogue while writing results locally. By
default it creates `./catalogue`; give an existing directory such as
`/path/to/working-directory` to create its `catalogue` child. Use `--root NAME` to choose
a different lite-root folder name. Repeating the export into the same
compatible lite catalogue copies only missing metadata and configuration files
and never overwrites existing files.

## Installation

From the repository root, create and activate a Python environment, then
install the package:

```bash
python -m venv .venv
source .venv/bin/activate
python -m pip install -e .
```

The editable installation makes the `csfdata` command available in the active
environment. Re-run the installation command after pulling changes that add or
update dependencies.

## Validate

Use `validate` to scan and validate a D-CAF grid:

```bash
csfdata validate /path/to/grid --report validation-report.yaml
```

The command finds D-CAF simulation directories below the supplied root, then
first performs fast structural validation. It checks matching segment lengths
and flags resumed background-gas segments whose time range moves backward.
Only simulations flagged by that first pass have their D-CAF `.amuse` snapshots
opened. For those simulations, `csfdata` compares each stored model time with
the corresponding `background_gas*.dat` record in the same numbered output
segment, and identifies a segment whose complete checkpoint and snapshot
timeline is duplicated by another segment.

This avoids opening snapshots for a structurally clean grid, which is important
on a large shared filesystem. A clean result therefore means the fast checks
passed; it is not a full snapshot-by-snapshot audit.

During an interactive terminal session, the current simulation is shown on one
updating line. When it completes, `csfdata` prints one `OK` or `ISSUE` line;
detailed issue messages appear only for affected simulations.

## Validation Report

`--report` is required. The report is YAML so that a later transfer tool can
read it without scanning the source grid again. It records the hostname and
absolute root path used for validation. Valid simulations are a compact list
of paths relative to that root; simulations with issues map each relative path
to its validation messages:

```yaml
schema_version: 1
source:
  hostname: trillium
  root: /shared/group/dcaf/grid

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

The terminal prints only the total number validated, the number ready for
transfer, the number with issues, and the report path.

## Import

Use `import` after reviewing a validation report:

```bash
csfdata import /shared/group/csf-catalogue \
  --report validation-report.yaml \
  --collection collection.yaml
```

Before a real transfer, use `--dry-run` to run the same preflight checks
without creating catalogue directories or copying files:

```bash
csfdata import /shared/group/csf-catalogue \
  --report validation-report.yaml \
  --collection collection.yaml \
  --dry-run
```

The catalogue root must already exist. On the first import for a collection,
the supplied `collection.yaml` is copied into the catalogue. Later imports must
use an equivalent collection configuration.

### Collection Name

The `id` field in `collection.yaml` names the collection. For example:

```yaml
id: dcaf-tff-grid-v1
```

With catalogue root `/shared/group/csf-catalogue`, the first successful import
creates this directory structure automatically:

```text
/shared/group/csf-catalogue/
  collections/
    dcaf-tff-grid-v1/
      collection.yaml
      .staging/
      simulations/
```

Do not create the collection directory manually. The catalogue root itself must
already exist, but the importer creates the collection directory only after its
preflight checks pass.

For each simulation approved by the report, the command assigns a local ID such
as `0001`, then re-reads only the source configuration to
create the catalogue-facing `config.yaml` and confirm required parameters. It
does not rediscover the grid or repeat full simulation validation. It copies
only the source paths selected by the D-CAF adapter into `raw/`, creates an
empty `derived/` directory, writes `metadata.yaml`, verifies the staged files,
and then promotes the simulation into the collection.

Each simulation is staged below `.staging/` before promotion. If an import
fails, its staging directory is kept for inspection. The command never
overwrites an existing simulation or follows a symbolic link in raw data.

During a real import, one updating terminal line shows the current simulation
and the fraction of its raw-data bytes copied. It updates after each copied raw
file; individual filenames are not printed. Each completed simulation leaves
one `OK` line.

## Current Scope

The current commands understand D-CAF directories only. They do not repair
simulations, import from remote hosts, submit scheduler jobs, or calculate
derived products.
