from pathlib import Path

from pytest import CaptureFixture

from csfdata.cli import main


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


def _write_dcaf_run(run_root: Path, final_time: float) -> None:
    output_root = run_root / "dcaf_output"
    output_root.mkdir(parents=True)
    (run_root / "config.yaml").write_text("t_end: 15.0 Myr\n", encoding="utf-8")
    (run_root / "background_gas.dat").write_text(
        f"0.0 5000\n{final_time} 60000\n",
        encoding="utf-8",
    )
    (output_root / "stars_000.amuse").touch()
