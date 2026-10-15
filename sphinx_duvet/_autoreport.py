"""Generate a compliance page per specification, as autosummary does for modules."""

from pathlib import Path

from sphinx.application import Sphinx

from ._project import get_project

_RECAP_OPTIONS = ("targets", "group-by", "sections", "levels")


def generate_pages(app: Sphinx) -> None:
    """Write an index page and a page per specification in the source folder."""
    defaults: dict[str, str] | None = app.config.duvet_autoreport
    loaded = get_project(app.srcdir)
    if defaults is None or loaded is None:
        return
    project = loaded.project
    folder = Path(app.srcdir, app.config.duvet_autoreport_dir)
    folder.mkdir(parents=True, exist_ok=True)
    report_options = _options(defaults)
    recap_options = _options(
        {key: value for key, value in defaults.items() if key in _RECAP_OPTIONS}
    )

    pages: list[str] = []
    for spec in project.specifications.values():
        name = _page_name(spec.path, pages)
        pages.append(name)
        content = _title(spec.title)
        if spec.url:
            content += f"Specification: {spec.url}\n\n"
        content += f".. duvet-recap:: {spec.path}\n{recap_options}\n"
        content += f".. duvet-report:: {spec.path}\n{report_options}"
        _write_if_changed(folder / f"{name}.rst", content)

    index = _title("Specification compliance")
    index += f".. duvet-recap::\n{recap_options}\n"
    index += ".. toctree::\n   :maxdepth: 1\n\n"
    index += "".join(f"   {name}\n" for name in pages)
    _write_if_changed(folder / "index.rst", index)


def _page_name(path: str, taken: list[str]) -> str:
    """Return the file name of a page: the name of the specification file, made unique."""
    name = Path(path).stem
    if name in taken:
        name = path.replace("/", "-").rsplit(".", 1)[0]
    return name


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
