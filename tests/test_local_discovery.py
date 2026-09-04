from pathlib import Path

from csfdata.adapters.dcaf import DcafAdapter
from csfdata.discovery.local import LocalGridDiscoverer


def test_local_discoverer_reports_valid_and_invalid_dcaf_runs(tmp_path: Path) -> None:
    grid_root = tmp_path / "grid"
    valid_run = grid_root / "valid"
    invalid_run = grid_root / "invalid"
    _write_dcaf_run(valid_run, final_time=15.0)
    _write_dcaf_run(invalid_run, final_time=10.0)
    (grid_root / "unrelated" / "nested").mkdir(parents=True)

    report = LocalGridDiscoverer(grid_root, DcafAdapter).discover()

    assert tuple(simulation.run_root for simulation in report.simulations) == (
        invalid_run,
        valid_run,
    )
    assert tuple(simulation.run_root for simulation in report.valid_simulations) == (valid_run,)
    assert tuple(simulation.run_root for simulation in report.invalid_simulations) == (invalid_run,)


def _write_dcaf_run(run_root: Path, final_time: float) -> None:
    output_root = run_root / "dcaf_output"
    output_root.mkdir(parents=True)
    (run_root / "config.yaml").write_text("t_end: 15.0 Myr\n", encoding="utf-8")
    (run_root / "background_gas.dat").write_text(
        f"0.0 5000\n{final_time} 60000\n",
        encoding="utf-8",
    )
    (output_root / "stars_000.amuse").touch()
