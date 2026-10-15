"""Annotations of the installed Python packages that a project depends on."""

import importlib.metadata
import importlib.util
import json
import os
import tomllib
from dataclasses import dataclass
from pathlib import Path
from pathlib import PurePosixPath

from .targets import ConfigError
from .targets import Dependency


@dataclass(frozen=True)
class InstalledDependency:
    """A dependency, the folder where its package is installed, and its version."""

    dependency: Dependency
    path: Path
    version: str

    @property
    def name(self) -> str:
        """The name of the package."""
        return self.dependency.package

    def relative(self, file: Path) -> str | None:
        """Return the path of a file in the package, from the folder that contains the package.

        :data:`None` if the file is not in the package.
        """
        try:
            return file.resolve().relative_to(self.path.parent).as_posix()
        except ValueError:
            return None

    def link(self, path: str, line: int) -> str | None:
        """Return the link to a line of the package in its repository, if the dependency sets a link."""
        if self.dependency.link is None:
            return None
        url = self.dependency.link.format(version=self.version, path=path)
        return f"{url}#L{line}"


def locate(dependency: Dependency) -> InstalledDependency:
    """Find the folder and the version of an installed package."""
    try:
        spec = importlib.util.find_spec(dependency.package)
    except ValueError:
        spec = None
    if spec is None:
        raise ConfigError(f"Dependency {dependency.package!r} is not installed")
    if not spec.submodule_search_locations:
        raise ConfigError(
            f"Dependency {dependency.package!r} is a module, not a package"
        )
    path = Path(next(iter(spec.submodule_search_locations))).resolve()
    distributions = importlib.metadata.packages_distributions().get(
        dependency.package, []
    )
    version = importlib.metadata.version(distributions[0]) if distributions else ""
    return InstalledDependency(dependency, path, version)


def duvet_config(root: Path, dependencies: list[InstalledDependency]) -> str:
    """Return the Duvet configuration of a project, with a source per dependency.

    Sources are relative to the root, so reports do not depend on the machine.
    A dependency uses the comment style of the first source of the project,
    unless it sets its own.
    """
    text = (root / ".duvet/config.toml").read_text()
    sources = tomllib.loads(text).get("source", [])
    default_style = next(
        (s["comment-style"] for s in sources if "comment-style" in s), None
    )
    blocks = [text.rstrip(), ""]
    for installed in dependencies:
        pattern = PurePosixPath(Path(os.path.relpath(installed.path, root)).as_posix())
        blocks.append("[[source]]")
        blocks.append(f"pattern = {json.dumps(str(pattern / '**/*.py'))}")
        blocks.append('type = "implementation"')
        style = installed.dependency.comment_style or default_style
        if style:
            items = ", ".join(
                f"{key} = {json.dumps(value)}" for key, value in style.items()
            )
            blocks.append(f"comment-style = {{ {items} }}")
        blocks.append("")
    return "\n".join(blocks)
