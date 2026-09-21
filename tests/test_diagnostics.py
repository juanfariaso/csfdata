"""Tests for the collection-level derived-diagnostic contract."""

from pathlib import Path, PurePosixPath

import h5py
import pytest

from csfdata.catalogue import CatalogueSimulation
from csfdata.catalogue.diagnostics import (
    ChoiceDefinition,
    CollectionDiagnostics,
    DiagnosticDefinition,
    DiagnosticField,
    DiagnosticRequirement,
    ScalarDiagnosticResult,
    ScalarValue,
    SimulationScalarDiagnostics,
    collection_diagnostics_path,
    read_collection_diagnostics,
    read_simulation_scalar_diagnostics,
    simulation_scalar_diagnostics_path,
    write_collection_diagnostics,
    write_simulation_scalar_diagnostics,
)


def test_collection_diagnostics_round_trip(tmp_path: Path) -> None:
    """Persist and recover time-series and scalar diagnostic definitions."""
    diagnostics = CollectionDiagnostics(
        choices=(
            ChoiceDefinition(
                "center",
                "Reference centre for position-dependent measurements.",
                ("origin", "stellar_com"),
                "stellar_com",
            ),
        ),
        diagnostics=(
            DiagnosticDefinition(
                "stellar_count",
                "v1",
                "time_series",
                "Number of stars through time.",
                PurePosixPath("derived/diagnostics/stellar_count/v1/series.h5"),
                (DiagnosticField("n_stars", "Number of stellar particles.", None),),
            ),
            DiagnosticDefinition(
                "lagrangian_radii",
                "v1",
                "time_series",
                "Stellar Lagrangian radii through time.",
                PurePosixPath("derived/diagnostics/lagrangian_radii/v1/series.h5"),
                (DiagnosticField("r_l50", "Half-mass radius.", "pc"),),
                ("center",),
            ),
            DiagnosticDefinition(
                "lagrangian_expansion_rates",
                "v1",
                "scalar",
                "Linear fits to Lagrangian-radius evolution.",
                PurePosixPath("derived/scalar_diagnostics.yaml"),
                (DiagnosticField("dRdt", "Expansion rate.", "km/s"),),
                ("center",),
                (
                    DiagnosticRequirement("lagrangian_radii", "v1"),
                    DiagnosticRequirement("stellar_count", "v1"),
                ),
            ),
        ),
    )
    path = collection_diagnostics_path(tmp_path / "example-collection")
    path.parent.mkdir()

    write_collection_diagnostics(diagnostics, path)

    assert read_collection_diagnostics(path) == diagnostics


def test_collection_diagnostics_rejects_unknown_choice() -> None:
    """Require every diagnostic choice to be registered by the collection."""
    diagnostic = DiagnosticDefinition(
        "lagrangian_radii",
        "v1",
        "time_series",
        "Stellar Lagrangian radii through time.",
        PurePosixPath("derived/diagnostics/lagrangian_radii/v1/series.h5"),
        (DiagnosticField("r_l50", "Half-mass radius.", "pc"),),
        ("center",),
    )

    with pytest.raises(ValueError, match="unregistered choices"):
        CollectionDiagnostics(choices=(), diagnostics=(diagnostic,))


def test_simulation_scalar_diagnostics_round_trip(tmp_path: Path) -> None:
    """Persist choice-specific scalar results using their published schema."""
    diagnostics = CollectionDiagnostics(
        choices=(
            ChoiceDefinition(
                "center",
                "Reference centre for position-dependent measurements.",
                ("origin", "stellar_com"),
                "stellar_com",
            ),
        ),
        diagnostics=(
            DiagnosticDefinition(
                "expansion_rate",
                "v1",
                "scalar",
                "Linear expansion-rate fit.",
                PurePosixPath("derived/scalar_diagnostics.yaml"),
                (DiagnosticField("dRdt", "Expansion rate.", "km/s"),),
                ("center",),
            ),
        ),
    )
    scalar_diagnostics = SimulationScalarDiagnostics(
        (
            ScalarDiagnosticResult(
                "expansion_rate",
                "v1",
                (("center", "stellar_com"),),
                (ScalarValue("dRdt", 0.12, "km/s"),),
            ),
        )
    )
    simulation_root = tmp_path / "0001"
    path = simulation_scalar_diagnostics_path(simulation_root)
    path.parent.mkdir(parents=True)

    write_simulation_scalar_diagnostics(scalar_diagnostics, diagnostics, path)

    assert read_simulation_scalar_diagnostics(path, diagnostics) == scalar_diagnostics


