from pathlib import Path

import pytest

from sphinx_duvet.targets import ConfigError
from sphinx_duvet.targets import Default
from sphinx_duvet.targets import Dependency
from sphinx_duvet.targets import Selector
from sphinx_duvet.targets import Target
from sphinx_duvet.targets import TargetConfig
from sphinx_duvet.targets import load_targets
from sphinx_duvet.targets import parse_selectors

FLASK = Target("server-flask", {"role": "server", "framework": "flask"})
CLIENT = Target("client", {"role": "client"})


def covers(path: str, pattern: str) -> list[Selector] | None:
    """Return the targets covered by a file, with a single default pattern."""
    config = TargetConfig([CLIENT], defaults=[Default(pattern, [])])
    return config.covers(path)


def test_selector_matches_every_constraint() -> None:
    """A selector matches the targets that have every key=value pair."""
    selector = Selector.parse("role=server, framework=flask")
    assert selector.matches(FLASK)
    assert not selector.matches(CLIENT)
    assert not Selector.parse("role=server,framework=django").matches(FLASK)


def test_empty_selector_matches_every_target() -> None:
    """A selector without constraints matches any target."""
    assert Selector.parse("").matches(FLASK)
    assert Selector.parse(" , ").matches(CLIENT)


@pytest.mark.parametrize("text", ["role", "=server", "role=server,flask"])
def test_invalid_selector(text: str) -> None:
    """A constraint without a key and a value is rejected."""
    with pytest.raises(ConfigError, match="expected key=value"):
        Selector.parse(text)


def test_selector_projection() -> None:
    """A projected selector keeps only the constraints on some keys."""
    selector = Selector.parse("role=server,framework=django")
    assert selector.project(["role"]) == Selector.parse("role=server")
    assert selector.project(["role"]).matches(FLASK)


def test_parse_selectors() -> None:
    """Selectors are separated by semicolons or new lines."""
    expected = [Selector.parse("role=server"), Selector.parse("role=client")]
    assert parse_selectors("role=server; role=client") == expected
    assert parse_selectors("role=server\n  role=client\n") == expected
    assert parse_selectors(["role=server", "role=client"]) == expected


@pytest.mark.parametrize(
    "path,pattern",
    [
        ("src/client.py", "src/client.py"),
        ("src/client.py", "src/*.py"),
        ("src/client.py", "src/client.p?"),
        ("src/client.py", "src/**"),
        ("src/client.py", "src/**/*.py"),
        ("src/server/flask.py", "src/**/*.py"),
        ("src/server/flask.py", "**/flask.py"),
    ],
)
def test_default_pattern_match(path: str, pattern: str) -> None:
    """Default patterns match whole paths, and ** matches any number of directories."""
    assert covers(path, pattern) is not None


@pytest.mark.parametrize(
    "path,pattern",
    [
        ("src/server/flask.py", "src/*.py"),
        ("src/server/flask.py", "src/server"),
        ("src/client.py", "client.py"),
        ("src/client.py", "src/client?py/**"),
        ("src/client+py", "src/client.py"),
    ],
)
def test_default_pattern_mismatch(path: str, pattern: str) -> None:
    """In default patterns, a star does not match a slash, and other characters are literal."""
    assert covers(path, pattern) is None


def test_load_targets(basic_root: Path) -> None:
    """The targets.toml file describes the targets, defaults and applicability."""
    config = load_targets(basic_root / ".duvet/targets.toml")
    assert [t.id for t in config.targets] == ["server-flask", "server-django", "client"]
    assert config.targets[0] == FLASK
    assert config.test_granularity == {"role"}
    assert config.defaults[0].pattern == "src/server/flask.py"
    assert config.applies[0].applies_to == [Selector.parse("role=client")]


def test_without_targets_file(tmp_path: Path) -> None:
    """A project without targets.toml has a single target."""
    config = load_targets(tmp_path / "targets.toml")
    assert config.targets == [Target("default")]
    assert config.covers("src/client.py") is None


def test_covers(basic_root: Path) -> None:
    """The first default that matches a file gives the targets of its annotations."""
    config = load_targets(basic_root / ".duvet/targets.toml")
    assert config.covers("src/client.py") == [Selector.parse("role=client")]
    assert config.covers("tests/test_server.py") == [
        Selector.parse("role=server,framework=flask")
    ]
    assert config.covers("src/common.py") is None
    assert config.covers(".duvet/exceptions/rfc9999.md") is None


def test_select(basic_root: Path) -> None:
    """Targets can be filtered with selectors."""
    config = load_targets(basic_root / ".duvet/targets.toml")
    assert config.select() == config.targets
    assert [t.id for t in config.select(parse_selectors("role=client"))] == ["client"]


def test_selectors_as_list(tmp_path: Path) -> None:
    """Selectors can be written as a TOML array."""
    path = tmp_path / "targets.toml"
    path.write_text('[[default]]\npattern = "src/**"\ncovers = ["role=a", "role=b"]\n')
    config = load_targets(path)
    assert config.defaults[0].covers == parse_selectors("role=a;role=b")


