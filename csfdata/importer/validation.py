"""Reading and validating YAML reports produced by ``csfdata validate``."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import yaml


_VALIDATION_REPORT_SCHEMA_VERSION = 1


@dataclass(frozen=True)
class ValidatedSource:
    """One complete source grid as approved by a validation report.

    Args:
        hostname: Hostname of the machine on which validation ran.
        root: Absolute source grid path recorded by validation.
        valid_simulation_paths: Approved simulation paths relative to ``root``.

    Notes:
        This object represents the whole source grid, not one simulation and
        not a destination collection. Each path in ``valid_simulation_paths``
        represents one simulation that may later receive an import ID.
    """

    hostname: str
    root: Path
    valid_simulation_paths: tuple[Path, ...]

    def __post_init__(self) -> None:
        """Validate the source location and approved relative paths.

        Raises:
            ValueError: If a source field is invalid or approved paths are not
                unique, relative, and safely contained below the source root.
        """
        if not self.hostname:
            raise ValueError("hostname must not be empty.")
        if not self.root.is_absolute():
            raise ValueError("root must be absolute.")

        if len(self.valid_simulation_paths) != len(set(self.valid_simulation_paths)):
            raise ValueError("valid_simulation_paths must not contain duplicates.")
        for path in self.valid_simulation_paths:
            validate_relative_simulation_path(path)


def read_validation_report(report_path: Path) -> ValidatedSource:
    """Read a version-1 validation YAML report into one validated source grid.

    Args:
        report_path: Path to the YAML report produced by ``csfdata validate``.

    Returns:
        One ``ValidatedSource`` representing the report's source grid and all
        of its approved simulation paths.

    Raises:
        FileNotFoundError: If the report path does not exist.
        OSError: If the report cannot be read.
        ValueError: If the report is malformed or uses an unsupported schema.
        yaml.YAMLError: If the report is not valid YAML.
    """
    with report_path.open(encoding="utf-8") as stream:
        contents = yaml.safe_load(stream)
    if not isinstance(contents, dict):
        raise ValueError("Validation report must contain a YAML mapping.")
    if contents.get("schema_version") != _VALIDATION_REPORT_SCHEMA_VERSION:
        raise ValueError(
            "Validation report must use schema_version "
            f"{_VALIDATION_REPORT_SCHEMA_VERSION}."
        )

    source = contents.get("source")
    if not isinstance(source, dict):
        raise ValueError("Validation report must contain a source mapping.")
    hostname = source.get("hostname")
    root = source.get("root")
    if not isinstance(hostname, str) or not hostname:
        raise ValueError("Validation report source.hostname must be a non-empty string.")
    if not isinstance(root, str) or not root:
        raise ValueError("Validation report source.root must be a non-empty string.")

    paths = contents.get("valid_simulations")
    if not isinstance(paths, list) or not all(isinstance(path, str) for path in paths):
        raise ValueError("Validation report valid_simulations must be a list of strings.")

    return ValidatedSource(
        hostname=hostname,
        root=Path(root),
        valid_simulation_paths=tuple(Path(path) for path in paths),
    )


def validate_relative_simulation_path(path: Path) -> None:
    """Reject a path that could refer outside the validated source root.

    Args:
        path: Candidate simulation path from a validation report.

    Raises:
        ValueError: If the path is absolute, empty, or contains ``.`` or
            ``..`` path components.
    """
    if path.is_absolute() or path == Path("."):
        raise ValueError(f"Simulation path must be non-empty and relative: {path}")
    if any(part in {".", ".."} for part in path.parts):
        raise ValueError(f"Simulation path contains an unsafe component: {path}")
