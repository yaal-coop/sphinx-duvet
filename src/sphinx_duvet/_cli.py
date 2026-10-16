"""The sphinx-duvet command: compliance reports in the terminal, and checks for the CI."""

import argparse
import json
import os
import shutil
import sys
from collections.abc import Callable
from collections.abc import Sequence
from pathlib import Path
from typing import TextIO

from .compliance import Project
from .compliance import State
from .compliance import Status
from .compliance import duvet_config_for
from .compliance import find_root
from .labels import DESCRIPTIONS
from .labels import PRESETS
from .report import DuvetError
from .report import DuvetNotFound
from .report import Specification
from .report import read_report
from .report import run_duvet
from .views import SHOW
from .views import View

FAIL_ON = ("missing", "partial", "todo", "untested", "unannotated")
DEFAULT_FAIL_ON = "missing,partial,untested"

_FAILURES: dict[str, Callable[[Status], bool]] = {
    "missing": lambda s: s.implementation == State.MISSING,
    "partial": lambda s: s.implementation == State.PARTIAL,
    "todo": lambda s: s.implementation == State.TODO,
    "untested": lambda s: s.test == State.MISSING,
    "unannotated": lambda s: s.implementation == State.UNANNOTATED,
}

# ANSI colors of the states: green, red, yellow, or dim.
_COLORS = {
    State.OK: "32",
    State.MISSING: "31",
    State.TODO: "33",
    State.PARTIAL: "33",
    State.EXCEPTION: "33",
    State.UNANNOTATED: "2",
    State.NOT_EXPECTED: "2",
    State.NOT_APPLICABLE: "2",
    State.OUTSIDE: "2",
}

_RECAP_HEADERS = [
    "level",
    "targets",
    "rules",
    "done",
    "deviations",
    "todo",
    "missing",
    "not annotated",
    "tested",
]


class _UsageError(Exception):
    """The command cannot run with these arguments."""


class _Output:
    """Write tables to a stream, with colors if the stream is a terminal."""

    def __init__(self, stream: TextIO, labels: str) -> None:
        """Choose the labels, the colors and the width of the output."""
        self.stream = stream
        self.labels = PRESETS[labels]
        is_terminal = stream.isatty()
        self.color = is_terminal and not os.environ.get("NO_COLOR")
        self.width = shutil.get_terminal_size().columns if is_terminal else None

    def write(self, text: str = "") -> None:
        """Write a line."""
        print(text, file=self.stream)

    def state(self, value: State) -> tuple[str, str]:
        """Return the label of a state, as plain text and as colored text."""
        label = self.labels[value]
        if not self.color:
            return label, label
        return label, f"\033[{_COLORS[value]}m{label}\033[0m"

    def status(self, status: Status, tests: bool = True) -> list[tuple[str, str]]:
        """Return the implementation and test cells of a status.

        A requirement that is unannotated, does not apply or is out of scope only has
        an implementation cell. Without tests, there is no test cell.
        """
        if not tests:
            return [self.state(status.implementation)]
        if status.implementation in (
            State.NOT_APPLICABLE,
            State.UNANNOTATED,
            State.OUTSIDE,
        ):
            return [self.state(status.implementation), _plain("")]
        return [self.state(status.implementation), self.state(status.test)]

    def table(
        self,
        headers: list[str],
        rows: list[list[tuple[str, str]]],
        last: int = 0,
        groups: list[tuple[str, int]] | None = None,
    ) -> None:
        """Write a table with aligned columns.

        Cells are (plain, colored) pairs. The text of the last column is cut
        to the width of the terminal, keeping at least the given width.
        With groups, a first header row has a (text, number of columns) pair
        per group, and the headers are a second row.
        """
        widths = [
            max([len(header), *(len(row[i][0]) for row in rows)])
            for i, header in enumerate(headers)
        ]
        if groups:
            self._groups(groups, widths)
        self.write(
            "  ".join(h.ljust(w) for h, w in zip(headers, widths, strict=True)).rstrip()
        )
        room = None
        if self.width is not None and last:
            room = max(self.width - sum(widths[:-1]) - 2 * (len(widths) - 1), last)
        for row in rows:
            cells = [
                colored + " " * (width - len(plain))
                for (plain, colored), width in zip(row[:-1], widths, strict=False)
            ]
            plain, text = row[-1]
            if room is not None and len(plain) > room:
                text = plain[: room - 1].rstrip() + "…"
            self.write("  ".join([*cells, text]).rstrip())

    def _groups(self, groups: list[tuple[str, int]], widths: list[int]) -> None:
        """Write the first header row. A group wider than its columns widens the last one."""
        texts = []
        start = 0
        for text, span in groups:
            columns = range(start, start + span)
            inner = sum(widths[i] for i in columns) + 2 * (span - 1)
            if len(text) > inner:
                widths[columns[-1]] += len(text) - inner
                inner = len(text)
            texts.append(text.ljust(inner))
            start += span
        self.write("  ".join(texts).rstrip())

    def legend(self, tests: bool = True) -> None:
        """Write a line that explains the labels.

        Without tests, the state of a test that is not expected is left out.
        """
        items = []
        for value, description in DESCRIPTIONS.items():
            if not tests and value == State.NOT_EXPECTED:
                continue
            plain, colored = self.state(value)
            items.append(
                colored if plain == description else f"{colored} {description}"
            )
        self.write(" · ".join(items))


