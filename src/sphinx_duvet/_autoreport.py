"""Generate a compliance page per specification, as autosummary does for modules."""

import re
from pathlib import Path

from sphinx.application import Sphinx
from sphinx.util import logging

from ._project import get_project

logger = logging.getLogger(__name__)

_RECAP_OPTIONS = ("targets", "group-by", "sections", "levels")


def generate_pages(app: Sphinx) -> None:
    """Write the pages of the specifications in the source folder, with two index pages.

    The compliance index lists the compliance pages, the specifications index
    lists the texts of the IETF specifications.
    """
    defaults: dict[str, str] | None = app.config.duvet_autoreport
    if defaults is None:
        return
    loaded = get_project(app.srcdir)
    if loaded is None:
        logger.warning(
            "duvet_autoreport is set, but no .duvet/config.toml found above the "
            "documentation, use duvet_root",
            type="duvet",
        )
        return
    project = loaded.project
    folder = Path(app.srcdir, app.config.duvet_autoreport_dir)
    folder.mkdir(parents=True, exist_ok=True)
    report_options = _options(defaults)
    recap_options = _options(
        {key: value for key, value in defaults.items() if key in _RECAP_OPTIONS}
    )

    pages: list[tuple[str, str]] = []
    texts: list[tuple[str, str]] = []
    for spec in project.specifications.values():
        name = _page_name(spec.path, [page for _, page in pages])
        label = _menu_title(spec.title, app.config.duvet_short_titles.get(spec.path))
        pages.append((label, name))
        content = _title(_compliance_title(spec.title))
        if spec.url:
            content += f"Specification: {spec.url}\n\n"
        if spec.format == "ietf":
            content += (
                f"Full text, with the requirements highlighted: :doc:`{name}-text`\n\n"
            )
            text = _title(spec.title) + f".. duvet-spec:: {spec.path}\n"
            _write_if_changed(folder / f"{name}-text.rst", text)
            texts.append((label, f"{name}-text"))
        if app.config.duvet_autoreport_recap:
            content += f".. duvet-recap:: {spec.path}\n{recap_options}\n"
        content += f".. duvet-report:: {spec.path}\n{report_options}"
        _write_if_changed(folder / f"{name}.rst", content)

    index = _title("Compliance")
    index += f".. duvet-recap::\n{recap_options}\n"
    index += _toctree(pages)
    _write_if_changed(folder / "index.rst", index)
    specifications = _title("Specifications")
    specifications += (
        "The texts of the specifications, with their requirements highlighted.\n\n"
    )
    specifications += _toctree(texts)
    _write_if_changed(folder / "specifications.rst", specifications)


def _toctree(pages: list[tuple[str, str]]) -> str:
    """Return a toctree of some pages, with their short titles."""
    entries = "".join(f"   {label} <{name}>\n" for label, name in pages)
    return ".. toctree::\n   :maxdepth: 1\n\n" + entries


def _short_title(title: str) -> str:
    """Return the number of an RFC, such as RFC 7643, or the whole title."""
    match = re.match(r"RFC \d+(?=: )", title)
    return match.group() if match else title


def _menu_title(title: str, short: str | None) -> str:
    """Return the title of a specification in the navigation, such as RFC 7643: Core Schema.

    It is the part of the title after its last colon, unless a short title is given.
    """
    number = _short_title(title)
    if number == title:
        return short or title
    return f"{number}: {short or title.rsplit(': ', 1)[-1]}"


def _page_name(path: str, taken: list[str]) -> str:
    """Return the file name of a page: the name of the specification file, made unique."""
    name = Path(path).stem
    if name in taken:
        name = path.replace("/", "-").rsplit(".", 1)[0]
    return name


def _compliance_title(title: str) -> str:
    """Return the title of a compliance page, such as RFC 7643 compliance."""
    return f"{_short_title(title)} compliance"


def _title(text: str) -> str:
    """Return a reStructuredText title."""
    return f"{text}\n{'=' * len(text)}\n\n"


def _options(options: dict[str, str]) -> str:
    """Return the options of a directive, one per line."""
    return "".join(f"   :{key}: {value}\n" for key, value in options.items())


def _write_if_changed(path: Path, content: str) -> None:
    """Write a file only if its content changes, so Sphinx does not read it again."""
    if path.exists() and path.read_text() == content:
        return
    path.write_text(content)
