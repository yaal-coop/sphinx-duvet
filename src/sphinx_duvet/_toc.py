"""Add the sections of the reports to the table of contents of their page."""

from docutils import nodes
from sphinx import addnodes
from sphinx.application import Sphinx

SECTIONS = "duvet_sections"
"""The attribute of a report table: the (anchor, title, number) of each of its sections."""


def add_report_sections(app: Sphinx, doctree: nodes.document) -> None:
    """Add the sections of each report below the section of the page that shows it.

    The sections of a report are rows of its table, not sections of the document,
    so Sphinx does not find them. They are nested by their numbers: 3.4.2 is below 3.4,
    or below 3 if the report has no row for 3.4.
    """
    docname = app.env.docname
    toc = app.env.tocs[docname]
    for table in doctree.findall(nodes.table):
        sections = table.get(SECTIONS)
        if not sections:
            continue
        item = _item(toc, table, doctree)
        if item is None:
            continue
        item.append(_entries(docname, sections))
        # Themes show the table of contents of a page that has several entries.
        app.env.toc_num_entries[docname] += len(sections)


def _item(
    toc: nodes.Element, table: nodes.table, doctree: nodes.document
) -> nodes.list_item | None:
    """Return the entry of the table of contents for the section that contains a table."""
    section = table.parent
    while section is not None and not isinstance(section, nodes.section):
        section = section.parent
    if section is None:
        return None
    first = next(doctree.findall(nodes.section))
    anchor = "" if section is first else "#" + section["ids"][0]
    items = {
        next(item.findall(nodes.reference))["anchorname"]: item
        for item in toc.findall(nodes.list_item)
    }
    return items.get(anchor)


def _entries(docname: str, sections: list[tuple[str, str, str]]) -> nodes.bullet_list:
    """Return the entries of some sections, nested by number."""
    root = nodes.bullet_list()
    stack: list[tuple[str, nodes.bullet_list]] = [("", root)]
    for anchor, title, number in sections:
        while len(stack) > 1 and not number.startswith(stack[-1][0] + "."):
            stack.pop()
        reference = nodes.reference(
            "", title, internal=True, refuri=docname, anchorname="#" + anchor
        )
        item = nodes.list_item("", addnodes.compact_paragraph("", "", reference))
        stack[-1][1].append(item)
        children = nodes.bullet_list()
        item += children
        stack.append((number, children))
    for empty in [b for b in root.findall(nodes.bullet_list) if not b.children]:
        empty.parent.remove(empty)
    return root
