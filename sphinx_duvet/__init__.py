"""Sphinx extension for specification compliance reports from Duvet."""

from importlib import metadata
from typing import Any

from sphinx.application import Sphinx

__version__ = metadata.version("sphinx-duvet")


def setup(app: Sphinx) -> dict[str, Any]:
    return {
        "version": __version__,
        "parallel_read_safe": True,
        "parallel_write_safe": True,
    }
