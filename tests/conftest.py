from pathlib import Path

import pytest

pytest_plugins = ("sphinx.testing.fixtures",)


@pytest.fixture(scope="session")
def rootdir() -> Path:
    """Return the folder of the Sphinx test projects."""
    return Path(__file__).parent / "roots"
