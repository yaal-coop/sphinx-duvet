import re
import shutil
import stat
import sys
from collections.abc import Callable
from pathlib import Path

import pytest
from docutils import nodes
from sphinx.errors import ExtensionError
from sphinx.testing.util import SphinxTestApp

import sphinx_duvet
from sphinx_duvet import _render as render
from sphinx_duvet._autoreport import _page_name
from sphinx_duvet._labels import duvet_label

PROJECT = Path(__file__).parent / "projects" / "basic"
CONF = {
    "duvet_root": str(PROJECT),
    "duvet_report_json": str(PROJECT / "report.json"),
}


def tables(app: SphinxTestApp, docname: str) -> list[nodes.table]:
    """Return the tables of a document."""
    return list(app.env.get_doctree(docname).findall(nodes.table))


def rows(table: nodes.table) -> list[list[str]]:
    """Return the text of the cells of a table body."""
    return [
        [" ".join(entry.astext().split()) for entry in row.findall(nodes.entry)]
        for row in table.findall(nodes.row)
        if isinstance(row.parent, nodes.tbody)
    ]


def headers(table: nodes.table) -> list[str]:
    """Return the text of the header cells of a table."""
    return [
        entry.astext()
        for entry in next(table.findall(nodes.thead)).findall(nodes.entry)
    ]


def warnings(app: SphinxTestApp) -> list[str]:
    """Return the warnings of a build."""
    return [line for line in app.warning.getvalue().splitlines() if "WARNING" in line]


@pytest.mark.sphinx("html", testroot="report", confoverrides=CONF, freshenv=True)
def test_setup(app: SphinxTestApp) -> None:
    """The extension declares its version and is safe for parallel builds."""
    extension = app.extensions["sphinx_duvet"]
    assert extension.version == sphinx_duvet.__version__
    assert extension.parallel_read_safe
    assert extension.parallel_write_safe


@pytest.mark.sphinx("html", testroot="report", confoverrides=CONF, freshenv=True)
def test_report(app: SphinxTestApp) -> None:
    """The report has a row per requirement and a column per target."""
    app.build()
    [table] = tables(app, "report")
    assert headers(table) == [
        "Section",
        "Requirement",
        "server-flask",
        "server-django",
        "client",
    ]
    body = rows(table)
    assert len(body) == 11
    assert body[0][0] == "2 MUST"
    assert (
        body[0][1] == "The client MUST send the token. src/client.py:2 (implementation)"
    )
    assert body[0][2:] == ["∅", "∅", "impl. ✔ test ✘"]
    assert body[5][2:] == ["?", "?", "?"]


@pytest.mark.sphinx("html", testroot="report", confoverrides=CONF, freshenv=True)
def test_report_links(app: SphinxTestApp) -> None:
    """Sections link to the RFC, and cites link to the code."""
    app.build()
    doctree = app.env.get_doctree("report")
    uris = [ref["refuri"] for ref in doctree.findall(nodes.reference)]
    assert "https://www.rfc-editor.org/rfc/rfc9999#section-2" in uris
    assert "https://github.com/example/project/blob/main/src/client.py#L2" in uris


@pytest.mark.sphinx("html", testroot="report", confoverrides=CONF, freshenv=True)
def test_report_text(app: SphinxTestApp) -> None:
    """Key words, levels, reasons and notes are rendered."""
    app.build()
    doctree = app.env.get_doctree("report")
    classes = {c for node in doctree.findall(nodes.inline) for c in node["classes"]}
    assert {"duvet-bcp14-must", "duvet-bcp14-should", "duvet-bcp14-may"} <= classes
    assert {"duvet-level-must", "duvet-level-should", "duvet-level-may"} <= classes
    assert "Caching is up to the application." in doctree.astext()
    [note] = [
        n for n in doctree.findall(nodes.container) if "duvet-note" in n["classes"]
    ]
    assert next(note.findall(nodes.emphasis)).astext() == "logging"
    legend = next(
        p for p in doctree.findall(nodes.paragraph) if "duvet-legend" in p["classes"]
    )
    assert "deliberate deviation" in legend.astext()


