# Lite Catalogue Analysis Workflow

Use this workflow when compute nodes can read the full catalogue on shared
storage but cannot write derived data there. The full catalogue remains
unchanged during computation. A lightweight working catalogue stores results
on a writable filesystem and imports them later.

The normal unit of work is one collection.

## Overview

```text
full source catalogue
    |
    | csfdata import-lite
    v
lite working catalogue
    |
    | csfdata analysis compute
    v
completed derived HDF5 files in the working location
    |
    | csfdata analysis import-derived
    v
derived files in the original full catalogue
```

The lite catalogue contains copied metadata, canonical configurations, and a
SQLite index. It does not contain raw snapshots, but it may contain small raw
support files declared by its collection configuration. Its `lite.yaml` records
the exact source catalogue and collection from which it was imported.

## 1. Import One Collection

From a node that can read the full catalogue, create the lite working copy:

```bash
csfdata import-lite \
  /path/to/source-catalogue \
  --collection example-collection \
  /path/to/working-directory
```

The default root name is `catalogue`, so this creates:

```text
/path/to/working-directory/catalogue/
  lite.yaml
  registry.sqlite
  collections/
    example-collection/
      collection.yaml
      simulations/
        0001/
          metadata.yaml
          config.yaml
```

The collection ID appears only below `collections/`. The root is always named
`catalogue` unless you explicitly choose another name:

```bash
csfdata import-lite \
  /path/to/source-catalogue \
  --collection example-collection \
  --root analysis-catalogue \
  /path/to/working-directory
```

Re-run the same import to fill missing lite-catalogue files. It checks that the
existing lite catalogue records the same full source catalogue and collection,
and never overwrites existing files unless `--overwrite` is supplied.

To import directly from a remote source, use the normal SSH source syntax:

```bash
csfdata import-lite \
  USER@HOST:/path/to/source-catalogue \
  --collection example-collection \
  /path/to/working-directory
```

CSFData runs `rsync` internally. SSH handles the caller's usual credentials.
Raw snapshots are excluded, while any files declared under `lite.include` in
the source `collection.yaml` are retained. The collection-level
`snapshot-times.yaml` inventory is also copied, so the lite catalogue can list
available remote snapshots locally without starting CSFData on the source host.

## 2. Compute On A Worker Node

On a worker node, run the analysis against the lite catalogue root:

```bash
csfdata analysis compute lagrangian_radii \
  --catalogue /path/to/working-directory/catalogue \
  --workers 12
```

Before computation begins, the command lists the selected collections and
simulation counts, then asks for confirmation:

```text
Selected collections:
  example-collection: 100 simulations
Total simulations: 100
Compute this diagnostic? [y/N]
```

The analysis code recognizes `lite.yaml`, verifies that the original source
collection, metadata, and canonical configuration still match, then reads raw
snapshots from the recorded source catalogue. It writes HDF5 files only under the lite catalogue's
`derived/diagnostics/` directories.

For a non-interactive Slurm job, skip the confirmation explicitly:

```bash
csfdata analysis compute lagrangian_radii \
  --catalogue /path/to/working-directory/catalogue \
  --workers 12 \
  --no-prompt
```

Use `--filter` to calculate only a selected subset. The command still prints
the resulting collection and simulation counts before confirmation.

## 3. Import Completed Derived Results

From a node that can write to the full catalogue, import results:

```bash
csfdata analysis import-derived /path/to/working-directory/catalogue \
  --catalogue /path/to/source-catalogue
```

The importer checks every completed HDF5 file against the destination:

- Collection ID and simulation ID.
- Copied simulation metadata.
- Canonical `config.yaml` SHA-256 fingerprint.
- Diagnostic name and version recorded both in the HDF5 file and its path.
- The HDF5 completion flag.

Only files that pass these checks are eligible for copying. A file is complete
only after the worker has written, validated, and atomically renamed it from a
temporary file to `series.h5`.

By default, missing destination files are copied and existing destination
files are skipped. This makes it safe to import partial results, continue the
worker computation, and import again later. The command reports missing,
incomplete, and mismatched results without copying them.

Preview the import without writing anything:

```bash
csfdata analysis import-derived /path/to/working-directory/catalogue \
  --catalogue /path/to/source-catalogue \
  --dry-run
```

Replace an existing derived file only when that is an intentional decision:

```bash
csfdata analysis import-derived /path/to/working-directory/catalogue \
  --catalogue /path/to/source-catalogue \
  --overwrite
```

## Safety Rules

- Do not edit `lite.yaml`; it is the provenance link to the full catalogue.
- Keep the source catalogue available at the absolute path recorded during
  import. If it is unavailable on the worker, computation stops before reading
  snapshots.
- Do not copy `raw/` data into the lite catalogue.
- Do not use `--overwrite` unless the replacement is deliberate and reviewed.
- Keep the lite catalogue until imported results have been checked and backed
  up as appropriate.
