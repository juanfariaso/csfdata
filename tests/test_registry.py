"""Tests for the rebuildable SQLite catalogue registry."""

from pathlib import Path
import sqlite3

from pytest import CaptureFixture

from csfdata.catalogue.configuration import (
    ConfigurationParameter,
    SimulationConfiguration,
    write_simulation_configuration,
)
from csfdata.catalogue.metadata import SimulationMetadata, write_simulation_metadata
from csfdata.catalogue.registry import (
    find_simulations,
    index_catalogue,
    missing_combinations,
    summarize_catalogue,
)
from csfdata.cli import main


def test_index_catalogue_replaces_one_collection_without_duplicates(tmp_path: Path) -> None:
    catalogue_root = tmp_path / "catalogue"
    simulation_root = (
        catalogue_root / "collections" / "dcaf-grid-v1" / "simulations" / "0001"
    )
    simulation_root.mkdir(parents=True)
    (simulation_root.parent.parent / "collection.yaml").write_text(
        """schema_version: 1
id: dcaf-grid-v1
importer: dcaf
config_schema_version: 1
required_parameters: []
optional_parameters: []
grid_axes:
  tff: [3.0, 4.0]
  sfe: [0.3]
""",
        encoding="utf-8",
    )
    write_simulation_metadata(
        SimulationMetadata(
            simulation_id="0001",
            collection_id="dcaf-grid-v1",
            importer="dcaf",
            source_hostname="trillium",
            source_root=tmp_path / "source",
            source_relative_path=Path("M1000/07"),
            imported_at="2026-09-14T12:00:00Z",
        ),
        simulation_root / "metadata.yaml",
    )
    write_simulation_configuration(
        SimulationConfiguration(
            parameters=(
                ConfigurationParameter("tff", 3.0, "Myr", "explicit"),
                ConfigurationParameter("sfe", 0.3, None, "explicit"),
                ConfigurationParameter("unavailable", None, None, "unknown"),
            ),
            code_parameters=(ConfigurationParameter("label", "test", None, "explicit"),),
        ),
        simulation_root / "config.yaml",
    )

    first_report = index_catalogue(catalogue_root)
    second_report = index_catalogue(catalogue_root, "dcaf-grid-v1")

    assert first_report.simulation_count == 1
    assert first_report.parameter_count == 3
    assert second_report.collection_ids == ("dcaf-grid-v1",)
    summary = summarize_catalogue(catalogue_root)
    assert "Collections: 1" in summary
    assert "dcaf-grid-v1 (dcaf)" in summary
    assert "Simulations: 1" in summary
    assert "tff [Myr]: 1/1; range 3 to 3 (parameters, number)" in summary
    assert "label: 1/1; 1 distinct values (code_parameters, text)" in summary
    assert "Expected combinations: 2" in summary
    assert "Indexed combinations: 1" in summary
    assert "Missing combinations: 1" in summary
    assert missing_combinations(catalogue_root, "dcaf-grid-v1") == (
        {"tff": 4.0, "sfe": 0.3},
    )
    matches = find_simulations(
        catalogue_root,
        collection_id="dcaf-grid-v1",
        filters={"tff": (2.0, 3.0), "sfe": 0.3},
    )
    assert len(matches) == 1
    assert matches[0].simulation_id == "0001"
    assert matches[0].importer == "dcaf"
    assert matches[0].path == simulation_root
    with sqlite3.connect(catalogue_root / "registry.sqlite") as connection:
        assert connection.execute("SELECT COUNT(*) FROM collections").fetchone() == (1,)
        assert connection.execute("SELECT COUNT(*) FROM simulations").fetchone() == (1,)
        assert connection.execute("SELECT COUNT(*) FROM parameter_values").fetchone() == (3,)
        assert connection.execute(
            "SELECT numeric_value, unit FROM parameter_values WHERE name = 'tff'"
        ).fetchone() == (3.0, "Myr")
        assert connection.execute(
            "SELECT text_value, section FROM parameter_values WHERE name = 'label'"
        ).fetchone() == ("test", "code_parameters")


def test_index_catalogue_command_prints_a_summary(
    tmp_path: Path,
    capsys: CaptureFixture[str],
) -> None:
    catalogue_root = tmp_path / "catalogue"
    collection_root = catalogue_root / "collections" / "empty-grid"
    collection_root.mkdir(parents=True)
    (collection_root / "collection.yaml").write_text(
        """schema_version: 1
id: empty-grid
importer: dcaf
config_schema_version: 1
required_parameters: []
optional_parameters: []
grid_axes:
  tff: [1.0]
""",
        encoding="utf-8",
    )
    (collection_root / "simulations").mkdir()

    assert main(["index-catalogue", str(catalogue_root)]) == 0

    output = capsys.readouterr().out
    assert "Indexed collections: empty-grid" in output
    assert "Simulations: 0" in output
    assert f"Registry: {catalogue_root / 'registry.sqlite'}" in output

    assert main(["catalogue-summary", str(catalogue_root)]) == 0

    output = capsys.readouterr().out
    assert "Collections: 1" in output
    assert "empty-grid (dcaf)" in output
    assert "Parameters: none" in output
    assert "Expected combinations: 1" in output
    assert "Missing combinations: 1" in output

    missing_path = tmp_path / "missing.csv"
    assert (
        main(
            [
                "missing-combinations",
                str(catalogue_root),
                "--collection",
                "empty-grid",
                "--output",
                str(missing_path),
            ]
        )
        == 0
    )
    assert missing_path.read_text(encoding="utf-8") == "tff\n1.0\n"
