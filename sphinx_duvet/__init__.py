"""Sphinx extension for specification compliance reports from Duvet."""

from importlib import metadata
from pathlib import Path
from typing import Any

from sphinx.application import Sphinx
from sphinx.config import Config

from ._autoreport import generate_pages
from ._directives import DuvetRecap
from ._directives import DuvetReport
from ._labels import check_labels
from ._labels import depart_label_html
from ._labels import duvet_label
from ._labels import visit_label_html
from ._project import load_project

__version__ = metadata.version("sphinx-duvet")

_STATIC = Path(__file__).parent / "static"


def _add_static_path(app: Sphinx, config: Config) -> None:
    """Add the folder of the stylesheet to the static files of the HTML output."""
    config.html_static_path.append(str(_STATIC))


def setup(app: Sphinx) -> dict[str, Any]:
    """Register the extension in Sphinx."""
    app.add_config_value("duvet_root", None, "env", types=[str])
    app.add_config_value("duvet_report_json", None, "env", types=[str])
    app.add_config_value("duvet_executable", "duvet", "env", types=[str])
    app.add_config_value("duvet_autoreport", None, "env", types=[dict])
    app.add_config_value("duvet_autoreport_dir", "compliance", "env", types=[str])
    app.add_config_value("duvet_labels", "symbols", "env", types=[str, dict])
    app.add_node(duvet_label, html=(visit_label_html, depart_label_html))
    app.add_directive("duvet-report", DuvetReport)
    app.add_directive("duvet-recap", DuvetRecap)
    app.add_css_file("duvet.css")
    app.connect("config-inited", _add_static_path)
    app.connect("config-inited", check_labels)
    app.connect("builder-inited", load_project)
    app.connect("builder-inited", generate_pages)
    return {
        "version": __version__,
        "parallel_read_safe": True,
        "parallel_write_safe": True,
    }
