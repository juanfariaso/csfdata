"""Catalogue configuration, metadata, and indexing for simulation collections."""

from csfdata.catalogue.registry import (
    IndexReport,
    index_catalogue,
    missing_combinations,
    summarize_catalogue,
)

__all__ = ["IndexReport", "index_catalogue", "missing_combinations", "summarize_catalogue"]
