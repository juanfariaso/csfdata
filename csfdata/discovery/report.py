"""Shared result models for simulation-grid discovery."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class DiscoveredSimulation:
    """One adapter-recognized simulation run found during discovery.

    Args:
        run_root: Root directory of the recognized simulation run.
        validation_issues: Validation messages reported by the selected adapter.
    """

    run_root: Path
    validation_issues: tuple[str, ...]

    @property
    def is_valid(self) -> bool:
        """Return whether the adapter found no validation issues.

        Returns:
            ``True`` when ``validation_issues`` is empty; otherwise, ``False``.
        """
        return not self.validation_issues


@dataclass(frozen=True)
class DiscoveryReport:
    """The recognized simulations found below one discovery root.

    Args:
        root: Source root that was scanned.
        simulations: Adapter-recognized simulation runs below ``root``.

    Notes:
        Unrelated folders are not included. A recognized run with validation
        issues remains in the report so that an import decision is traceable.
    """

    root: Path
    simulations: tuple[DiscoveredSimulation, ...]

    @property
    def valid_simulations(self) -> tuple[DiscoveredSimulation, ...]:
        """Return recognized simulations with no validation issues.

        Returns:
            Valid simulations in the report's original discovery order.
        """
        return tuple(simulation for simulation in self.simulations if simulation.is_valid)

    @property
    def invalid_simulations(self) -> tuple[DiscoveredSimulation, ...]:
        """Return recognized simulations with one or more validation issues.

        Returns:
            Invalid simulations in the report's original discovery order.
        """
        return tuple(simulation for simulation in self.simulations if not simulation.is_valid)
