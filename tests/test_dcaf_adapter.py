from pathlib import Path

import h5py

from csfdata.adapters.dcaf import DcafAdapter


_MYR_IN_SECONDS = 365.25 * 24.0 * 60.0 * 60.0 * 1.0e6


def test_dcaf_adapter_reads_resumed_background_gas_segments(tmp_path: Path) -> None:
    run_root = tmp_path / "run"
    output_root = run_root / "dcaf_output"
    resumed_output_root = run_root / "dcaf_output_1"
    output_root.mkdir(parents=True)
    resumed_output_root.mkdir()
    (run_root / "config.yaml").write_text("seed_index: 0\nt_end: 15.0 Myr\n", encoding="utf-8")
    (run_root / "background_gas.dat").write_text(
        "# Time [Myr] mtot [MSun]\n0.0 5000\n10.0 55000\n",
        encoding="utf-8",
    )
    (run_root / "background_gas_1.dat").write_text("10.0 55000\n15.1 60000\n", encoding="utf-8")
    snapshot = output_root / "stars_020.amuse"
    _write_snapshot(snapshot, 0.0)
    _write_snapshot(output_root / "stars_021.amuse", 10.0)
    _write_snapshot(resumed_output_root / "stars_022.amuse", 10.0)
    _write_snapshot(resumed_output_root / "stars_023.amuse", 15.1)
    derived = run_root / "derived_data" / "summary.csv"
    derived.parent.mkdir()
    derived.touch()

    adapter = DcafAdapter(run_root)

    assert adapter.is_simulation()
    assert adapter.configuration_path() == run_root / "config.yaml"
    assert adapter.read_configuration()["seed_index"] == 0
    assert adapter.model_time() == 15.1
    assert adapter.checkpoint_times() == (0.0, 10.0, 10.0, 15.1)
    assert adapter.snapshot_paths() == (
        snapshot,
        output_root / "stars_021.amuse",
        resumed_output_root / "stars_022.amuse",
        resumed_output_root / "stars_023.amuse",
    )
    assert adapter.snapshot_time(snapshot) == 0.0
    assert adapter.validate_simulation() == ()
    assert tuple(adapter.raw_data_paths()) == (
        run_root / "background_gas.dat",
        run_root / "background_gas_1.dat",
        snapshot,
        output_root / "stars_021.amuse",
        resumed_output_root / "stars_022.amuse",
        resumed_output_root / "stars_023.amuse",
    )
    assert derived not in adapter.raw_data_paths()


def test_dcaf_adapter_reports_time_mismatch_and_missing_segment(tmp_path: Path) -> None:
    run_root = tmp_path / "run"
    output_root = run_root / "dcaf_output"
    resumed_output_root = run_root / "dcaf_output_2"
    output_root.mkdir(parents=True)
    resumed_output_root.mkdir()
    (run_root / "config.yaml").write_text("t_end: 15.0 Myr\n", encoding="utf-8")
    (run_root / "background_gas.dat").write_text("0.0 5000\n10.0 55000\n", encoding="utf-8")
    (run_root / "background_gas_2.dat").write_text("20.0 60000\n", encoding="utf-8")
    _write_snapshot(output_root / "stars_020.amuse", 0.0)
    _write_snapshot(output_root / "stars_021.amuse", 10.0)
    _write_snapshot(resumed_output_root / "stars_022.amuse", 20.0)

    issues = DcafAdapter(run_root).validate_simulation()

    assert "Missing background-gas segment(s): 1." in issues
    assert "Missing output segment(s): 1." in issues
    assert any("differs from configured t_end" in issue for issue in issues)
    assert DcafAdapter(run_root, tolerance_myr=5.0).validate_simulation()[:2] == issues[:2]


def test_dcaf_adapter_reports_precise_mismatches_and_duplicate_segments(tmp_path: Path) -> None:
    run_root = tmp_path / "run"
    run_root.mkdir()
    (run_root / "config.yaml").write_text("t_end: 2.0 Myr\n", encoding="utf-8")
    _write_segment(run_root, 0, (0.0, 1.0), (0.0, 1.0))
    _write_segment(run_root, 1, (0.0, 1.0), (0.0, 1.0))
    _write_segment(run_root, 2, (2.0,), (2.5,))

    issues = DcafAdapter(run_root).validate_simulation()

    assert (
        "Segment 1 is fully duplicated by segment 0: checkpoint and snapshot time "
        "sequences from 0 to 1 Myr are identical."
    ) in issues
    assert (
        "Segment 2: background-gas record background_gas_2.dat line 1 at 2 Myr "
        "does not match next snapshot dcaf_output_2/stars_000.amuse at 2.5 Myr."
    ) in issues


def _write_segment(
    run_root: Path,
    segment: int,
    gas_times: tuple[float, ...],
    snapshot_times: tuple[float, ...],
) -> None:
    gas_name = "background_gas.dat" if segment == 0 else f"background_gas_{segment}.dat"
    output_name = "dcaf_output" if segment == 0 else f"dcaf_output_{segment}"
    (run_root / gas_name).write_text(
        "".join(f"{time} 5000\n" for time in gas_times),
        encoding="utf-8",
    )
    output_root = run_root / output_name
    output_root.mkdir()
    for index, time in enumerate(snapshot_times):
        _write_snapshot(output_root / f"stars_{index:03d}.amuse", time)


def _write_snapshot(path: Path, time_myr: float) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with h5py.File(path, "w") as snapshot_file:
        group = snapshot_file.create_group("data/0000000001")
        group.attrs["model_time"] = time_myr * _MYR_IN_SECONDS
