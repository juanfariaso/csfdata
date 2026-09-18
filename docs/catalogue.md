# Catalogue

The catalogue is the long-lived local store for imported simulations. The
`csfdata` Git repository contains code and documentation only; raw simulation
data live in a separate shared catalogue directory.

## Layout

```text
catalogue-root/
  registry.sqlite
  collections/
    dcaf-grid-v1/
      collection.yaml
      simulations/
        0001/
          metadata.yaml
          config.yaml
          raw/
          derived/
```

Each collection is one coherent simulation grid or campaign. Simulation IDs
such as `0001` are permanent within their collection. Different code families,
for example future MHD simulations, belong in separate collections.

## Simulation Records

Each imported simulation has two top-level YAML records:

- `metadata.yaml` contains stable identity and provenance: simulation ID,
  collection ID, importer, original source path, hostname, and import time.
- `config.yaml` contains canonical scientific parameters. It has `parameters`
  for shared catalogue parameters and `code_parameters` for additional
  code-specific values.

The original input files are retained unchanged under `raw/`. Derived analysis
products belong under `derived/` and do not modify raw data.

## Registry

`registry.sqlite` is a rebuildable SQLite search index. It is not the source of
truth: the YAML files remain authoritative and readable without database
software. The registry makes selecting simulations by many parameters fast
without opening every YAML file.

The registry keeps universal catalogue facts in ordinary database columns and
scientific parameters in rows. This permits collections with different
parameter vocabularies without changing the database structure.

```text
simulations
  collection_id, simulation_id, relative_path, imported_at

parameter_values
  collection_id, simulation_id, name, value_type,
  numeric_value, text_value, unit, section
```

Known numeric values are stored in the catalogue's canonical units. Unknown or
not-applicable parameters are not indexed, so they can never be mistaken for
scientific values in a query.

## Build The Index

Index every collection after import:

```bash
csfdata index-catalogue /path/to/catalogue
```

Index only one changed or newly imported collection:

```bash
csfdata index-catalogue /path/to/catalogue --collection dcaf-grid-v1
```

The selected collection's prior rows are replaced in one SQLite transaction.
This prevents duplicate rows and removes stale entries. A full index rebuild
replaces the complete registry.

## Operational Workflow

Use the catalogue in this order:

```text
validate source grid
    -> import approved simulations into a collection
    -> index the catalogue
    -> inspect the global summary
    -> inspect collection coverage and missing combinations
    -> select simulations for formal analysis
```

## Lite Collections

A lite collection is a queryable working copy of exactly one
full catalogue collection. It is intended for worker-node analysis when the
worker can read the source catalogue but cannot write there. The lite copy stores its
source catalogue path and collection fingerprint in `lite.yaml`; it is not a
new scientific collection or a replacement for the original raw data.

Import it with `csfdata import-lite`, compute derived data inside the lite
catalogue, then use `csfdata analysis import-derived` from a writable node to
validate and copy only completed products back into the recorded source.

Each full collection also has one `snapshot-times.yaml` inventory. It records
snapshot paths, times, and sizes for the whole collection and is created after
an import. Run `csfdata refresh-snapshot-times` after raw files change. Lite
imports copy this small file, allowing snapshot selection without accessing the
source server's Python environment.

Each collection can declare small raw support files that every lite copy keeps:

```yaml
lite:
  include:
    - raw/background_gas*.dat
```

Patterns are relative to each simulation root and must stay below `raw/`. This
is a collection policy: different collections may retain different timing or
checkpoint files. All undeclared raw files, including snapshots, remain absent
from lite copies.

The global commands discover collection IDs themselves. You only need to give
`--collection` after the global summary has shown the collection you want to
inspect or update.

## Inspect Contents

Print a compact summary of everything currently indexed:

```bash
csfdata catalogue-summary /path/to/catalogue
```

Inspect one collection only:

```bash
csfdata catalogue-summary /path/to/catalogue --collection dcaf-grid-v1
```

The summary reports each collection's simulation count and each available
parameter's section, value type, unit, availability, and either numeric range
or number of distinct text values. It reads `registry.sqlite` and the small
collection configuration only; it does not rescan simulation directories.

For example:

```text
Registry: /shared/group/csf-catalogue/registry.sqlite
Collections: 1
dcaf-grid-v1 (dcaf)
  Simulations: 1858
  Parameters:
    sfe: 1858/1858; range 0.05 to 0.3 (parameters, number)
    tff [Myr]: 1858/1858; range 0.5 to 3 (parameters, number)
  Grid coverage:
    Expected combinations: 1900
    Indexed combinations: 1858
    Missing combinations: 42
```

## Grid Coverage

A collection can optionally declare the full expected Cartesian grid in its
`collection.yaml`:

```yaml
grid_axes:
  tff: [0.5, 1.0, 3.0]
  sfe: [0.05, 0.1, 0.3]
  seed_index: [0, 1, 2, 3]
```

Declare `grid_axes` before the first import for a collection. The importer
preserves the reviewed `collection.yaml` in the catalogue and rejects later
imports whose collection configuration differs. A controlled collection-update
workflow can be added later if a real campaign needs to change its axes.

When present, `catalogue-summary --collection` adds expected, indexed, and
missing combination counts. `grid_axes` must list only independently varied
parameters; coupled axes and exclusions are not represented in the first
version.

Write every declared but absent combination to a CSV file:

```bash
csfdata missing-combinations /path/to/catalogue \
  --collection dcaf-grid-v1 \
  --output missing-combinations.csv
```

The CSV headers follow the `grid_axes` declaration order. This report can be
used to inspect gaps manually or to prepare later scheduler submissions.

An empty CSV containing only its headers means the declared grid is complete.

## Next Use

Use `find_simulations(...)` from Python to query this registry by collection
and parameter ranges. The analysis add-on uses the same function to select
exactly which catalogue simulations receive a diagnostic:

```python
from csfdata.catalogue import find_simulations

simulations = find_simulations(
    "/path/to/catalogue",
    collection_id="dcaf-grid-v1",
    filters={"tff": (0.5, 3.0), "sfe": 0.3},
)
```
