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
    """A variant of the project, such as a role or a framework, described by attributes."""

    id: str
    attrs: dict[str, str] = field(default_factory=dict, hash=False)


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


@dataclass
class TargetConfig:
    """The targets of a project, read from :file:`.duvet/targets.toml`."""

    targets: list[Target]
    test_granularity: set[str] = field(default_factory=set)
    defaults: list[Default] = field(default_factory=list)
    applies: list[Applies] = field(default_factory=list)

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
    """Read a :file:`targets.toml` file.

    Without the file, the project has a single ``default`` target.
    """
    if not path.exists():
        return TargetConfig([Target("default")])
    config = tomllib.loads(path.read_text())
    targets = [_target(entry) for entry in config.get("target", [])]
    return TargetConfig(
        targets=targets or [Target("default")],
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
    )


def _get(entry: dict[str, Any], key: str, table: str) -> str:
    """Return a string value of a TOML table entry, or raise ConfigError."""
    value = entry.get(key)
    if not isinstance(value, str):
        raise ConfigError(f"Each [[{table}]] entry needs a {key!r} string")
    return value


def _selectors(entry: dict[str, Any], key: str, table: str) -> list[Selector]:
    """Read selectors written as a string or as an array of strings."""
    value = entry.get(key)
    if isinstance(value, list) and all(isinstance(item, str) for item in value):
        return parse_selectors(value)
    return parse_selectors(_get(entry, key, table))


def _target(entry: dict[str, Any]) -> Target:
    """Read a [[target]] entry. Every attribute must be a string."""
    target_id = _get(entry, "id", "target")
    attrs = {key: value for key, value in entry.items() if key != "id"}
    for key, value in attrs.items():
        if not isinstance(value, str):
            raise ConfigError(f"Target {target_id!r}: {key!r} must be a string")
    return Target(target_id, attrs)
