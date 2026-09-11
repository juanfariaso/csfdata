from pathlib import Path

import pytest

from csfdata.catalogue.configuration import (
    ConfigurationParameter,
    SimulationConfiguration,
    extract_parameters,
    read_simulation_configuration,
    write_simulation_configuration,
)


def test_simulation_configuration_round_trips_through_yaml(tmp_path: Path) -> None:
    configuration = SimulationConfiguration(
        parameters=(
            ConfigurationParameter("initial_mass", 1000.0, "Msun", "explicit"),
            ConfigurationParameter("tff", 3.0, "Myr", "inferred", "From density."),
        ),
        code_parameters=(
            ConfigurationParameter("eta_sigma", 0.3, None, "explicit"),
        ),
    )
    path = tmp_path / "config.yaml"

    write_simulation_configuration(configuration, path)

    assert read_simulation_configuration(path) == configuration


def test_missing_required_parameters_includes_unknown_and_absent_values() -> None:
    configuration = SimulationConfiguration(
        parameters=(
            ConfigurationParameter("initial_mass", 1000.0, "Msun", "explicit"),
            ConfigurationParameter("tff", None, "Myr", "unknown"),
        )
    )

    assert configuration.missing_required_parameters(("initial_mass", "tff", "sfe")) == (
        "tff",
        "sfe",
    )


def test_extract_parameters_reads_all_supported_yaml_scalars(tmp_path: Path) -> None:
    path = tmp_path / "source-config.yaml"
    path.write_text(
        "seed_index: 4\ntff: 3.0 Myr\nRcl: 10.0 parsec\nt_ge: null\n",
        encoding="utf-8",
    )

    parameters = extract_parameters(path)

    assert parameters == (
        ConfigurationParameter("seed_index", 4, None, "explicit"),
        ConfigurationParameter("tff", 3.0, "Myr", "explicit"),
        ConfigurationParameter("Rcl", 10.0, "pc", "explicit"),
        ConfigurationParameter("t_ge", None, None, "unknown"),
    )


def test_extract_parameters_rejects_unsupported_source_format(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="Unsupported configuration format"):
        extract_parameters(tmp_path / "source-config.toml", format="toml")
