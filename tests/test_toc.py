from pathlib import Path

import pytest
from docutils import nodes
from sphinx.testing.util import SphinxTestApp

from sphinx_duvet._toc import _entries

PROJECT = Path(__file__).parent / "projects" / "basic"
CONF = {
    "duvet_root": str(PROJECT),
    "duvet_report_json": str(PROJECT / "report.json"),
}


def titles(node: nodes.Element) -> list:
    """Return the titles of a list of entries, with the titles of their children."""
    result = []
    for item in node.children:
        if not isinstance(item, nodes.list_item):
            continue
        title = next(item.findall(nodes.reference)).astext()
        children = [c for c in item.children if isinstance(c, nodes.bullet_list)]
        result.append((title, titles(children[0])) if children else title)
    return result


def test_entries_nested_by_number() -> None:
    """Sections are nested by their numbers, even when a parent section has no row."""
    entries = _entries(
        "report",
        [
            ("a", "2. Requests", "2"),
            ("b", "2.1. Parameters", "2.1"),
            ("c", "2.1.3. Values", "2.1.3"),
            ("d", "3.1. Background", "3.1"),
            ("e", "3.1.1. Details", "3.1.1"),
        ],
    )
    assert titles(entries) == [
        ("2. Requests", [("2.1. Parameters", ["2.1.3. Values"])]),
        ("3.1. Background", ["3.1.1. Details"]),
    ]
    assert next(entries.findall(nodes.reference))["anchorname"] == "#a"


@pytest.mark.sphinx("html", testroot="report", confoverrides=CONF, freshenv=True)
def test_report_sections_in_toc(app: SphinxTestApp) -> None:
    """The sections of a report are in the table of contents of its page."""
    app.build()
    toc = app.env.tocs["report"]
    assert titles(toc) == [
        ("Report", [("2. Requests", ["2.1. Parameters"]), "3. Security"]),
    ]
    assert app.env.toc_num_entries["report"] == 4
    html = (Path(app.outdir) / "report.html").read_text()
    assert 'href="#duvet-section-rfc9999-2.1"' in html


@pytest.mark.sphinx("html", testroot="toc", confoverrides=CONF, freshenv=True)
def test_report_sections_below_their_section(app: SphinxTestApp) -> None:
    """The sections of a report go below the section that shows it, even in a container.

    A page without a title has no entry to put them below.
    """
    app.build()
    assert titles(app.env.tocs["index"]) == [
        (
            "Toc",
            [
                "Recap",
                ("Report", [("2. Requests", ["2.1. Parameters"]), "3. Security"]),
            ],
        ),
    ]
    assert titles(app.env.tocs["contained"]) == [
        ("Contained", [("2. Requests", ["2.1. Parameters"]), "3. Security"]),
    ]
    assert titles(app.env.tocs["untitled"]) == []
