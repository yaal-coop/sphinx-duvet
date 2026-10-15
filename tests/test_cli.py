import io
import json
import re
import runpy
import sys
from pathlib import Path

import pytest

from sphinx_duvet._cli import main

PROJECT = Path(__file__).parent / "projects" / "basic"
REPORT = ["--report-json", str(PROJECT / "report.json")]


class Terminal(io.StringIO):
    """An output stream that looks like a terminal."""

    def isatty(self) -> bool:
        """Return True, as a terminal does."""
        return True


@pytest.fixture(autouse=True)
def in_project(monkeypatch: pytest.MonkeyPatch) -> None:
    """Run the commands from the root of the test project."""
    monkeypatch.chdir(PROJECT)
    monkeypatch.delenv("NO_COLOR", raising=False)


def run(capsys: pytest.CaptureFixture[str], *args: str) -> tuple[int, str, str]:
    """Run the command and return its exit code, output and errors."""
    code = main([*args])
    captured = capsys.readouterr()
    return code, captured.out, captured.err


def test_report(capsys: pytest.CaptureFixture[str]) -> None:
    """The report shows a table per specification and a legend."""
    code, out, err = run(capsys, "report", *REPORT)
    assert code == 0
    lines = out.splitlines()
    assert lines[0] == "spec/extension.md: Example extension"
    assert "spec/rfc9999.txt: RFC 9999: Example Token Exchange Protocol" in lines
    index = lines.index(
        "section  level   server-flask  server-django  client      requirement"
    )
    assert lines[index + 1 : index + 3] == [
        "                 impl  test    impl  test     impl  test",
        "2        MUST    ∅             ∅              ✔     ✘     The client MUST send the token.",
    ]
    assert lines[-1].startswith("✔ done · ✘ missing · ? not annotated yet")
    assert "\033[" not in out
    assert (
        "no requirement matches the [[applies]] entry spec/rfc9999.txt#section-3" in err
    )
    assert "rfc9999.rst:8: no requirement matches the note" in err


def test_report_options(capsys: pytest.CaptureFixture[str]) -> None:
    """Specifications, targets, groups, sections, levels and states narrow the report."""
    code, out, _ = run(
        capsys,
        "report",
        "spec/rfc9999.txt",
        *REPORT,
        "--targets",
        "role=server",
        "--group-by",
        "role",
        "--sections",
        "2",
        "--levels",
        "must",
        "--show",
        "missing",
        "--labels",
        "text",
    )
    assert code == 0
    assert out.splitlines()[1:5] == [
        "section  level  server         requirement",
        "                impl     test",
        "2.1      MUST   partial  done  The server MUST validate the café parameter and the response MUST be encoded as JSON.",
        "",
    ]
    assert out.splitlines()[-1].startswith(
        "done · missing · not annotated not annotated yet"
    )


def test_report_nothing(capsys: pytest.CaptureFixture[str]) -> None:
    """A view without requirements says so."""
    code, out, _ = run(capsys, "report", "spec/rfc9999.txt", *REPORT, "--sections", "1")
    assert code == 0
    assert out.splitlines()[1] == "No requirement matches this view."


