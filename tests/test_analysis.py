"""Tests for optional analysis add-on discovery."""

from types import SimpleNamespace

import pytest

from csfdata import analysis


def test_available_returns_sorted_plugin_names(monkeypatch: pytest.MonkeyPatch) -> None:
    """Available add-ons are reported in a stable order."""
    monkeypatch.setattr(
        analysis,
        "entry_points",
        lambda group: [
            SimpleNamespace(name="second"),
            SimpleNamespace(name="first"),
        ],
    )

    assert analysis.available() == ("first", "second")


def test_load_returns_registered_object(monkeypatch: pytest.MonkeyPatch) -> None:
    """A named entry point is loaded only when requested."""
    plugin = object()
    monkeypatch.setattr(
        analysis,
        "entry_points",
        lambda group: [
            SimpleNamespace(name="example", load=lambda: plugin),
        ],
    )

    assert analysis.load("example") is plugin


def test_load_rejects_unknown_plugin(monkeypatch: pytest.MonkeyPatch) -> None:
    """An unknown plug-in name produces a helpful error."""
    monkeypatch.setattr(analysis, "entry_points", lambda group: [])

    with pytest.raises(LookupError, match="No CSFData analysis add-on"):
        analysis.load("missing")