@pytest.mark.parametrize(
    "content,message",
    [
        ('[[target]]\nrole = "server"\n', "Each \\[\\[target\\]\\] entry needs a 'id'"),
        ('[[target]]\nid = "a"\nport = 80\n', "Target 'a': 'port' must be a string"),
        (
            '[[default]]\ncovers = "role=a"\n',
            "Each \\[\\[default\\]\\] entry needs a 'pattern'",
        ),
        (
            '[[default]]\npattern = "src/**"\n',
            "Each \\[\\[default\\]\\] entry needs a 'covers'",
        ),
        (
            '[[applies]]\ntarget = "a#b"\nquote = "q"\n',
            "Each \\[\\[applies\\]\\] entry needs a 'applies-to'",
        ),
        (
            '[[outside]]\ntarget = "a#b"\n',
            "Each \\[\\[outside\\]\\] entry needs a 'reason'",
        ),
        (
            '[[outside]]\ntarget = "a#b"\nquote = 1\nreason = "r"\n',
            "Each \\[\\[outside\\]\\] entry needs a 'quote'",
        ),
        ('tests = "no"\n', "'tests' must be true or false"),
    ],
)
def test_invalid_targets_file(tmp_path: Path, content: str, message: str) -> None:
    """Missing keys and non-string attributes are reported."""
    path = tmp_path / "targets.toml"
    path.write_text(content)
    with pytest.raises(ConfigError, match=message):
        load_targets(path)


def test_dependencies(tmp_path: Path) -> None:
    """Dependencies have a package, and optionally covered targets, a link and a comment style."""
    path = tmp_path / "targets.toml"
    path.write_text(
        '[[dependency]]\npackage = "a"\n'
        '[[dependency]]\npackage = "b"\ncovers = "role=server"\nlink = "https://x/{path}"\n'
        'comment-style = { meta = "//=", content = "//#" }\n'
    )
    first, second = load_targets(path).dependencies
    assert first == Dependency("a")
    assert first.covers is None
    assert second.covers == parse_selectors("role=server")
    assert second.link == "https://x/{path}"
    assert second.comment_style == {"meta": "//=", "content": "//#"}


@pytest.mark.parametrize(
    "content,message",
    [
        ("[[dependency]]\n", "Each \\[\\[dependency\\]\\] entry needs a 'package'"),
        ('[[dependency]]\npackage = "a"\nlink = 1\n', "'link' must be a string"),
        (
            '[[dependency]]\npackage = "a"\ncomment-style = "##="\n',
            "'comment-style' must be a table of strings",
        ),
    ],
)
def test_invalid_dependencies(tmp_path: Path, content: str, message: str) -> None:
    """Invalid dependencies are reported."""
    path = tmp_path / "targets.toml"
    path.write_text(content)
    with pytest.raises(ConfigError, match=message):
        load_targets(path)


INCLUDING = Path(__file__).parent / "projects" / "including"


def test_include() -> None:
    """An included project brings its targets, applicability, granularity and notes."""
    config = load_targets(INCLUDING / ".duvet/targets.toml")
    assert [t.id for t in config.targets] == [
        "server",
        "client",
        "server-local",
        "checker",
    ]
    assert config.test_granularity == {"role"}
    assert [a.target for a in config.applies] == ["rfc/spec.md#requests"] * 3
    assert [d.pattern for d in config.defaults] == [
        "src/checks.py",
        "src/**",
        "tests/**",
    ]
    assert config.notes == [
        (INCLUDING / "rfc/.duvet/notes", "rfc/"),
        (INCLUDING / ".duvet/notes", ""),
    ]
    assert config.files == [
        INCLUDING / ".duvet/targets.toml",
        INCLUDING / "rfc/.duvet/targets.toml",
    ]


def make_project(root: Path, content: str) -> Path:
    """Write the targets.toml of a project, and return its path."""
    (root / ".duvet").mkdir(parents=True)
    path = root / ".duvet/targets.toml"
    path.write_text(content)
    return path


def test_include_list(tmp_path: Path) -> None:
    """Several projects can be included."""
    make_project(tmp_path / "a", '[[target]]\nid = "a"\n')
    make_project(tmp_path / "b", '[[target]]\nid = "b"\n')
    path = make_project(tmp_path / "main", 'include = ["../a", "../b/"]\n')
    assert [t.id for t in load_targets(path).targets] == ["a", "b"]
    assert load_targets(path).notes[1] == (tmp_path / "main/../b/.duvet/notes", "../b/")


def test_include_without_targets(tmp_path: Path) -> None:
    """A project that includes only projects without targets has the default target."""
    make_project(tmp_path / "a", "")
    path = make_project(tmp_path / "main", 'include = "../a"\n')
    assert load_targets(path).targets == [Target("default")]


@pytest.mark.parametrize(
    "content,message",
    [
        ('include = "missing"\n', "git submodule update --init"),
        ("include = 1\n", "'include' must be a string or an array of strings"),
        ('include = "../a"\n[[target]]\nid = "a"\n', "Target 'a' is defined twice"),
    ],
)
def test_invalid_include(tmp_path: Path, content: str, message: str) -> None:
    """Missing included projects, invalid includes and duplicate targets are reported."""
    make_project(tmp_path / "a", '[[target]]\nid = "a"\n')
    path = make_project(tmp_path / "main", content)
    with pytest.raises(ConfigError, match=message):
        load_targets(path)


def test_checker(tmp_path: Path) -> None:
    """A target with checks is a checker. Its checks are selectors, not attributes."""
    path = tmp_path / "targets.toml"
    path.write_text(
        '[[target]]\nid = "t"\nkind = "checker"\nchecks = "role=server; role=client"\n'
    )
    [target] = load_targets(path).targets
    assert target.attrs == {"kind": "checker"}
    assert target.checks == parse_selectors("role=server; role=client")
    assert Selector.parse("kind=checker").matches(target)


def test_tests(tmp_path: Path) -> None:
    """A project can follow its implementation only. An included project does not decide it."""
    shared = tmp_path / "shared/.duvet"
    shared.mkdir(parents=True)
    (shared / "targets.toml").write_text("tests = false\n")
    path = tmp_path / ".duvet/targets.toml"
    path.parent.mkdir()
    path.write_text('include = "shared"\n')
    assert load_targets(path).tests
    path.write_text('include = "shared"\ntests = false\n')
    assert not load_targets(path).tests
