"""Load the Duvet project of a Sphinx documentation."""

from dataclasses import dataclass
from os import PathLike
from pathlib import Path

from docutils import nodes
from sphinx.application import Sphinx
from sphinx.errors import ExtensionError
from sphinx.util import logging

from .compliance import Project
from .compliance import find_root
from .report import DuvetError
from .report import DuvetNotFound
from .report import read_report
from .targets import ConfigError

logger = logging.getLogger(__name__)


@dataclass
class LoadedProject:
    """The Duvet project of a documentation, and the report file it was read from."""

    project: Project
    report: Path | None


# Loaded projects by source folder. Directives only get the environment,
# and the application it holds is deprecated since Sphinx 9.
_PROJECTS: dict[str, LoadedProject] = {}


def load_project(app: Sphinx) -> None:
    """Load the project once per build, and warn about entries that match nothing.

    A documentation without a Duvet project can still refer to the requirements
    of other documentations, so it is not an error.
    """
    _PROJECTS.pop(str(app.srcdir), None)
    root = _root(app)
    if root is None:
        return
    report_path = _report_file(app)
    try:
        figures = app.config.duvet_figure_requirements
        if report_path is None:
            project = Project.from_duvet(root, app.config.duvet_executable, figures)
        else:
            project = Project(root, read_report(report_path), figures)
    except DuvetNotFound as exc:
        raise ExtensionError(
            f"Cannot load the Duvet report: {exc}. "
            "Or set duvet_report_json to a report produced elsewhere."
        ) from exc
    except (DuvetError, ConfigError, OSError, KeyError, ValueError) as exc:
        raise ExtensionError(f"Cannot load the Duvet report: {exc}") from exc

    targets = root / ".duvet/targets.toml"
    for entry in project.unused_applies:
        logger.warning(
            "no requirement matches the [[applies]] entry %s: %r",
            entry.target,
            entry.quote,
            type="duvet",
            subtype="unused",
            location=_location(targets, _line_of(targets, entry.quote)),
        )
    for note in project.unused_notes:
        logger.warning(
            "no requirement matches the note %s: %r",
            note.target,
            note.quote,
            type="duvet",
            subtype="unused",
            location=_location(note.source, note.line),
        )
    _PROJECTS[str(app.srcdir)] = LoadedProject(project, report_path)


def get_project(srcdir: str | PathLike[str]) -> LoadedProject | None:
    """Return the project loaded at the start of the build of a documentation, if any."""
    return _PROJECTS.get(str(srcdir))


def _report_file(app: Sphinx) -> Path | None:
    """Return the path of the JSON report set in the configuration, if any."""
    if not app.config.duvet_report_json:
        return None
    return Path(app.confdir, app.config.duvet_report_json)


def _root(app: Sphinx) -> Path | None:
    """Return the root of the Duvet project, from the configuration or found above conf.py."""
    if app.config.duvet_root:
        return Path(app.confdir, app.config.duvet_root)
    return find_root(Path(app.confdir))


def _line_of(path: Path, text: str) -> int | None:
    """Return the number of the first line of a file that contains the start of a text."""
    lines = text.strip().splitlines()
    if not lines:
        return None
    for number, line in enumerate(path.read_text().splitlines(), start=1):
        if lines[0] in line:
            return number
    return None


def _location(path: Path, line: int | None) -> nodes.Element:
    """Return a node that points to a file, for the location of a warning."""
    # Workaround for Sphinx: a string location is read as a document name, and gets
    # a .rst suffix. A node with a source is shown as is. Remove when Sphinx accepts
    # file paths as locations.
    node = nodes.Element()
    node.source = str(path)
    node.line = line
    return node
