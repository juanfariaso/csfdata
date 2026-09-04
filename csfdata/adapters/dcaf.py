"""Read-only inspection and validation of one D-CAF simulation run."""

from __future__ import annotations

import re
from collections.abc import Iterable
from pathlib import Path
from typing import Any

import yaml

from csfdata.adapters.base import SimulationAdapter


_BACKGROUND_GAS_PATTERN = re.compile(r"background_gas(?:_(\d+))?\.dat$")
_OUTPUT_FOLDER_PATTERN = re.compile(r"dcaf_output(?:_(\d+))?$")
_SNAPSHOT_PATTERN = re.compile(r"stars_\d+\.amuse$")


class DcafAdapter(SimulationAdapter):
    """Inspect D-CAF files stored in one simulation run directory.

    This adapter interpretates D-CAF's configuration, resumed output
    segments, gas time series, and snapshots.
    """

    def __init__(self, run_root: Path, tolerance_myr: float = 0.5) -> None:
        """Initialize the adapter.

        Args:
            run_root: Directory containing the D-CAF simulation run.
            tolerance_myr: Maximum allowed difference between the final recorded
                model time and the configured ``t_end``, in Myr.

        Raises:
            ValueError: If ``tolerance_myr`` is negative.
        """
        if tolerance_myr < 0:
            raise ValueError("Validation tolerance must be non-negative.")
        self.run_root = run_root
        self.tolerance_myr = tolerance_myr

    def is_simulation(self) -> bool:
        """Return whether this directory has the minimum D-CAF run marker.

        Returns:
            ``True`` when ``config.yaml`` exists in ``run_root``; otherwise,
                ``False``.
        """
        return self.configuration_path().is_file()

    def configuration_path(self) -> Path:
        """Return the path of D-CAF's authoritative configuration file.

        Returns:
            The expected ``config.yaml`` path. The path may not exist; callers
            can use
            [`SimulationAdapter.is_simulation`][csfdata.adapters.base.SimulationAdapter.is_simulation]
            to check that first.
        """
        return self.run_root / "config.yaml"

    def read_configuration(self) -> dict[str, Any]:
        """Read the D-CAF YAML configuration mapping.

        Returns:
            The parsed contents of ``config.yaml``.

        Raises:
            FileNotFoundError: If ``config.yaml`` does not exist.
            yaml.YAMLError: If the configuration is not valid YAML.
            ValueError: If the YAML document is not a mapping.
        """
        with self.configuration_path().open(encoding="utf-8") as stream:
            configuration = yaml.safe_load(stream)
        if not isinstance(configuration, dict):
            raise ValueError("D-CAF config.yaml must contain a YAML mapping.")
        return configuration

    def model_time(self) -> float | None:
        """Return the final time from all background-gas segments.

        Returns:
            The final recorded model time in Myr, or ``None`` when no valid
                background-gas time records can be read.

        Notes:
            D-CAF writes ``background_gas.dat`` for its first output segment
            and ``background_gas_N.dat`` after a resume. Segments are read in
            numeric order, not filename order.
        """
        try:
            times = self._gas_times()
        except ValueError:
            return None
        return times[-1] if times else None

    def validate_simulation(self) -> tuple[str, ...]:
        """Validate the D-CAF configuration and raw-output structure.

        Returns:
            A tuple of human-readable validation issues. An empty tuple means
                no issue was found.

        Notes:
            Validation checks contiguous output and background-gas segments,
            snapshot presence and names, monotonic gas times, and agreement
            between the final model time and ``t_end`` within ``tolerance_myr``.
        """
        try:
            configuration = self.read_configuration()
        except (OSError, ValueError, yaml.YAMLError) as error:
            return (f"Cannot read config.yaml: {error}",)

        issues: list[str] = []
        gas_segments = self._background_gas_segments()
        output_segments = self._output_segments()
        issues.extend(self._sequence_issues("background-gas", gas_segments))
        issues.extend(self._sequence_issues("output", output_segments))

        for _, output_folder in output_segments:
            snapshots = tuple(output_folder.glob("stars_*.amuse"))
            if not snapshots:
                issues.append(f"No stellar snapshots found in {output_folder.name}.")
            for snapshot in snapshots:
                if not _SNAPSHOT_PATTERN.fullmatch(snapshot.name):
                    issues.append(f"Invalid snapshot filename: {snapshot.name}.")

        try:
            times = self._gas_times()
        except ValueError as error:
            issues.append(str(error))
            times = ()

        if times:
            issues.extend(self._time_order_issues(times))
        else:
            issues.append("No readable background-gas time records found.")

        try:
            configured_end_time = self._configured_end_time_myr(configuration)
        except ValueError as error:
            issues.append(str(error))
        else:
            if times and abs(times[-1] - configured_end_time) > self.tolerance_myr:
                issues.append(
                    "Final model time "
                    f"{times[-1]:g} Myr differs from configured t_end "
                    f"{configured_end_time:g} Myr by more than {self.tolerance_myr:g} Myr."
                )

        return tuple(issues)

    def raw_data_paths(self) -> Iterable[Path]:
        """Return the raw D-CAF files eligible for copying.

        Returns:
            An ordered collection containing background-gas segments and valid
                stellar snapshots. Derived products and scheduler files are omitted.
        """
        gas_files = (path for _, path in self._background_gas_segments())
        snapshot_files = (
            snapshot
            for _, output_folder in self._output_segments()
            for snapshot in output_folder.glob("stars_*.amuse")
            if _SNAPSHOT_PATTERN.fullmatch(snapshot.name)
        )
        return tuple(sorted((*gas_files, *snapshot_files)))

    def _background_gas_segments(self) -> tuple[tuple[int, Path], ...]:
        """Return numbered background-gas segments in numeric order.

        Returns:
            Pairs of segment number and file path. The unnumbered
                ``background_gas.dat`` file is segment zero.
        """
        return _numbered_paths(self.run_root, _BACKGROUND_GAS_PATTERN, require_directory=False)

    def _output_segments(self) -> tuple[tuple[int, Path], ...]:
        """Return numbered D-CAF output directories in numeric order.

        Returns:
            Pairs of segment number and directory path. The unnumbered
                ``dcaf_output`` directory is segment zero.
        """
        return _numbered_paths(self.run_root, _OUTPUT_FOLDER_PATTERN, require_directory=True)

    def _gas_times(self) -> tuple[float, ...]:
        """Read all background-gas times in resumed-segment order.

        Returns:
            All model times in Myr, preserving the order written by D-CAF.

        Raises:
            ValueError: If a segment has no time records or contains an invalid
                time value.
        """
        times: list[float] = []
        for _, path in self._background_gas_segments():
            file_times = _times_from_file(path)
            if not file_times:
                raise ValueError(f"No time records found in {path.name}.")
            times.extend(file_times)
        return tuple(times)

    @staticmethod
    def _sequence_issues(label: str, segments: tuple[tuple[int, Path], ...]) -> tuple[str, ...]:
        """Report gaps in a sequence of numbered output segments.

        Args:
            label: Human-readable name of the sequence being checked.
            segments: Segment numbers paired with their paths.

        Returns:
            One issue describing missing segments, or an empty tuple when the
                sequence is continuous or absent.
        """
        if not segments:
            return ()
        found = {segment for segment, _ in segments}
        missing = sorted(set(range(max(found) + 1)) - found)
        if not missing:
            return ()
        missing_text = ", ".join(str(segment) for segment in missing)
        return (f"Missing {label} segment(s): {missing_text}.",)

    @staticmethod
    def _time_order_issues(times: tuple[float, ...]) -> tuple[str, ...]:
        """Report whether a background-gas time sequence decreases.

        Args:
            times: Model times in the order they were recorded.

        Returns:
            One issue when a time decreases, otherwise an empty tuple.
        """
        if any(current < previous for previous, current in zip(times, times[1:])):
            return ("Background-gas time records decrease across output segments.",)
        return ()

    @staticmethod
    def _configured_end_time_myr(configuration: dict[str, Any]) -> float:
        """Extract ``t_end`` from a D-CAF configuration in Myr.

        Args:
            configuration: Parsed D-CAF configuration mapping.

        Returns:
            The configured end time in Myr.

        Raises:
            ValueError: If ``t_end`` is absent or is not an explicit Myr value.
        """
        value = configuration.get("t_end")
        if isinstance(value, (int, float)):
            return float(value)
        if isinstance(value, str):
            fields = value.split()
            if len(fields) == 2 and fields[1] == "Myr":
                return float(fields[0])
        raise ValueError("D-CAF config.yaml must define t_end in Myr.")


