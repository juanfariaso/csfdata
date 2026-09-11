from pathlib import Path

import pytest

from csfdata.adapters.dcaf import DcafAdapter
from csfdata.catalogue.configuration import read_simulation_configuration
from csfdata.catalogue.metadata import read_simulation_metadata
from csfdata.importer.local import import_manifest
from csfdata.importer.manifest import create_import_manifest
from csfdata.importer.validation import ValidatedSource


def test_import_manifest_copies_one_simulation_through_staging(tmp_path: Path) -> None:
    source_root = tmp_path / "source-grid"
    run_root = source_root / "M1000" / "tff3.0" / "07"
    run_root.mkdir(parents=True)
    (run_root / "config.yaml").write_text("tff: 3.0 Myr\nt_end: 15.0 Myr\n", encoding="utf-8")
    (run_root / "code.out").write_text("D-CAF output\n", encoding="utf-8")
    (run_root / "background_gas.dat").write_text("0.0 5000\n15.0 6000\n", encoding="utf-8")
    output_file = run_root / "dcaf_output" / "diagnostics.dat"
    output_file.parent.mkdir()
    output_file.write_text("raw output\n", encoding="utf-8")

    collection_path = tmp_path / "collection.yaml"
    collection_path.write_text(
        """schema_version: 1
id: dcaf-tff-grid-v1
importer: dcaf
config_schema_version: 1
required_parameters:
  - tff
optional_parameters: []
""",
        encoding="utf-8",
    )
    manifest = create_import_manifest(
        ValidatedSource(
            hostname="trillium",
            root=source_root,
            valid_simulation_paths=(Path("M1000/tff3.0/07"),),
        ),
        "dcaf-tff-grid-v1",
    )
    catalogue_root = tmp_path / "catalogue"
    catalogue_root.mkdir()

    destination = catalogue_root / "collections" / "dcaf-tff-grid-v1" / "simulations" / "0001"
    planned_destinations = import_manifest(
        manifest,
        catalogue_root,
        collection_path,
        DcafAdapter,
        dry_run=True,
    )
    assert planned_destinations == (destination,)
    assert not (catalogue_root / "collections").exists()

    destinations = import_manifest(manifest, catalogue_root, collection_path, DcafAdapter)

    assert destinations == (destination,)
    assert (catalogue_root / "collections" / "dcaf-tff-grid-v1" / "collection.yaml").is_file()
    assert (destination / "raw" / "config.yaml").read_text(encoding="utf-8") == (
        run_root / "config.yaml"
    ).read_text(encoding="utf-8")
    assert (destination / "raw" / "dcaf_output" / "diagnostics.dat").read_text(
        encoding="utf-8"
    ) == "raw output\n"
    assert (destination / "derived").is_dir()
    assert read_simulation_configuration(destination / "config.yaml").parameter("tff").value == 3.0
    metadata = read_simulation_metadata(destination / "metadata.yaml")
    assert metadata.simulation_id == "0001"
    assert metadata.source_hostname == "trillium"
    assert metadata.source_relative_path == Path("M1000/tff3.0/07")
    assert not (catalogue_root / "collections" / "dcaf-tff-grid-v1" / ".staging" / "0001").exists()


def test_import_manifest_rejects_raw_symbolic_links(tmp_path: Path) -> None:
    source_root = tmp_path / "source-grid"
    run_root = source_root / "M1000" / "tff3.0" / "07"
    run_root.mkdir(parents=True)
    (run_root / "config.yaml").write_text("tff: 3.0 Myr\n", encoding="utf-8")
    output_root = run_root / "dcaf_output"
    output_root.mkdir()
    external_file = tmp_path / "external.dat"
    external_file.write_text("outside source grid\n", encoding="utf-8")
    (output_root / "linked.dat").symlink_to(external_file)

    collection_path = tmp_path / "collection.yaml"
    collection_path.write_text(
        """schema_version: 1
id: dcaf-tff-grid-v1
importer: dcaf
config_schema_version: 1
required_parameters:
  - tff
optional_parameters: []
""",
        encoding="utf-8",
    )
    manifest = create_import_manifest(
        ValidatedSource(
            hostname="trillium",
            root=source_root,
            valid_simulation_paths=(Path("M1000/tff3.0/07"),),
        ),
        "dcaf-tff-grid-v1",
    )
    catalogue_root = tmp_path / "catalogue"
    catalogue_root.mkdir()

    with pytest.raises(ValueError, match="Symbolic links"):
        import_manifest(manifest, catalogue_root, collection_path, DcafAdapter)
