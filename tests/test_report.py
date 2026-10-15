import json
import os
import stat
import sys
from pathlib import Path

import pytest

from sphinx_duvet.report import Cite
from sphinx_duvet.report import DuvetError
from sphinx_duvet.report import DuvetNotFound
from sphinx_duvet.report import Report
from sphinx_duvet.report import Requirement
from sphinx_duvet.report import _separate_duplicates
from sphinx_duvet.report import ietf_title
from sphinx_duvet.report import parse_report
from sphinx_duvet.report import read_report
from sphinx_duvet.report import run_duvet

V2 = "https://awslabs.github.io/duvet/v2/"
INLINE = V2 + "sources.json#inline"
SPECIFICATION = V2 + "annotations.json#specification"
CITE = V2 + "annotations.json#cite"


def test_specifications(basic_report: Report) -> None:
    """Specifications are sorted by path and keep their title and sections."""
    specs = parse_report(basic_report)
    assert list(specs) == ["spec/extension.md", "spec/rfc9999.txt"]
    rfc = specs["spec/rfc9999.txt"]
    assert rfc.title == "RFC 9999: Example Token Exchange Protocol"
    assert rfc.format == "ietf"
    assert rfc.sections["section-2.1"] == "Parameters"
    assert specs["spec/extension.md"].title == "Example extension"
    assert specs["spec/extension.md"].format == "markdown"


def test_specification_url(basic_report: Report) -> None:
    """RFC files link to rfc-editor.org. Other files have no link."""
    specs = parse_report(basic_report)
    rfc = specs["spec/rfc9999.txt"]
    assert rfc.url == "https://www.rfc-editor.org/rfc/rfc9999"
    assert (
        rfc.section_url("section-2")
        == "https://www.rfc-editor.org/rfc/rfc9999#section-2"
    )
    assert specs["spec/extension.md"].url is None
    assert specs["spec/extension.md"].section_url("discovery") is None


def test_requirements(basic_report: Report) -> None:
    """Requirements keep the order of the specification, with their section and level."""
    rfc = parse_report(basic_report)["spec/rfc9999.txt"]
    assert [(r.section, r.level) for r in rfc.requirements[:3]] == [
        ("section-2", "MUST"),
        ("section-2", "MUST"),
        ("section-2", "SHOULD"),
    ]
    assert rfc.requirements[0].text == "The client MUST send the token."


def test_requirement_text_spans_lines(basic_report: Report) -> None:
    """The text of a requirement is normalized, and non-ASCII characters are kept."""
    rfc = parse_report(basic_report)["spec/rfc9999.txt"]
    [requirement] = [r for r in rfc.requirements if "café" in r.text]
    assert requirement.text == (
        "The server MUST validate the café parameter and the response "
        "MUST be encoded as JSON."
    )
    assert requirement.section == "section-2.1"


def test_cites(basic_report: Report) -> None:
    """Cites are attached to the requirements they quote."""
    rfc = parse_report(basic_report)["spec/rfc9999.txt"]
    cites = rfc.requirements[1].cites
    assert sorted((c.type, c.path, c.line) for c in cites) == [
        ("CITATION", "src/server/django.py", 2),
        ("CITATION", "src/server/flask.py", 2),
        ("TEST", "tests/test_server.py", 2),
    ]
    [exception] = [r for r in rfc.requirements if r.level == "MAY"][0].cites
    assert exception.type == "EXCEPTION"
    assert exception.reason == "Caching is up to the application."


def test_cite_url(basic_report: Report) -> None:
    """Cites link to the source file, with the blob link of the repository."""
    rfc = parse_report(basic_report)["spec/rfc9999.txt"]
    cite = rfc.requirements[0].cites[0]
    assert cite.url == "https://github.com/example/project/blob/main/src/client.py#L2"
    assert Cite("CITATION", "src/a.py", 3, [], blob_link="https://h/b/").url == (
        "https://h/b/src/a.py#L3"
    )
    assert Cite("CITATION", "src/a.py", 3, []).url is None


def test_report_without_optional_parts() -> None:
    """A report may have no repositories, sections, requirements or cites."""
    report = {
        "sources": {INLINE: {"s": {"file_name": "spec/plain.txt", "contents": "Text"}}},
        "annotations": {SPECIFICATION: {"a": {"source": {"src": "s"}}}},
    }
    [spec] = parse_report(report).values()
    assert spec.title == "spec/plain.txt"
    assert spec.format == ""
    assert spec.requirements == []
    assert spec.sections == {}


def test_requirement_outside_sections(basic_report: Report) -> None:
    """A requirement outside any section has an empty section."""
    report = json.loads(json.dumps(basic_report))
    for name in list(report["annotations"]):
        if name.endswith("#section"):
            del report["annotations"][name]
    rfc = parse_report(report)["spec/rfc9999.txt"]
    assert {r.section for r in rfc.requirements} == {""}


def test_cite_without_line(basic_report: Report) -> None:
    """A cite without a line number gets line 0."""
    report = json.loads(json.dumps(basic_report))
    for cite in report["annotations"][CITE].values():
        del cite["source"]["line"]
    rfc = parse_report(report)["spec/rfc9999.txt"]
    assert {c.line for r in rfc.requirements for c in r.cites} == {0}


