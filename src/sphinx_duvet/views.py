"""Views of a project: the requirements and the columns that a report shows."""

from collections.abc import Iterable
from dataclasses import dataclass
from dataclasses import field

from .compliance import Project
from .compliance import State
from .compliance import Status
from .compliance import in_sections
from .report import Requirement
from .report import Specification
from .targets import ConfigError
from .targets import Selector
from .targets import Target
from .targets import parse_selectors

SHOW = ("all", "missing", "unannotated")
"""The values of the show option."""


@dataclass
class Row:
    """A requirement and its status in each column."""

    requirement: Requirement
    statuses: list[Status]


@dataclass
class View:
    """The options of a report: targets, columns, sections, levels and rows to show."""

    selectors: list[Selector] | None = None
    group_by: str | None = None
    sections: list[str] = field(default_factory=list)
    levels: set[str] | None = None
    show: str = "all"

    @classmethod
    def parse(
        cls,
        targets: str | None = None,
        group_by: str | None = None,
        sections: str | None = None,
        levels: str | None = None,
        show: str | None = None,
    ) -> "View":
        """Read the options as they are written in a directive or on the command line.

        Sections and levels are separated by commas. Levels are case insensitive.
        """
        show = show or "all"
        if show not in SHOW:
            raise ConfigError(
                f"Invalid show value {show!r}: expected {', '.join(SHOW)}"
            )
        return cls(
            selectors=parse_selectors(targets) if targets else None,
            group_by=group_by or None,
            sections=_split(sections),
            levels={level.upper() for level in _split(levels)} or None,
            show=show,
        )

    def keep(self, requirement: Requirement) -> bool:
        """Return :data:`True` if the requirement is in the selected sections and levels."""
        if not in_sections(requirement, self.sections):
            return False
        return self.levels is None or requirement.level in self.levels

    def shows(self, statuses: list[Status]) -> bool:
        """Return :data:`True` if a row with these statuses matches the show option."""
        if self.show == "missing":
            return any(s.gap for s in statuses)
        if self.show == "unannotated":
            return any(s.implementation == State.UNANNOTATED for s in statuses)
        return True

    def columns(self, project: Project) -> list[tuple[str, list[Target]]]:
        """Return the (label, targets) pairs of the columns."""
        return project.columns(self.selectors, self.group_by)

    def rows(self, project: Project, spec: Specification) -> list[Row]:
        """Return the rows of a specification.

        Requirements that apply to no column are left out.
        """
        columns = self.columns(project)
        rows = []
        for requirement in spec.requirements:
            if not self.keep(requirement):
                continue
            statuses = [project.group(requirement, targets) for _, targets in columns]
            if all(s.implementation == State.NOT_APPLICABLE for s in statuses):
                continue
            if self.shows(statuses):
                rows.append(Row(requirement, statuses))
        return rows

    def requirements(self, specs: Iterable[Specification]) -> list[Requirement]:
        """Return the requirements of some specifications in the selected sections and levels."""
        return [r for spec in specs for r in spec.requirements if self.keep(r)]


def _split(text: str | None) -> list[str]:
    """Split a comma separated list, and drop the blank items."""
    if not text:
        return []
    return [item.strip() for item in text.split(",") if item.strip()]
