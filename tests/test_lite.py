"""Tests for collection-scoped lite catalogue imports."""

from pathlib import Path

from csfdata.catalogue.configuration import (
    ConfigurationParameter,
    SimulationConfiguration,
    write_simulation_configuration,
)
from csfdata.catalogue.lite import file_sha256, import_lite_collection, read_lite_source
from csfdata.catalogue.metadata import SimulationMetadata, write_simulation_metadata
from csfdata.catalogue.registry import index_catalogue
from csfdata.catalogue.snapshots import refresh_snapshot_times


def test_import_lite_collection_copies_derived_files_without_raw_data(tmp_path: Path) -> None:
    source = tmp_path / "full"
    simulation = source / "collections" / "grid" / "simulations" / "0001"
    simulation.mkdir(parents=True)
    (simulation.parent.parent / "collection.yaml").write_text(
        """schema_version: 1
id: grid
importer: dcaf
config_schema_version: 1
required_parameters: []
optional_parameters: []
""",
        encoding="utf-8",
    )
    write_simulation_metadata(
        SimulationMetadata("0001", "grid", "dcaf", "host", tmp_path / "source", Path("run"), "2026-01-01T00:00:00Z"),
        simulation / "metadata.yaml",
    )
    write_simulation_configuration(
        SimulationConfiguration((ConfigurationParameter("tff", 1.0, "Myr", "explicit"),), ()),
        simulation / "config.yaml",
    )
    (simulation / "raw").mkdir()
    (simulation / "raw" / "background_gas.dat").write_text("0.0 1.0\n", encoding="utf-8")
    snapshot = simulation / "raw" / "dcaf_output" / "stars_000.amuse"
    snapshot.parent.mkdir()
    snapshot.write_bytes(b"snapshot")
    derived = simulation / "derived" / "diagnostics" / "test" / "v1"
    derived.mkdir(parents=True)
    (derived / "series.h5").write_bytes(b"derived")

    index_catalogue(source)
    refresh_snapshot_times(source, "grid")
    report = import_lite_collection(source, "grid", tmp_path / "lite")

    copied = report.destination / "collections" / "grid" / "simulations" / "0001"
    assert report.simulation_count == 1
    assert (copied / "metadata.yaml").is_file()
    assert (copied / "config.yaml").is_file()
    assert (copied / "derived" / "diagnostics" / "test" / "v1" / "series.h5").is_file()
    assert not (copied / "raw").exists()
    assert (report.destination / "collections" / "grid" / "snapshot-times.yaml").is_file()
    assert (report.destination / "registry.sqlite").is_file()
    assert read_lite_source(report.destination).catalogue_root == source.resolve()

    (simulation.parent.parent / "collection.yaml").write_text(
        """schema_version: 1
id: grid
importer: dcaf
config_schema_version: 1
required_parameters: []
optional_parameters: []
lite:
  include:
    - raw/background_gas*.dat
""",
        encoding="utf-8",
    )
    refresh_snapshot_times(source, "grid")
    report = import_lite_collection(source, "grid", report.destination)

    assert report.simulation_count == 1
    assert (copied / "raw" / "background_gas.dat").read_text(encoding="utf-8") == "0.0 1.0\n"
    assert not (copied / "raw" / "dcaf_output" / "stars_000.amuse").exists()
    assert read_lite_source(report.destination).collection_sha256 == file_sha256(
        simulation.parent.parent / "collection.yaml"
    )