def test_ietf_title() -> None:
    """The title is the indented block before the abstract."""
    text = "Request for Comments: 1\n\n      A Title\n      on two lines\n\nAbstract\n"
    assert ietf_title(text) == "RFC 1: A Title on two lines"
    assert ietf_title("      A Title\n\nAbstract\n") == "A Title"
    assert ietf_title("Abstract\n") is None
    assert ietf_title("No abstract") is None


def fake_duvet(tmp_path: Path, script: str) -> str:
    """Write an executable Python script that stands for Duvet."""
    path = tmp_path / "duvet"
    path.write_text(f"#!{sys.executable}\nimport sys\n{script}\n")
    path.chmod(path.stat().st_mode | stat.S_IXUSR)
    return os.fspath(path)


def test_run_duvet(tmp_path: Path) -> None:
    """Duvet runs in the project and its v2 JSON report is returned."""
    executable = fake_duvet(
        tmp_path,
        "import os\n"
        "assert sys.argv[1:3] == ['report', '--json-v2']\n"
        "open(sys.argv[3], 'w').write('{\"cwd\": \"%s\"}' % os.getcwd())",
    )
    assert run_duvet(tmp_path, executable) == {"cwd": str(tmp_path)}


def test_run_duvet_failure(tmp_path: Path) -> None:
    """The error output of Duvet is reported."""
    executable = fake_duvet(tmp_path, "sys.exit('invalid config')")
    with pytest.raises(DuvetError, match="Duvet failed:\ninvalid config"):
        run_duvet(tmp_path, executable)


def test_run_duvet_not_installed(tmp_path: Path) -> None:
    """A missing executable is reported."""
    with pytest.raises(DuvetNotFound, match="Install it with: cargo install duvet"):
        run_duvet(tmp_path, os.fspath(tmp_path / "missing"))


def test_run_duvet_config(tmp_path: Path) -> None:
    """A generated configuration is written next to the original one, then removed."""
    (tmp_path / ".duvet").mkdir()
    executable = fake_duvet(
        tmp_path,
        "import json, pathlib\n"
        "config = pathlib.Path(sys.argv[sys.argv.index('--config-path') + 1])\n"
        "assert config.parent.name == '.duvet'\n"
        "open(sys.argv[3], 'w').write(json.dumps({'config': config.read_text()}))",
    )
    assert run_duvet(tmp_path, executable, "generated") == {"config": "generated"}
    assert list((tmp_path / ".duvet").iterdir()) == []


def test_specification_names() -> None:
    """Specifications are named after their file, or their path if two files share a name."""
    report = {
        "sources": {
            INLINE: {
                "a": {"file_name": "one/spec.txt", "contents": "Text"},
                "b": {"file_name": "two/spec.txt", "contents": "Text"},
                "c": {"file_name": "rfc1.txt", "contents": "Text"},
            }
        },
        "annotations": {
            SPECIFICATION: {key: {"source": {"src": key}} for key in "abc"}
        },
    }
    names = [spec.name for spec in parse_report(report).values()]
    assert names == ["one-spec", "rfc1", "two-spec"]


def test_requirement_ids(basic_report: Report) -> None:
    """Requirements are numbered in each section. Requirements outside a section are in section 0."""
    rfc = parse_report(basic_report)["spec/rfc9999.txt"]
    assert [r.id for r in rfc.requirements[:4]] == [
        "rfc9999#2-1",
        "rfc9999#2-2",
        "rfc9999#2-3",
        "rfc9999#2.1-1",
    ]
    report = json.loads(json.dumps(basic_report))
    for name in list(report["annotations"]):
        if name.endswith("#section"):
            del report["annotations"][name]
    assert parse_report(report)["spec/rfc9999.txt"].requirements[0].id == "rfc9999#0-1"


def test_same_sentence_twice() -> None:
    """Requirements with the same sentence are at each place of the sentence, and share their cites."""
    report = read_report(Path(__file__).parent / "projects" / "layout" / "report.json")
    [spec] = parse_report(report).values()
    first, second = [r for r in spec.requirements if r.text == "The client MUST retry."]
    assert first.ranges != second.ranges
    assert spec.contents[second.ranges[0][0] : second.ranges[-1][1]] == (
        b"The client\n   MUST retry."
    )
    assert [r.id for r in spec.requirements if r.section == "section-1.1.1"] == [
        "rfc9997#1.1.1-1",
        "rfc9997#1.1.1-2",
        "rfc9997#1.1.1-3",
    ]
    assert len(first.cites) == len(second.cites) == 1


def test_same_sentence_not_found() -> None:
    """Without another place for the sentence, the requirements stay together."""
    contents = b"The client MUST retry. Page 2. The client\fMUST retry."
    requirements = [
        Requirement(
            spec="spec.txt",
            section="section-1",
            level="MUST",
            text="The client MUST retry.",
            ranges=[(0, 22)],
            contents=contents,
        )
        for _ in range(2)
    ]
    _separate_duplicates(requirements, contents, {"section-1": 30})
    assert [r.ranges for r in requirements] == [[(0, 22)], [(0, 22)]]


def test_requirement_in_a_list_item() -> None:
    """A requirement at the start of a list item leaves out the marker of the item."""
    report = read_report(Path(__file__).parent / "projects" / "layout" / "report.json")
    [spec] = parse_report(report).values()
    requirement = next(r for r in spec.requirements if r.id == "rfc9997#2-1")
    assert requirement.text == "The client MUST send a token."
    start = requirement.ranges[0][0]
    assert spec.contents[start : start + 10] == b"The client"
