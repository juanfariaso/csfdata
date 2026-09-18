"""Catalogue configuration, metadata, and indexing for simulation collections."""

from csfdata.catalogue.lite import (
    LiteImportReport,
    LiteSource,
    file_sha256,
    import_lite_collection,
    is_lite_catalogue,
    read_lite_source,
)
from csfdata.catalogue.registry import (
    CatalogueSimulation,
    IndexReport,
    find_simulations,
    index_catalogue,
    missing_combinations,
    summarize_catalogue,
)

__all__ = [
    "CatalogueSimulation",
    "IndexReport",
    "LiteImportReport",
    "LiteSource",
    "file_sha256",
    "find_simulations",
    "import_lite_collection",
    "index_catalogue",
    "is_lite_catalogue",
    "missing_combinations",
    "read_lite_source",
    "summarize_catalogue",
]
