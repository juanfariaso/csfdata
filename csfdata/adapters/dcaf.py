"""Read-only inspection and validation of one D-CAF simulation run."""

from __future__ import annotations

import math
import re
from pathlib import Path

import h5py
import yaml

from csfdata.adapters.base import SimulationAdapter
from csfdata.catalogue.configuration import SimulationConfiguration, extract_parameters


_BACKGROUND_GAS_PATTERN = re.compile(r"background_gas(?:_(\d+))?\.dat$")
_OUTPUT_FOLDER_PATTERN = re.compile(r"dcaf_output(?:_(\d+))?$")
_SNAPSHOT_PATTERN = re.compile(r"stars_\d+\.amuse$")
_MYR_IN_SECONDS = 365.25 * 24.0 * 60.0 * 60.0 * 1.0e6
_CHECKPOINT_ABSOLUTE_TOLERANCE_MYR = 1.0e-8
_CHECKPOINT_RELATIVE_TOLERANCE = 1.0e-5


class DcafAdapter(SimulationAdapter):
    """Inspect D-CAF files stored in one simulation run directory.

    This adapter interprets D-CAF's configuration, resumed output segments,
    gas time series, and stellar snapshots.
    """

    def __init__(self, run_root: Path, tolerance_myr: float = 0.5) -> None:
        """Initialize the adapter.

        Args:
            run_root: Directory containing the D-CAF simulation run.
            tolerance_myr: Maximum allowed difference between the final recorded
                model time and configured ``t_end``, in Myr.

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

    def read_configuration(self) -> dict[str, object]:
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
        if not isinstance(configuration, dict) or not all(
            isinstance(name, str) for name in configuration
        ):
            raise ValueError("D-CAF config.yaml must contain a YAML mapping.")
        return configuration

    def model_time(self) -> float | None:
        """Return the final time of the latest usable stellar snapshot.

        Returns:
            The final usable snapshot model time in Myr, or ``None`` when no
            snapshot-time mapping can be read reliably.
        """
        try:
            times = self.snapshot_times()
        except ValueError:
            return None
        return max(times.values(), default=None)

    def background_gas_times(self) -> tuple[float, ...]:
        """Return D-CAF background-gas times in resumed-output order.

        Returns:
            Model times in Myr from all ``background_gas*.dat`` files, ordered
            by resumed output segment and then by file record.

        Raises:
            ValueError: If a background-gas segment has no time records or
                contains an invalid time value.
        """
        segments: list[tuple[int, Path]] = []
        for path in self.run_root.iterdir():
            match = _BACKGROUND_GAS_PATTERN.fullmatch(path.name)
            if path.is_file() and match is not None:
                segments.append((int(match.group(1) or 0), path))

        times: list[float] = []
        for _, path in sorted(segments):
            file_times: list[float] = []
            for line_number, line in enumerate(
                path.read_text(encoding="utf-8").splitlines(), start=1
            ):
                fields = line.split()
                if not fields or line.lstrip().startswith("#"):
                    continue
                try:
                    file_times.append(float(fields[0]))
                except ValueError as error:
                    raise ValueError(f"Invalid time in {path.name} line {line_number}.") from error
            if not file_times:
                raise ValueError(f"No time records found in {path.name}.")
            times.extend(file_times)
        return tuple(times)

    def snapshot_times(self) -> dict[Path, float]:
        """Map D-CAF stellar snapshot paths to their stored model times.

        Returns:
            Mapping from paths relative to ``run_root`` to exact snapshot times
            in Myr, ordered by D-CAF output segment and filename.

        Raises:
            ValueError: If no stellar snapshot exists or any snapshot does not
                contain a readable model time.
        """
        times: dict[Path, float] = {}
        for snapshot_path in self.snapshot_paths():
            snapshot_time = self.snapshot_time(snapshot_path)
            if snapshot_time is None:
                raise ValueError(
                    "Cannot read snapshot model time: "
                    f"{snapshot_path.relative_to(self.run_root)}"
                )
            times[snapshot_path.relative_to(self.run_root)] = snapshot_time
        if not times:
            raise ValueError("No D-CAF stellar snapshots found.")
        return times

    def snapshot_paths(self) -> tuple[Path, ...]:
        """Return D-CAF stellar snapshots in resumed-output order.

        Returns:
            Valid ``stars_*.amuse`` paths, ordered by output segment and then
                by snapshot filename.
        """
        segments: list[tuple[int, Path]] = []
        for path in self.run_root.iterdir():
            match = _OUTPUT_FOLDER_PATTERN.fullmatch(path.name)
            if path.is_dir() and match is not None:
                segments.append((int(match.group(1) or 0), path))

        snapshots: list[Path] = []
        for _, output_folder in sorted(segments):
            snapshots.extend(
                path
                for path in sorted(output_folder.glob("stars_*.amuse"))
                if _SNAPSHOT_PATTERN.fullmatch(path.name)
            )
        return tuple(snapshots)

    def snapshot_time(self, snapshot_path: Path) -> float | None:
        """Return a D-CAF snapshot time from its HDF5 metadata.

        Args:
            snapshot_path: D-CAF ``stars_*.amuse`` snapshot path.

        Returns:
            The snapshot model time in Myr, or ``None`` when its HDF5 metadata
                cannot be read.
        """
        try:
            with h5py.File(snapshot_path, "r") as snapshot_file:
                data_group = snapshot_file["data"]
                group_names = sorted(data_group.keys())
                if not group_names:
                    return None
                attributes = data_group[group_names[0]].attrs
                model_time = attributes.get("model_time", attributes.get("code_time"))
            return float(model_time) / _MYR_IN_SECONDS
        except (KeyError, OSError, TypeError, ValueError):
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
        gas_segments: list[tuple[int, Path]] = []
        output_segments: list[tuple[int, Path]] = []
        # D-CAF uses unnumbered files for segment 0 and numbered names after resumes.
        for path in self.run_root.iterdir():
            gas_match = _BACKGROUND_GAS_PATTERN.fullmatch(path.name)
            output_match = _OUTPUT_FOLDER_PATTERN.fullmatch(path.name)
            if path.is_file() and gas_match is not None:
                gas_segments.append((int(gas_match.group(1) or 0), path))
            if path.is_dir() and output_match is not None:
                output_segments.append((int(output_match.group(1) or 0), path))
        gas_segments.sort()
        output_segments.sort()

        for label, segments in (
            ("background-gas", gas_segments),
            ("output", output_segments),
        ):
            if segments:
                found = {segment for segment, _ in segments}
                missing = sorted(set(range(max(found) + 1)) - found)
                if missing:
                    missing_text = ", ".join(str(segment) for segment in missing)
                    issues.append(f"Missing {label} segment(s): {missing_text}.")

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

        snapshot_paths_by_segment: dict[int, tuple[Path, ...]] = {}
        for segment, output_folder in output_segments:
            candidates = tuple(sorted(output_folder.glob("stars_*.amuse")))
            if not candidates:
                issues.append(f"No stellar snapshots found in {output_folder.name}.")
            for snapshot in candidates:
                if not _SNAPSHOT_PATTERN.fullmatch(snapshot.name):
                    issues.append(f"Invalid snapshot filename: {snapshot.name}.")
            snapshot_paths_by_segment[segment] = tuple(
                path for path in candidates if _SNAPSHOT_PATTERN.fullmatch(path.name)
            )

        gas_records_by_segment: dict[int, tuple[tuple[Path, int, float], ...]] = {}
        for segment, gas_path in gas_segments:
            records: list[tuple[Path, int, float]] = []
            for line_number, line in enumerate(
                gas_path.read_text(encoding="utf-8").splitlines(), start=1
            ):
                fields = line.split()
                if not fields or line.lstrip().startswith("#"):
                    continue
                try:
                    records.append((gas_path, line_number, float(fields[0])))
                except ValueError:
                    issues.append(f"Invalid time in {gas_path.name} line {line_number}.")
                    records = []
                    break
            if records:
                gas_records_by_segment[segment] = tuple(records)
            else:
                issues.append(f"No time records found in {gas_path.name}.")

        for segment in sorted(gas_by_segment.keys() & output_by_segment.keys()):
            gas_records = gas_records_by_segment.get(segment)
            if gas_records is None:
                continue
            snapshot_count = len(snapshot_paths_by_segment[segment])
            if len(gas_records) != snapshot_count:
                issues.append(
                    f"Segment {segment}: {gas_by_segment[segment].name} has {len(gas_records)} time records "
                    f"but {output_by_segment[segment].name} has {snapshot_count} stellar snapshots."
                )

        segments_with_records = sorted(gas_records_by_segment)
        for previous_segment, segment in zip(
            segments_with_records, segments_with_records[1:]
        ):
            previous_time = gas_records_by_segment[previous_segment][-1][2]
            current_time = gas_records_by_segment[segment][0][2]
            if current_time < previous_time and not math.isclose(
                current_time,
                previous_time,
                rel_tol=_CHECKPOINT_RELATIVE_TOLERANCE,
                abs_tol=_CHECKPOINT_ABSOLUTE_TOLERANCE_MYR,
            ):
                issues.append(
                    f"Background-gas segment {segment} starts at {current_time:g} Myr "
                    f"before segment {previous_segment} ends at {previous_time:g} Myr."
                )

        if detailed:
            timelines: list[tuple[int, tuple[float, ...], tuple[float, ...]]] = []
            for segment in sorted(gas_by_segment.keys() & output_by_segment.keys()):
                gas_records = gas_records_by_segment.get(segment)
                if gas_records is None:
                    continue

                snapshot_records: list[tuple[Path, float]] = []
                for snapshot_path in snapshot_paths_by_segment[segment]:
                    try:
                        with h5py.File(snapshot_path, "r") as snapshot_file:
                            data_group = snapshot_file["data"]
                            group_names = sorted(data_group.keys())
                            if not group_names:
                                raise ValueError("snapshot has no particle-data group")
                            attributes = data_group[group_names[0]].attrs
                            model_time = attributes.get(
                                "model_time", attributes.get("code_time")
                            )
                        if model_time is None:
                            raise ValueError("snapshot has no model_time attribute")
                        snapshot_records.append(
                            (snapshot_path, float(model_time) / _MYR_IN_SECONDS)
                        )
                    except (KeyError, OSError, TypeError, ValueError) as error:
                        issues.append(
                            "Cannot read model time from "
                            f"{snapshot_path.relative_to(self.run_root)}: {error}"
                        )

                segment_issues: list[str] = []
                # Text gas output is rounded, so compare it with HDF5 times using tolerances.
                for label, records in (
                    ("background-gas record", gas_records),
                    ("snapshot", snapshot_records),
                ):
                    for previous, current in zip(records, records[1:]):
                        previous_time = previous[-1]
                        current_time = current[-1]
                        if current_time < previous_time and not math.isclose(
                            current_time,
                            previous_time,
                            rel_tol=_CHECKPOINT_RELATIVE_TOLERANCE,
                            abs_tol=_CHECKPOINT_ABSOLUTE_TOLERANCE_MYR,
                        ):
                            if label == "background-gas record":
                                previous_location = f"{previous[0].name} line {previous[1]}"
                                current_location = f"{current[0].name} line {current[1]}"
                            else:
                                previous_location = str(
                                    previous[0].relative_to(self.run_root)
                                )
                                current_location = str(current[0].relative_to(self.run_root))
                            segment_issues.append(
                                f"Segment {segment}: {label} time decreases from "
                                f"{previous_location} at {previous_time:g} Myr to "
                                f"{current_location} at {current_time:g} Myr."
                            )

                gas_index = 0
                snapshot_index = 0
                while gas_index < len(gas_records) and snapshot_index < len(snapshot_records):
                    gas_path, gas_line, gas_time = gas_records[gas_index]
                    snapshot_path, snapshot_time = snapshot_records[snapshot_index]
                    if math.isclose(
                        gas_time,
                        snapshot_time,
                        rel_tol=_CHECKPOINT_RELATIVE_TOLERANCE,
                        abs_tol=_CHECKPOINT_ABSOLUTE_TOLERANCE_MYR,
                    ):
                        gas_index += 1
                        snapshot_index += 1
                    elif snapshot_time < gas_time:
                        segment_issues.append(
                            f"Segment {segment}: snapshot "
                            f"{snapshot_path.relative_to(self.run_root)} at {snapshot_time:g} Myr "
                            f"does not match next background-gas record {gas_path.name} "
                            f"line {gas_line} at {gas_time:g} Myr."
                        )
                        snapshot_index += 1
                    else:
                        segment_issues.append(
                            f"Segment {segment}: background-gas record {gas_path.name} line "
                            f"{gas_line} at {gas_time:g} Myr does not match next snapshot "
                            f"{snapshot_path.relative_to(self.run_root)} at {snapshot_time:g} Myr."
                        )
                        gas_index += 1
                for gas_path, gas_line, gas_time in gas_records[gas_index:]:
                    segment_issues.append(
                        f"Segment {segment}: background-gas record {gas_path.name} line "
                        f"{gas_line} at {gas_time:g} Myr has no stellar snapshot."
                    )
                for snapshot_path, snapshot_time in snapshot_records[snapshot_index:]:
                    segment_issues.append(
                        f"Segment {segment}: snapshot "
                        f"{snapshot_path.relative_to(self.run_root)} at {snapshot_time:g} Myr "
                        "has no background-gas time record."
                    )

                issues.extend(segment_issues)
                if not segment_issues:
                    timelines.append(
                        (
                            segment,
                            tuple(record[2] for record in gas_records),
                            tuple(record[1] for record in snapshot_records),
                        )
                    )

            for candidate_segment, candidate_gas, candidate_snapshots in timelines:
                for reference_segment, reference_gas, reference_snapshots in timelines:
                    if candidate_segment == reference_segment:
                        continue
                    if len(candidate_gas) > len(reference_gas):
                        continue
                    if (
                        len(candidate_gas) == len(reference_gas)
                        and candidate_segment < reference_segment
                    ):
                        continue

                    duplicate = True
                    # Both gas and stellar time sequences must occur together in one segment.
                    for candidate_times, reference_times in (
                        (candidate_gas, reference_gas),
                        (candidate_snapshots, reference_snapshots),
                    ):
                        if len(candidate_times) > len(reference_times):
                            duplicate = False
                            break
                        found = False
                        for start in range(len(reference_times) - len(candidate_times) + 1):
                            if all(
                                math.isclose(
                                    candidate_time,
                                    reference_time,
                                    rel_tol=_CHECKPOINT_RELATIVE_TOLERANCE,
                                    abs_tol=_CHECKPOINT_ABSOLUTE_TOLERANCE_MYR,
                                )
                                for candidate_time, reference_time in zip(
                                    candidate_times,
                                    reference_times[start : start + len(candidate_times)],
                                )
                            ):
                                found = True
                                break
                        if not found:
                            duplicate = False
                            break
                    if duplicate:
                        issues.append(
                            f"Segment {candidate_segment} is fully duplicated by segment "
                            f"{reference_segment}: checkpoint and snapshot time sequences from "
                            f"{candidate_gas[0]:g} to {candidate_gas[-1]:g} Myr are identical."
                        )
                        break

        if not gas_records_by_segment:
            issues.append("No readable background-gas time records found.")

        # The final usable stellar snapshot is the generic definition of model time.
        final_snapshot_time = self.model_time()
        if final_snapshot_time is None:
            issues.append("No readable stellar snapshot model time found.")

        value = configuration.get("t_end")
        try:
            if isinstance(value, (int, float)):
                configured_end_time = float(value)
            elif isinstance(value, str):
                fields = value.split()
                if len(fields) != 2 or fields[1] != "Myr":
                    raise ValueError
                configured_end_time = float(fields[0])
            else:
                raise ValueError
        except ValueError:
            issues.append("D-CAF config.yaml must define t_end in Myr.")
        else:
            if (
                final_snapshot_time is not None
                and abs(final_snapshot_time - configured_end_time) > self.tolerance_myr
            ):
                issues.append(
                    "Final model time "
                    f"{final_snapshot_time:g} Myr differs from configured t_end "
                    f"{configured_end_time:g} Myr by more than {self.tolerance_myr:g} Myr."
                )

        return tuple(issues)

    def raw_data_paths(self) -> tuple[Path, ...]:
        """Return the raw D-CAF files eligible for copying.

        Returns:
            The original configuration, optional ``code.out``, background-gas
            segments, and all files below D-CAF output directories. Derived
            products and scheduler files are omitted.
        """
        paths = [self.configuration_path()]
        code_output = self.run_root / "code.out"
        if code_output.is_file():
            paths.append(code_output)

        gas_segments: list[tuple[int, Path]] = []
        output_segments: list[tuple[int, Path]] = []
        # Copy each complete D-CAF output folder, not only stellar snapshots.
        for path in self.run_root.iterdir():
            gas_match = _BACKGROUND_GAS_PATTERN.fullmatch(path.name)
            output_match = _OUTPUT_FOLDER_PATTERN.fullmatch(path.name)
            if path.is_file() and gas_match is not None:
                gas_segments.append((int(gas_match.group(1) or 0), path))
            if path.is_dir() and output_match is not None:
                output_segments.append((int(output_match.group(1) or 0), path))
        paths.extend(path for _, path in sorted(gas_segments))
        paths.extend(
            path
            for _, output_folder in sorted(output_segments)
            for path in sorted(output_folder.rglob("*"))
            if path.is_file()
        )
        return tuple(paths)

    def build_configuration(self) -> SimulationConfiguration:
        """Build canonical configuration by preserving D-CAF parameter names.

        Returns:
            A configuration with no shared standard parameters yet and every
            scalar D-CAF ``config.yaml`` field recorded as a code-specific
            parameter.

        Raises:
            FileNotFoundError: If D-CAF's ``config.yaml`` does not exist.
            yaml.YAMLError: If the D-CAF configuration is not valid YAML.
            ValueError: If the configuration is not a mapping or has a value
                that the first catalogue schema cannot represent.

        Notes:
            The shared cross-code vocabulary has not yet been agreed. Keeping
            D-CAF names intact avoids guessing scientific equivalences while
            still making collection-specific requirements enforceable. Strings
            with an explicit supported unit are normalized by
            [`UnitConverter`][csfdata.units.UnitConverter].
        """
        code_parameters = extract_parameters(self.configuration_path())
        return SimulationConfiguration(parameters=(), code_parameters=code_parameters)
