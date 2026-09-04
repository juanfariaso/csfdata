import pytest

from csfdata.discovery.base import GridDiscoverer


def test_grid_discoverer_cannot_be_instantiated_without_discover() -> None:
    with pytest.raises(TypeError):
        GridDiscoverer()
