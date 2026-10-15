import re
import shutil
import stat
import sys
import zlib
from collections.abc import Callable
from pathlib import Path

import pytest
from docutils import nodes
from sphinx.errors import ExtensionError
from sphinx.testing.util import SphinxTestApp

import sphinx_duvet
from sphinx_duvet import _render as render
from sphinx_duvet._autoreport import _page_name
from sphinx_duvet._domain import REPORT
from sphinx_duvet._domain import TEXT
from sphinx_duvet._domain import RuleLocation
from sphinx_duvet._labels import duvet_label

PROJECT = Path(__file__).parent / "projects" / "basic"
CONF = {
    "duvet_root": str(PROJECT),
    "duvet_report_json": str(PROJECT / "report.json"),
}
LAYOUT = Path(__file__).parent / "projects" / "layout"
LAYOUT_CONF = {
    "duvet_root": str(LAYOUT),
    "duvet_report_json": str(LAYOUT / "report.json"),
}


def tables(app: SphinxTestApp, docname: str) -> list[nodes.table]:
    """Return the tables of a document."""
    return list(app.env.get_doctree(docname).findall(nodes.table))


def cell_text(entry: nodes.entry) -> str:
    """Return the text of a cell, without its permalink and its links to the text."""
    entry = entry.deepcopy()
    for permalink in list(entry.findall(render.duvet_permalink)):
        permalink.parent.remove(permalink)
    for link in list(entry.findall(render.duvet_optional_link)):
        link.parent.remove(link)
    return " ".join(entry.astext().split())


def rows(table: nodes.table) -> list[list[str]]:
    """Return the text of the cells of the requirement rows of a table body."""
    return [
        [cell_text(entry) for entry in row.findall(nodes.entry)]
        for row in table.findall(nodes.row)
        if isinstance(row.parent, nodes.tbody) and "duvet-section" not in row["classes"]
    ]


def sections(table: nodes.table) -> list[str]:
    """Return the text of the section rows of a table."""
    return [
        cell_text(next(row.findall(nodes.entry)))
        for row in table.findall(nodes.row)
        if "duvet-section" in row["classes"]
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
        "Level",
        "Requirement",
        "server-flask",
        "server-django",
        "client",
    ]
    body = rows(table)
    assert len(body) == 11
    assert body[0][0] == "MUST"
    assert sections(table) == [
        "2. Requests RFC ↗",
        "2.1. Parameters RFC ↗",
        "3. Security RFC ↗",
    ]
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
    uris = [
        ref["refuri"] for ref in doctree.findall(nodes.reference) if "refuri" in ref
    ]
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
    assert headers(table) == ["Level", "Requirement", "server"]
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
    assert [row[0] for row in rows(table)] == ["MAY"]
    assert sections(table) == ["2.1. Parameters RFC ↗"]
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
    """Without a Duvet project, the directives warn and render nothing."""
    app.build()
    messages = warnings(app)
    assert len(messages) == 3
    assert "index.rst:4: WARNING: no .duvet/config.toml found above" in messages[0]
    assert "index.rst:6: WARNING: no .duvet/config.toml found above" in messages[1]
    assert "index.rst:8: WARNING: no .duvet/config.toml found above" in messages[2]
    assert not tables(app, "index")


@pytest.mark.sphinx(
    "html",
    testroot="missing-config",
    freshenv=True,
    confoverrides={"duvet_autoreport": {}},
)
def test_autoreport_without_project(app: SphinxTestApp) -> None:
    """Generated pages need a Duvet project."""
    assert (
        "duvet_autoreport is set, but no .duvet/config.toml found" in warnings(app)[0]
    )


