"""The duvet-report, duvet-recap and duvet-spec directives."""

import re
from typing import ClassVar
from typing import cast

from docutils import nodes
from docutils.parsers.rst import directives
from docutils.statemachine import StringList
from pygments.lexers import get_lexer_by_name
from pygments.token import Error
from pygments.token import is_token_subtype
from pygments.util import ClassNotFound
from sphinx import addnodes
from sphinx.util import logging
from sphinx.util.docutils import SphinxDirective
from sphinx.util.typing import OptionSpec

from . import _render as render
from . import layout
from ._domain import REPORT
from ._domain import SECTION
from ._domain import TEXT
from ._domain import DuvetDomain
from ._domain import rule_anchor
from ._domain import section_anchor
from ._domain import text_anchor
from ._labels import SINGLE
from ._labels import Labels
from ._labels import label_sources
from ._project import LoadedProject
from ._project import get_project
from .compliance import Counts
from .compliance import Project
from .compliance import State
from .compliance import Status
from .report import Requirement
from .report import Specification
from .report import section_number
from .targets import ConfigError
from .targets import Target
from .views import SHOW
from .views import View

logger = logging.getLogger(__name__)

_RFC_URL = "https://www.rfc-editor.org/rfc/rfc"


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

    def loaded_project(self) -> LoadedProject | None:
        """Return the Duvet project of the documentation, or warn that there is none."""
        loaded = get_project(self.env.srcdir)
        if loaded is None:
            logger.warning(
                "no .duvet/config.toml found above the documentation, use duvet_root",
                type="duvet",
                location=self.get_location(),
            )
        return loaded

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

    def unique_anchor(self, base: str) -> str:
        """Return an anchor that is not used yet in the document.

        An element shown twice in a document gets a numbered anchor the second time,
        such as duvet-rfc7643-3.1-9~2. Identifiers never contain a tilde.
        """
        used = cast(set[str], self.env.temp_data.setdefault("duvet_anchors", set()))
        anchor = base
        number = 1
        while anchor in used:
            number += 1
            anchor = f"{base}~{number}"
        used.add(anchor)
        return anchor

    def permalink(self, anchor: str, title: str) -> list[nodes.Node]:
        """Return a permalink to an anchor, or nothing if permalinks are disabled."""
        if not self.config.html_permalinks:
            return []
        return [
            render.duvet_permalink(
                "",
                self.config.html_permalinks_icon,
                refid=anchor,
                reftitle=title,
                classes=["headerlink"],
            )
        ]


