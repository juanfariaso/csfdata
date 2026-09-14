"""Catalogue configuration, metadata, and indexing for simulation collections."""

from csfdata.catalogue.lite import (
    LiteExportReport,
    LiteSource,
    export_lite_collection,
    file_sha256,
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
    "LiteExportReport",
    "LiteSource",
    "export_lite_collection",
    "file_sha256",
    "find_simulations",
    "index_catalogue",
    "is_lite_catalogue",
    "missing_combinations",
    "read_lite_source",
    "summarize_catalogue",
]
