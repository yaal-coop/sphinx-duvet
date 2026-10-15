from pathlib import Path

import pytest

from sphinx_duvet.compliance import Project
from sphinx_duvet.report import Report
from sphinx_duvet.report import read_report

pytest_plugins = ("sphinx.testing.fixtures",)


@pytest.fixture(scope="session")
def rootdir() -> Path:
    """Return the folder of the Sphinx test projects."""
    return Path(__file__).parent / "roots"


@pytest.fixture(scope="session")
def basic_root() -> Path:
    """Return the folder of the basic Duvet test project."""
    return Path(__file__).parent / "projects" / "basic"


@pytest.fixture(scope="session")
def basic_report(basic_root: Path) -> Report:
    """Return the Duvet report of the basic test project."""
    return read_report(basic_root / "report.json")


@pytest.fixture
def project(basic_root: Path, basic_report: Report) -> Project:
    """Return the basic test project."""
    return Project(basic_root, basic_report)
