import os
import sys
from pathlib import Path

import pytest

from sphinx_duvet.compliance import Project
from sphinx_duvet.compliance import duvet_config_for
from sphinx_duvet.dependencies import duvet_config
from sphinx_duvet.dependencies import locate
from sphinx_duvet.report import Report
from sphinx_duvet.report import read_report
from sphinx_duvet.targets import ConfigError
from sphinx_duvet.targets import Dependency
from sphinx_duvet.targets import parse_selectors


def statuses(project: Project, text: str) -> list[str]:
    """Return the implementation/test states of a requirement for each target."""
    [requirement] = [
        r
        for s in project.specifications.values()
        for r in s.requirements
        if r.text.startswith(text)
    ]
    return [
        f"{status.implementation}/{status.test}"
        for status in (project.status(requirement, t) for t in project.targets)
    ]


def test_locate(depending_root: Path) -> None:
    """An installed package is found with its version."""
    installed = locate(Dependency("fakelib"))
    assert installed.name == "fakelib"
    assert installed.path == (depending_root / "site-packages/fakelib").resolve()
    assert installed.version == "1.2.3"
    assert installed.relative(installed.path / "__init__.py") == "fakelib/__init__.py"
    assert installed.relative(depending_root / "src/server.py") is None


def test_locate_errors(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """Missing packages and plain modules are reported."""
    (tmp_path / "plainmodule.py").write_text("")
    monkeypatch.syspath_prepend(str(tmp_path))
    with pytest.raises(ConfigError, match="'missinglib' is not installed"):
        locate(Dependency("missinglib"))
    with pytest.raises(ConfigError, match="'' is not installed"):
        locate(Dependency(""))
    with pytest.raises(ConfigError, match="'plainmodule' is a module, not a package"):
        locate(Dependency("plainmodule"))


def test_version_without_metadata(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """A package without distribution metadata has no version."""
    (tmp_path / "barelib").mkdir()
    (tmp_path / "barelib/__init__.py").write_text("")
    monkeypatch.syspath_prepend(str(tmp_path))
    assert locate(Dependency("barelib")).version == ""


def test_link(depending_root: Path) -> None:
    """The link of a dependency is built from its version and the path of the file."""
    link = "https://example.com/{version}/{path}"
    installed = locate(Dependency("fakelib", link=link))
    assert installed.link("fakelib/__init__.py", 3) == (
        "https://example.com/1.2.3/fakelib/__init__.py#L3"
    )
    assert locate(Dependency("fakelib")).link("fakelib/__init__.py", 3) is None


def test_duvet_config(depending_root: Path) -> None:
    """The configuration of Duvet gets a source per dependency, relative to the root."""
    config = duvet_config(depending_root, [locate(Dependency("fakelib"))])
    assert config.startswith(
        (depending_root / ".duvet/config.toml").read_text().rstrip()
    )
    assert config.endswith(
        "[[source]]\n"
        'pattern = "site-packages/fakelib/**/*.py"\n'
        'type = "implementation"\n'
        'comment-style = { meta = "##=", content = "##%" }\n'
    )
    style = {"meta": "//=", "content": "//#"}
    config = duvet_config(
        depending_root, [locate(Dependency("fakelib", comment_style=style))]
    )
    assert config.endswith('comment-style = { meta = "//=", content = "//#" }\n')


def test_duvet_config_default_style(depending_root: Path, tmp_path: Path) -> None:
    """Without a comment style in the project, Duvet uses its default style."""
    (tmp_path / ".duvet").mkdir()
    (tmp_path / ".duvet/config.toml").write_text('[[source]]\npattern = "src/**"\n')
    installed = locate(Dependency("fakelib"))
    config = duvet_config(tmp_path, [installed])
    pattern = Path(os.path.relpath(installed.path, tmp_path)).as_posix()
    assert config.endswith(
        f'[[source]]\npattern = "{pattern}/**/*.py"\ntype = "implementation"\n'
    )


def test_duvet_config_for(depending_root: Path, basic_root: Path) -> None:
    """Only projects with dependencies need a generated configuration."""
    assert duvet_config_for(basic_root) is None
    config = duvet_config_for(depending_root)
    assert config is not None
    assert "site-packages/fakelib/**/*.py" in config


@pytest.mark.parametrize(
    "text,expected",
    [
        ("The server MUST reply.", ["ok/-", "missing/-"]),
        ("The server MUST validate", ["ok/ok", "missing/-"]),
        ("The server MUST answer quickly.", ["ok/ok", "missing/-"]),
        ("The client MUST ask.", ["missing/-", "ok/missing"]),
    ],
)
def test_status(depending: Project, text: str, expected: list[str]) -> None:
    """A dependency implements requirements, and its tests are its own concern.

    The project tests what it implements. A test of the project still counts.
    """
    assert statuses(depending, text) == expected


def test_cites(depending: Project) -> None:
    """Cites of a dependency keep its name, its version and its link."""
    spec = depending.specifications["spec/spec.md"]
    [cite] = spec.requirements[0].cites
    assert cite.dependency == "fakelib"
    assert cite.version == "1.2.3"
    assert cite.path == "fakelib/__init__.py"
    assert (
        cite.url
        == "https://github.com/example/fakelib/blob/v1.2.3/src/fakelib/__init__.py#L2"
    )
    assert cite.covers == parse_selectors("role=server")
    local = next(c for c in spec.requirements[3].cites if c.type == "CITATION")
    assert local.dependency is None
    assert (
        local.url == "https://github.com/example/depending/blob/main/src/client.py#L2"
    )


def test_report_from_another_machine(depending_root: Path) -> None:
    """A report produced with other site-packages folders is recognized."""
    report: Report = read_report(depending_root / "report.json")
    for source in report["sources"][
        "https://awslabs.github.io/duvet/v2/sources.json#linked"
    ].values():
        source["file_name"] = source["file_name"].replace(
            "site-packages/", "/home/ci/.venv/lib/python3.14/site-packages/"
        )
    project = Project(depending_root, report)
    cite = project.specifications["spec/spec.md"].requirements[0].cites[0]
    assert (cite.dependency, cite.path) == ("fakelib", "fakelib/__init__.py")


def test_dependencies(depending: Project, depending_root: Path) -> None:
    """The files of the dependencies are tracked too."""
    files = depending.dependencies(depending.specifications["spec/spec.md"])
    assert (depending_root / "site-packages/fakelib/__init__.py").resolve() in files
    assert depending_root / "src/server.py" in files


def test_not_installed(depending_root: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """A project whose dependency is not installed cannot be loaded."""
    monkeypatch.setattr(sys, "path", [p for p in sys.path if "depending" not in p])
    monkeypatch.delitem(sys.modules, "fakelib", raising=False)
    with pytest.raises(ConfigError, match="'fakelib' is not installed"):
        Project(depending_root, read_report(depending_root / "report.json"))
