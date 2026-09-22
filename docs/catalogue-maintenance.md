# Catalogue Maintenance

Catalogue maintenance keeps the searchable registry and the snapshot-time
inventories consistent with the files already stored in a catalogue. It never
modifies raw simulation input or output data.

## When To Maintain

Run maintenance after importing simulations, changing a simulation's canonical
`metadata.yaml` or `config.yaml`, or adding raw snapshots to an existing
collection.

For an ordinary import, CSFData automatically indexes the imported collection
and creates its initial snapshot-time inventory. The commands below are needed
only after later changes.

## Rebuild The Registry

The SQLite registry indexes every simulation's small `metadata.yaml` and
`config.yaml` records. It does not open raw snapshots.

Refresh one changed collection:

```bash
csfdata index-catalogue /path/to/catalogue --collection example-collection
```

Refresh every collection:

```bash
csfdata index-catalogue /path/to/catalogue
```

The command replaces the affected SQLite rows in one transaction. The YAML
records remain the source of truth, so `registry.sqlite` can always be rebuilt.

## Refresh Snapshot Times

Each collection has one `snapshot-times.yaml` inventory. It maps every usable
primary snapshot to its exact model time and source size. Lite catalogues copy
this small inventory, allowing snapshot selection without running Python on the
server that stores the raw data.

Refresh one collection after adding or replacing snapshots:

```bash
csfdata refresh-snapshot-times /path/to/catalogue \
  --collection example-collection
```

Omit `--collection` to refresh every collection:

```bash
csfdata refresh-snapshot-times /path/to/catalogue
```

For D-CAF, this operation opens every `.amuse` HDF5 snapshot and reads its
stored model time. This is deliberately read-only, but can take substantial
time for a large grid on a shared filesystem. The progress bar identifies the
current collection and simulation.

For a long refresh on a login node, use `tmux` so the task survives a dropped
terminal connection:

```bash
tmux new -s csfdata-maintenance
csfdata refresh-snapshot-times /path/to/catalogue
```

Detach with `Ctrl-b d`; later resume with:

```bash
tmux attach -t csfdata-maintenance
```

The refresh writes only
`collections/<collection-id>/snapshot-times.yaml`. It does not alter any
simulation's `raw/` directory. If any snapshot cannot be read, the inventory
still contains all successful entries, the command reports the affected
simulations, and exits with a nonzero status. Correct the data or rerun the
refresh when the source becomes readable.

## Update Lite Copies

After refreshing a full collection, rerun its compatible lite import to copy
the updated `snapshot-times.yaml` and any newly available metadata or derived
products:

```bash
csfdata import-lite /path/to/catalogue /path/to/working-directory \
  --collection example-collection
```

Existing lite files are preserved by default. The command copies missing files
and refreshes its SQLite registry without overwriting data unless `--overwrite`
is explicitly supplied.

## Import Selected Snapshots

Use the lite catalogue to select and retrieve only the snapshots needed for a
local task. The resulting `snapshots.yaml` is a portable manifest, not a copy
of snapshot data.

First, inspect the indexed parameter names, units, and available values:

```bash
csfdata catalogue-summary /path/to/lite-catalogue \
  --collection example-collection
```

Use the displayed parameter names in one or more `--filter` options. An exact
filter uses `NAME=VALUE`; a numeric inclusive range uses `NAME=LOWER:UPPER`.
For example, select the closest snapshot to `24.9 Myr` from simulations with
one exact and one range filter:

```bash
csfdata list-snapshots /path/to/lite-catalogue \
  --collection example-collection \
  --time 24.9 \
  --filter tff=1.0 \
  --filter sfe=0.1:0.3 \
  --output snapshots.yaml
```

The command reads the local `snapshot-times.yaml` inventory and writes
`snapshots.yaml` in the requested location. It reports simulations for which
no snapshot is close enough to the requested time. Use
`--normalization PARAMETER` when `--time` is a multiplier of a Myr-valued
parameter rather than a physical Myr value.

Then copy the approved snapshots into that same lite catalogue:

```bash
csfdata import-snapshots snapshots.yaml /path/to/lite-catalogue
```

The importer checks the source identity and local snapshot inventory before it
starts a resumable `rsync` transfer. Existing snapshots are skipped unless
`--overwrite` is supplied.