@pytest.mark.sphinx("html", testroot="report", confoverrides=CONF, freshenv=True)
def test_report_options(app: SphinxTestApp) -> None:
    """Targets, groups, sections, levels and states narrow the report.

    Gaps are the requirements studied but not done. Unannotated requirements are shown apart.
    """
    app.build()
    missing, unannotated, may, nothing = (
        section
        for section in app.env.get_doctree("grouped").findall(nodes.section)
        if section.parent is not None and isinstance(section.parent, nodes.section)
    )
    [table] = missing.findall(nodes.table)
    assert headers(table) == ["Section", "Requirement", "server"]
    assert [re.split(" (?:src|\\.duvet)/", row[1])[0] for row in rows(table)] == [
        "The server SHOULD log the request.",
        "The server MUST validate the café parameter and the response MUST be encoded as JSON.",
        "The server MUST reject replayed tokens and SHOULD alert the administrator.",
        "reject expired tokens,",
    ]
    [table] = unannotated.findall(nodes.table)
    assert [row[1] for row in rows(table)] == [
        "Servers SHOULD rotate their keys.",
        "The server MUST:",
        "reject revoked tokens.",
    ]
    [table] = may.findall(nodes.table)
    assert [row[0] for row in rows(table)] == ["2.1 MAY"]
    assert not list(nothing.findall(nodes.table))
    assert "No requirement matches this view." in nothing.astext()


@pytest.mark.sphinx("html", testroot="report", confoverrides=CONF, freshenv=True)
def test_recap(app: SphinxTestApp) -> None:
    """The recap counts the requirements per level and per group of targets."""
    app.build()
    every, one = tables(app, "recap")
    assert headers(every)[:3] == ["Level", "Targets", "Rules"]
    assert rows(every) == [
        ["MUST", "server", "7", "2", "0", "2", "1", "2", "3/4"],
        ["SHOULD", "server", "3", "0", "0", "1", "0", "2", "0/1"],
        ["MUST", "client", "4", "2", "0", "1", "0", "1", "0/2"],
        ["SHOULD", "client", "2", "0", "0", "0", "0", "2", "0/0"],
        ["MAY", "client", "1", "0", "1", "0", "0", "0", "0/0"],
    ]
    assert [row[:3] for row in rows(one)] == [
        ["MUST", "server-flask", "7"],
        ["MUST", "server-django", "7"],
        ["MUST", "client", "4"],
    ]
    classes = {c for node in every.findall(nodes.paragraph) for c in node["classes"]}
    assert {"duvet-todo", "duvet-missing"} <= classes


@pytest.mark.sphinx("html", testroot="report", confoverrides=CONF, freshenv=True)
def test_warnings(app: SphinxTestApp) -> None:
    """Unknown specifications, invalid selectors and unused entries are reported."""
    app.build()
    messages = warnings(app)
    assert (
        sum(
            "errors.rst:4: WARNING: unknown specification spec/unknown.txt" in m
            for m in messages
        )
        == 1
    )
    assert (
        sum(
            "errors.rst:6: WARNING: unknown specification spec/unknown.txt" in m
            for m in messages
        )
        == 1
    )
    assert sum("Invalid selector 'role'" in m for m in messages) == 2
    assert any(
        f"{PROJECT}/.duvet/targets.toml:70: WARNING: no requirement matches the [[applies]] entry"
        in m
        for m in messages
    )
    assert any(
        f"{PROJECT}/.duvet/notes/rfc9999.rst:8: WARNING: no requirement matches the note"
        in m
        for m in messages
    )
    assert len(messages) == 6


