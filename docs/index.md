# CSFData

CSFData is the lightweight backbone for validating, importing, indexing, and
organizing simulation catalogues. It keeps raw data, catalogue metadata, and
derived products distinct.

## Architecture

CSFData owns the catalogue structure, source provenance, canonical simulation
configuration, SQLite index, and safe import workflows. It has no scientific
analysis dependency.

Optional add-ons perform science-specific work. The first is CSFData Analysis,
which reads raw snapshots, computes versioned derived products, and provides
Pandas interfaces for time-series and snapshot data.

## Documentation

- [Catalogue](catalogue.md) explains collections, simulation records, and the
  registry.
- [Catalogue Workflow](catalogue-workflow.md) explains validation, import, and
  indexing.
- [Lite Catalogue Workflow](lite-catalogue-workflow.md) explains safe worker
  computation and later derived-data import.
- [Command Line](command-line.md) lists the available backbone commands.
- [Canonical Units](units.md) describes the standard unit conventions.
- [CSFData Analysis Documentation](https://juanfariaso.github.io/csfdata_analysis/)
  covers diagnostics and researcher-facing derived-data tools.