class DuvetReport(_DuvetDirective):
    """Table of the requirements of a specification, with a status per column."""

    required_arguments = 1

    def run(self) -> list[nodes.Node]:
        """Return the legend and the table."""
        loaded = self.loaded_project()
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
        shown = view.rows(project, spec)
        if not shown:
            return [
                render.paragraph(nodes.Text("No requirement matches this view.")),
                *messages,
            ]
        headers = ["Level", "Requirement", *(label for label, _ in columns)]
        rows: list[nodes.row] = []
        section = None
        for item in shown:
            if item.requirement.section != section:
                section = item.requirement.section
                rows.append(self.section_row(spec, section, len(headers)))
            rows.append(
                self.row(project, item.requirement, columns, item.statuses, labels)
            )
        widths = [3, 65] + [10] * len(columns)
        legend = labels.legend(project.config.tests)
        return [
            legend,
            render.table(headers, rows, widths, classes=["duvet-report"]),
            *messages,
        ]

    def section_row(self, spec: Specification, section: str, columns: int) -> nodes.row:
        """Return a row with the number and the title of a section, and links to it.

        A permalink after the title points to the row. The links lead to the section
        in the text of the specification, if a page shows it, and on rfc-editor.org.
        """
        title = spec.sections.get(section, "")
        number = section_number(section)
        if section.startswith(("section-", "appendix-")):
            title = f"{number}. {title}".strip()
        anchor = self.unique_anchor(section_anchor(spec.name, number or "0"))
        heading = nodes.inline(text=title or number, classes=["duvet-section-title"])
        heading += self.permalink(anchor, f"{spec.name} {title or number}")
        links = nodes.inline(
            "",
            "",
            render.optional_link("Text", "section", f"{spec.name}#{section}"),
            classes=["duvet-section-link"],
        )
        url = spec.section_url(section)
        if url is not None:
            # The text of the specification in the documentation replaces it.
            links += nodes.reference(
                "RFC ↗", "RFC ↗", refuri=url, classes=["duvet-fallback"]
            )
        return render.spanning_row(
            columns,
            heading,
            nodes.Text(" "),
            links,
            classes=["duvet-section"],
            ids=[anchor],
        )

    def anchor(self, requirement: Requirement) -> str:
        """Return a unique anchor for a requirement in the document, and record it in the domain."""
        anchor = self.unique_anchor(rule_anchor(requirement.id))
        domain = cast(DuvetDomain, self.env.get_domain("duvet"))
        domain.note_rule(
            requirement.id, self.env.docname, anchor, requirement.text, REPORT
        )
        return anchor

    def parse_label(self, markup: str, messages: list[nodes.Node]) -> list[nodes.Node]:
        """Parse the inline markup of a label, and keep its error messages."""
        children, problems = self.state.inline_text(markup, self.lineno)
        messages.extend(problems)
        return list(children)

    def row(
        self,
        project: Project,
        requirement: Requirement,
        columns: list[tuple[str, list[Target]]],
        statuses: list[Status],
        labels: Labels,
    ) -> nodes.row:
        """Return the row of a requirement: level, text, statuses.

        A permalink after the level shows the identifier of the requirement.
        A link after the text leads to the requirement in the text of the specification,
        if a page shows it. The annotations of each column are chips below its states.
        """
        anchor = self.anchor(requirement)
        sentence = render.requirement_text(requirement.text)
        sentence += render.optional_link(
            "§", "text", requirement.id, classes=["duvet-rule-link"]
        )
        text: list[nodes.Node] = [sentence]
        reasons = dict.fromkeys(c.reason for c in requirement.cites if c.reason)
        text += [
            render.paragraph(
                nodes.Text(f"Deviation: {reason}"), classes=["duvet-reason"]
            )
            for reason in reasons
        ]
        for note in requirement.notes:
            container = nodes.container(classes=["duvet-note"])
            self.state.nested_parse(
                StringList(note.body, source=str(note.source)),
                self.content_offset,
                container,
            )
            text.append(container)
        if requirement.outside is not None:
            text.append(
                render.paragraph(
                    nodes.Text(f"Out of scope: {requirement.outside}"),
                    classes=["duvet-outside-reason"],
                )
            )
        permalink = anchor if self.config.html_permalinks else None
        level = render.level_cell(requirement.level, permalink, requirement.id)
        cells: list[nodes.Node | list[nodes.Node]] = [level, text]
        for (_, targets), status in zip(columns, statuses, strict=True):
            cells.append(
                self.status_cell(project, requirement, targets, status, labels)
            )
        node = render.row(cells, ids=[anchor])
        strength = render.level_strength(requirement.level)
        level_entry = cast(nodes.entry, node[0])
        level_entry["classes"] += [
            "duvet-level-column",
            f"duvet-level-column-{strength}",
        ]
        return node

    @staticmethod
    def status_cell(
        project: Project,
        requirement: Requirement,
        targets: list[Target],
        status: Status,
        labels: Labels,
    ) -> list[nodes.Node]:
        """Return the states of a column, each one followed by the annotations behind it."""
        cell = labels.status_cell(status, project.config.tests)
        if status.implementation in SINGLE:
            return cell
        implementations, tests = project.evidence(requirement, targets)
        if not project.config.tests:
            return [*cell, *render.chips(implementations, "CITATION")]
        return [
            cell[0],
            *render.chips(implementations, "CITATION"),
            cell[1],
            *render.chips(tests, "TEST"),
        ]


