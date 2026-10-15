import json
import os
import stat
import sys
from pathlib import Path

import pytest

from sphinx_duvet.compliance import Counts
from sphinx_duvet.compliance import Project
from sphinx_duvet.compliance import State
from sphinx_duvet.compliance import Status
from sphinx_duvet.compliance import find_root
from sphinx_duvet.compliance import in_sections
from sphinx_duvet.report import Report
from sphinx_duvet.report import Requirement
from sphinx_duvet.targets import parse_selectors


def requirement(project: Project, text: str) -> Requirement:
    """Return the only requirement that starts with a text."""
    [match] = [
        r
        for s in project.specifications.values()
        for r in s.requirements
        if r.text.startswith(text)
    ]
    return match


def statuses(project: Project, text: str) -> list[str]:
    """Return the implementation/test states of a requirement for each target."""
    req = requirement(project, text)
    return [
        f"{status.implementation}/{status.test}"
        for status in (project.status(req, t) for t in project.targets)
    ]


@pytest.mark.parametrize(
    "text,expected",
    [
        ("The client MUST send the token.", ["n/a/n/a", "n/a/n/a", "ok/missing"]),
        ("The server MUST reject invalid tokens.", ["ok/ok", "ok/ok", "n/a/n/a"]),
        ("The server SHOULD log the request.", ["ok/missing", "todo/-", "n/a/n/a"]),
        (
            "The server MUST validate",
            ["partial/ok", "partial/ok", "partial/missing"],
        ),
        ("The client MAY cache the response.", ["n/a/n/a", "n/a/n/a", "exception/-"]),
        ("Servers SHOULD rotate their keys.", ["unannotated/-"] * 3),
        ("The token MUST NOT be empty.", ["ok/-"] * 3),
        ("reject expired tokens,", ["ok/missing", "missing/-", "n/a/n/a"]),
        (
            "The server MUST reject replayed tokens",
            ["ok/ok", "partial/-", "n/a/n/a"],
        ),
    ],
)
def test_status(project: Project, text: str, expected: list[str]) -> None:
    """Each target gets an implementation status and a test status.

    Tests only need to cover the part of a requirement cited as implemented.
    Parts cited as exceptions need no test.
    """
    assert statuses(project, text) == expected


def test_test_granularity(basic_root: Path, basic_report: Report) -> None:
    """Without test granularity, a test only covers the targets of its file."""
    project = Project(basic_root, basic_report)
    project.config.test_granularity = set()
    assert statuses(project, "The server MUST reject invalid tokens.") == [
        "ok/ok",
        "ok/missing",
        "n/a/n/a",
    ]


def test_gap() -> None:
    """A gap is a missing implementation or a missing test, not an unannotated requirement."""
    assert not Status(State.OK, State.OK).gap
    assert not Status(State.EXCEPTION, State.NOT_EXPECTED).gap
    assert not Status(State.NOT_APPLICABLE, State.NOT_APPLICABLE).gap
    assert Status(State.OK, State.MISSING).gap
    assert Status(State.TODO, State.NOT_EXPECTED).gap
    assert not Status(State.UNANNOTATED, State.NOT_EXPECTED).gap


@pytest.mark.parametrize(
    "text,selectors,expected",
    [
        ("The server SHOULD log the request.", "role=server", "todo/missing"),
        ("The server MUST reject invalid tokens.", "role=server", "ok/ok"),
        ("The token MUST NOT be empty.", "", "ok/-"),
        ("The client MUST send the token.", "role=server", "n/a/n/a"),
    ],
)
def test_group(project: Project, text: str, selectors: str, expected: str) -> None:
    """The status of a group of targets is the worst status of its targets."""
    targets = project.config.select(parse_selectors(selectors))
    status = project.group(requirement(project, text), targets)
    assert f"{status.implementation}/{status.test}" == expected


