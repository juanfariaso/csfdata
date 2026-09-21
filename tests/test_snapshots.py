"""Tests for snapshot-selection manifests."""

from pathlib import Path
import socket

import h5py
import pytest
import yaml

from csfdata.catalogue.configuration import (
    ConfigurationParameter,
    SimulationConfiguration,
    write_simulation_configuration,
)
from csfdata.catalogue.metadata import SimulationMetadata, write_simulation_metadata
from csfdata.catalogue.lite import file_sha256
from csfdata.catalogue.registry import index_catalogue
from csfdata.catalogue.snapshots import (
    clear_snapshots,
    import_snapshots,
    refresh_snapshot_times,
)
from csfdata.cli import main


def test_list_snapshots_writes_manifest_and_clear_requires_lite_catalogue(
    tmp_path: Path,
    capsys,
) -> None:
    """Select snapshots and clear them only after the root is marked as lite."""
    catalogue = tmp_path / "catalogue"
    simulation = catalogue / "collections" / "example-collection" / "simulations" / "0001"
    simulation.mkdir(parents=True)
    (simulation.parent.parent / "collection.yaml").write_text(
        """schema_version: 1
id: example-collection
importer: dcaf
config_schema_version: 1
required_parameters: []
optional_parameters: []
""",
        encoding="utf-8",
    )
    write_simulation_metadata(
        SimulationMetadata(
            "0001",
            "example-collection",
            "dcaf",
            "host",
            tmp_path / "source",
            Path("run"),
            "2026-01-01T00:00:00Z",
        ),
        simulation / "metadata.yaml",
    )
    write_simulation_configuration(
        SimulationConfiguration(
            (ConfigurationParameter("tff", 1.0, "Myr", "explicit"),),
            (),
        ),
        simulation / "config.yaml",
    )
    raw_output = simulation / "raw" / "dcaf_output"
    raw_output.mkdir(parents=True)
    for index, time in enumerate((0.0, 10.0, 20.0)):
        with h5py.File(raw_output / f"stars_{index:03d}.amuse", "w") as snapshot:
            group = snapshot.create_group("data/0000000001")
            group.attrs["model_time"] = time * 365.25 * 24.0 * 60.0 * 60.0 * 1.0e6
    index_catalogue(catalogue)
    progress: list[tuple[int, int, str]] = []
    refresh_snapshot_times(
        catalogue,
        "example-collection",
        progress=lambda number, total, simulation_id: progress.append(
            (number, total, simulation_id)
        ),
    )
    assert progress == [(1, 1, "0001")]

    manifest = tmp_path / "snapshots.yaml"
    assert main(
        [
            "list-snapshots",
            str(catalogue),
            "--collection",
            "example-collection",
            "--time",
            "16",
            "--filter",
            "tff=1.0",
            "--output",
            str(manifest),
        ]
    ) == 0

    contents = yaml.safe_load(manifest.read_text(encoding="utf-8"))
    assert contents["summary"] == {
        "matched_simulations": 1,
        "selected_snapshots": 1,
        "unmatched_simulations": 0,
    }
    assert contents["selected_snapshots"] == [
        {
            "simulation_id": "0001",
            "target_time": 16.0,
            "snapshot_time": 20.0,
            "time_offset": 4.0,
            "tolerance": 5.0,
            "source_paths": [
                "collections/example-collection/simulations/0001/raw/dcaf_output/stars_002.amuse"
            ],
        }
    ]
    assert contents["total_selected_size"].endswith("KiB")
    with pytest.raises(ValueError, match="only from a lite catalogue"):
        clear_snapshots(catalogue)
    (catalogue / "lite.yaml").write_text(
        f"""schema_version: 1
source:
  catalogue_root: /path/to/source-catalogue
  hostname: host
  collection_id: example-collection
  collection_sha256: {file_sha256(simulation.parent.parent / "collection.yaml")}
""",
        encoding="utf-8",
    )
    assert main(["clear", "snapshots", str(catalogue)]) == 0
    assert not tuple(raw_output.glob("stars_*.amuse"))
    output = capsys.readouterr().out
    assert "Selected snapshots: 1" in output
    assert "Deleted snapshots: 3" in output


def test_import_snapshots_copies_only_manifest_inventory_paths(tmp_path: Path) -> None:
    """Copy an approved source snapshot once and preserve it on a repeat run."""
    source = tmp_path / "full-catalogue"
    lite = tmp_path / "lite-catalogue"
    collection_id = "example-collection"
    collection_text = """schema_version: 1
id: example-collection
importer: dcaf
config_schema_version: 1
required_parameters: []
optional_parameters: []
"""
    source_collection = source / "collections" / collection_id
    lite_collection = lite / "collections" / collection_id
    source_collection.mkdir(parents=True)
    lite_collection.mkdir(parents=True)
    (source_collection / "collection.yaml").write_text(collection_text, encoding="utf-8")
    (lite_collection / "collection.yaml").write_text(collection_text, encoding="utf-8")
    snapshot_path = Path("collections/example-collection/simulations/0001/raw/stars_000.amuse")
    source_snapshot = source / snapshot_path
    source_snapshot.parent.mkdir(parents=True)
    source_snapshot.write_bytes(b"snapshot")
    collection_hash = file_sha256(source_collection / "collection.yaml")
    inventory = {
        "schema_version": 2,
        "collection_id": collection_id,
        "collection_sha256": collection_hash,
        "summary": {"simulations": 1, "snapshots": 1, "simulations_with_issues": 0},
        "snapshot_times": {
            "0001": [
                {"path": "raw/stars_000.amuse", "time": 10.0, "size_bytes": 8}
            ]
        },
        "issues": {},
    }
    (lite_collection / "snapshot-times.yaml").write_text(
        yaml.safe_dump(inventory, sort_keys=False),
        encoding="utf-8",
    )
    (lite / "lite.yaml").write_text(
        yaml.safe_dump(
            {
                "schema_version": 1,
                "source": {
                    "catalogue_root": str(source),
                    "hostname": socket.gethostname(),
                    "collection_id": collection_id,
                    "collection_sha256": collection_hash,
                },
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    manifest = tmp_path / "snapshots.yaml"
    manifest.write_text(
        yaml.safe_dump(
            {
                "schema_version": 2,
                "source": {
                    "catalogue_root": str(source),
                    "hostname": socket.gethostname(),
                    "collection_id": collection_id,
                    "collection_sha256": collection_hash,
                },
                "selected_snapshots": [
                    {
                        "simulation_id": "0001",
                        "snapshot_time": 10.0,
                        "source_paths": [str(snapshot_path)],
                    }
                ],
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )

    first = import_snapshots(lite, manifest)
    assert first.copied_paths == (snapshot_path,)
    assert (lite / snapshot_path).read_bytes() == b"snapshot"
    assert import_snapshots(lite, manifest).skipped_paths == (snapshot_path,)
