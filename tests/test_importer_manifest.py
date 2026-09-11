from pathlib import Path

import pytest

from csfdata.importer.manifest import (
    ImportItem,
    create_import_manifest,
)
from csfdata.importer.validation import ValidatedSource


def test_import_manifest_assigns_collection_local_sequential_ids(tmp_path: Path) -> None:
    source = ValidatedSource(
        hostname="trillium",
        root=Path("/shared/dcaf-grid"),
        valid_simulation_paths=(Path("M1000/tff3.0/07"),),
    )
    manifest = create_import_manifest(source, "dcaf-tff-grid-v1")
    assert manifest.items == (ImportItem("0001", Path("M1000/tff3.0/07")),)


def test_import_item_rejects_path_outside_the_validated_source() -> None:
    with pytest.raises(ValueError, match="unsafe component"):
        ImportItem("0001", Path("../outside"))


def test_import_item_rejects_simulation_id_that_is_a_path() -> None:
    with pytest.raises(ValueError, match="safe directory name"):
        ImportItem("../outside", Path("M1000/tff3.0/07"))
