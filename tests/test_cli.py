from pathlib import Path

import h5py
from pytest import CaptureFixture
import yaml

from csfdata.cli import main


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
    assert report["valid_simulations"] == ["valid"]
    assert "invalid" in report["simulations_with_issues"]
    assert any(
        "differs from configured t_end" in issue
        for issue in report["simulations_with_issues"]["invalid"]
    )


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