def test_catalogue_simulation_exposes_lazy_diagnostic_results(tmp_path: Path) -> None:
    """One simulation provides inspectable, lazy time-series and scalar results."""
    collection_root = tmp_path / "catalogue" / "collections" / "example-grid"
    simulation_root = collection_root / "simulations" / "0001"
    diagnostics = CollectionDiagnostics(
        choices=(
            ChoiceDefinition(
                "center",
                "Reference centre for position-dependent measurements.",
                ("origin", "stellar_com"),
                "stellar_com",
            ),
        ),
        diagnostics=(
            DiagnosticDefinition(
                "lagrangian_radii",
                "v1",
                "time_series",
                "Stellar Lagrangian radii through time.",
                PurePosixPath("derived/diagnostics/lagrangian_radii/v1/series.h5"),
                (
                    DiagnosticField("r_l50", "Half-mass radius.", "pc"),
                    DiagnosticField("n_stars", "Number of stars.", "1"),
                ),
                ("center",),
            ),
            DiagnosticDefinition(
                "expansion_rate",
                "v1",
                "scalar",
                "Linear expansion-rate fit.",
                PurePosixPath("derived/scalar_diagnostics.yaml"),
                (DiagnosticField("dRdt", "Expansion rate.", "km/s"),),
                ("center",),
            ),
        ),
    )
    simulation_root.mkdir(parents=True)
    write_collection_diagnostics(diagnostics, collection_diagnostics_path(collection_root))

    time_series_path = simulation_root / "derived/diagnostics/lagrangian_radii/v1/series.h5"
    time_series_path.parent.mkdir(parents=True)
    with h5py.File(time_series_path, "w") as result_file:
        result_file.attrs["complete"] = True
        result_file.attrs["format_schema_version"] = 2
        result_file.attrs["diagnostic_name"] = "lagrangian_radii"
        result_file.attrs["diagnostic_version"] = 1
        result_file.create_dataset("time", data=(1.0, 2.0))
        choices_group = result_file.create_group("choices")
        center_group = choices_group.create_group("stellar_com")
        center_group.create_dataset("r_l50", data=(1.5, 2.5))
        center_group.create_dataset("n_stars", data=(10, 20))

    scalar_path = simulation_scalar_diagnostics_path(simulation_root)
    write_simulation_scalar_diagnostics(
        SimulationScalarDiagnostics(
            (
                ScalarDiagnosticResult(
                    "expansion_rate",
                    "v1",
                    (("center", "origin"),),
                    (ScalarValue("dRdt", 0.10, "km/s"),),
                ),
                ScalarDiagnosticResult(
                    "expansion_rate",
                    "v1",
                    (("center", "stellar_com"),),
                    (ScalarValue("dRdt", 0.12, "km/s"),),
                ),
            )
        ),
        diagnostics,
        scalar_path,
    )
    simulation = CatalogueSimulation("example-grid", "0001", simulation_root, "dcaf")

    radii = simulation.diagnostics.time_series[("lagrangian_radii", "v1")]
    rates = simulation.diagnostics.scalar[("expansion_rate", "v1")]

    assert list(simulation.diagnostics.time_series) == [("lagrangian_radii", "v1")]
    assert list(simulation.diagnostics.scalar) == [("expansion_rate", "v1")]
    assert radii.complete is True
    assert radii.fields == {"r_l50": "pc", "n_stars": "1"}
    assert radii.choices == {"center": ("origin", "stellar_com")}
    assert radii.available_choices == ({"center": "stellar_com"},)
    assert radii.read({"center": "stellar_com"}, ("r_l50",))["time"].tolist() == [1.0, 2.0]
    assert radii.read({"center": "stellar_com"}, ("r_l50",))["r_l50"].tolist() == [1.5, 2.5]
    assert list(radii.iter_data(("n_stars",)))[0][1]["n_stars"].tolist() == [10, 20]
    assert rates.complete is True
    assert rates.available_choices == (
        {"center": "origin"},
        {"center": "stellar_com"},
    )
    assert rates.read({"center": "stellar_com"}) == {"dRdt": 0.12}
    assert "available_choices" in repr(simulation.diagnostics)
