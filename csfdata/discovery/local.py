"""Discovery of simulation runs stored in a local directory tree."""

from __future__ import annotations

from pathlib import Path

from csfdata.adapters.base import SimulationAdapter
from csfdata.discovery.base import GridDiscoverer
from csfdata.discovery.report import DiscoveredSimulation, DiscoveryReport


class LocalGridDiscoverer(GridDiscoverer):
    """Discover simulations below a local filesystem root.

    Args:
        root: Local directory tree to scan.
        adapter: Simulation adapter class used to inspect each candidate
            directory.
    """

    def __init__( self, root: Path, adapter: type[SimulationAdapter],) -> None:

        if not isinstance(adapter, type) or not issubclass(adapter, SimulationAdapter):
            raise TypeError("adapter must inherit from SimulationAdapter.")

        self.root = root
        self.adapter = adapter

    def discover(self) -> DiscoveryReport:
        """Scan the local tree and return recognized simulation runs.

        Returns:
            A report containing each adapter-recognized run and its validation
                issues, in deterministic path order.

        Raises:
            NotADirectoryError: If ``root`` is not an existing directory.

        Notes:
            Every directory is presented to the adapter, but only directories
            for which ``is_simulation()`` returns ``True`` enter the report.
        """
        if not self.root.is_dir():
            raise NotADirectoryError(f"Discovery root is not a directory: {self.root}")

        simulations: list[DiscoveredSimulation] = []
        candidate_paths = (
            self.root,
            *sorted(path for path in self.root.rglob("*") if path.is_dir()),
        )
        for candidate_path in candidate_paths:
            simulation = self.adapter(candidate_path)
            if not simulation.is_simulation():
                continue
            simulations.append(
                DiscoveredSimulation(
                    run_root=candidate_path,
                    validation_issues=simulation.validate_simulation(),
                )
            )

        return DiscoveryReport(root=self.root, simulations=tuple(simulations))