class DuvetRecap(_DuvetDirective):
    """Counts per level and per column, for a specification or for all of them."""

    optional_arguments = 1

    def run(self) -> list[nodes.Node]:
        """Return the table of counts."""
        loaded = self.loaded_project()
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
                    rows.append(self.row(level, label, count, project.config.tests))
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
        ][: None if project.config.tests else -1]
        widths = [8, 8] + [7] * (len(headers) - 2)
        return [render.table(headers, rows, widths, classes=["duvet-recap"])]

    @staticmethod
    def row(level: str, label: str, count: Counts, tests: bool) -> list[nodes.Node]:
        """Return the cells of a level for a group of targets. Gaps are highlighted.

        Without tests, the count of tested requirements is left out.
        """
        todo = count.todo + count.partial
        cells: list[nodes.Node] = [
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
        ]
        if tests:
            cells.append(
                render.paragraph(nodes.Text(f"{count.tested}/{count.needs_test}"))
            )
        return cells


def _highlight(value: str) -> str:
    """Check the value of the highlight option: auto, none, or a Pygments lexer."""
    if value in ("auto", "none"):
        return value
    try:
        get_lexer_by_name(value)
    except ClassNotFound:
        raise ValueError(f"unknown Pygments lexer {value!r}") from None
    return value


def _keywords(children: list[nodes.Node]) -> list[nodes.Node]:
    """Return text nodes with their BCP 14 key words marked, as in the HTML RFCs."""
    return [
        node
        for child in children
        for node in (
            render.bcp14_text(child.astext())
            if isinstance(child, nodes.Text)
            else [child]
        )
    ]