@pytest.mark.sphinx("html", testroot="report", confoverrides=CONF, freshenv=True)
def test_dependencies(app: SphinxTestApp) -> None:
    """A page with a report is read again when the annotated files or the report change."""
    app.build()
    dependencies = {str(path) for path in app.env.dependencies["report"]}
    assert str(PROJECT / "report.json") in dependencies
    assert str(PROJECT / "src/client.py") in dependencies
    assert str(PROJECT / ".duvet/notes/rfc9999.rst") in dependencies


@pytest.mark.sphinx("html", testroot="report", confoverrides=CONF, freshenv=True)
def test_stylesheet(app: SphinxTestApp) -> None:
    """The stylesheet is copied and linked in the HTML pages."""
    app.build()
    assert (Path(app.outdir) / "_static/duvet.css").exists()
    assert "_static/duvet.css" in (Path(app.outdir) / "report.html").read_text()


@pytest.mark.sphinx("html", testroot="missing-config", freshenv=True)
def test_missing_config(app: SphinxTestApp) -> None:
    """Without a Duvet project, a warning is shown and the directives render nothing."""
    app.build()
    [message] = warnings(app)
    assert "no .duvet/config.toml found above" in message
    assert not tables(app, "index")


@pytest.mark.sphinx(
    "html",
    testroot="missing-config",
    confoverrides={"duvet_root": str(PROJECT), "duvet_report_json": "missing.json"},
)
def test_missing_report(
    make_app: Callable[..., SphinxTestApp], app_params: tuple
) -> None:
    """A report that cannot be read stops the build."""
    args, kwargs = app_params
    with pytest.raises(ExtensionError, match="Cannot load the Duvet report"):
        make_app(*args, **kwargs)


@pytest.mark.sphinx(
    "html",
    testroot="missing-config",
    confoverrides={"duvet_root": str(PROJECT), "duvet_executable": "/missing/duvet"},
)
def test_missing_duvet(
    make_app: Callable[..., SphinxTestApp], app_params: tuple
) -> None:
    """Without a report file, Duvet runs during the build. If it is missing, the build stops."""
    args, kwargs = app_params
    with pytest.raises(ExtensionError, match="Duvet is not installed"):
        make_app(*args, **kwargs)


@pytest.mark.sphinx(
    "html",
    testroot="autoreport",
    srcdir="autoreport-pages",
    confoverrides={
        **CONF,
        "duvet_autoreport": {"group-by": "role", "show": "unannotated"},
        "suppress_warnings": ["duvet.unused"],
    },
)
def test_autoreport(app: SphinxTestApp) -> None:
    """A page is generated per specification, with an index."""
    folder = Path(app.srcdir) / "compliance"
    assert sorted(path.name for path in folder.iterdir()) == [
        "extension.rst",
        "index.rst",
        "rfc9999.rst",
    ]
    assert (folder / "rfc9999.rst").read_text() == (
        "RFC 9999: Example Token Exchange Protocol\n"
        "=========================================\n\n"
        "Specification: https://www.rfc-editor.org/rfc/rfc9999\n\n"
        ".. duvet-recap:: spec/rfc9999.txt\n"
        "   :group-by: role\n\n"
        ".. duvet-report:: spec/rfc9999.txt\n"
        "   :group-by: role\n"
        "   :show: unannotated\n"
    )
    assert "Specification:" not in (folder / "extension.rst").read_text()
    assert (folder / "index.rst").read_text() == (
        "Specification compliance\n"
        "========================\n\n"
        ".. duvet-recap::\n"
        "   :group-by: role\n\n"
        ".. toctree::\n"
        "   :maxdepth: 1\n\n"
        "   extension\n"
        "   rfc9999\n"
    )
    app.build()
    assert warnings(app) == []
    recap, report = tables(app, "compliance/extension")
    assert rows(recap)[0][:3] == ["SHOULD", "server", "1"]
    assert rows(report)[0][0] == "discovery SHOULD"
    assert rows(report)[0][1] == 'The server SHOULD publish its "metadata".'

    every = tables(app, "compliance/index")[0]
    assert [row[:3] for row in rows(every)][-1] == ["MAY", "client", "1"]


