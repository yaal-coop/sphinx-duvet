"""Targets of a project, and how annotations and requirements map to them."""

import re
import tomllib
from collections.abc import Iterable
from dataclasses import dataclass
from dataclasses import field
from pathlib import Path
from typing import Any


class ConfigError(ValueError):
    """The target configuration is invalid."""


@dataclass(frozen=True)
class Target:
    """A variant of the project, such as a role or a framework, described by attributes.

    A target with ``checks`` is a checker: it does not implement the requirements,
    it checks that the targets that match ``checks`` implement them.
    """

    id: str
    attrs: dict[str, str] = field(default_factory=dict, hash=False)
    checks: "list[Selector] | None" = field(default=None, hash=False)


@dataclass(frozen=True)
class Selector:
    """A set of key=value constraints. A missing key matches any value."""

    items: frozenset[tuple[str, str]]

    @classmethod
    def parse(cls, text: str) -> "Selector":
        """Parse ``key=value`` pairs separated by commas."""
        items = set()
        for part in text.split(","):
            if not part.strip():
                continue
            key, sep, value = part.partition("=")
            if not sep or not key.strip():
                raise ConfigError(f"Invalid selector {text!r}: expected key=value")
            items.add((key.strip(), value.strip()))
        return cls(frozenset(items))

    def matches(self, target: Target) -> bool:
        """Return :data:`True` if the target has every attribute of the selector."""
        return all(target.attrs.get(key) == value for key, value in self.items)

    def project(self, keys: Iterable[str]) -> "Selector":
        """Return a selector with only the constraints on some keys."""
        keys = set(keys)
        return Selector(frozenset((k, v) for k, v in self.items if k in keys))


def parse_selectors(text: str | Iterable[str]) -> list[Selector]:
    """Parse selectors separated by ``;`` or new lines.

    A target matches the list if it matches one of the selectors.
    """
    if isinstance(text, str):
        text = re.split(r"\s*[;\n]\s*", text)
    return [Selector.parse(part) for part in text if part.strip()]


def matches_any(selectors: Iterable[Selector], target: Target) -> bool:
    """Return :data:`True` if the target matches one of the selectors."""
    return any(selector.matches(target) for selector in selectors)


# Workaround for Python 3.11 and 3.12: PurePath.full_match is new in Python 3.13.
# Remove when Python 3.13 is the oldest supported version.
def _glob_match(path: str, pattern: str) -> bool:
    """Match a whole relative path against a glob pattern.

    * and ? do not match /. A ** segment matches any number of directories.
    """
    return re.fullmatch(_glob_regex(pattern), path) is not None


def _glob_regex(pattern: str) -> str:
    """Translate a glob pattern into a regular expression."""
    parts = []
    segments = pattern.split("/")
    for index, segment in enumerate(segments):
        last = index == len(segments) - 1
        if segment == "**":
            parts.append(".*" if last else "(?:[^/]+/)*")
            continue
        regex = "".join(
            "[^/]*" if char == "*" else "[^/]" if char == "?" else re.escape(char)
            for char in segment
        )
        parts.append(regex if last else regex + "/")
    return "".join(parts)


@dataclass(frozen=True)
class Default:
    """Targets covered by the annotations of the files that match a pattern."""

    pattern: str
    covers: list[Selector] = field(hash=False)


@dataclass(frozen=True)
class Applies:
    """Targets a requirement applies to."""

    target: str
    quote: str
    applies_to: list[Selector] = field(hash=False)


@dataclass(frozen=True)
class Outside:
    """Requirements that are out of the scope of the project, with the reason.

    Without a quote, every requirement of the section and its subsections is out of scope.
    """

    target: str
    quote: str | None
    reason: str


@dataclass(frozen=True)
class Dependency:
    """An installed Python package whose annotations count for the project."""

    package: str
    covers: list[Selector] | None = field(default=None, hash=False)
    link: str | None = None
    comment_style: dict[str, str] | None = field(default=None, hash=False)


@dataclass
class TargetConfig:
    """The targets of a project, read from :file:`.duvet/targets.toml`."""

    targets: list[Target]
    tests: bool = True
    """False to follow the implementation only: no test is expected."""
    test_granularity: set[str] = field(default_factory=set)
    defaults: list[Default] = field(default_factory=list)
    applies: list[Applies] = field(default_factory=list)
    outside: list[Outside] = field(default_factory=list)
    dependencies: list[Dependency] = field(default_factory=list)
    notes: list[tuple[Path, str]] = field(default_factory=list)
    files: list[Path] = field(default_factory=list)

    def covers(self, path: str) -> list[Selector] | None:
        """Return the targets covered by the annotations of a file.

        :data:`None` means every target.
        Annotations in :file:`.duvet/` cover every target.
        """
        if path.startswith(".duvet/"):
            return None
        for default in self.defaults:
            if _glob_match(path, default.pattern):
                return default.covers
        return None

    def select(self, selectors: list[Selector] | None = None) -> list[Target]:
        """Return the targets that match the selectors, or every target."""
        if not selectors:
            return list(self.targets)
        return [t for t in self.targets if matches_any(selectors, t)]