def test_recap(project: Project) -> None:
    """Requirements are counted per level, and unannotated ones apart from missing ones."""
    requirements = project.specifications["spec/rfc9999.txt"].requirements
    recap = project.recap(
        requirements, project.config.select(parse_selectors("role=server"))
    )
    assert recap == {
        "MUST": Counts(
            requirements=7,
            implemented=2,
            partial=2,
            missing=1,
            unannotated=2,
            needs_test=4,
            tested=3,
        ),
        "SHOULD": Counts(requirements=2, todo=1, unannotated=1, needs_test=1),
        "MAY": Counts(),
    }


def test_recap_other_level(project: Project) -> None:
    """Levels other than MUST, SHOULD and MAY get their own counts."""
    req = requirement(project, "Servers SHOULD rotate their keys.")
    req.level = "OPTIONAL"
    assert project.recap([req], project.targets)["OPTIONAL"] == Counts(
        requirements=1, unannotated=1
    )


def test_columns(project: Project) -> None:
    """Columns are single targets, or groups of targets that share an attribute."""
    assert [label for label, _ in project.columns()] == [
        "server-flask",
        "server-django",
        "client",
    ]
    grouped = project.columns(group_by="role")
    assert [(label, [t.id for t in targets]) for label, targets in grouped] == [
        ("server", ["server-flask", "server-django"]),
        ("client", ["client"]),
    ]
    assert [label for label, _ in project.columns(group_by="framework")] == [
        "flask",
        "django",
        "?",
    ]
    selected = project.columns(parse_selectors("role=client"))
    assert [label for label, _ in selected] == ["client"]


def test_unused_entries(project: Project) -> None:
    """Applicability entries and notes that match no requirement are reported."""
    assert [entry.quote for entry in project.unused_applies] == [
        "This text is not in the specification."
    ]
    assert [note.line for note in project.unused_notes] == [8]
    note = requirement(project, "The server SHOULD log the request.").notes[0]
    assert note.line == 1


def test_dependencies(project: Project, basic_root: Path) -> None:
    """The files of a specification report are the spec, the config, the cited files and the notes."""
    spec = project.specifications["spec/rfc9999.txt"]
    paths = [
        path.relative_to(basic_root).as_posix() for path in project.dependencies(spec)
    ]
    assert paths == [
        ".duvet/config.toml",
        ".duvet/exceptions/rfc9999.md",
        ".duvet/targets.toml",
        "spec/rfc9999.txt",
        "src/client.py",
        "src/common.py",
        "src/server/django.py",
        "src/server/flask.py",
        "tests/test_server.py",
        ".duvet/notes/rfc9999.rst",
    ]


def test_from_duvet(tmp_path: Path, basic_report: Report) -> None:
    """A project can be loaded by running Duvet."""
    (tmp_path / "report.json").write_text(json.dumps(basic_report))
    executable = tmp_path / "duvet"
    executable.write_text(
        f"#!{sys.executable}\nimport shutil, sys\nshutil.copy('report.json', sys.argv[3])\n"
    )
    executable.chmod(executable.stat().st_mode | stat.S_IXUSR)
    project = Project.from_duvet(tmp_path, os.fspath(executable))
    assert list(project.specifications) == ["spec/extension.md", "spec/rfc9999.txt"]
    assert [t.id for t in project.targets] == ["default"]


def test_find_root(basic_root: Path, tmp_path: Path) -> None:
    """The root is the closest parent with a Duvet configuration."""
    assert find_root(basic_root / "src/server") == basic_root.resolve()
    assert find_root(basic_root) == basic_root.resolve()
    assert find_root(tmp_path) is None


@pytest.mark.parametrize(
    "sections,expected",
    [
        ([], True),
        (["2"], True),
        (["section-2"], True),
        (["2.1"], True),
        (["2.2"], False),
        (["3", "2.1"], True),
        (["appendix-A"], False),
    ],
)
def test_in_sections(project: Project, sections: list[str], expected: bool) -> None:
    """A requirement belongs to its section and to the parent sections."""
    req = requirement(project, "The client MAY cache the response.")
    assert in_sections(req, sections) is expected