@pytest.mark.sphinx(
    "html",
    testroot="autoreport",
    srcdir="autoreport-unchanged",
    confoverrides={
        **CONF,
        "duvet_autoreport": {},
        "suppress_warnings": ["duvet.unused"],
    },
)
def test_autoreport_unchanged(
    app: SphinxTestApp, make_app: Callable[..., SphinxTestApp]
) -> None:
    """Pages that did not change are not written again."""
    page = Path(app.srcdir) / "compliance/rfc9999.rst"
    page.touch()
    mtime = page.stat().st_mtime_ns
    make_app("html", srcdir=app.srcdir, confoverrides=app.config.overrides)
    assert page.stat().st_mtime_ns == mtime


@pytest.mark.sphinx(
    "html", testroot="autoreport", srcdir="autoreport-none", confoverrides=CONF
)
def test_without_autoreport(app: SphinxTestApp) -> None:
    """Pages are generated only if duvet_autoreport is set."""
    assert not (Path(app.srcdir) / "compliance").exists()


def test_page_name() -> None:
    """Page names are the specification file names, and the full path if two files share a name."""
    assert _page_name("spec/rfc9999.txt", []) == "rfc9999"
    assert _page_name("other/rfc9999.txt", ["rfc9999"]) == "other-rfc9999"


@pytest.mark.sphinx("html", testroot="report", freshenv=True)
def test_run_duvet(
    make_app: Callable[..., SphinxTestApp], app_params: tuple, tmp_path: Path
) -> None:
    """Without a report file, Duvet runs during the build."""
    executable = tmp_path / "duvet"
    executable.write_text(
        f"#!{sys.executable}\nimport shutil, sys\n"
        f"shutil.copy({str(PROJECT / 'report.json')!r}, sys.argv[3])\n"
    )
    executable.chmod(executable.stat().st_mode | stat.S_IXUSR)
    args, kwargs = app_params
    kwargs["confoverrides"] = {
        "duvet_root": str(PROJECT),
        "duvet_executable": str(executable),
    }
    app = make_app(*args, **kwargs)
    app.build()
    assert len(rows(tables(app, "report")[0])) == 11
    assert str(PROJECT / "report.json") not in app.env.dependencies["report"]


@pytest.mark.sphinx("html", testroot="missing-config", freshenv=True)
def test_unused_entry_lines(
    make_app: Callable[..., SphinxTestApp], app_params: tuple, tmp_path: Path
) -> None:
    """The line of an unused entry is not shown if its quote cannot be found in the file."""
    root = tmp_path / "project"
    shutil.copytree(PROJECT, root)
    with (root / ".duvet/targets.toml").open("a") as file:
        file.write(
            "\n[[applies]]\n"
            'target = "spec/rfc9999.txt#section-9"\n'
            'quote = ""\n'
            'applies-to = "role=server"\n'
            "\n[[applies]]\n"
            'target = "spec/rfc9999.txt#section-9"\n'
            'quote = "Escaped \\u0071uote"\n'
            'applies-to = "role=server"\n'
        )
    args, kwargs = app_params
    kwargs["confoverrides"] = {
        "duvet_root": str(root),
        "duvet_report_json": str(root / "report.json"),
    }
    app = make_app(*args, **kwargs)
    messages = [m for m in warnings(app) if "section-9" in m]
    assert len(messages) == 2
    assert all(f"{root}/.duvet/targets.toml:: WARNING" in m for m in messages)


def test_bcp14_text() -> None:
    """Key words are marked at the start, in the middle and at the end of a text."""
    result = render.bcp14_text("MUST do or MAY")
    assert [node.astext() for node in result] == ["MUST", " do or ", "MAY"]
    assert [type(node) for node in result] == [nodes.inline, nodes.Text, nodes.inline]


