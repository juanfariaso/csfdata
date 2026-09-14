"""Catalogue configuration, metadata, and indexing for simulation collections."""

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
    "find_simulations",
    "index_catalogue",
    "missing_combinations",
    "summarize_catalogue",
]
