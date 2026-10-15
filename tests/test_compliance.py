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
from sphinx_duvet.report import Cite
from sphinx_duvet.report import Report
from sphinx_duvet.report import Requirement
from sphinx_duvet.report import read_report
from sphinx_duvet.targets import Target
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


def test_group_by_all(project: Project) -> None:
    """With group-by all, every target is in one column, and the worst state wins."""
    [(label, targets)] = project.columns(group_by="all")
    assert label == "State"
    assert targets == project.targets


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
    """Columns are single targets, or groups of targets that share an attribute.

    A target without the attribute gets a column of its own.
    """
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
        "client",
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


def test_included_project() -> None:
    """Shared targets, applicability, notes and requirements come from an included project."""
    root = Path(__file__).parent / "projects" / "including"
    project = Project(root, read_report(root / "report.json"))
    assert project.unused_applies == []
    assert project.unused_notes == []
    spec = project.specifications["rfc/spec.md"]
    assert [t.id for t in project.targets] == [
        "server",
        "client",
        "server-local",
        "checker",
    ]
    assert [statuses(project, r.text) for r in spec.requirements] == [
        ["ok/ok", "n/a/n/a", "ok/ok", "ok/missing"],
        ["n/a/n/a", "unannotated/-", "n/a/n/a", "n/a/n/a"],
        ["ok/missing", "n/a/n/a", "ok/missing", "missing/-"],
    ]
    assert spec.requirements[0].notes[0].body == ["A shared note about replies."]
    files = project.dependencies(spec)
    assert root / "rfc/.duvet/targets.toml" in files
    assert root / "rfc/.duvet/notes/spec.rst" in files


def applicable_ids(project: Project, text: str) -> list[str]:
    """Return the identifiers of the targets a requirement applies to."""
    return [t.id for t in project.applicable(requirement(project, text))]


def test_checker(project: Project) -> None:
    """A checker applies to the requirements of the targets it checks."""
    checker = Target(
        "checker", {"kind": "checker"}, checks=parse_selectors("framework=django")
    )
    project.config.targets.append(checker)
    assert applicable_ids(project, "The server MUST reject invalid tokens.") == [
        "server-flask",
        "server-django",
        "checker",
    ]
    assert applicable_ids(project, "The client MUST send the token.") == ["client"]
    assert "checker" in applicable_ids(project, "Servers SHOULD rotate their keys.")
    assert [label for label, _ in project.columns(group_by="role")][-1] == "checker"


def test_outside() -> None:
    """Requirements out of scope are not counted, unless the project cites them."""
    root = Path(__file__).parent / "projects" / "outside"
    project = Project(root, read_report(root / "report.json"))
    [spec] = project.specifications.values()
    states = {
        r.id: project.group(r, project.targets).implementation
        for r in spec.requirements
    }
    assert states["rfc9997#1.1-1"] == State.OUTSIDE
    assert states["rfc9997#1.1.1-1"] == State.OK
    assert states["rfc9997#2-2"] == State.OUTSIDE
    assert states["rfc9997#2-1"] == State.OK
    [unused] = project.unused_outside
    assert unused.target == "spec/rfc9997.txt#section-9"
    counts = project.recap(spec.requirements, project.targets)
    assert counts["MUST"].requirements == 4
    assert not Status(State.OUTSIDE, State.OUTSIDE).gap


def test_outside_with_cites() -> None:
    """A requirement that the project cites stays in scope, without the reason."""
    root = Path(__file__).parent / "projects" / "outside"
    project = Project(root, read_report(root / "report.json"))
    [spec] = project.specifications.values()
    cited = next(r for r in spec.requirements if r.id == "rfc9997#1.1.1-1")
    assert cited.outside is None
    assert project.group(cited, project.targets).implementation == State.OK


def test_citation_with_todo(project: Project) -> None:
    """A requirement cited in full is partly done when a todo annotation remains."""
    req = requirement(project, "The server MUST reject invalid tokens.")
    targets = [t for t in project.targets if t.id == "server-flask"]
    assert project.group(req, targets).implementation == State.OK
    todo = Cite(type="TODO", path="src/a.py", line=1, ranges=[], reason="")
    req.cites.append(todo)
    assert project.group(req, targets).implementation == State.PARTIAL


def test_requirement_in_a_table() -> None:
    """A requirement in a table is the text of its cell, and keeps its cites."""
    root = Path(__file__).parent / "projects" / "layout"
    project = Project(root, read_report(root / "report.json"))
    [spec] = project.specifications.values()
    rule = next(r for r in spec.requirements if r.id == "rfc9997#2-2")
    assert rule.text == "The server MUST check it."
    assert spec.contents[rule.ranges[0][0] : rule.ranges[0][1]] == b"The server MUST"