@pytest.mark.sphinx("html", testroot="report", confoverrides=CONF, freshenv=True)
def test_label_descriptions(app: SphinxTestApp) -> None:
    """Each label shows the description of its state on hover."""
    app.build()
    doctree = app.env.get_doctree("report")
    labels = {
        node.astext(): node["explanation"] for node in doctree.findall(duvet_label)
    }
    assert labels == {
        "✔": "done",
        "✘": "missing",
        "?": "not annotated yet",
        "…": "planned",
        "½": "partly done",
        "≠": "deliberate deviation",
        "—": "no test expected",
        "∅": "not applicable",
    }
    assert (
        '<abbr class="duvet-status duvet-ok" title="done">✔</abbr>'
        in (Path(app.outdir) / "report.html").read_text()
    )


@pytest.mark.sphinx(
    "html",
    testroot="report",
    confoverrides={**CONF, "duvet_labels": "text"},
    freshenv=True,
)
def test_text_labels(app: SphinxTestApp) -> None:
    """With the text preset, the legend leaves out the descriptions that repeat a label."""
    app.build()
    [table] = tables(app, "report")
    assert rows(table)[0][2:] == ["n/a", "n/a", "impl. done test missing"]
    doctree = app.env.get_doctree("report")
    legend = next(
        p for p in doctree.findall(nodes.paragraph) if "duvet-legend" in p["classes"]
    )
    assert legend.astext().startswith(
        "done · missing · not annotated not annotated yet · todo planned"
    )


@pytest.mark.sphinx(
    "html",
    testroot="report",
    confoverrides={
        **CONF,
        "duvet_labels": {"ok": "*yes*", "missing": ":sup:`no`"},
    },
    freshenv=True,
)
def test_markup_labels(app: SphinxTestApp) -> None:
    """Labels are inline markup, such as an icon role. Other states keep their symbol."""
    app.build()
    [table] = tables(app, "report")
    assert rows(table)[0][2:] == ["∅", "∅", "impl. yes test no"]
    doctree = app.env.get_doctree("report")
    ok = next(n for n in doctree.findall(duvet_label) if n.astext() == "yes")
    assert isinstance(ok[0], nodes.emphasis)
    assert ok["explanation"] == "done"


@pytest.mark.sphinx(
    "html",
    testroot="report",
    confoverrides={**CONF, "duvet_labels": {"ok": ":unknown-role:`x`", "done": "x"}},
    freshenv=True,
)
def test_invalid_labels(app: SphinxTestApp) -> None:
    """Unknown keys and invalid markup are reported."""
    app.build()
    messages = warnings(app)
    assert sum("unknown duvet_labels key 'done'" in m for m in messages) == 1
    assert (
        'report.rst:4: ERROR: Unknown interpreted text role "unknown-role"'
        in app.warning.getvalue()
    )


@pytest.mark.sphinx(
    "html",
    testroot="report",
    confoverrides={**CONF, "duvet_labels": "emoji"},
    freshenv=True,
)
def test_unknown_preset(app: SphinxTestApp) -> None:
    """An unknown preset is reported, and the symbols are used."""
    app.build()
    assert any(
        "unknown duvet_labels preset 'emoji', expected 'symbols' or 'text'" in m
        for m in warnings(app)
    )
    [table] = tables(app, "report")
    assert rows(table)[0][2:] == ["∅", "∅", "impl. ✔ test ✘"]


@pytest.mark.sphinx("text", testroot="report", confoverrides=CONF, freshenv=True)
def test_text_builder(app: SphinxTestApp) -> None:
    """Formats other than HTML show the labels without their description."""
    app.build()
    text = (Path(app.outdir) / "report.txt").read_text()
    assert "✔ done · ✘ missing" in text
    assert "(done)" not in text