class DuvetSpec(_DuvetDirective):
    """The text of an IETF specification, with its requirements highlighted.

    Each section of the specification becomes a section of the document.
    Each requirement links to its row in a report, and is colored by its worst state.
    """

    required_arguments = 1
    option_spec: ClassVar[OptionSpec] = {
        "highlight": _highlight,
        "targets": directives.unchanged,
    }

    spec: Specification
    states: dict[str, State]
    highlight: str
    texts: list[layout.SectionText]
    structures: dict[str, list[layout.Element]]
    section_ids: dict[str, str]
    references: dict[str, str]
    reference_ids: dict[int, str]
    anchored: set[str]
    requirements: list[Requirement]

    def run(self) -> list[nodes.Node]:
        """Return the sections of the specification."""
        loaded = self.loaded_project()
        if loaded is None:
            return []
        project = loaded.project
        spec = self.specification(loaded, self.arguments[0])
        if spec is None:
            return []
        if spec.format != "ietf":
            logger.warning(
                "duvet-spec only shows IETF text specifications, not %s",
                spec.path,
                type="duvet",
                location=self.get_location(),
            )
            return []
        try:
            view = self.view()
        except ConfigError as exc:
            logger.warning(str(exc), type="duvet", location=self.get_location())
            return []
        targets = [t for _, column in view.columns(project) for t in column]
        self.spec = spec
        self.states = {
            requirement.id: project.group(requirement, targets).implementation
            for requirement in spec.requirements
        }
        self.highlight = self.options.get("highlight") or self.configured_highlight()
        self.texts = layout.sections(spec)
        self.structures = {
            text.section: layout.structure(text.blocks) for text in self.texts
        }
        self.section_ids = {
            text.section: self.unique_anchor(text.section) for text in self.texts
        }
        domain = cast(DuvetDomain, self.env.get_domain("duvet"))
        for text in self.texts:
            domain.note_rule(
                f"{spec.name}#{text.section}",
                self.env.docname,
                self.section_ids[text.section],
                text.heading,
                SECTION,
            )
        self.note_references()
        self.anchored = set()
        self.requirements = spec.requirements
        result: list[nodes.Node] = [render.state_legend(), *self.front_matter()]
        parents: list[nodes.Element] = []
        for text in self.texts:
            section = self.section(text)
            del parents[text.depth - 1 :]
            (parents[-1] if parents else result).append(section)
            parents.append(section)
        self.note_unanchored()
        return result

    def configured_highlight(self) -> str:
        """Return the highlight setting of the configuration, or auto if it is invalid."""
        try:
            return _highlight(self.config.duvet_spec_highlight)
        except ValueError as error:
            logger.warning(
                "duvet_spec_highlight: %s",
                error,
                type="duvet",
                location=self.get_location(),
            )
            return "auto"

    def note_references(self) -> None:
        """Give an anchor to each entry of the references, such as ``[RFC7644]``."""
        self.references = {}
        self.reference_ids = {}
        for text in self.texts:
            if "References" not in text.title:
                continue
            for element in self.structures[text.section]:
                if not isinstance(element, layout.DefinitionList):
                    continue
                for definition in element.items:
                    term = self.text_of(definition.term)
                    if not (term.startswith("[") and term.endswith("]")):
                        continue
                    label = term[1:-1]
                    anchor = self.unique_anchor(nodes.make_id(f"reference-{label}"))
                    self.references.setdefault(label, anchor)
                    self.reference_ids[id(definition)] = anchor

    def note_unanchored(self) -> None:
        """Link the requirements that start out of the text, such as on a list marker, to their section."""
        domain = cast(DuvetDomain, self.env.get_domain("duvet"))
        for requirement in self.spec.requirements:
            anchor = self.section_ids.get(requirement.section)
            if requirement.id in self.anchored or anchor is None:
                continue
            domain.note_rule(
                requirement.id, self.env.docname, anchor, requirement.text, TEXT
            )

    def text_of(self, block: layout.Block) -> str:
        """Return the text of a block, on one line."""
        return " ".join(self.spec.contents[a:b].decode() for a, b in block.pieces())

    def front_matter(self) -> list[nodes.Node]:
        """Return the header of the first page as a table, and the blocks after it.

        The title is left out when it is the title of the specification, as it is
        the title of the page.
        """
        spec_blocks = layout.front_matter(self.spec)
        result: list[nodes.Node] = [
            render.table(
                [],
                [
                    [nodes.Text(left), nodes.Text(right)]
                    for left, right in layout.header_rows(block)
                ],
                [1, 1],
                classes=["duvet-front-matter"],
            )
            for block in spec_blocks[:1]
        ]
        title = self.spec.title.split(": ", 1)[-1]
        result.extend(
            self.figure_node(layout.Figure(block))
            for block in spec_blocks[1:]
            if " ".join(self.text_of(block).split()) != " ".join(title.split())
        )
        return result

    def section(self, text: layout.SectionText) -> nodes.section:
        """Return a section of the specification, with its content.

        The table of contents becomes a list of links to the sections.
        Smart quotes are disabled, so the quotes of the specification are kept.
        """
        section = nodes.section(ids=[self.section_ids[text.section]])
        section["support_smartquotes"] = False
        section += nodes.title(text.heading, text.heading)
        if text.section == "name-table-of-contents":
            section += self.contents(text)
            return section
        lines = text.section.startswith("name-author")
        section.extend(self.element_nodes(self.structures[text.section], lines))
        return section

    def contents(self, toc: layout.SectionText) -> nodes.bullet_list:
        """Return the sections after the table of contents, as nested lists of links."""
        depth = layout.toc_depth(toc, self.spec.contents)
        texts = self.texts[self.texts.index(toc) + 1 :]
        root = nodes.bullet_list(classes=["duvet-contents"])
        stack: list[tuple[int, nodes.bullet_list]] = [(1, root)]
        for text in texts:
            if text.depth > depth:
                continue
            while stack[-1][0] > text.depth:
                stack.pop()
            if stack[-1][0] < text.depth and stack[-1][1].children:
                nested = nodes.bullet_list()
                cast(nodes.list_item, stack[-1][1].children[-1]).append(nested)
                stack.append((text.depth, nested))
            reference = nodes.reference(
                text.heading, text.heading, refid=self.section_ids[text.section]
            )
            stack[-1][1].append(nodes.list_item("", nodes.paragraph("", "", reference)))
        return root

    def element_nodes(
        self, elements: list[layout.Element], lines: bool = False
    ) -> list[nodes.Element]:
        """Return the nodes of paragraphs, figures, tables and lists.

        With lines, paragraphs keep their line breaks, as in the addresses of the authors.
        """
        result: list[nodes.Element] = []
        for element in elements:
            if isinstance(element, layout.Paragraph):
                result.append(self.paragraph_node(element.block, lines))
            elif isinstance(element, layout.Figure):
                result.append(self.figure_node(element))
            elif isinstance(element, layout.Table):
                result.append(self.table_node(element))
            elif isinstance(element, layout.ItemList):
                result.append(self.list_node(element))
            else:
                result.append(self.definitions_node(element))
        return result

    def paragraph_node(self, block: layout.Block, lines: bool) -> nodes.Element:
        """Return a paragraph, or a block of lines."""
        if lines:
            return nodes.line_block(
                "",
                *(
                    nodes.line("", "", *self.inline(layout.Block(block.kind, [line])))
                    for line in block.lines
                ),
            )
        paragraph = nodes.paragraph("", "", *self.inline(block))
        paragraph["support_smartquotes"] = False
        return paragraph

    def list_node(self, item_list: layout.ItemList) -> nodes.bullet_list:
        """Return a list. Markers other than bullets, such as ``(A)``, are kept.

        An item always starts with a paragraph: the text after its marker.
        """
        node = nodes.bullet_list(
            classes=[] if item_list.bullet else ["duvet-enumerated"]
        )
        for item in item_list.items:
            body = self.element_nodes(item.body)
            if not item_list.bullet:
                marker = nodes.inline(
                    item.marker, item.marker, classes=["duvet-marker"]
                )
                body[0][0:0] = [marker, nodes.Text(" ")]
            node += nodes.list_item("", *body)
        return node

    def definitions_node(
        self, definitions: layout.DefinitionList
    ) -> nodes.definition_list:
        """Return a list of terms and their definitions."""
        node = nodes.definition_list()
        for definition in definitions.items:
            anchor = self.reference_ids.get(id(definition))
            term = nodes.term("", "", *self.inline(definition.term, links=False))
            term["ids"] = [anchor] if anchor else []
            node += nodes.definition_list_item(
                "", term, nodes.definition("", *self.element_nodes(definition.body))
            )
        return node

    def table_node(self, table: layout.Table) -> nodes.table:
        """Return a table, with a paragraph per cell."""
        node = nodes.table(classes=["duvet-spec-table"])
        if table.caption is not None:
            node += nodes.title("", "", *self.inline(table.caption, links=False))
        group = nodes.tgroup(cols=len(table.widths))
        node += group
        for width in table.widths:
            group += nodes.colspec(colwidth=width)
        if table.header:
            group += nodes.thead("", *(self.row_node(row) for row in table.header))
        group += nodes.tbody("", *(self.row_node(row) for row in table.rows))
        return node

    def row_node(self, cells: list[layout.Block]) -> nodes.row:
        """Return a row of a table."""
        row = nodes.row()
        for cell in cells:
            entry = nodes.entry()
            if cell.lines:
                entry += self.paragraph_node(cell, lines=False)
            row += entry
        return row

    def figure_node(self, figure: layout.Figure) -> nodes.Element:
        """Return a block that keeps its layout, with its caption below, as in the specification.

        Figures are examples, so their requirements are not highlighted.
        They link to the section of the figure. Examples in JSON or HTTP are highlighted.
        """
        runs = layout.runs(figure.block, self.spec.contents, [])
        text = "".join(run.text for run in runs)
        literal = nodes.literal_block(
            text, text, language=self.language(text) or "text", classes=["duvet-figure"]
        )
        if figure.caption is None:
            return literal
        caption = nodes.caption("", "", *self.inline(figure.caption, links=False))
        return nodes.container(
            "",
            literal,
            caption,
            classes=["literal-block-wrapper", "duvet-figure-wrapper"],
            literal_block=True,
        )

    def language(self, text: str) -> str | None:
        """Return the language to highlight a figure in, if its text has no syntax error."""
        if self.highlight == "none":
            return None
        language = (
            layout.figure_language(text) if self.highlight == "auto" else self.highlight
        )
        if language is None:
            return None
        tokens = get_lexer_by_name(language).get_tokens(text)
        if any(is_token_subtype(token, Error) for token, _ in tokens):
            return None
        return language

    def inline(self, block: layout.Block, links: bool = True) -> list[nodes.Node]:
        """Return the text of a block, with its requirements and its links."""
        return [
            node
            for run in layout.runs(block, self.spec.contents, self.requirements)
            for node in self.run_nodes(run, links)
        ]

    def run_nodes(self, run: layout.Run, links: bool) -> list[nodes.Node]:
        """Return a run of text. A requirement is highlighted, and links to its report.

        The links of the text, such as [RFC7644], cut the link to the report in parts.
        The run gets an anchor for each requirement that starts in it,
        so a requirement hidden by another one can still be referenced.
        """
        pending = [r for r in run.starts if r.id not in self.anchored]
        children: list[nodes.Node] = (
            self.linked(run.text) if links else [nodes.Text(run.text)]
        )
        if run.owner is None:
            return _keywords(children)
        anchors = [self.anchor(requirement) for requirement in pending]
        state = self.states[run.owner.id]
        if state == State.NOT_APPLICABLE:
            return [nodes.inline("", "", *_keywords(children), ids=anchors)]
        parts = [
            addnodes.pending_xref(
                "",
                nodes.inline(
                    "",
                    "",
                    *render.bcp14_text(child.astext()),
                    classes=["duvet-rule-text"],
                ),
                refdomain="duvet",
                reftype="status",
                reftarget=run.owner.id,
                refexplicit=True,
                refwarn=False,
            )
            if isinstance(child, nodes.Text)
            else child
            for child in children
        ]
        return [
            nodes.inline(
                "",
                "",
                *parts,
                ids=anchors,
                classes=["duvet-rule", f"duvet-rule-{state.name.lower()}"],
            )
        ]

    def anchor(self, requirement: Requirement) -> str:
        """Return a new anchor for a requirement in the text, and record it."""
        domain = cast(DuvetDomain, self.env.get_domain("duvet"))
        anchor = self.unique_anchor(text_anchor(requirement.id))
        domain.note_rule(
            requirement.id, self.env.docname, anchor, requirement.text, TEXT
        )
        self.anchored.add(requirement.id)
        return anchor

    def linked(self, text: str) -> list[nodes.Node]:
        """Return a text with links to sections, references, other RFCs and addresses."""
        result: list[nodes.Node] = []
        position = 0
        for link in layout.links(text):
            node = self.link_node(link, text[link.start : link.end])
            if node is None:
                continue
            if link.start > position:
                result.append(nodes.Text(text[position : link.start]))
            result.append(node)
            position = link.end
        if position < len(text):
            result.append(nodes.Text(text[position:]))
        return result

    def link_node(self, link: layout.Link, text: str) -> nodes.reference | None:
        """Return the node of a link, or None if its target is unknown."""
        if link.kind == "section":
            anchor = self.section_ids.get(link.target)
            return nodes.reference(text, text, refid=anchor) if anchor else None
        if link.kind == "reference":
            anchor = self.references.get(link.target)
            if anchor is not None:
                return nodes.reference(text, text, refid=anchor)
            if not re.fullmatch(r"RFC\d+", link.target):
                return None
            return nodes.reference(text, text, refuri=_RFC_URL + link.target[3:])
        if link.kind == "rfc":
            return nodes.reference(text, text, refuri=_RFC_URL + link.target)
        if link.kind == "email":
            return nodes.reference(text, text, refuri=f"mailto:{link.target}")
        return nodes.reference(text, text, refuri=link.target)
