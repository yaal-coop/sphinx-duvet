"""Docutils nodes for the compliance reports."""

import re
from collections.abc import Sequence

from docutils import nodes
from sphinx import addnodes
from sphinx.transforms.post_transforms import SphinxPostTransform
from sphinx.writers.html5 import HTML5Translator

from ._labels import duvet_label
from .report import Cite

# Key words of RFC 2119 and RFC 8174, the longest first, with their strength.
_BCP14 = {
    "MUST NOT": "must",
    "SHALL NOT": "must",
    "SHOULD NOT": "should",
    "NOT RECOMMENDED": "should",
    "REQUIRED": "must",
    "RECOMMENDED": "should",
    "OPTIONAL": "may",
    "MUST": "must",
    "SHALL": "must",
    "SHOULD": "should",
    "MAY": "may",
}
_BCP14_PATTERN = re.compile(r"\b(" + "|".join(_BCP14) + r")\b")

CITE_TYPES = {
    "CITATION": "implementation",
    "IMPLICATION": "implication",
    "EXCEPTION": "exception",
    "TODO": "todo",
    "TEST": "test",
}


class duvet_permalink(nodes.reference):
    """A link to a row of a report, shown on hover like the permalinks of headings.

    Formats other than HTML leave it out.
    """


def visit_permalink_html(translator: HTML5Translator, node: duvet_permalink) -> None:
    """Open the link, as any reference."""
    translator.visit_reference(node)


def depart_permalink_html(translator: HTML5Translator, node: duvet_permalink) -> None:
    """Close the link, as any reference."""
    translator.depart_reference(node)


def skip_permalink(translator: nodes.NodeVisitor, node: duvet_permalink) -> None:
    """Leave the link out of formats other than HTML."""
    raise nodes.SkipNode


def chips(cites: Sequence[Cite], plain: str) -> list[nodes.Node]:
    """Return the cites as chips, one per file and kind, with a link per line.

    Cites of the plain type have no label: their place in the cell says their kind.
    A chip with one line is a link as a whole.
    """
    groups: dict[tuple[str, str], list[Cite]] = {}
    for cite in sorted(cites, key=lambda c: (c.path, c.line)):
        label = (
            "" if cite.type == plain else CITE_TYPES.get(cite.type, cite.type.lower())
        )
        if cite.dependency is not None:
            label = f"{label} {cite.dependency} {cite.version}".strip()
        groups.setdefault((label, cite.path), []).append(cite)
    if not groups:
        return []
    box = nodes.paragraph(classes=["duvet-chips"])
    for (label, path), group in groups.items():
        box += _chip(label, path, group)
    return [box]


def _chip(label: str, path: str, cites: list[Cite]) -> nodes.Element:
    """Return the chip of the cites of a file."""
    name = _short_name(path)
    head: list[nodes.Node] = []
    if label:
        head += [
            nodes.inline(text=label, classes=["duvet-chip-label"]),
            nodes.Text(" "),
        ]
    first = cites[0]
    if len(cites) == 1 and first.url is not None:
        head += [nodes.inline(text=name, classes=["duvet-chip-name"]), nodes.Text(" ")]
        return nodes.reference(
            "",
            "",
            *head,
            nodes.inline(text=str(first.line), classes=["duvet-chip-line"]),
            refuri=first.url,
            reftitle=f"{path}:{first.line}",
            classes=["duvet-chip"],
        )
    chip = nodes.inline(classes=["duvet-chip"])
    chip.extend(head)
    chip += duvet_label(name, name, explanation=path, classes=["duvet-chip-name"])
    for index, cite in enumerate(cites):
        chip += nodes.Text(" · " if index else " ")
        number = str(cite.line)
        if cite.url is None:
            chip += nodes.inline(text=number, classes=["duvet-chip-line"])
            continue
        chip += nodes.reference(
            number,
            number,
            refuri=cite.url,
            reftitle=f"{path}:{cite.line}",
            classes=["duvet-chip-line"],
        )
    return chip


def _short_name(path: str, width: int = 24) -> str:
    """Return the name of a file, shortened in the middle if it is long."""
    name = path.rsplit("/", 1)[-1]
    if len(name) <= width:
        return name
    half = (width - 1) // 2
    return name[:half] + "…" + name[-half:]


def paragraph(*children: nodes.Node, classes: Sequence[str] = ()) -> nodes.paragraph:
    """Return a paragraph with some children."""
    node = nodes.paragraph(classes=list(classes))
    node.extend(children)
    return node


def bcp14_text(text: str) -> list[nodes.Node]:
    """Return the text of a requirement, with the BCP 14 key words marked.

    The key words are marked as in the HTML RFCs, with a class per strength.
    """
    result: list[nodes.Node] = []
    position = 0
    for match in _BCP14_PATTERN.finditer(text):
        if match.start() > position:
            result.append(nodes.Text(text[position : match.start()]))
        word = match.group(1)
        result.append(
            nodes.inline(
                text=word, classes=["duvet-bcp14", f"duvet-bcp14-{_BCP14[word]}"]
            )
        )
        position = match.end()
    if position < len(text):
        result.append(nodes.Text(text[position:]))
    return result


def requirement_text(text: str) -> nodes.paragraph:
    """Return the text of a requirement as it is in the specification.

    Smart quotes are disabled, so the quotes of the specification are kept.
    """
    node = paragraph(*bcp14_text(text))
    node["support_smartquotes"] = False
    return node


