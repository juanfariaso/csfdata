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
      diagnostics.yaml
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

## Derived Diagnostics

`diagnostics.yaml` is the collection-level, versioned description of available
derived analysis data. It records diagnostic names, versions, output fields,
canonical units, storage locations, and the scientific choices that affect
each result. It does not duplicate results, which remain below each
simulation's `derived/` directory.

The analysis add-on publishes this file when it computes a diagnostic. Core
catalogue tools can therefore inspect, index, and query existing derived data
without importing analysis dependencies such as AMUSE. Time-series and scalar
diagnostics use the same description format.

Definitions can also declare completed diagnostic versions they require. This
make analysis dependency chains explicit: a scalar fit can state that it
needs particular time-series diagnostics before it can run. The catalogue
records and validates these requirements; analysis runners later use them to
report missing prerequisites clearly.

Simulation-level derived values are stored separately in each simulation's
`derived/scalar_diagnostics.yaml`. Each value uses the same small record format as a
canonical catalogue parameter:

```yaml
value: 0.12
unit: km/s
```

The surrounding scalar-diagnostic record identifies the diagnostic name, version, and
concrete choices that produced the value. `csfdata index-catalogue` validates
that record against the collection `diagnostics.yaml` before indexing it.
Default-choice scalar values join the same query space as configuration
parameters, so one filter can combine both kinds of value:

```python
find_simulations(
    "/path/to/catalogue",
    collection_id="example-collection",
    filters={"tff": 1.0, "derived_parameter": (0.1, None)},
)
```

No manual database edits are needed. A future analysis or import tool writes
the validated scalar-diagnostics YAML; rerun `csfdata index-catalogue` to refresh the
rebuildable SQLite registry.

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

The summary is based on the completed index. It separates normal simulation
parameters from default-choice scalar diagnostics, because both can be used in
catalogue queries but have different meanings. Simulation parameters show up
to ten stored values; higher-cardinality numeric parameters show their number
of distinct values and range. Scalar diagnostics show availability, range,
median, and mean plus standard deviation.

Time-series diagnostics are shown separately. Their fields are not ordinary
catalogue query filters because they also require a time and sometimes a
scientific choice. During indexing, CSFData records only whether each declared
time-series file is complete, so the summary can show coverage without reading
its numerical HDF5 datasets. Tables wrap long value or field lists to the
current terminal width.

For example:

```text
Registry: /shared/group/csf-catalogue/registry.sqlite
Collections: 1
dcaf-grid-v1 (dcaf)
  Simulations: 1858
  Simulation parameters:
    name  source      unit  available  values
    sfe   parameters  1     1858/1858  0.05, 0.1, 0.3
    tff   parameters  Myr   1858/1858  0.5, 1, 3
  Derived parameters:
    none
  Time-series diagnostics:
    diagnostic         version  available  fields
    lagrangian_radii   v1       1858/1858  stellar_mass [Msun], r_l50 [pc], ...;
                                               choices: center=origin,stellar_com
                                               (default stellar_com)
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
