"""Base interface for read-only simulation-format adapters."""

from __future__ import annotations

from abc import ABC, abstractmethod
from pathlib import Path

from csfdata.catalogue.collection import CollectionConfiguration
from csfdata.catalogue.configuration import SimulationConfiguration


class SimulationAdapter(ABC):
    """Define the read-only and import-preparation contract for one run.

    Each adapter represents one candidate run. It identifies the run, exposes
    its raw files, reports its final model time in canonical Myr, and returns
    validation issues without changing source files. It also converts its own
    source format into a canonical catalogue configuration.
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
    def snapshot_times(self) -> dict[Path, float]:
        """Return every primary snapshot path mapped to its model time.

        Returns:
            Dictionary from paths relative to this adapter's ``run_root`` to
            exact model times in canonical ``Myr``.

        Raises:
            ValueError: If snapshot paths or their times cannot be mapped
                reliably.
        """

    @abstractmethod
    def snapshot_paths(self) -> tuple[Path, ...]:
        """Return primary snapshot files in checkpoint order.

        Returns:
            Paths to primary snapshot files, ordered as their checkpoints occur
                in the simulation output.
        """

    @abstractmethod
    def snapshot_time(self, snapshot_path: Path) -> float | None:
        """Return the model time stored in one snapshot when available.

        Args:
            snapshot_path: Path returned by ``snapshot_paths()``.

        Returns:
            The snapshot's model time in canonical ``Myr``, or ``None`` when
                the simulation format does not store it accessibly.
        """

    @abstractmethod
    def validate_simulation(self, detailed: bool = False) -> tuple[str, ...]:
        """Inspect the run for format-specific structural or scientific issues.

        Args:
            detailed: Whether to perform potentially expensive validation of
                primary output contents.

        Returns:
            A tuple of human-readable issue descriptions. An empty tuple means
                the adapter found no issue under its documented validation rules.

        Notes:
            Validation is read-only. It reports evidence for an import decision;
            it does not repair, remove, or copy source files.
        """

    @abstractmethod
    def raw_data_paths(self) -> tuple[Path, ...]:
        """Return raw source files that are eligible for copying.

        Returns:
            Complete source-file payload in deterministic order. Derived
                artifacts and scheduler markers must be omitted.

        Notes:
            A code-specific adapter decides which filenames are scientific
            source inputs or outputs. Generic copy code does not know them.
        """

    @abstractmethod
    def build_configuration(self) -> SimulationConfiguration:
        """Build this run's canonical top-level catalogue configuration.

        Returns:
            Canonical configuration derived from source files without changing
            those files.
        """

    def prepare_configuration(
        self,
        collection: CollectionConfiguration,
    ) -> SimulationConfiguration:
        """Build configuration and check the destination collection requirements.

        Args:
            collection: Destination collection whose required parameters must
                be known for this simulation.

        Returns:
            The canonical configuration when collection requirements are met.

        Raises:
            ValueError: If a required collection parameter is absent, unknown,
                or not applicable for this simulation.
        """
        configuration = self.build_configuration()
        missing = configuration.missing_required_parameters(
            collection.required_parameters
        )
        if missing:
            names = ", ".join(missing)
            raise ValueError(
                f"Simulation {self.run_root} does not provide required parameters: {names}."
            )
        return configuration
