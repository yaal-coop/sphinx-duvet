from pathlib import Path

import pytest

from sphinx_duvet.targets import ConfigError
from sphinx_duvet.targets import Default
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
    ],
)
def test_invalid_targets_file(tmp_path: Path, content: str, message: str) -> None:
    """Missing keys and non-string attributes are reported."""
    path = tmp_path / "targets.toml"
    path.write_text(content)
    with pytest.raises(ConfigError, match=message):
        load_targets(path)
