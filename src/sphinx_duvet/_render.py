"""Docutils nodes for the compliance reports."""

import re
from collections.abc import Sequence

from docutils import nodes
from sphinx.writers.html5 import HTML5Translator

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


def cite_kind(cite: Cite) -> str:
    """Return the kind of a cite, and the dependency it comes from."""
    kind = CITE_TYPES.get(cite.type, cite.type.lower())
    if cite.dependency is None:
        return kind
    return f"{kind}, {cite.dependency} {cite.version}".rstrip()


def paragraph(*children: nodes.Node, classes: Sequence[str] = ()) -> nodes.paragraph:
    """Return a paragraph with some children."""
    node = nodes.paragraph(classes=list(classes))
    node.extend(children)
    return node


def link(text: str, uri: str | None) -> nodes.Node:
    """Return a link, or plain text without an URI."""
    if uri is None:
        return nodes.Text(text)
    return nodes.reference(text, text, refuri=uri)


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


def level_badge(level: str) -> nodes.inline:
    """Return a badge for a requirement level. The stronger the level, the heavier the badge."""
    strength = _BCP14.get(level, "may")
    return nodes.inline(text=level, classes=["duvet-level", f"duvet-level-{strength}"])


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
    """Return a table. Each row is a row node, or a list of cells."""
    node = nodes.table(classes=["duvet-table", *classes])
    group = nodes.tgroup(cols=len(headers))
    node += group
    for width in widths:
        group += nodes.colspec(colwidth=width)
    head = nodes.thead()
    group += head
    header_row = nodes.row()
    for header in headers:
        header_row += nodes.entry("", paragraph(nodes.Text(header)))
    head += header_row
    body = nodes.tbody()
    group += body
    for item in rows:
        body += item if isinstance(item, nodes.row) else row(item)
    return node
