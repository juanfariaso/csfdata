from pathlib import Path

import pytest

from csfdata.importer.validation import validate_relative_simulation_path


def test_validate_relative_simulation_path_rejects_unsafe_paths() -> None:
    validate_relative_simulation_path(Path("M1000/tff3.0/07"))

    for path in (Path("."), Path("../outside"), Path("/absolute/path")):
        with pytest.raises(ValueError):
            validate_relative_simulation_path(path)
