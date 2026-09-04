"""Common interface for local and remote simulation-grid discovery."""

from __future__ import annotations

from abc import ABC, abstractmethod

from csfdata.discovery.report import DiscoveryReport


class GridDiscoverer(ABC):
    """Produce a read-only report of simulations found in one grid.

    Implementations decide how to access and traverse their source. A local
    discoverer may walk directories, while a future remote discoverer may use
    SSH. Both must return the same ``DiscoveryReport`` structure.
    """

    @abstractmethod
    def discover(self) -> DiscoveryReport:
        """Discover recognized simulation runs and validate each one.

        Returns:
            A report containing recognized simulations and their validation
                issues. Unrelated source folders are omitted.

        Notes:
            Discovery is read-only. It must not copy, modify, register, or
            delete simulation data.
        """