def test_intersphinx(
    make_app: Callable[..., SphinxTestApp], rootdir: Path, tmp_path: Path
) -> None:
    """A documentation without a Duvet project refers to the requirements of another one."""
    shutil.copytree(rootdir / "test-rules", tmp_path / "provider")
    provider = make_app("html", srcdir=tmp_path / "provider", confoverrides=CONF)
    provider.build()
    shutil.copytree(rootdir / "test-consumer", tmp_path / "consumer")
    consumer = make_app(
        "html",
        srcdir=tmp_path / "consumer",
        confoverrides={
            "intersphinx_mapping": {"provider": (str(provider.outdir), None)}
        },
    )
    consumer.build()
    # A second application in the same process registers the nodes of Sphinx again,
    # which gives unrelated warnings.
    assert [m for m in warnings(consumer) if "is already registered" not in m] == []
    html = (Path(consumer.outdir) / "index.html").read_text()
    assert f'href="{provider.outdir}/report.html#duvet-rfc9999-2-1"' in html
    assert f'href="{provider.outdir}/report.html#duvet-rfc9999-2-2"' in html


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
    with pytest.raises(
        ExtensionError, match="cargo install duvet --locked. Or set duvet_report_json"
    ):
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
        "rfc9999-text.rst",
        "rfc9999.rst",
    ]
    assert (folder / "rfc9999.rst").read_text() == (
        "RFC 9999 compliance\n"
        "===================\n\n"
        "Specification: https://www.rfc-editor.org/rfc/rfc9999\n\n"
        "Full text, with the requirements highlighted: :doc:`rfc9999-text`\n\n"
        ".. toctree::\n"
        "   :hidden:\n\n"
        "   rfc9999-text\n\n"
        ".. duvet-recap:: spec/rfc9999.txt\n"
        "   :group-by: role\n\n"
        ".. duvet-report:: spec/rfc9999.txt\n"
        "   :group-by: role\n"
        "   :show: unannotated\n"
    )
    assert "Specification:" not in (folder / "extension.rst").read_text()
    assert (
        (folder / "extension.rst")
        .read_text()
        .startswith("Example extension compliance\n")
    )
    assert (folder / "rfc9999-text.rst").read_text() == (
        "RFC 9999: Example Token Exchange Protocol\n"
        "=========================================\n\n"
        ".. duvet-spec:: spec/rfc9999.txt\n"
    )
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
    assert rows(report)[0][0] == "SHOULD"
    assert sections(report) == ["Discovery"]
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
    assert "¶" not in text


@pytest.mark.sphinx("html", testroot="depending", freshenv=True)
def test_dependency_cites(
    make_app: Callable[..., SphinxTestApp], app_params: tuple, depending_root: Path
) -> None:
    """Cites of a dependency show its name and version, and link to its repository."""
    args, kwargs = app_params
    kwargs["confoverrides"] = {
        "duvet_root": str(depending_root),
        "duvet_report_json": str(depending_root / "report.json"),
    }
    app = make_app(*args, **kwargs)
    app.build()
    doctree = app.env.get_doctree("index")
    assert "fakelib/__init__.py:2 (implementation, fakelib 1.2.3)" in doctree.astext()
    uris = [
        ref["refuri"] for ref in doctree.findall(nodes.reference) if "refuri" in ref
    ]
    assert (
        "https://github.com/example/fakelib/blob/v1.2.3/src/fakelib/__init__.py#L2"
        in uris
    )


@pytest.mark.sphinx("html", testroot="rules", confoverrides=CONF, freshenv=True)
def test_rule_references(app: SphinxTestApp) -> None:
    """Requirements can be referenced with the duvet:rule and any roles."""
    app.build()
    html = (Path(app.outdir) / "index.html").read_text()
    assert (
        '<a class="reference internal" href="report.html#duvet-rfc9999-2-1" '
        'title="The client MUST send the token.">'
    ) in html
    assert 'href="report.html#duvet-rfc9999-2-2"' in html
    assert '<span class="xref duvet duvet-rule">the second rule</span></a>' in html
    assert 'href="report.html#duvet-rfc9999-2-3"' in html
    assert [m for m in warnings(app) if "rfc9999#99-1" in m] == [
        m for m in warnings(app) if "index.rst:9: WARNING: unknown requirement" in m
    ]
    assert len([m for m in warnings(app) if "rfc9999#99-1" in m]) == 1


