"""Discovery interface for optional CSFData analysis add-ons.

Analysis packages register themselves in the ``csfdata.analysis`` entry-point
group. The core package discovers them without importing their optional science
dependencies until a caller explicitly loads one.
"""

from importlib.metadata import entry_points
from typing import Any


def available() -> tuple[str, ...]:
    """Return the names of installed CSFData analysis add-ons.

    Returns:
        Tuple[str, ...]: Sorted registered add-on names. An empty tuple means
            that no analysis add-ons are installed.
    """
    return tuple(sorted(entry_point.name for entry_point in entry_points(group="csfdata.analysis")))


def load(name: str) -> Any:
    """Load an installed analysis add-on by its registered name.

    Args:
        name: Registered add-on name returned by :func:`available`.

    Returns:
        Any: The object declared by the add-on's entry point. Its public
            interface will be defined with the first analysis product.

    Raises:
        LookupError: If no installed add-on has the requested name, or if more
            than one installed add-on uses that name.
    """
    matches = [
        entry_point
        for entry_point in entry_points(group="csfdata.analysis")
        if entry_point.name == name
    ]
    if not matches:
        raise LookupError(f"No CSFData analysis add-on is registered as {name!r}.")
    if len(matches) > 1:
        raise LookupError(f"More than one CSFData analysis add-on is registered as {name!r}.")
    return matches[0].load()