def level_strength(level: str) -> str:
    """Return the strength of a requirement level: must, should or may."""
    return _BCP14.get(level, "may")


def level_badge(level: str) -> nodes.inline:
    """Return a badge for a requirement level. The stronger the level, the heavier the badge."""
    strength = level_strength(level)
    return nodes.inline(text=level, classes=["duvet-level", f"duvet-level-{strength}"])


def level_cell(level: str, anchor: str | None, title: str) -> nodes.paragraph:
    """Return the level of a requirement, written vertically, as a link to its row.

    Without an anchor, the level is not a link.
    """
    word = nodes.inline(text=level, classes=["duvet-level-word"])
    cell = paragraph(classes=["duvet-level-cell"])
    if anchor is None:
        cell += word
        return cell
    cell += nodes.reference(
        "", "", word, refid=anchor, reftitle=title, classes=["duvet-level-link"]
    )
    return cell


Cells = Sequence[nodes.Node | list[nodes.Node]]


def row(cells: Cells, ids: Sequence[str] = ()) -> nodes.row:
    """Return a table row. Each cell is a node or a list of nodes."""
    node = nodes.row(ids=list(ids))
    for cell in cells:
        entry = nodes.entry()
        entry.extend(cell if isinstance(cell, list) else [cell])
        node += entry
    return node


def spanning_row(
    columns: int,
    *children: nodes.Node,
    classes: Sequence[str] = (),
    ids: Sequence[str] = (),
) -> nodes.row:
    """Return a table row with a single cell over every column."""
    entry = nodes.entry(morecols=columns - 1)
    entry += paragraph(*children)
    return nodes.row("", entry, classes=list(classes), ids=list(ids))


def table(
    headers: Sequence[str],
    rows: Sequence[Cells | nodes.row],
    widths: Sequence[int],
    classes: Sequence[str] = (),
) -> nodes.table:
    """Return a table. Each row is a row node, or a list of cells.

    Without headers, the table has no header row.
    """
    node = nodes.table(classes=["duvet-table", *classes])
    group = nodes.tgroup(cols=len(widths))
    node += group
    for width in widths:
        group += nodes.colspec(colwidth=width)
    if headers:
        header_row = nodes.row()
        for header in headers:
            header_row += nodes.entry("", paragraph(nodes.Text(header)))
        group += nodes.thead("", header_row)
    body = nodes.tbody()
    group += body
    for item in rows:
        body += item if isinstance(item, nodes.row) else row(item)
    return node


_RULE_STATES = [
    ("ok", "done"),
    ("partial", "partly done or planned"),
    ("missing", "missing"),
    ("exception", "deliberate deviation"),
    ("unannotated", "not annotated yet"),
    ("outside", "out of scope"),
]


def state_legend() -> nodes.paragraph:
    """Return a line that explains the highlight colors of the requirements."""
    node = paragraph(nodes.Text("Requirements: "), classes=["duvet-legend"])
    for index, (state, text) in enumerate(_RULE_STATES):
        if index:
            node += nodes.Text(" · ")
        node += nodes.inline(text=text, classes=["duvet-rule", f"duvet-rule-{state}"])
    return node


class duvet_optional_link(nodes.inline):
    """The content of a link between the text of a specification and its reports.

    The link is left out when it leads nowhere, and in formats other than HTML,
    as the permalinks.
    """


def visit_optional_link_html(
    translator: HTML5Translator, node: duvet_optional_link
) -> None:
    """Open the content of the link, as any inline text."""
    translator.visit_inline(node)


def depart_optional_link_html(
    translator: HTML5Translator, node: duvet_optional_link
) -> None:
    """Close the content of the link, as any inline text."""
    translator.depart_inline(node)


class FallbackLinks(SphinxPostTransform):
    """Remove a fallback link, such as the link to the RFC, when an optional link next to it leads somewhere.

    Other formats than HTML keep the fallback, as they leave out the optional links.
    """

    default_priority = 19
    formats = ("html",)

    def run(self, **kwargs: object) -> None:
        """Remove the fallbacks next to the optional links that are links."""
        for content in self.document.findall(duvet_optional_link):
            link = content.parent
            if not isinstance(link, nodes.reference) or link.parent is None:
                continue
            for sibling in list(link.parent.children):
                if isinstance(sibling, nodes.Element) and (
                    "duvet-fallback" in sibling["classes"]
                ):
                    link.parent.remove(sibling)


class OptionalLinks(SphinxPostTransform):
    """Remove the links between the text of a specification and its reports, when they lead nowhere."""

    default_priority = 20

    def run(self, **kwargs: object) -> None:
        """Remove the contents that are not in a link."""
        for content in list(self.document.findall(duvet_optional_link)):
            if not isinstance(content.parent, nodes.reference):
                content.parent.remove(content)


def optional_link(
    text: str, kind: str, target: str, classes: Sequence[str] = ()
) -> nodes.Node:
    """Return a link to a requirement or a section, left out if it leads nowhere."""
    return addnodes.pending_xref(
        "",
        duvet_optional_link(text, text, classes=list(classes)),
        refdomain="duvet",
        reftype=kind,
        reftarget=target,
        refexplicit=True,
        refwarn=False,
    )
