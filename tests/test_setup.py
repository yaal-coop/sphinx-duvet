import pytest
from sphinx.testing.util import SphinxTestApp

import sphinx_duvet


@pytest.mark.sphinx("html", testroot="basic")
def test_build_with_the_extension(app: SphinxTestApp) -> None:
    """A project that enables the extension builds without warnings."""
    app.build()
    assert "sphinx_duvet" in app.extensions
    assert app.extensions["sphinx_duvet"].version == sphinx_duvet.__version__
    assert app.warning.getvalue() == ""


@pytest.mark.sphinx("html", testroot="basic")
def test_parallel_safety(app: SphinxTestApp) -> None:
    """The extension declares itself safe for parallel builds."""
    extension = app.extensions["sphinx_duvet"]
    assert extension.parallel_read_safe
    assert extension.parallel_write_safe