@pytest.mark.sphinx("html", testroot="rules", confoverrides=CONF, freshenv=True)
def test_rule_anchors(app: SphinxTestApp) -> None:
    """Rows and sections have anchors, numbered when shown twice in a document."""
    app.build()
    html = (Path(app.outdir) / "twice.html").read_text()
    ids = re.findall(r'<tr[^>]* id="([^"]+)"', html)
    assert len(ids) == len(set(ids))
    assert {
        "duvet-rfc9999-2-1",
        "duvet-rfc9999-2-1~2",
        "duvet-rfc9999-2.1-2",
        "duvet-rfc9999-2.1-2~2",
        "duvet-section-rfc9999-2",
        "duvet-section-rfc9999-2.1~2",
    } <= set(ids)
    assert (
        '<a class="headerlink reference internal" href="#duvet-rfc9999-2-1" '
        'title="rfc9999#2-1">¶</a>'
    ) in html
    assert (
        '<a class="headerlink reference internal" href="#duvet-section-rfc9999-2" '
        'title="rfc9999 2. Requests">¶</a>'
    ) in html


@pytest.mark.sphinx("html", testroot="rules", confoverrides=CONF, freshenv=True)
def test_rule_inventory(app: SphinxTestApp) -> None:
    """Requirements are in the inventory, so other projects can refer to them."""
    app.build()
    domain = app.env.get_domain("duvet")
    objects = {
        name: (docname, anchor)
        for name, _, _, docname, anchor, _ in domain.get_objects()
    }
    assert objects["rfc9999#2-1"] == ("report", "duvet-rfc9999-2-1")
    assert objects["rfc9999#3-5"] == ("report", "duvet-rfc9999-3-5")
    assert b"rfc9999#2-1" in zlib.decompress(
        (Path(app.outdir) / "objects.inv").read_bytes().split(b"\n", 4)[4]
    )


@pytest.mark.sphinx("html", testroot="rules", confoverrides=CONF, freshenv=True)
def test_rule_locations(app: SphinxTestApp) -> None:
    """The places of a requirement follow the documents that are read again.

    The rule role prefers the text of the specification, the status role a report.
    """
    app.build()
    domain = app.env.get_domain("duvet")
    assert domain.location("rfc9999#2-1").docname == "report"
    domain.clear_doc("report")
    assert domain.location("rfc9999#2-1").docname == "twice"
    assert domain.location("rfc9999#3-5") is None
    domain.merge_domaindata(
        ["report", "text"],
        {
            "rules": {
                "rfc9999#2-1": [
                    RuleLocation("report", "a", REPORT, "t"),
                    RuleLocation("text", "b", TEXT, "t"),
                ],
                "other#1-1": [RuleLocation("ignored", "b", REPORT, "t")],
            }
        },
    )
    assert domain.location("rfc9999#2-1").docname == "text"
    assert domain.location("rfc9999#2-1", "status").docname == "report"
    assert domain.location("other#1-1") is None


@pytest.mark.sphinx(
    "html",
    testroot="report",
    confoverrides={**CONF, "html_permalinks": False},
    freshenv=True,
)
def test_without_permalinks(app: SphinxTestApp) -> None:
    """Rows keep their anchor, but show no permalink when permalinks are disabled."""
    app.build()
    html = (Path(app.outdir) / "report.html").read_text()
    assert 'id="duvet-rfc9999-2-1"' in html
    assert "headerlink" not in html


def test_link_without_uri() -> None:
    """Without an address, a link is plain text, such as a cite without a repository link."""
    assert isinstance(render.link("src/a.py:1", None), nodes.Text)


