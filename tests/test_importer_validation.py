from pathlib import Path

import pytest
import yaml

from csfdata.importer.validation import (
    read_validation_report,
    validate_relative_simulation_path,
)


def test_validate_relative_simulation_path_rejects_unsafe_paths() -> None:
    validate_relative_simulation_path(Path("M1000/tff3.0/07"))

    for path in (Path("."), Path("../outside"), Path("/absolute/path")):
        with pytest.raises(ValueError):
            validate_relative_simulation_path(path)


def test_read_validation_report_rejects_an_inconsistent_summary(tmp_path: Path) -> None:
    report_path = tmp_path / "validation-report.yaml"
    report_path.write_text(
        yaml.safe_dump(
            {
                "schema_version": 1,
                "source": {"hostname": "trillium", "root": "/shared/grid"},
                "summary": {
                    "total_simulations": 2,
                    "valid_simulations": 2,
                    "simulations_with_issues": 0,
                },
                "valid_simulations": ["M1000/tff3.0/07"],
                "simulations_with_issues": {},
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="summary does not match"):
        read_validation_report(report_path)
