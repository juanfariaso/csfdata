"""Base interface for read-only simulation-format adapters."""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Iterable
from pathlib import Path
from typing import Any

class SimulationAdapter(ABC):
    """Define the read-only contract for one simulation run.

    Each adapter represents one candidate run. It identifies the run, exposes
    its authoritative configuration and raw output files, reports its final
    model time in canonical Myr, and returns validation issues without changing
    any source files.
    """

    @abstractmethod
    def __init__(self, run_root: Path) -> None:
        """Initialize an adapter for one candidate simulation run.

        Args:
            run_root: Path supplied by the caller for the candidate run.

        Notes:
            An implementation may retain this path, transform it, or obtain its
            state in another way. All public inspection methods operate on the
            adapter instance and take no run-path argument.
        """

    @abstractmethod
    def is_simulation(self) -> bool:
        """Decide whether the candidate satisfies this format's run criteria.

        Returns:
            ``True`` only when the adapter has sufficient format-specific
                evidence that the candidate is one simulation run. ``False``
                means it must not be imported as that format.
        """

    @abstractmethod
    def configuration_path(self) -> Path:
        """Locate the authoritative scientific configuration.

        Returns:
            The expected path of the configuration file. The returned path may
                not exist when ``is_simulation()`` is ``False``.
        """

    @abstractmethod
    def read_configuration(self) -> dict[str, Any]:
        """Read the authoritative configuration without normalizing its meaning.

        Returns:
            A dictionary containing the parsed configuration in the simulation
                format's own field names and values.

        Notes:
            Adapters must not silently infer, replace, or rewrite scientific
            parameters while reading the raw configuration.
        """

    @abstractmethod
    def model_time(self) -> float | None:
        """Report the final trustworthy simulated time.

        Returns:
            Final model time in canonical ``Myr``, or ``None`` when it cannot
                be determined from trustworthy source data.

        Notes:
            An adapter may convert an explicit source unit to Myr. It must not
            guess a missing or ambiguous unit.
        """

    @abstractmethod
    def validate_simulation(self) -> tuple[str, ...]:
        """Inspect the run for format-specific structural or scientific issues.

        Returns:
            A tuple of human-readable issue descriptions. An empty tuple means
                the adapter found no issue under its documented validation rules.

        Notes:
            Validation is read-only. It reports evidence for an import decision;
            it does not repair, remove, or copy source files.
        """

    @abstractmethod
    def raw_data_paths(self) -> Iterable[Path]:
        """List raw simulation-output files that are eligible for copying.

        Returns:
            Paths to source snapshots, time series, and other primary output
                files in a deterministic order. Derived artifacts and scheduler
                markers must be omitted.

        Notes:
            The authoritative configuration is supplied separately by
            ``configuration_path()`` so an importer can preserve it alongside
            the raw outputs.
        """