@pytest.mark.sphinx("html", testroot="spec", confoverrides=CONF, freshenv=True)
def test_spec_text(app: SphinxTestApp) -> None:
    """The text of a specification has its sections, with the requirements highlighted."""
    app.build()
    doctree = app.env.get_doctree("text")
    titles = [section[0].astext() for section in doctree.findall(nodes.section)][1:]
    assert titles == [
        "Abstract",
        "1. Introduction",
        "2. Requests",
        "2.1. Parameters",
        "3. Security",
    ]
    nested = next(
        s for s in doctree.findall(nodes.section) if s["ids"] == ["section-2.1"]
    )
    assert nested.parent["ids"] == ["section-2"]
    legend = next(doctree.findall(nodes.paragraph))
    assert legend.astext().startswith("Requirements: done · partly done or planned")
    header = next(doctree.findall(nodes.table))
    assert "duvet-front-matter" in header["classes"]
    assert "Request for Comments: 9999" in header.astext()
    assert (
        "Example Token Exchange Protocol"
        not in header.parent.astext().split("Abstract")[0]
    )
    html = (Path(app.outdir) / "text.html").read_text()
    assert (
        '<span class="duvet-rule duvet-rule-partial" id="duvet-text-rfc9999-2.1-1">'
        "The server <span" in html
    )
    assert (
        'class="duvet-rule duvet-rule-unannotated" id="duvet-text-rfc9999-3-1"' in html
    )
    assert (
        'send the token.</span><a class="reference internal" '
        'href="report.html#duvet-rfc9999-2-1" title="The client MUST send the token.">'
        '<span class="duvet-rule-link">¶</span></a>'
    ) in html
    assert "The server MUST validate the café parameter" in doctree.astext()


@pytest.mark.sphinx("html", testroot="spec", confoverrides=CONF, freshenv=True)
def test_spec_roles(app: SphinxTestApp) -> None:
    """The rule role links to the text, the status role to the report."""
    app.build()
    html = (Path(app.outdir) / "index.html").read_text()
    assert 'href="text.html#duvet-text-rfc9999-2-1"' in html
    assert 'href="report.html#duvet-rfc9999-2-1"' in html
    messages = warnings(app)
    assert any(
        "index.rst:9: WARNING: no report shows the requirement extension#discovery-1"
        in m
        for m in messages
    )
    assert any(
        "index.rst:12: WARNING: duvet-spec only shows IETF text specifications, "
        "not spec/extension.md" in m
        for m in messages
    )
    assert any(
        "index.rst:14: WARNING: unknown specification spec/unknown.txt" in m
        for m in messages
    )


@pytest.mark.sphinx("html", testroot="spec", confoverrides=CONF, freshenv=True)
def test_spec_without_report(app: SphinxTestApp) -> None:
    """Without a report, requirements in the text are highlighted, but are not links."""
    (Path(app.srcdir) / "report.rst").write_text("Report\n======\n")
    app.build()
    html = (Path(app.outdir) / "text.html").read_text()
    assert 'id="duvet-text-rfc9999-2-1"' in html
    assert "report.html#duvet-rfc9999" not in html
    assert "duvet-rule-link" not in html


@pytest.mark.sphinx("text", testroot="spec", confoverrides=CONF, freshenv=True)
def test_spec_text_builder(app: SphinxTestApp) -> None:
    """Out of HTML, requirements have no link to their report."""
    app.build()
    text = (Path(app.outdir) / "text.txt").read_text()
    assert "The client MUST send the token." in text
    assert "¶" not in text


