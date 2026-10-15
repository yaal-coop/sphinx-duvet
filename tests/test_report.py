import json
import os
import stat
import sys
from pathlib import Path

import pytest

from sphinx_duvet.report import Cite
from sphinx_duvet.report import DuvetError
from sphinx_duvet.report import Report
from sphinx_duvet.report import ietf_title
from sphinx_duvet.report import parse_report
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
    with pytest.raises(DuvetError, match="Duvet is not installed"):
        run_duvet(tmp_path, os.fspath(tmp_path / "missing"))
