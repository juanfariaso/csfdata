"""Tests for the collection-level derived-diagnostic contract."""

from pathlib import Path, PurePosixPath

import pytest

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
