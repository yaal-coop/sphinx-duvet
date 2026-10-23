"""Sphinx extension for specification compliance reports from Duvet."""

from importlib import metadata
from pathlib import Path
from typing import Any

from sphinx.application import Sphinx
from sphinx.config import Config

from ._autoreport import generate_pages
from ._directives import DuvetRecap
from ._directives import DuvetReport
from ._directives import DuvetSpec
from ._domain import DuvetDomain
from ._labels import check_labels
from ._labels import depart_label_html
from ._labels import duvet_label
from ._labels import visit_label_html
from ._project import load_project
from ._render import FallbackLinks
from ._render import depart_permalink_html
from ._render import duvet_permalink
from ._render import skip_permalink
from ._render import visit_permalink_html
from ._toc import add_report_sections

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
    app.add_config_value("duvet_autoreport_recap", False, "env", types=[bool])
    app.add_config_value("duvet_short_titles", {}, "env", types=[dict])
    app.add_config_value("duvet_labels", "symbols", "env", types=[str, dict])
    app.add_config_value("duvet_spec_highlight", "auto", "env", types=[str])
    app.add_config_value("duvet_figure_requirements", False, "env", types=[bool])
    app.add_node(duvet_label, html=(visit_label_html, depart_label_html))
    skip = (skip_permalink, None)
    app.add_node(
        duvet_permalink,
        html=(visit_permalink_html, depart_permalink_html),
        latex=skip,
        text=skip,
        man=skip,
        texinfo=skip,
    )
    app.add_domain(DuvetDomain)
    app.add_post_transform(FallbackLinks)
    app.add_directive("duvet-report", DuvetReport)
    app.add_directive("duvet-recap", DuvetRecap)
    app.add_directive("duvet-spec", DuvetSpec)
    app.add_css_file("duvet.css")
    app.connect("config-inited", _add_static_path)
    app.connect("config-inited", check_labels)
    app.connect("builder-inited", load_project)
    app.connect("builder-inited", generate_pages)
    # After the collector of Sphinx, which builds the table of contents.
    app.connect("doctree-read", add_report_sections, priority=600)
    return {
        "version": __version__,
        "parallel_read_safe": True,
        "parallel_write_safe": True,
    }