@pytest.mark.sphinx("html", testroot="layout", confoverrides=LAYOUT_CONF, freshenv=True)
def test_spec_layout(app: SphinxTestApp) -> None:
    """The text keeps its structure: header, contents, definitions, lists, tables and figures."""
    app.build()
    assert warnings(app) == []
    doctree = app.env.get_doctree("index")
    header, *spec_tables = tables(app, "index")
    assert [row.astext().split("\n\n") for row in header.findall(nodes.row)][:2] == [
        ["Internet Engineering Task Force (IETF)", "A. Author"],
        ["Request for Comments: 9997", "Example Org"],
    ]
    blocks = [block.astext() for block in doctree.findall(nodes.literal_block)]
    assert blocks[0] == "Updated Edition"
    assert not any("Example Layout Protocol" in block for block in blocks)

    contents = next(
        node
        for node in doctree.findall(nodes.bullet_list)
        if "duvet-contents" in node["classes"]
    )
    assert [ref["refid"] for ref in contents.findall(nodes.reference)] == [
        "section-1",
        "section-1.1",
        "section-2",
        "section-3",
        "section-4",
        "appendix-A",
        "name-author-s-address",
    ]
    terms = [term.astext() for term in doctree.findall(nodes.term)]
    assert terms == [
        "Client",
        "Server",
        "Token",
        "Endpoint",
        "[RFC9998]",
        "[OTHER]",
        "Unlabeled",
    ]

    lists = [
        [item.astext().removesuffix("¶") for item in node.children]
        for node in doctree.findall(nodes.bullet_list)
        if node is not contents and node.parent is not contents
    ]
    assert lists[-2:] == [
        ["The client MUST send a token.", "a name,\n\nwith a second paragraph."],
        ["(A) The client sends a request.", "(B) The server answers."],
    ]

    captions = [
        table[0].astext() for table in spec_tables if table[0].tagname == "title"
    ]
    assert captions == ["Table 1: Parameters", "Table 2: Methods"]
    parameters = [
        row.astext().replace("¶", "").split("\n\n")
        for row in spec_tables[0].findall(nodes.row)
    ]
    assert parameters == [
        ["Name", "Use"],
        ["token", "The server MUST check it."],
        ["name", ""],
    ]
    assert not list(spec_tables[1].findall(nodes.thead))

    lines = [line.astext() for line in doctree.findall(nodes.line)]
    assert lines == [
        "A. Author",
        "Example Org",
        "Email: author@example.org",
        "Email: author@yaal.coop",
    ]

    html = (Path(app.outdir) / "index.html").read_text()
    assert '<div class="duvet-figure highlight-http notranslate">' in html
    [wrapper] = [
        node
        for node in doctree.findall(nodes.container)
        if "duvet-figure-wrapper" in node["classes"]
    ]
    assert [child.tagname for child in wrapper.children] == ["literal_block", "caption"]
    assert '<span class="caption-text">Figure 1: A token</span>' in html
    assert html.count("highlight-json") == 2
    assert 'class="duvet-rule-link"' not in html
    assert (
        'answer as in <a class="reference internal" href="#section-2">Section 2</a>.'
        in html
    )
    assert (
        'per <a class="reference internal" href="#section-2">Section 2</a> and Section 9.'
        in html
    )
    assert (
        'href="https://www.rfc-editor.org/rfc/rfc9998#section-4">Section 4</a>' in html
    )
    assert (
        'href="https://www.rfc-editor.org/rfc/rfc9999#section-1">Section 1</a>' in html
    )
    assert (
        '<a class="reference internal" href="#reference-rfc9998">[RFC9998]</a>' in html
    )
    assert 'href="https://www.rfc-editor.org/rfc/rfc1234">[RFC1234]</a>' in html
    assert '<a class="reference internal" href="#reference-other">[OTHER]</a>' in html
    assert "server at https://example.com/ per" in html
    assert "but not [NOWHERE]." in html
    assert (
        '<p><a class="reference internal" href="#section-3">Section 3</a> has' in html
    )
    assert '<dt id="reference-rfc9998">' in html
    assert 'href="#appendix-A">Appendix A</a>' in html
    assert 'href="mailto:' in html

    domain = app.env.get_domain("duvet")
    assert domain.location("rfc9997#2-1").anchor == "duvet-text-rfc9997-2-1"
    assert domain.location("rfc9997#2-2").anchor == "duvet-text-rfc9997-2-2"
    assert domain.location("rfc9997#name-table-of-contents-1").anchor == (
        "name-table-of-contents"
    )
    assert domain.location("rfc9997#3-1") is None


@pytest.mark.sphinx(
    "html",
    testroot="layout",
    confoverrides={**LAYOUT_CONF, "duvet_figure_requirements": True},
    freshenv=True,
)
def test_spec_figure_requirements(app: SphinxTestApp) -> None:
    """The requirements of figures can be kept. They link to the section of their figure."""
    app.build()
    domain = app.env.get_domain("duvet")
    assert domain.location("rfc9997#3-1").anchor == "section-3"


