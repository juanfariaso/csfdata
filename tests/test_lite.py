"""Tests for collection-scoped lite catalogue exports."""

from pathlib import Path

from csfdata.catalogue.configuration import (
    ConfigurationParameter,
    SimulationConfiguration,
    write_simulation_configuration,
)
from csfdata.catalogue.lite import export_lite_collection, read_lite_source
from csfdata.catalogue.metadata import SimulationMetadata, write_simulation_metadata


def test_export_lite_collection_copies_query_files_without_raw_data(tmp_path: Path) -> None:
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

    report = export_lite_collection(source, "grid", tmp_path / "lite")

    copied = report.destination / "collections" / "grid" / "simulations" / "0001"
    assert report.simulation_count == 1
    assert (copied / "metadata.yaml").is_file()
    assert (copied / "config.yaml").is_file()
    assert not (copied / "raw").exists()
    assert (report.destination / "registry.sqlite").is_file()
    assert read_lite_source(report.destination).catalogue_root == source.resolve()