def load_targets(path: Path) -> TargetConfig:
    """Read a :file:`targets.toml` file, and the projects it includes.

    Without the file, the project has a single ``default`` target.
    An included project brings its targets, its ``[[applies]]`` entries,
    its test granularity and its notes. Their specification paths get the
    path of the included project as a prefix.
    """
    root = path.parent.parent
    if not path.exists():
        return TargetConfig([Target("default")], notes=[(root / ".duvet/notes", "")])
    config = tomllib.loads(path.read_text())
    own = _load_own(config)
    targets: list[Target] = []
    applies: list[Applies] = []
    granularity: set[str] = set()
    notes: list[tuple[Path, str]] = []
    files = [path]
    for include in _includes(config):
        included = _load_included(root, include)
        targets += included.targets
        applies += included.applies
        granularity |= included.test_granularity
        notes += included.notes
        files += included.files
    targets += own.targets
    ids = [t.id for t in targets]
    duplicates = sorted({i for i in ids if ids.count(i) > 1})
    if duplicates:
        raise ConfigError(f"Target {duplicates[0]!r} is defined twice")
    return TargetConfig(
        targets=targets or [Target("default")],
        tests=_tests(config),
        test_granularity=granularity | own.test_granularity,
        defaults=own.defaults,
        applies=applies + own.applies,
        outside=own.outside,
        dependencies=own.dependencies,
        notes=[*notes, (root / ".duvet/notes", "")],
        files=files,
    )


def _tests(config: dict[str, Any]) -> bool:
    """Return whether the project follows its tests. Included projects do not decide it."""
    value = config.get("tests", True)
    if not isinstance(value, bool):
        raise ConfigError("'tests' must be true or false")
    return value


def _includes(config: dict[str, Any]) -> list[str]:
    """Return the included projects of a configuration."""
    value = config.get("include", [])
    if isinstance(value, str):
        value = [value]
    if not isinstance(value, list) or not all(isinstance(v, str) for v in value):
        raise ConfigError("'include' must be a string or an array of strings")
    return value


def _load_included(root: Path, include: str) -> TargetConfig:
    """Read the configuration of an included project, with prefixed specification paths.

    Included projects are read without their own includes.
    """
    folder = root / include
    path = folder / ".duvet/targets.toml"
    if not path.exists():
        raise ConfigError(
            f"The included project {include!r} has no .duvet/targets.toml. "
            "If it is a git submodule, run: git submodule update --init"
        )
    prefix = include.rstrip("/") + "/"
    included = _load_own(tomllib.loads(path.read_text()))
    included.applies = [
        Applies(prefix + entry.target, entry.quote, entry.applies_to)
        for entry in included.applies
    ]
    included.notes = [(folder / ".duvet/notes", prefix)]
    included.files = [path]
    return included


def _load_own(config: dict[str, Any]) -> TargetConfig:
    """Read the entries of a configuration, without its includes."""
    targets = [_target(entry) for entry in config.get("target", [])]
    return TargetConfig(
        targets=targets,
        test_granularity=set(config.get("test-granularity", [])),
        defaults=[
            Default(
                _get(entry, "pattern", "default"),
                _selectors(entry, "covers", "default"),
            )
            for entry in config.get("default", [])
        ],
        applies=[
            Applies(
                _get(entry, "target", "applies"),
                _get(entry, "quote", "applies"),
                _selectors(entry, "applies-to", "applies"),
            )
            for entry in config.get("applies", [])
        ],
        outside=[
            Outside(
                _get(entry, "target", "outside"),
                _optional(entry, "quote", "outside"),
                _get(entry, "reason", "outside"),
            )
            for entry in config.get("outside", [])
        ],
        dependencies=[_dependency(entry) for entry in config.get("dependency", [])],
    )


def _get(entry: dict[str, Any], key: str, table: str) -> str:
    """Return a string value of a TOML table entry, or raise ConfigError."""
    value = entry.get(key)
    if not isinstance(value, str):
        raise ConfigError(f"Each [[{table}]] entry needs a {key!r} string")
    return value


def _optional(entry: dict[str, Any], key: str, table: str) -> str | None:
    """Return an optional string value of a TOML table entry, or raise ConfigError."""
    if key not in entry:
        return None
    return _get(entry, key, table)


def _selectors(entry: dict[str, Any], key: str, table: str) -> list[Selector]:
    """Read selectors written as a string or as an array of strings."""
    value = entry.get(key)
    if isinstance(value, list) and all(isinstance(item, str) for item in value):
        return parse_selectors(value)
    return parse_selectors(_get(entry, key, table))


def _dependency(entry: dict[str, Any]) -> Dependency:
    """Read a [[dependency]] entry. Without covers, its annotations cover every target."""
    package = _get(entry, "package", "dependency")
    link = entry.get("link")
    if link is not None and not isinstance(link, str):
        raise ConfigError(f"Dependency {package!r}: 'link' must be a string")
    style = entry.get("comment-style")
    if style is not None and not (
        isinstance(style, dict) and all(isinstance(v, str) for v in style.values())
    ):
        raise ConfigError(
            f"Dependency {package!r}: 'comment-style' must be a table of strings"
        )
    return Dependency(
        package=package,
        covers=_selectors(entry, "covers", "dependency") if "covers" in entry else None,
        link=link,
        comment_style=style,
    )


def _target(entry: dict[str, Any]) -> Target:
    """Read a [[target]] entry. Every attribute must be a string, and checks are selectors."""
    target_id = _get(entry, "id", "target")
    attrs = {key: value for key, value in entry.items() if key not in ("id", "checks")}
    for key, value in attrs.items():
        if not isinstance(value, str):
            raise ConfigError(f"Target {target_id!r}: {key!r} must be a string")
    checks = _selectors(entry, "checks", "target") if "checks" in entry else None
    return Target(target_id, attrs, checks)
