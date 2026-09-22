from pathlib import Path

import h5py
from pytest import CaptureFixture
import yaml

import csfdata.cli as cli
from csfdata.catalogue.snapshots import SnapshotTimeRefreshReport
from csfdata.cli import main, run_analysis, validate_grid, validation_report_data
from csfdata.importer.validation import ValidatedSource


_MYR_IN_SECONDS = 365.25 * 24.0 * 60.0 * 60.0 * 1.0e6


def test_validate_command_writes_a_portable_yaml_report(
    tmp_path: Path,
    capsys: CaptureFixture[str],
) -> None:
    grid_root = tmp_path / "grid"
    _write_dcaf_run(grid_root / "valid", final_time=15.0)
    _write_dcaf_run(grid_root / "invalid", final_time=10.0)
    report_path = tmp_path / "validation-report.yaml"

    exit_code = main(["validate", str(grid_root), "--report", str(report_path)])

    output = capsys.readouterr().out
    report = yaml.safe_load(report_path.read_text(encoding="utf-8"))
    assert exit_code == 0
    assert "Validated: 2 simulations" in output
    assert "Valid for transfer: 1" in output
    assert "With issues: 1" in output
    assert f"Report saved: {report_path}" in output
    assert report["schema_version"] == 1
    assert report["source"]["root"] == str(grid_root.resolve())
    assert report["source"]["hostname"]
    assert report["summary"] == {
        "total_simulations": 2,
        "valid_simulations": 1,
        "simulations_with_issues": 1,
    }
    assert report["valid_simulations"] == ["valid"]
    assert "invalid" in report["simulations_with_issues"]
    assert any(
        "differs from configured t_end" in issue
        for issue in report["simulations_with_issues"]["invalid"]
    )


def test_public_validation_functions_work_without_a_cli_parser(tmp_path: Path) -> None:
    grid_root = tmp_path / "grid"
    _write_dcaf_run(grid_root / "valid", final_time=15.0)
    report_path = tmp_path / "validation-report.yaml"

    assert validate_grid(grid_root, report_path) == 0
    assert validation_report_data(grid_root, ((grid_root / "valid", ()),))[
        "valid_simulations"
    ] == ["valid"]


def test_analysis_command_forwards_arguments_to_the_installed_add_on(
    monkeypatch,
) -> None:
    received: list[str] = []

    def analysis_command(arguments: list[str] | None) -> int:
        received.extend(arguments or [])
        return 7

    monkeypatch.setattr(cli, "load_analysis", lambda name: analysis_command)

    assert main(["analysis", "diagnostics"]) == 7
    assert received == ["diagnostics"]
    assert run_analysis(["compute", "simulation", "lagrangian_radii"]) == 7
    assert received == [
        "diagnostics",
        "compute",
        "simulation",
        "lagrangian_radii",
    ]


def test_import_command_creates_a_local_catalogue_entry(
    tmp_path: Path,
    capsys: CaptureFixture[str],
) -> None:
    source_root = tmp_path / "source-grid"
    run_root = source_root / "M1000" / "tff3.0" / "07"
    run_root.mkdir(parents=True)
    (run_root / "config.yaml").write_text("tff: 3.0 Myr\n", encoding="utf-8")
    output_root = run_root / "dcaf_output"
    output_root.mkdir()
    _write_snapshot(output_root / "stars_000.amuse", 0.0)
    report_path = tmp_path / "validation-report.yaml"
    report_path.write_text(
        yaml.safe_dump(
            {
                "schema_version": 1,
                "source": {"hostname": "trillium", "root": str(source_root)},
                "summary": {
                    "total_simulations": 1,
                    "valid_simulations": 1,
                    "simulations_with_issues": 0,
                },
                "valid_simulations": ["M1000/tff3.0/07"],
                "simulations_with_issues": {},
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )
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
    catalogue_root = tmp_path / "catalogue"
    catalogue_root.mkdir()

    dry_run_exit_code = main(
        [
            "import",
            str(report_path),
            str(catalogue_root),
            "--collection",
            str(collection_path),
            "--dry-run",
        ]
    )

    dry_run_output = capsys.readouterr().out
    assert dry_run_exit_code == 0
    assert "Dry run: 1 simulations ready to import" in dry_run_output
    assert not (catalogue_root / "collections").exists()

    exit_code = main(
        [
            "import",
            str(report_path),
            str(catalogue_root),
            "--collection",
            str(collection_path),
        ]
    )

    output = capsys.readouterr().out
    assert exit_code == 0
    assert "Imported: 1 simulations" in output
    assert (
        catalogue_root
        / "collections"
        / "dcaf-tff-grid-v1"
        / "snapshot-times.yaml"
    ).is_file()
    assert (
        catalogue_root
        / "collections"
        / "dcaf-tff-grid-v1"
        / "simulations"
        / "0001"
        / "metadata.yaml"
    ).is_file()


def test_refresh_snapshot_times_without_collection_refreshes_every_collection(
    tmp_path: Path,
    capsys: CaptureFixture[str],
    monkeypatch,
) -> None:
    """Refresh every collection when the command receives no collection filter."""
    catalogue = tmp_path / "catalogue"
    for collection_id in ("first", "second"):
        (catalogue / "collections" / collection_id).mkdir(parents=True)
    refreshed: list[str] = []

    def refresh(
        root: Path,
        collection_id: str,
        progress=None,
    ) -> SnapshotTimeRefreshReport:
        refreshed.append(collection_id)
        return SnapshotTimeRefreshReport(
            catalogue / "collections" / collection_id / "snapshot-times.yaml",
            1,
            2,
            {},
        )

    monkeypatch.setattr(cli, "refresh_snapshot_times", refresh)

    assert main(["refresh-snapshot-times", str(catalogue)]) == 0
    assert refreshed == ["first", "second"]
    assert "Collection: first" in capsys.readouterr().out


def _write_dcaf_run(run_root: Path, final_time: float) -> None:
    output_root = run_root / "dcaf_output"
    output_root.mkdir(parents=True)
    (run_root / "config.yaml").write_text("t_end: 15.0 Myr\n", encoding="utf-8")
    (run_root / "background_gas.dat").write_text(
        f"0.0 5000\n{final_time} 60000\n",
        encoding="utf-8",
    )
    _write_snapshot(output_root / "stars_000.amuse", 0.0)
    _write_snapshot(output_root / "stars_001.amuse", final_time)


def _write_snapshot(path: Path, time: float) -> None:
    with h5py.File(path, "w") as snapshot_file:
        group = snapshot_file.create_group("data/0000000001")
        group.attrs["model_time"] = time * _MYR_IN_SECONDS