def _plain(text: str) -> tuple[str, str]:
    """Return a cell without color."""
    return text, text


def report(
    project: Project,
    view: View,
    specs: list[Specification],
    args: argparse.Namespace,
    out: _Output,
) -> int:
    """Write a table per specification, with a row per requirement."""
    columns = [label for label, _ in view.columns(project)]
    states = ["impl", "test"] if project.config.tests else ["impl"]
    for index, spec in enumerate(specs):
        if index:
            out.write()
        out.write(f"{spec.path}: {spec.title}")
        rows = [
            [
                _plain(row.requirement.id.partition("#")[2]),
                _plain(row.requirement.level),
                *(
                    cell
                    for status in row.statuses
                    for cell in out.status(status, project.config.tests)
                ),
                _plain(row.requirement.text),
            ]
            for row in view.rows(project, spec)
        ]
        if not rows:
            out.write("No requirement matches this view.")
            continue
        out.table(
            ["", "", *(states * len(columns)), ""],
            rows,
            last=20,
            groups=[
                ("rule", 1),
                ("level", 1),
                *((label, len(states)) for label in columns),
                ("requirement", 1),
            ],
        )
    out.write()
    out.legend(project.config.tests)
    return 0


def recap(
    project: Project,
    view: View,
    specs: list[Specification],
    args: argparse.Namespace,
    out: _Output,
) -> int:
    """Write the counts per level and per column."""
    requirements = view.requirements(specs)
    rows = []
    for label, targets in view.columns(project):
        for level, count in project.recap(requirements, targets).items():
            if not count.requirements:
                continue
            values = [
                level,
                label,
                count.requirements,
                count.implemented,
                count.exceptions,
                count.todo + count.partial,
                count.missing,
                count.unannotated,
                f"{count.tested}/{count.needs_test}",
            ][: None if project.config.tests else -1]
            rows.append([_plain(str(value)) for value in values])
    out.table(_RECAP_HEADERS[: None if project.config.tests else -1], rows)
    return 0


def check(
    project: Project,
    view: View,
    specs: list[Specification],
    args: argparse.Namespace,
    out: _Output,
) -> int:
    """Write the requirements that fail, and return 1 if there are some."""
    fail_on = args.failures
    columns = view.columns(project)
    failures = 0
    for spec in specs:
        for requirement in view.requirements([spec]):
            for label, targets in columns:
                status = project.group(requirement, targets)
                reasons = [name for name in fail_on if _FAILURES[name](status)]
                if not reasons:
                    continue
                failures += 1
                out.write(
                    f"{requirement.id} {requirement.level} "
                    f"{label}: {', '.join(reasons)}"
                )
                out.write(f"    {requirement.text}")
    unused = (
        len(project.unused_applies)
        + len(project.unused_notes)
        + len(project.unused_outside)
    )
    if failures:
        out.write(f"{failures} failure{'s' if failures > 1 else ''}.")
    else:
        out.write("No failure.")
    if failures or (args.strict and unused):
        return 1
    return 0


def _fail_on(text: str) -> list[str]:
    """Read the states that make the check fail."""
    names = [name.strip() for name in text.split(",") if name.strip()]
    unknown = [name for name in names if name not in FAIL_ON]
    if unknown:
        raise _UsageError(
            f"unknown --fail-on value {unknown[0]!r}, expected {', '.join(FAIL_ON)}"
        )
    return names


