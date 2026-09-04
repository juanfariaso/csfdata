from pathlib import Path

from csfdata.adapters.dcaf import DcafAdapter


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
    snapshot.touch()
    (resumed_output_root / "stars_021.amuse").touch()
    derived = run_root / "derived_data" / "summary.csv"
    derived.parent.mkdir()
    derived.touch()

    adapter = DcafAdapter(run_root)

    assert adapter.is_simulation()
    assert adapter.configuration_path() == run_root / "config.yaml"
    assert adapter.read_configuration()["seed_index"] == 0
    assert adapter.model_time() == 15.1
    assert adapter.validate_simulation() == ()
    assert tuple(adapter.raw_data_paths()) == (
        run_root / "background_gas.dat",
        run_root / "background_gas_1.dat",
        snapshot,
        resumed_output_root / "stars_021.amuse",
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
    (output_root / "stars_020.amuse").touch()
    (resumed_output_root / "stars_021.amuse").touch()

    issues = DcafAdapter(run_root).validate_simulation()

    assert "Missing background-gas segment(s): 1." in issues
    assert "Missing output segment(s): 1." in issues
    assert any("differs from configured t_end" in issue for issue in issues)
    assert DcafAdapter(run_root, tolerance_myr=5.0).validate_simulation()[:2] == issues[:2]
