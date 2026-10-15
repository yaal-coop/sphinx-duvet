"""Compute the compliance of each target with the requirements of a project."""

from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path

from .notes import Note
from .notes import load_notes
from .report import Report
from .report import Requirement
from .report import Specification
from .report import normalize
from .report import parse_report
from .report import run_duvet
from .targets import Applies
from .targets import Selector
from .targets import Target
from .targets import load_targets
from .targets import matches_any

_IMPLEMENTATION_TYPES = {"CITATION", "IMPLICATION", "EXCEPTION"}
_TEST_TYPES = {"TEST", "IMPLICATION"}
LEVELS = ("MUST", "SHOULD", "MAY")
"""Requirement levels of BCP 14, from the strongest to the weakest."""


class State(StrEnum):
    """The implementation or test state of a requirement for a target."""

    OK = "ok"
    EXCEPTION = "exception"
    TODO = "todo"
    PARTIAL = "partial"
    MISSING = "missing"
    UNANNOTATED = "unannotated"
    NOT_EXPECTED = "-"
    NOT_APPLICABLE = "n/a"


_RANK = {
    State.UNANNOTATED: 0,
    State.MISSING: 0,
    State.PARTIAL: 1,
    State.TODO: 1,
    State.EXCEPTION: 2,
    State.OK: 3,
}


@dataclass(frozen=True)
class Status:
    """The implementation and test states of a requirement for some targets."""

    implementation: State
    test: State

    @property
    def gap(self) -> bool:
        """:data:`True` if the implementation or a test is missing.

        A requirement without any annotation is not a gap: it has not been studied yet.
        """
        done = (State.OK, State.EXCEPTION, State.NOT_APPLICABLE, State.UNANNOTATED)
        return self.implementation not in done or self.test == State.MISSING


_NOT_APPLICABLE = Status(State.NOT_APPLICABLE, State.NOT_APPLICABLE)


@dataclass
class Counts:
    """Requirement counts for one level and one group of targets."""

    requirements: int = 0
    implemented: int = 0
    exceptions: int = 0
    todo: int = 0
    partial: int = 0
    missing: int = 0
    unannotated: int = 0
    needs_test: int = 0
    tested: int = 0


_COUNTERS = {
    State.OK: "implemented",
    State.EXCEPTION: "exceptions",
    State.TODO: "todo",
    State.PARTIAL: "partial",
    State.MISSING: "missing",
    State.UNANNOTATED: "unannotated",
}