def _parser() -> argparse.ArgumentParser:
    """Return the parser of the command line."""
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument(
        "specs", nargs="*", metavar="SPEC", help="specifications, all by default"
    )
    common.add_argument("--root", type=Path, help="the folder that contains .duvet/")
    source = common.add_mutually_exclusive_group()
    source.add_argument("--report-json", type=Path, help="a v2 JSON report of Duvet")
    source.add_argument("--duvet", default="duvet", help="the Duvet executable")
    common.add_argument("--targets", help="target selectors, separated by ';'")
    common.add_argument("--group-by", help="one column per value of a target attribute")
    common.add_argument("--sections", help="sections, separated by commas")
    common.add_argument("--levels", help="levels, separated by commas")
    common.add_argument("--labels", choices=sorted(PRESETS), default="symbols")
    common.add_argument(
        "--figure-requirements",
        action="store_true",
        help="keep the requirements found in the figures of IETF specifications",
    )

    parser = argparse.ArgumentParser(
        prog="sphinx-duvet", description="Compliance reports from Duvet."
    )
    commands = parser.add_subparsers(required=True, metavar="COMMAND")
    command = commands.add_parser(
        "report", parents=[common], help="show the requirements and their states"
    )
    command.add_argument("--show", choices=SHOW, default="all")
    command.set_defaults(command=report)
    command = commands.add_parser(
        "recap", parents=[common], help="count the requirements per level"
    )
    command.set_defaults(command=recap)
    command = commands.add_parser(
        "check", parents=[common], help="fail if some requirements are not done"
    )
    command.add_argument(
        "--fail-on",
        default=DEFAULT_FAIL_ON,
        help=f"states that fail, among {', '.join(FAIL_ON)} (default: {DEFAULT_FAIL_ON})",
    )
    command.add_argument(
        "--strict",
        action="store_true",
        help="also fail on [[applies]] entries and notes that match no requirement",
    )
    command.set_defaults(command=check)
    command = commands.add_parser(
        "export",
        help="write the Duvet report, with the annotations of the dependencies",
    )
    command.add_argument("output", type=Path, help="the JSON file to write")
    command.add_argument("--root", type=Path, help="the folder that contains .duvet/")
    command.add_argument("--duvet", default="duvet", help="the Duvet executable")
    command.set_defaults(command=export)
    return parser


def export(args: argparse.Namespace) -> int:
    """Run Duvet with the dependencies, and write its v2 JSON report."""
    root = _root(args)
    report = run_duvet(root, args.duvet, duvet_config_for(root))
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
    return 0


def _root(args: argparse.Namespace) -> Path:
    """Return the root of the project, given or found above the current folder."""
    root: Path | None = args.root or find_root(Path.cwd())
    if root is None:
        raise _UsageError("no .duvet/config.toml found, use --root")
    return root


def _load(args: argparse.Namespace) -> Project:
    """Load the project and its report."""
    root = _root(args)
    figures = args.figure_requirements
    if args.report_json is None:
        return Project.from_duvet(root, args.duvet, figures)
    return Project(root, read_report(args.report_json), figures)


def _specifications(project: Project, paths: list[str]) -> list[Specification]:
    """Return the specifications to show, all by default."""
    if not paths:
        return list(project.specifications.values())
    unknown = [path for path in paths if path not in project.specifications]
    if unknown:
        raise _UsageError(f"unknown specification {unknown[0]}")
    return [project.specifications[path] for path in paths]


def _warn_unused(project: Project) -> None:
    """Warn about the [[applies]] and [[outside]] entries and notes that match no requirement."""
    for entry in project.unused_applies:
        print(
            f"warning: no requirement matches the [[applies]] entry {entry.target}: {entry.quote!r}",
            file=sys.stderr,
        )
    for outside in project.unused_outside:
        print(
            f"warning: no requirement matches the [[outside]] entry {outside.target}: {outside.quote or ''!r}",
            file=sys.stderr,
        )
    for note in project.unused_notes:
        print(
            f"warning: {note.source}:{note.line}: no requirement matches the note {note.target}: {note.quote!r}",
            file=sys.stderr,
        )


def main(argv: Sequence[str] | None = None) -> int:
    """Run the command, and return its exit code."""
    args = _parser().parse_args(argv)
    command: Callable[..., int] = args.command
    try:
        if command is export:
            return export(args)
        project = _load(args)
        view = View.parse(
            args.targets,
            args.group_by,
            args.sections,
            args.levels,
            getattr(args, "show", None),
        )
        specs = _specifications(project, args.specs)
        if command is check:
            args.failures = _fail_on(args.fail_on)
    except DuvetNotFound as exc:
        print(
            f"sphinx-duvet: error: {exc}. "
            "Or use --report-json with a report produced elsewhere.",
            file=sys.stderr,
        )
        return 2
    except (_UsageError, DuvetError, OSError, KeyError, ValueError) as exc:
        print(f"sphinx-duvet: error: {exc}", file=sys.stderr)
        return 2
    _warn_unused(project)
    return command(project, view, specs, args, _Output(sys.stdout, args.labels))
