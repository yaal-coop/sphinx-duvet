"""The duvet-report and duvet-recap directives."""

from typing import ClassVar

from docutils import nodes
from docutils.parsers.rst import directives
from docutils.statemachine import StringList
from sphinx.util import logging
from sphinx.util.docutils import SphinxDirective
from sphinx.util.typing import OptionSpec

from . import _render as render
from ._labels import Labels
from ._labels import label_sources
from ._project import LoadedProject
from ._project import get_project
from .compliance import Counts
from .compliance import Status
from .report import Requirement
from .report import Specification
from .targets import ConfigError
from .views import SHOW
from .views import View

logger = logging.getLogger(__name__)


def _show(value: str) -> str:
    """Check the value of the show option."""
    return directives.choice(value, SHOW)


class _DuvetDirective(SphinxDirective):
    """Base class of the directives that read the Duvet project."""

    option_spec: ClassVar[OptionSpec] = {
        "targets": directives.unchanged,
        "group-by": directives.unchanged,
        "sections": directives.unchanged,
        "levels": directives.unchanged,
        "show": _show,
    }

    def view(self) -> View:
        """Read the options of the directive."""
        return View.parse(
            targets=self.options.get("targets"),
            group_by=self.options.get("group-by"),
            sections=self.options.get("sections"),
            levels=self.options.get("levels"),
            show=self.options.get("show"),
        )

    def specification(self, loaded: LoadedProject, path: str) -> Specification | None:
        """Return a specification of the project, and track the files it depends on."""
        project = loaded.project
        spec = project.specifications.get(path)
        if spec is None:
            logger.warning(
                "unknown specification %s",
                path,
                type="duvet",
                location=self.get_location(),
            )
            return None
        for dependency in project.dependencies(spec):
            self.env.note_dependency(str(dependency))
        if loaded.report is not None:
            self.env.note_dependency(str(loaded.report))
        return spec


class DuvetReport(_DuvetDirective):
    """Table of the requirements of a specification, with a status per column."""

    required_arguments = 1

    def run(self) -> list[nodes.Node]:
        """Return the legend and the table."""
        loaded = get_project(self.env.srcdir)
        if loaded is None:
            return []
        project = loaded.project
        spec = self.specification(loaded, self.arguments[0])
        if spec is None:
            return []
        try:
            view = self.view()
        except ConfigError as exc:
            logger.warning(str(exc), type="duvet", location=self.get_location())
            return []
        columns = view.columns(project)

        messages: list[nodes.Node] = []
        labels = Labels(
            label_sources(self.config.duvet_labels)[0],
            lambda markup: self.parse_label(markup, messages),
        )
        rows = [
            self.row(spec, row.requirement, row.statuses, labels)
            for row in view.rows(project, spec)
        ]

        if not rows:
            return [
                render.paragraph(nodes.Text("No requirement matches this view.")),
                *messages,
            ]
        headers = ["Section", "Requirement", *(label for label, _ in columns)]
        widths = [8, 60] + [10] * len(columns)
        return [labels.legend(), render.table(headers, rows, widths), *messages]

    def parse_label(self, markup: str, messages: list[nodes.Node]) -> list[nodes.Node]:
        """Parse the inline markup of a label, and keep its error messages."""
        children, problems = self.state.inline_text(markup, self.lineno)
        messages.extend(problems)
        return list(children)

    def row(
        self,
        spec: Specification,
        requirement: Requirement,
        statuses: list[Status],
        labels: Labels,
    ) -> list[nodes.Node | list[nodes.Node]]:
        """Return the cells of a requirement: section and level, text, statuses."""
        number = requirement.section.removeprefix("section-").removeprefix("appendix-")
        section = render.link(number, spec.section_url(requirement.section))
        text: list[nodes.Node] = [render.requirement_text(requirement.text)]
        if requirement.cites:
            items = nodes.bullet_list(classes=["duvet-cites"])
            for cite in sorted(requirement.cites, key=lambda c: (c.path, c.line)):
                item = render.paragraph(
                    render.link(f"{cite.path}:{cite.line}", cite.url)
                )
                item += nodes.Text(f" ({render.cite_kind(cite)})")
                if cite.reason:
                    item += nodes.Text(f": {cite.reason}")
                items += nodes.list_item("", item)
            text.append(items)
        for note in requirement.notes:
            container = nodes.container(classes=["duvet-note"])
            self.state.nested_parse(
                StringList(note.body, source=str(note.source)),
                self.content_offset,
                container,
            )
            text.append(container)
        cells: list[nodes.Node | list[nodes.Node]] = [
            [
                render.paragraph(section),
                render.paragraph(render.level_badge(requirement.level)),
            ],
            text,
        ]
        cells += [labels.status_cell(status) for status in statuses]
        return cells


class DuvetRecap(_DuvetDirective):
    """Counts per level and per column, for a specification or for all of them."""

    optional_arguments = 1

    def run(self) -> list[nodes.Node]:
        """Return the table of counts."""
        loaded = get_project(self.env.srcdir)
        if loaded is None:
            return []
        project = loaded.project
        if self.arguments:
            spec = self.specification(loaded, self.arguments[0])
            if spec is None:
                return []
            specs = [spec]
        else:
            specs = [
                s
                for path in project.specifications
                if (s := self.specification(loaded, path)) is not None
            ]
        try:
            view = self.view()
        except ConfigError as exc:
            logger.warning(str(exc), type="duvet", location=self.get_location())
            return []
        requirements = view.requirements(specs)

        rows = []
        for label, targets in view.columns(project):
            for level, count in project.recap(requirements, targets).items():
                if count.requirements:
                    rows.append(self.row(level, label, count))
        headers = [
            "Level",
            "Targets",
            "Rules",
            "Done",
            "Deviations",
            "Todo",
            "Missing",
            "Not annotated",
            "Tested",
        ]
        return [render.table(headers, rows, [8, 8] + [7] * 7, classes=["duvet-recap"])]

    @staticmethod
    def row(level: str, label: str, count: Counts) -> list[nodes.Node]:
        """Return the cells of a level for a group of targets. Gaps are highlighted."""
        todo = count.todo + count.partial
        return [
            render.paragraph(render.level_badge(level)),
            render.paragraph(nodes.Text(label)),
            render.paragraph(nodes.Text(str(count.requirements))),
            render.paragraph(nodes.Text(str(count.implemented))),
            render.paragraph(nodes.Text(str(count.exceptions))),
            render.paragraph(
                nodes.Text(str(todo)), classes=["duvet-todo"] if todo else []
            ),
            render.paragraph(
                nodes.Text(str(count.missing)),
                classes=["duvet-missing"] if count.missing else [],
            ),
            render.paragraph(nodes.Text(str(count.unannotated))),
            render.paragraph(nodes.Text(f"{count.tested}/{count.needs_test}")),
        ]
