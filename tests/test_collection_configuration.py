from pathlib import Path

import pytest

from csfdata.catalogue import read_collection
from csfdata.catalogue.collection import CollectionConfiguration, read_collection_configuration


def test_read_collection_configuration(tmp_path: Path) -> None:
    configuration_path = tmp_path / "collection.yaml"
    configuration_path.write_text(
        """schema_version: 1
id: dcaf-tff-grid-v1
importer: dcaf
config_schema_version: 1
required_parameters:
  - Mstars
  - tff
optional_parameters:
  - sfe
grid_axes:
  tff: [0.5, 1.0]
  sfe: [0.1, 0.3]
lite:
  include:
    - raw/background_gas*.dat
""",
        encoding="utf-8",
    )

    configuration = read_collection_configuration(configuration_path)

    assert configuration.collection_id == "dcaf-tff-grid-v1"
    assert configuration.importer == "dcaf"
    assert configuration.required_parameters == ("Mstars", "tff")
    assert configuration.optional_parameters == ("sfe",)
    assert configuration.grid_axes == (("tff", (0.5, 1.0)), ("sfe", (0.1, 0.3)))
    assert configuration.lite_include == ("raw/background_gas*.dat",)


def test_read_collection_uses_catalogue_root_and_id(tmp_path: Path) -> None:
    """Read one collection without exposing its on-disk hierarchy to callers."""
    collection_root = tmp_path / "collections" / "dcaf-tff-grid-v1"
    collection_root.mkdir(parents=True)
    (collection_root / "collection.yaml").write_text(
        """schema_version: 1
id: dcaf-tff-grid-v1
importer: dcaf
config_schema_version: 1
required_parameters: []
optional_parameters: []
grid_axes:
  tff: [0.5, 1.0]
lite:
  include: []
""",
        encoding="utf-8",
    )

    configuration = read_collection(tmp_path, "dcaf-tff-grid-v1")

    assert configuration.grid_axes == (("tff", (0.5, 1.0)),)


def test_read_collection_rejects_mismatched_directory_id(tmp_path: Path) -> None:
    """Reject a collection layout that could otherwise return the wrong configuration."""
    collection_root = tmp_path / "collections" / "expected-id"
    collection_root.mkdir(parents=True)
    (collection_root / "collection.yaml").write_text(
        """schema_version: 1
id: different-id
importer: dcaf
config_schema_version: 1
required_parameters: []
optional_parameters: []
grid_axes: {}
lite:
  include: []
""",
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="does not match"):
        read_collection(tmp_path, "expected-id")


def test_collection_configuration_rejects_shared_parameter() -> None:
    with pytest.raises(ValueError, match="both required and optional"):
        CollectionConfiguration(
            collection_id="dcaf-tff-grid-v1",
            importer="dcaf",
            config_schema_version=1,
            required_parameters=("tff",),
            optional_parameters=("tff",),
        )


def test_collection_configuration_rejects_unsafe_lite_include() -> None:
    """Reject lite support-file patterns outside a simulation raw directory."""
    with pytest.raises(ValueError, match="below raw"):
        CollectionConfiguration(
            collection_id="example-collection",
            importer="dcaf",
            config_schema_version=1,
            required_parameters=(),
            optional_parameters=(),
            lite_include=("../outside",),
        )