@pytest.mark.sphinx("html", testroot="layout", confoverrides=LAYOUT_CONF, freshenv=True)
def test_spec_highlight_option(app: SphinxTestApp) -> None:
    """The highlight option sets the language of every figure, or disables highlighting."""
    app.build()
    plain = (Path(app.outdir) / "plain.html").read_text()
    assert "highlight-json" not in plain
    assert "highlight-http" not in plain
    json = (Path(app.outdir) / "json.html").read_text()
    assert json.count("highlight-json") == 2
    assert "highlight-http" not in json


@pytest.mark.sphinx(
    "html",
    testroot="layout",
    confoverrides={**LAYOUT_CONF, "duvet_spec_highlight": "nope"},
    freshenv=True,
)
def test_spec_highlight_config(app: SphinxTestApp) -> None:
    """An unknown language in the configuration is reported, and figures are highlighted automatically."""
    (Path(app.srcdir) / "plain.rst").write_text(
        "Plain\n=====\n\n.. duvet-spec:: spec/rfc9997.txt\n   :highlight: nope\n"
    )
    app.build()
    messages = warnings(app)
    assert any(
        "index.rst:9: WARNING: duvet_spec_highlight: unknown Pygments lexer 'nope'" in m
        for m in messages
    )
    output = app.warning.getvalue()
    assert 'plain.rst:4: ERROR: Error in "duvet-spec" directive' in output
    assert "unknown Pygments lexer 'nope'" in output.split("plain.rst:4")[1]
    html = (Path(app.outdir) / "index.html").read_text()
    assert "highlight-http" in html


@pytest.mark.sphinx(
    "html", testroot="spec", srcdir="spec-links", confoverrides=CONF, freshenv=True
)
def test_report_links_to_text(app: SphinxTestApp) -> None:
    """A report links each section and each requirement to the text of the specification."""
    app.build()
    doctree = app.env.get_doctree("report")
    html = (Path(app.outdir) / "report.html").read_text()
    section = re.search(
        r'id="duvet-section-rfc9999-2".*?<span class="duvet-section-link">(.*?)</span></p>',
        html,
        re.DOTALL,
    )
    assert section is not None
    assert re.findall(r'href="([^"]+)"', section.group(1)) == [
        "text.html#section-2",
        "https://www.rfc-editor.org/rfc/rfc9999#section-2",
    ]
    assert re.search(
        r'send the token\.<a [^>]*href="text\.html#duvet-text-rfc9999-2-1"[^>]*>'
        r'<span class="duvet-rule-link">§</span></a>',
        html,
    )
    level = next(
        p
        for p in doctree.findall(nodes.paragraph)
        if "duvet-level-cell" in p["classes"]
    )
    assert [child.tagname for child in level.children] == ["inline", "duvet_permalink"]
    inventory = zlib.decompress(
        (Path(app.outdir) / "objects.inv").read_bytes().split(b"\n", 4)[4]
    )
    assert b"rfc9999#section-2" not in inventory


@pytest.mark.sphinx("html", testroot="report", confoverrides=CONF, freshenv=True)
def test_report_without_text(app: SphinxTestApp) -> None:
    """Without a page for the text, a report has no link to it."""
    app.build()
    html = (Path(app.outdir) / "report.html").read_text()
    assert "duvet-rule-link" not in html
    assert "<span>Text</span>" not in html
    assert 'href="https://www.rfc-editor.org/rfc/rfc9999#section-2">RFC ↗</a>' in html


@pytest.mark.sphinx(
    "html",
    testroot="autoreport",
    srcdir="autoreport-without-recap",
    confoverrides={
        **CONF,
        "duvet_autoreport": {},
        "duvet_autoreport_recap": False,
        "suppress_warnings": ["duvet.unused"],
    },
)
def test_autoreport_without_recap(app: SphinxTestApp) -> None:
    """The pages of the specifications can leave out their counts. The index keeps them."""
    folder = Path(app.srcdir) / "compliance"
    assert "duvet-recap" not in (folder / "rfc9999.rst").read_text()
    assert ".. duvet-recap::\n" in (folder / "index.rst").read_text()