def test_terminal(
    capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    """In a terminal, states are colored and long requirements are cut to the width."""
    terminal = Terminal()
    monkeypatch.setattr(sys, "stdout", terminal)
    monkeypatch.setenv("COLUMNS", "80")
    assert main(["report", "spec/rfc9999.txt", *REPORT]) == 0
    lines = terminal.getvalue().splitlines()
    assert "\033[32m✔\033[0m     \033[31m✘\033[0m" in lines[3]
    validate = next(line for line in lines if line.startswith("2.1      MUST"))
    assert validate.endswith("The server MUST valid…")
    assert len(re.sub("\033\\[[0-9]+m", "", validate)) <= 80


def test_no_color(
    capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    """NO_COLOR disables the colors in a terminal."""
    terminal = Terminal()
    monkeypatch.setattr(sys, "stdout", terminal)
    monkeypatch.setenv("NO_COLOR", "1")
    assert main(["report", *REPORT]) == 0
    assert "\033[" not in terminal.getvalue()


def test_recap(capsys: pytest.CaptureFixture[str]) -> None:
    """The recap counts the requirements per level and per column."""
    code, out, _ = run(
        capsys, "recap", *REPORT, "--group-by", "role", "--levels", "MUST"
    )
    assert code == 0
    assert out.splitlines() == [
        "level  targets  rules  done  deviations  todo  missing  not annotated  tested",
        "MUST   server   7      2     0           2     1        2              3/4",
        "MUST   client   4      2     0           1     0        1              0/2",
    ]


def test_check(capsys: pytest.CaptureFixture[str]) -> None:
    """The check lists the failing requirements per column, and fails."""
    code, out, _ = run(
        capsys, "check", *REPORT, "--levels", "MUST", "--group-by", "role"
    )
    assert code == 1
    lines = out.splitlines()
    assert lines[:2] == [
        "spec/rfc9999.txt#section-2 MUST client: untested",
        "    The client MUST send the token.",
    ]
    assert "spec/rfc9999.txt#section-2.1 MUST client: partial, untested" in lines
    assert lines[-1] == "5 failures."


def test_check_fail_on(capsys: pytest.CaptureFixture[str]) -> None:
    """The failing states can be chosen."""
    code, out, _ = run(
        capsys, "check", *REPORT, "--fail-on", "todo, unannotated", "--levels", "SHOULD"
    )
    assert code == 1
    assert (
        out.splitlines()[0]
        == "spec/extension.md#discovery SHOULD server-flask: unannotated"
    )
    assert "spec/rfc9999.txt#section-2 SHOULD server-django: todo" in out


def test_check_success(capsys: pytest.CaptureFixture[str]) -> None:
    """Without failing requirements, the check succeeds, unless it is strict about unused entries."""
    code, out, _ = run(capsys, "check", *REPORT, "--levels", "MAY")
    assert (code, out) == (0, "No failure.\n")
    code, out, _ = run(
        capsys, "check", *REPORT, "--sections", "3", "--targets", "framework=flask"
    )
    assert (code, out.splitlines()[-1]) == (1, "1 failure.")
    code, _, _ = run(capsys, "check", *REPORT, "--levels", "MAY", "--strict")
    assert code == 1


@pytest.mark.parametrize(
    "args,message",
    [
        (["check", *REPORT, "--fail-on", "done"], "unknown --fail-on value 'done'"),
        (
            ["report", "spec/unknown.txt", *REPORT],
            "unknown specification spec/unknown.txt",
        ),
        (["report", *REPORT, "--targets", "role"], "Invalid selector 'role'"),
        (["report", "--duvet", "/missing/duvet"], "Duvet is not installed"),
        (["report", "--report-json", "missing.json"], "No such file or directory"),
    ],
)
def test_errors(
    capsys: pytest.CaptureFixture[str], args: list[str], message: str
) -> None:
    """Invalid arguments and reports that cannot be loaded are errors."""
    code, out, err = run(capsys, *args)
    assert code == 2
    assert out == ""
    assert err.startswith("sphinx-duvet: error: ")
    assert message in err


def test_invalid_report(capsys: pytest.CaptureFixture[str], tmp_path: Path) -> None:
    """A report without the expected content is an error."""
    report = tmp_path / "report.json"
    report.write_text(json.dumps({"sources": {}}))
    code, _, err = run(capsys, "report", "--report-json", str(report))
    assert code == 2
    assert err.startswith("sphinx-duvet: error: ")


def test_root(
    capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """The project is found above the current folder, or given with --root."""
    monkeypatch.chdir(PROJECT / "src/server")
    assert run(capsys, "recap", *REPORT)[0] == 0
    monkeypatch.chdir(tmp_path)
    code, _, err = run(capsys, "recap", *REPORT)
    assert code == 2
    assert "no .duvet/config.toml found, use --root" in err
    assert run(capsys, "recap", *REPORT, "--root", str(PROJECT))[0] == 0


def test_module(monkeypatch: pytest.MonkeyPatch) -> None:
    """The command also runs with python -m sphinx_duvet."""
    monkeypatch.setattr(sys, "argv", ["sphinx-duvet", "recap", *REPORT])
    with pytest.raises(SystemExit) as exit_info:
        runpy.run_module("sphinx_duvet", run_name="__main__")
    assert exit_info.value.code == 0
