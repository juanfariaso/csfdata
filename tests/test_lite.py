"""Tests for collection-scoped lite catalogue imports."""

from pathlib import Path

import h5py

from csfdata.catalogue.configuration import (
    ConfigurationParameter,
    SimulationConfiguration,
    write_simulation_configuration,
)
from csfdata.catalogue.diagnostics import (
    ChoiceDefinition,
    CollectionDiagnostics,
    DiagnosticDefinition,
    DiagnosticField,
    write_collection_diagnostics,
)
from csfdata.catalogue.lite import (
    file_sha256,
    import_lite_collection,
    read_derived_selection,
    read_lite_source,
    synchronize_selected_time_series,
)
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
    assert (report.destination / "collections" / "grid" / "snapshot-times.sqlite").is_file()
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


def test_import_lite_collection_filters_selected_time_series(tmp_path: Path) -> None:
    """Selection keeps requested groups and fields while particles remain opt-in."""
    source = tmp_path / "full"
    simulation = source / "collections" / "grid" / "simulations" / "0001"
    simulation.mkdir(parents=True)
    collection = simulation.parent.parent
    (collection / "collection.yaml").write_text(
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
        SimulationMetadata(
            "0001",
            "grid",
            "dcaf",
            "host",
            tmp_path / "source",
            Path("run"),
            "2026-01-01T00:00:00Z",
        ),
        simulation / "metadata.yaml",
    )
    write_simulation_configuration(
        SimulationConfiguration(
            (ConfigurationParameter("tff", 1.0, "Myr", "explicit"),),
            (),
        ),
        simulation / "config.yaml",
    )
    diagnostics = CollectionDiagnostics(
        (
            ChoiceDefinition(
                "center",
                "Reference centre.",
                ("origin", "stellar_com"),
                "stellar_com",
            ),
        ),
        (
            DiagnosticDefinition(
                "test_series",
                "v1",
                "time_series",
                "Test evolving values.",
                Path("derived/diagnostics/test_series/v1/series.h5"),
                (
                    DiagnosticField("radius", "Test radius.", "pc"),
                    DiagnosticField("count", "Test count.", "1"),
                ),
                ("center",),
            ),
        ),
    )
    write_collection_diagnostics(diagnostics, collection / "diagnostics.yaml")
    source_series = (
        simulation / "derived" / "diagnostics" / "test_series" / "v1" / "series.h5"
    )
    source_series.parent.mkdir(parents=True)
    with h5py.File(source_series, "w") as output:
        output.attrs["complete"] = True
        output.attrs["format_schema_version"] = 2
        output.attrs["diagnostic_name"] = "test_series"
        output.attrs["diagnostic_version"] = 1
        output.attrs["particle_series_file"] = "particles.h5"
        output.attrs["series_id"] = "series-1"
        output.create_dataset("time", data=[0.0, 1.0])
        output.create_dataset("snapshot_id", data=[b"s0", b"s1"])
        groups = output.create_group("choices")
        for center, offset in (("origin", 0.0), ("stellar_com", 10.0)):
            group = groups.create_group(center)
            group.create_dataset("radius", data=[offset + 1.0, offset + 2.0])
            group.create_dataset("count", data=[1, 2])
    source_particles = source_series.with_name("particles.h5")
    with h5py.File(source_particles, "w") as output:
        output.attrs["complete"] = True
        output.attrs["format_schema_version"] = 1
        output.attrs["diagnostic_name"] = "test_series"
        output.attrs["diagnostic_version"] = 1
        output.attrs["series_id"] = "series-1"
        groups = output.create_group("choices")
        for center in ("origin", "stellar_com"):
            group = groups.create_group(center)
            group.create_dataset("snapshot_id", data=[b"s0", b"s1"])
            group.create_dataset("particle_key", data=[1, 2])
            group.create_dataset("bound", data=[1, 0])
            group.create_dataset("energy", data=[-1.0, 1.0])

    index_catalogue(source)
    refresh_snapshot_times(source, "grid")
    selection_path = tmp_path / "selection.yaml"
    selection_path.write_text(
        """schema_version: 1
collection: grid
time_series:
  test_series:
    choices:
      center: [stellar_com]
    fields: [radius]
""",
        encoding="utf-8",
    )
    selection = read_derived_selection(selection_path)
    lite = tmp_path / "lite"

    import_lite_collection(source, None, lite, selection=selection)

    copied_series = (
        lite
        / "collections"
        / "grid"
        / "simulations"
        / "0001"
        / "derived"
        / "diagnostics"
        / "test_series"
        / "v1"
        / "series.h5"
    )
    with h5py.File(copied_series, "r") as copied:
        assert copied.attrs["csfdata_subset"] == True
        assert "particle_series_file" not in copied.attrs
        assert tuple(copied["choices"]) == ("stellar_com",)
        assert tuple(copied["choices/stellar_com"]) == ("radius",)
        assert copied["choices/stellar_com/radius"][:].tolist() == [11.0, 12.0]
    assert not copied_series.with_name("particles.h5").exists()
    assert (lite / "derived-selection.yaml").is_file()

    # Exercise the same selective rsync staging used for an SSH source without
    # requiring a network host in the test environment.
    synchronize_selected_time_series(
        None,
        f"{collection}/",
        lite / "collections" / "grid",
        selection,
    )

    selection_path.write_text(
        """schema_version: 1
collection: grid
time_series:
  test_series:
    choices:
      center: [stellar_com]
    fields: [radius]
    particle_fields: [bound]
""",
        encoding="utf-8",
    )
    import_lite_collection(
        source,
        None,
        lite,
        selection=read_derived_selection(selection_path),
    )

    with h5py.File(copied_series.with_name("particles.h5"), "r") as copied:
        assert copied.attrs["csfdata_subset"] == True
        assert tuple(copied["choices"]) == ("stellar_com",)
        assert tuple(copied["choices/stellar_com"]) == (
            "bound",
            "particle_key",
            "snapshot_id",
        )