class Project:
    """A Duvet project, its report and its targets."""

    def __init__(self, root: Path, report: Report) -> None:
        """Load the targets and notes of a project, and the report of Duvet."""
        self.root = Path(root)
        self.config = load_targets(self.root / ".duvet/targets.toml")
        self.specifications = parse_report(report)
        self.notes = load_notes(self.root / ".duvet/notes")
        requirements = [r for s in self.specifications.values() for r in s.requirements]
        for requirement in requirements:
            for cite in requirement.cites:
                cite.covers = self.config.covers(cite.path)
        self.unused_applies = self._attach_applies(requirements)
        self.unused_notes = self._attach_notes(requirements)

    @classmethod
    def from_duvet(cls, root: Path, executable: str = "duvet") -> "Project":
        """Load a project and run Duvet to get its report."""
        return cls(root, run_duvet(root, executable))

    @property
    def targets(self) -> list[Target]:
        """The targets of the project."""
        return self.config.targets

    def _attach_applies(self, requirements: list[Requirement]) -> list[Applies]:
        """Set the targets of the requirements. Return the entries that match nothing."""
        unused = []
        for entry in self.config.applies:
            matches = _find(requirements, entry.target, entry.quote)
            if not matches:
                unused.append(entry)
            for requirement in matches:
                requirement.applies = entry.applies_to
        return unused

    def _attach_notes(self, requirements: list[Requirement]) -> list[Note]:
        """Attach the notes to the requirements. Return the notes that match nothing."""
        unused = []
        for note in self.notes:
            matches = _find(requirements, note.target, note.quote)
            if not matches:
                unused.append(note)
            for requirement in matches:
                requirement.notes.append(note)
        return unused

    def dependencies(self, spec: Specification) -> list[Path]:
        """Return the files whose changes affect the report of a specification."""
        paths = {spec.path, ".duvet/targets.toml", ".duvet/config.toml"}
        for requirement in spec.requirements:
            paths.update(cite.path for cite in requirement.cites)
        files = [self.root / path for path in sorted(paths)]
        files += [note.source for note in self.notes]
        return [path for path in dict.fromkeys(files) if path.exists()]

    def applicable(self, requirement: Requirement) -> list[Target]:
        """Return the targets a requirement applies to."""
        if requirement.applies is None:
            return list(self.targets)
        return [t for t in self.targets if matches_any(requirement.applies, t)]

    def status(self, requirement: Requirement, target: Target) -> Status:
        """Return the implementation and test states of a requirement for a target.

        A test is expected if a part of the requirement is cited as implemented.
        The tests must then cover that part.
        Parts cited as exceptions need no test.
        """
        if target not in self.applicable(requirement):
            return _NOT_APPLICABLE
        if not requirement.cites:
            return Status(State.UNANNOTATED, State.NOT_EXPECTED)

        cites = [
            c
            for c in requirement.cites
            if c.covers is None or matches_any(c.covers, target)
        ]
        implementations = [c for c in cites if c.type in _IMPLEMENTATION_TYPES]
        if implementations and requirement.covered_by(implementations):
            types = {c.type for c in implementations}
            implementation = State.EXCEPTION if types == {"EXCEPTION"} else State.OK
        elif any(c.type == "TODO" for c in cites):
            implementation = State.TODO
        elif implementations:
            implementation = State.PARTIAL
        else:
            implementation = State.MISSING

        citations = [c for c in implementations if c.type == "CITATION"]
        if not citations:
            return Status(implementation, State.NOT_EXPECTED)

        # Tests only need to cover the implemented part of the requirement.
        # They may cover the target at a coarser granularity, e.g. per role only.
        keys = self.config.test_granularity
        tests = [
            c
            for c in requirement.cites
            if c.type in _TEST_TYPES
            and (c.covers is None or matches_any(_project(c.covers, keys), target))
        ]
        tested = bool(tests) and requirement.covered_by(tests, within=citations)
        return Status(implementation, State.OK if tested else State.MISSING)

    def group(self, requirement: Requirement, targets: list[Target]) -> Status:
        """Return the status of a requirement for several targets.

        The worst state of the targets wins.
        """
        statuses = [self.status(requirement, t) for t in targets]
        statuses = [s for s in statuses if s.implementation != State.NOT_APPLICABLE]
        if not statuses:
            return _NOT_APPLICABLE
        implementation = min(
            (s.implementation for s in statuses), key=_RANK.__getitem__
        )
        tests = {s.test for s in statuses}
        if State.MISSING in tests:
            test = State.MISSING
        elif State.OK in tests:
            test = State.OK
        else:
            test = State.NOT_EXPECTED
        return Status(implementation, test)

    def recap(
        self, requirements: list[Requirement], targets: list[Target]
    ) -> dict[str, Counts]:
        """Count requirements per level for a group of targets.

        A requirement without any annotation is counted as "unannotated",
        not as "missing": it has not been studied yet.
        """
        counts = {level: Counts() for level in LEVELS}
        for requirement in requirements:
            status = self.group(requirement, targets)
            if status.implementation == State.NOT_APPLICABLE:
                continue
            count = counts.setdefault(requirement.level, Counts())
            count.requirements += 1
            counter = _COUNTERS[status.implementation]
            setattr(count, counter, getattr(count, counter) + 1)
            count.needs_test += status.test != State.NOT_EXPECTED
            count.tested += status.test == State.OK
        return counts

    def columns(
        self, selectors: list[Selector] | None = None, group_by: str | None = None
    ) -> list[tuple[str, list[Target]]]:
        """Return (label, targets) pairs, one per column."""
        targets = self.config.select(selectors)
        if not group_by:
            return [(t.id, [t]) for t in targets]
        groups: dict[str, list[Target]] = {}
        for target in targets:
            groups.setdefault(target.attrs.get(group_by, "?"), []).append(target)
        return list(groups.items())


def _project(selectors: list[Selector], keys: set[str]) -> list[Selector]:
    """Keep only the constraints on some keys. Without keys, keep every constraint."""
    if not keys:
        return selectors
    return [s.project(keys) for s in selectors]


def _find(
    requirements: list[Requirement], target: str, quote: str
) -> list[Requirement]:
    """Return the requirements of a section that match a quote."""
    spec, _, section = target.partition("#")
    quote = normalize(quote)
    return [
        r
        for r in requirements
        if r.spec == spec
        and r.section == section
        and (quote in r.text or r.text in quote)
    ]


def find_root(start: Path) -> Path | None:
    """Find the closest parent directory that contains :file:`.duvet/config.toml`."""
    start = Path(start).resolve()
    for path in [start, *start.parents]:
        if (path / ".duvet/config.toml").exists():
            return path
    return None


def in_sections(requirement: Requirement, sections: list[str]) -> bool:
    """Return :data:`True` if a requirement belongs to one of the sections or their subsections.

    Sections may omit the ``section-`` prefix: ``4.1`` means ``section-4.1``.
    """
    if not sections:
        return True
    prefixed = [
        s if s.startswith(("section-", "appendix-")) else f"section-{s}"
        for s in sections
    ]
    return any(
        requirement.section == s or requirement.section.startswith(s + ".")
        for s in prefixed
    )
