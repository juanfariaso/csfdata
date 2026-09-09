"""Read-only inspection and validation of one D-CAF simulation run."""

from __future__ import annotations

import re
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import h5py
import yaml

from csfdata.adapters.base import SimulationAdapter


_BACKGROUND_GAS_PATTERN = re.compile(r"background_gas(?:_(\d+))?\.dat$")
_OUTPUT_FOLDER_PATTERN = re.compile(r"dcaf_output(?:_(\d+))?$")
_SNAPSHOT_PATTERN = re.compile(r"stars_\d+\.amuse$")
_MYR_IN_SECONDS = 365.25 * 24.0 * 60.0 * 60.0 * 1.0e6
_CHECKPOINT_TOLERANCE_MYR = 1.0e-6


@dataclass(frozen=True)
class _GasTimeRecord:
    """One timestamp read from a background-gas file."""

    path: Path
    line_number: int
    time_myr: float


@dataclass(frozen=True)
class _SnapshotTimeRecord:
    """One timestamp read from a D-CAF stellar snapshot."""

    path: Path
    time_myr: float


@dataclass(frozen=True)
class _SegmentTimeline:
    """Validated checkpoint and snapshot time sequences for one segment."""

    segment: int
    checkpoint_times: tuple[float, ...]
    snapshot_times: tuple[float, ...]


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
            times = self.checkpoint_times()
        except ValueError:
            return None
        return times[-1] if times else None

    def checkpoint_times(self) -> tuple[float, ...]:
        """Return D-CAF background-gas times as output checkpoint times.

        Returns:
            Model times in Myr from all ``background_gas*.dat`` files, ordered
                by resumed output segment and then by file record.

        Raises:
            ValueError: If a background-gas segment has no time records or
                contains an invalid time value.
        """
        return self._gas_times()

    def snapshot_paths(self) -> tuple[Path, ...]:
        """Return D-CAF stellar snapshots in resumed-output order.

        Returns:
            Valid ``stars_*.amuse`` paths, ordered by output segment and then
                by snapshot filename.
        """
        return tuple(
            snapshot
            for _, output_folder in self._output_segments()
            for snapshot in sorted(output_folder.glob("stars_*.amuse"))
            if _SNAPSHOT_PATTERN.fullmatch(snapshot.name)
        )

    def snapshot_time(self, snapshot_path: Path) -> float | None:
        """Return a D-CAF snapshot time from its HDF5 metadata.

        Args:
            snapshot_path: D-CAF ``stars_*.amuse`` snapshot path.

        Returns:
            The snapshot model time in Myr, or ``None`` when its HDF5 metadata
                cannot be read.
        """
        try:
            return _snapshot_time_myr(snapshot_path)
        except (OSError, ValueError):
            return None

    def validate_simulation(self, detailed: bool = False) -> tuple[str, ...]:
        """Validate the D-CAF configuration and raw-output structure.

        Args:
            detailed: Whether to read every stellar snapshot and compare its
                HDF5 model time with the matching background-gas record.

        Returns:
            A tuple of human-readable validation issues. An empty tuple means
                no issue was found.

        Notes:
            Basic validation checks file structure and final model time. Detailed
            validation additionally checks snapshot/checkpoint agreement within
            one segment and duplicate segment timelines.
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

        gas_by_segment = dict(gas_segments)
        output_by_segment = dict(output_segments)
        for segment in sorted(gas_by_segment.keys() - output_by_segment.keys()):
            issues.append(
                f"Segment {segment}: {gas_by_segment[segment].name} has no matching output directory."
            )
        for segment in sorted(output_by_segment.keys() - gas_by_segment.keys()):
            issues.append(
                f"Segment {segment}: {output_by_segment[segment].name} has no matching background-gas file."
            )

        for _, output_folder in output_segments:
            snapshots = tuple(output_folder.glob("stars_*.amuse"))
            if not snapshots:
                issues.append(f"No stellar snapshots found in {output_folder.name}.")
            for snapshot in snapshots:
                if not _SNAPSHOT_PATTERN.fullmatch(snapshot.name):
                    issues.append(f"Invalid snapshot filename: {snapshot.name}.")

        if detailed:
            timelines: list[_SegmentTimeline] = []
            for segment in sorted(gas_by_segment.keys() & output_by_segment.keys()):
                gas_path = gas_by_segment[segment]
                output_folder = output_by_segment[segment]
                try:
                    gas_records = _gas_time_records(gas_path)
                except ValueError as error:
                    issues.append(str(error))
                    continue
                if not gas_records:
                    issues.append(f"No time records found in {gas_path.name}.")
                    continue

                snapshot_records: list[_SnapshotTimeRecord] = []
                for snapshot_path in self._snapshot_paths_in_folder(output_folder):
                    try:
                        snapshot_records.append(
                            _SnapshotTimeRecord(snapshot_path, _snapshot_time_myr(snapshot_path))
                        )
                    except (OSError, ValueError) as error:
                        issues.append(
                            "Cannot read model time from "
                            f"{self._relative_path(snapshot_path)}: {error}"
                        )

                segment_issues = [
                    *self._time_order_issues(segment, gas_records, "background-gas record"),
                    *self._time_order_issues(segment, snapshot_records, "snapshot"),
                    *self._checkpoint_match_issues(segment, gas_records, snapshot_records),
                ]
                issues.extend(segment_issues)
                if not segment_issues:
                    timelines.append(
                        _SegmentTimeline(
                            segment=segment,
                            checkpoint_times=tuple(record.time_myr for record in gas_records),
                            snapshot_times=tuple(record.time_myr for record in snapshot_records),
                        )
                    )

            issues.extend(self._duplicate_timeline_issues(timelines))

        try:
            times = self._gas_times()
        except ValueError as error:
            issues.append(str(error))
            times = ()

        if not times:
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
        return tuple(sorted((*gas_files, *self.snapshot_paths())))

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

    @staticmethod
    def _snapshot_paths_in_folder(output_folder: Path) -> tuple[Path, ...]:
        """Return valid stellar snapshots in one output-folder order."""
        return tuple(
            path
            for path in sorted(output_folder.glob("stars_*.amuse"))
            if _SNAPSHOT_PATTERN.fullmatch(path.name)
        )

    def _relative_path(self, path: Path) -> Path:
        """Return a path relative to this run root for issue messages."""
        return path.relative_to(self.run_root)

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

    def _time_order_issues(
        self,
        segment: int,
        records: tuple[_GasTimeRecord, ...] | list[_SnapshotTimeRecord],
        label: str,
    ) -> tuple[str, ...]:
        """Report time decreases within one output segment."""
        issues: list[str] = []
        for previous, current in zip(records, records[1:]):
            if current.time_myr < previous.time_myr - _CHECKPOINT_TOLERANCE_MYR:
                issues.append(
                    f"Segment {segment}: {label} time decreases from "
                    f"{self._record_location(previous)} at {previous.time_myr:g} Myr to "
                    f"{self._record_location(current)} at {current.time_myr:g} Myr."
                )
        return tuple(issues)

    def _checkpoint_match_issues(
        self,
        segment: int,
        gas_records: tuple[_GasTimeRecord, ...],
        snapshot_records: list[_SnapshotTimeRecord],
    ) -> tuple[str, ...]:
        """Report unmatched D-CAF checkpoint and snapshot records."""
        issues: list[str] = []
        gas_index = 0
        snapshot_index = 0
        while gas_index < len(gas_records) and snapshot_index < len(snapshot_records):
            gas_record = gas_records[gas_index]
            snapshot_record = snapshot_records[snapshot_index]
            difference = snapshot_record.time_myr - gas_record.time_myr
            if abs(difference) <= _CHECKPOINT_TOLERANCE_MYR:
                gas_index += 1
                snapshot_index += 1
            elif difference < 0:
                issues.append(
                    f"Segment {segment}: snapshot {self._relative_path(snapshot_record.path)} at "
                    f"{snapshot_record.time_myr:g} Myr does not match next background-gas "
                    f"record {gas_record.path.name} line {gas_record.line_number} at "
                    f"{gas_record.time_myr:g} Myr."
                )
                snapshot_index += 1
            else:
                issues.append(
                    f"Segment {segment}: background-gas record {gas_record.path.name} line "
                    f"{gas_record.line_number} at {gas_record.time_myr:g} Myr does not match "
                    f"next snapshot {self._relative_path(snapshot_record.path)} at "
                    f"{snapshot_record.time_myr:g} Myr."
                )
                gas_index += 1

        for gas_record in gas_records[gas_index:]:
            issues.append(
                f"Segment {segment}: background-gas record {gas_record.path.name} line "
                f"{gas_record.line_number} at {gas_record.time_myr:g} Myr has no stellar snapshot."
            )
        for snapshot_record in snapshot_records[snapshot_index:]:
            issues.append(
                f"Segment {segment}: snapshot {self._relative_path(snapshot_record.path)} at "
                f"{snapshot_record.time_myr:g} Myr has no background-gas time record."
            )
        return tuple(issues)

    def _duplicate_timeline_issues(
        self, timelines: list[_SegmentTimeline]
    ) -> tuple[str, ...]:
        """Report segments whose complete timeline occurs in another segment."""
        issues: list[str] = []
        for candidate in timelines:
            for reference in timelines:
                if candidate.segment == reference.segment:
                    continue
                if not _timeline_is_contained(candidate, reference):
                    continue
                if len(candidate.checkpoint_times) > len(reference.checkpoint_times):
                    continue
                if (
                    len(candidate.checkpoint_times) == len(reference.checkpoint_times)
                    and candidate.segment < reference.segment
                ):
                    continue
                issues.append(
                    f"Segment {candidate.segment} is fully duplicated by segment "
                    f"{reference.segment}: checkpoint and snapshot time sequences from "
                    f"{candidate.checkpoint_times[0]:g} to {candidate.checkpoint_times[-1]:g} "
                    "Myr are identical."
                )
                break
        return tuple(issues)

    def _record_location(self, record: _GasTimeRecord | _SnapshotTimeRecord) -> str:
        """Return a concise source location for one timestamp record."""
        if isinstance(record, _GasTimeRecord):
            return f"{record.path.name} line {record.line_number}"
        return str(self._relative_path(record.path))

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
    return tuple(record.time_myr for record in _gas_time_records(path))


def _gas_time_records(path: Path) -> tuple[_GasTimeRecord, ...]:
    """Read background-gas times together with their source locations."""
    records: list[_GasTimeRecord] = []
    for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        fields = line.split()
        if not fields or line.lstrip().startswith("#"):
            continue
        try:
            records.append(_GasTimeRecord(path, line_number, float(fields[0])))
        except ValueError as error:
            raise ValueError(f"Invalid time in {path.name} line {line_number}.") from error
    return tuple(records)


def _snapshot_time_myr(path: Path) -> float:
    """Read a D-CAF AMUSE-HDF5 snapshot model time in Myr."""
    try:
        with h5py.File(path, "r") as snapshot_file:
            data_group = snapshot_file["data"]
            group_names = sorted(data_group.keys())
            if not group_names:
                raise ValueError("snapshot has no particle-data group")
            attributes = data_group[group_names[0]].attrs
            model_time = attributes.get("model_time", attributes.get("code_time"))
    except KeyError as error:
        raise ValueError("snapshot has no D-CAF particle-data group") from error

    if model_time is None:
        raise ValueError("snapshot has no model_time attribute")
    try:
        return float(model_time) / _MYR_IN_SECONDS
    except (TypeError, ValueError) as error:
        raise ValueError("snapshot model_time is not numeric") from error


def _timeline_is_contained(candidate: _SegmentTimeline, reference: _SegmentTimeline) -> bool:
    """Return whether both candidate time sequences occur in a reference timeline."""
    return _time_sequence_is_contained(
        candidate.checkpoint_times, reference.checkpoint_times
    ) and _time_sequence_is_contained(candidate.snapshot_times, reference.snapshot_times)


def _time_sequence_is_contained(
    candidate: tuple[float, ...], reference: tuple[float, ...]
) -> bool:
    """Return whether one time sequence occurs contiguously in another."""
    if not candidate or len(candidate) > len(reference):
        return False
    for start in range(len(reference) - len(candidate) + 1):
        window = reference[start : start + len(candidate)]
        if all(
            abs(candidate_time - reference_time) <= _CHECKPOINT_TOLERANCE_MYR
            for candidate_time, reference_time in zip(candidate, window)
        ):
            return True
    return False