def _numbered_paths(
    run_root: Path, pattern: re.Pattern[str], require_directory: bool
) -> tuple[tuple[int, Path], ...]:
    """Collect matching numbered files or directories below a run root.

    Args:
        run_root: Directory containing the candidate output segments.
        pattern: Regular expression with an optional numeric first capture group.
        require_directory: Whether matches must be directories instead of files.

    Returns:
        Segment-number and path pairs in numeric order. An unnumbered match is
            treated as segment zero.
    """
    paths: list[tuple[int, Path]] = []
    for path in run_root.iterdir():
        if require_directory != path.is_dir():
            continue
        match = pattern.fullmatch(path.name)
        if match is not None:
            segment = int(match.group(1) or 0)
            paths.append((segment, path))
    return tuple(sorted(paths))


def _times_from_file(path: Path) -> tuple[float, ...]:
    """Read the first numeric column from a background-gas time-series file.

    Args:
        path: Background-gas file to parse.

    Returns:
        The time values in file order.

    Raises:
        ValueError: If a non-comment data row has a non-numeric first column.
    """
    times: list[float] = []
    for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        fields = line.split()
        if not fields or line.lstrip().startswith("#"):
            continue
        try:
            times.append(float(fields[0]))
        except ValueError as error:
            raise ValueError(f"Invalid time in {path.name} line {line_number}.") from error
    return tuple(times)
