from pathlib import Path

import h5py
from pytest import CaptureFixture

from csfdata.cli import main


_MYR_IN_SECONDS = 365.25 * 24.0 * 60.0 * 60.0 * 1.0e6


def test_discover_command_reports_grid_status(
    tmp_path: Path,
    capsys: CaptureFixture[str],
) -> None:
    grid_root = tmp_path / "grid"
    _write_dcaf_run(grid_root / "valid", final_time=15.0)
    _write_dcaf_run(grid_root / "invalid", final_time=10.0)

    exit_code = main(["discover", str(grid_root)])

    output = capsys.readouterr().out
    assert exit_code == 0
    assert f"Grid: {grid_root}" in output
    assert "Simulations found: 2" in output
    assert "Valid: 1" in output
    assert "Invalid: 1" in output
    assert f"- {grid_root / 'invalid'}" in output
    assert "Final model time" in output
    assert "configured t_end" in output


def test_validate_command_writes_a_clean_report(
    tmp_path: Path,
    capsys: CaptureFixture[str],
) -> None:
    grid_root = tmp_path / "grid"
    _write_dcaf_run(grid_root / "valid", final_time=15.0)
    _write_dcaf_run(grid_root / "invalid", final_time=10.0)
    report_path = tmp_path / "validation-report.txt"

    exit_code = main(["validate", str(grid_root), "--report", str(report_path)])

    output = capsys.readouterr().out
    report = report_path.read_text(encoding="utf-8")
    assert exit_code == 0
    assert f"Report saved: {report_path}" in output
    assert report.startswith(f"D-CAF validation report for: {grid_root}\n")
    assert f"OK: {grid_root / 'valid'}" in report
    assert f"ISSUE: {grid_root / 'invalid'}" in report
    assert "Checked: 2" in report
    assert "No issues: 1" in report
    assert "With issues: 1" in report


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


def _write_snapshot(path: Path, time_myr: float) -> None:
    with h5py.File(path, "w") as snapshot_file:
        group = snapshot_file.create_group("data/0000000001")
        group.attrs["model_time"] = time_myr * _MYR_IN_SECONDS
