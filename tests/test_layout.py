import pytest

from sphinx_duvet.layout import PARAGRAPH
from sphinx_duvet.layout import PREFORMATTED
from sphinx_duvet.layout import DefinitionList
from sphinx_duvet.layout import Element
from sphinx_duvet.layout import Figure
from sphinx_duvet.layout import Paragraph
from sphinx_duvet.layout import Table
from sphinx_duvet.layout import blocks
from sphinx_duvet.layout import figure_language
from sphinx_duvet.layout import figure_requirements
from sphinx_duvet.layout import front_matter
from sphinx_duvet.layout import header_rows
from sphinx_duvet.layout import links
from sphinx_duvet.layout import runs
from sphinx_duvet.layout import sections
from sphinx_duvet.layout import structure
from sphinx_duvet.report import Requirement
from sphinx_duvet.report import Specification

TEXT = """\
Internet Engineering Task Force (IETF)                         A. Author
Request for Comments: 9998                                  October 2026

                         Example Layout Protocol

Abstract

   This document has a café and a page break in the middle of a
   sentence.

1.  Introduction

   The client MUST send the
   token.  The server MUST reply.

   o  a list item,

   o  another item.

      ABNF = DIGIT



Author                        Experimental                      [Page 1]
\f
RFC 9998                        Layout                      October 2026


   A paragraph ends here.



Author                        Experimental                      [Page 2]
\f
RFC 9998                        Layout                      October 2026


   And the next one starts after the page break.

1.1.  Details

   Detail text.
"""
CONTENTS = TEXT.encode()


def offset(text: str) -> int:
    """Return the byte offset of a text in the specification."""
    return CONTENTS.index(text.encode())


def span(text: str) -> tuple[int, int]:
    """Return the byte range of a text in the specification."""
    start = offset(text)
    return start, start + len(text.encode())


def requirement(text: str, *parts: str, section: str = "section-1") -> Requirement:
    """Return a requirement that quotes some parts of the specification."""
    return Requirement(
        spec="spec.txt",
        section=section,
        level="MUST",
        text=text,
        ranges=[span(part) for part in parts or (text,)],
        contents=CONTENTS,
        id=f"spec#{text[:10]}",
    )


def specification() -> Specification:
    """Return the specification of the test text, with its sections."""
    return Specification(
        path="spec.txt",
        title="RFC 9998: Example Layout Protocol",
        format="ietf",
        sections={
            "name-abstract": "Abstract",
            "section-1": "Introduction",
            "section-1.1": "Details",
        },
        requirements=[],
        name="spec",
        contents=CONTENTS,
        section_ranges={
            "name-abstract": (offset("Abstract"), offset("1.  Introduction")),
            "section-1": (offset("Introduction"), offset("1.1.  Details")),
            "section-1.1": (offset("Details"), len(CONTENTS)),
        },
    )


def texts(spec_blocks: list) -> list[tuple[str, list[str]]]:
    """Return the kind and the text of each line of some blocks."""
    return [
        (block.kind, [CONTENTS[a:b].decode() for a, b in block.pieces()])
        for block in spec_blocks
    ]


def test_sections() -> None:
    """Sections keep their order, their number and their depth."""
    result = sections(specification())
    assert [(s.section, s.number, s.title, s.depth) for s in result] == [
        ("name-abstract", "", "Abstract", 1),
        ("section-1", "1", "Introduction", 1),
        ("section-1.1", "1.1", "Details", 2),
    ]


def test_paragraphs_and_preformatted_blocks() -> None:
    """Prose is a paragraph. Lists and blocks indented more than the section keep their layout."""
    introduction = sections(specification())[1]
    assert texts(introduction.blocks) == [
        (PARAGRAPH, ["The client MUST send the", "token.  The server MUST reply."]),
        (PREFORMATTED, ["o  a list item,"]),
        (PREFORMATTED, ["o  another item."]),
        (PREFORMATTED, ["ABNF = DIGIT"]),
        (PARAGRAPH, ["A paragraph ends here."]),
        (PARAGRAPH, ["And the next one starts after the page break."]),
    ]


def test_page_break_in_a_sentence() -> None:
    """A page break in the middle of a sentence joins the two halves of the paragraph."""
    text = TEXT.replace("   A paragraph ends here.\n", "   A paragraph does not end\n")
    contents = text.encode()
    start = contents.index(b"Introduction")
    end = contents.index(b"1.1.  Details")
    result = blocks(contents, start, end)
    pieces = [contents[a:b].decode() for a, b in result[-1].pieces()]
    assert pieces == [
        "A paragraph does not end",
        "And the next one starts after the page break.",
    ]


def test_front_matter() -> None:
    """The header of the first page and the title come before the first section."""
    assert texts(front_matter(specification())) == [
        (
            PREFORMATTED,
            [
                "Internet Engineering Task Force (IETF)                         A. Author",
                "Request for Comments: 9998                                  October 2026",
            ],
        ),
        (PREFORMATTED, ["Example Layout Protocol"]),
    ]


def test_utf8_offsets() -> None:
    """Offsets are in bytes, so non-ASCII characters keep the requirements in place."""
    abstract = sections(specification())[0]
    rule = requirement("a page break", section="name-abstract")
    found = [
        (run.text, run.owner) for run in runs(abstract.blocks[0], CONTENTS, [rule])
    ]
    assert found == [
        ("This document has a café and ", None),
        ("a page break", rule),
        (" in the middle of a sentence.", None),
    ]


def test_runs() -> None:
    """Runs follow the requirements, and the blanks inside a requirement belong to it."""
    block = sections(specification())[1].blocks[0]
    send = requirement(
        "The client MUST send the token.", "The client MUST send the", "token."
    )
    reply = requirement("The server MUST reply.")
    result = runs(block, CONTENTS, [send, reply])
    assert [(run.text, run.owner) for run in result] == [
        ("The client MUST send the token.", send),
        ("  ", None),
        ("The server MUST reply.", reply),
    ]
    assert [run.starts for run in result] == [[send], [], [reply]]


def test_overlapping_runs() -> None:
    """When requirements overlap, the first one owns the text, and both start in it."""
    block = sections(specification())[1].blocks[0]
    reply = requirement("The server MUST reply.")
    inner = requirement("MUST reply.", "MUST reply.")
    result = runs(block, CONTENTS, [reply, inner])
    owned = [run for run in result if run.owner is not None]
    assert [run.owner for run in owned] == [reply]
    assert owned[0].starts == [reply, inner]


def test_preformatted_runs() -> None:
    """Preformatted blocks keep their line breaks."""
    block = sections(specification())[1].blocks[3]
    assert [run.text for run in runs(block, CONTENTS, [])] == ["ABNF = DIGIT"]
    abstract_block = sections(specification())[0].blocks[0]
    assert runs(abstract_block, CONTENTS, [])[0].text == (
        "This document has a café and a page break in the middle of a sentence."
    )


def test_page_break_at_the_end() -> None:
    """A page break at the end of a section is not a paragraph of its own."""
    contents = (
        b"1.  Title\n\n   Last words.\n\n\n\n"
        b"Author                        Experimental                      [Page 3]\n"
    )
    result = blocks(contents, contents.index(b"Title"), len(contents))
    assert [block.kind for block in result] == [PARAGRAPH]


def parse(text: str) -> list[Element]:
    """Return the structure of a text, as if it were the content of a section."""
    contents = text.encode()
    return structure(blocks(contents, 0, len(contents), title=False))


def test_figure_without_prose() -> None:
    """Without any block of one indentation, blocks form one figure, with its blank lines."""
    text = "   {\n     b\n\n     c\n   }\n"
    [figure] = parse(text)
    assert isinstance(figure, Figure)
    found = [run.text for run in runs(figure.block, text.encode(), [])]
    assert found == ["{\n  b\n\n  c\n}"]


def test_hanging_sentence() -> None:
    """A long first line followed by indented lines is not a definition."""
    elements = parse(
        "   The text goes on, and this first line is long enough.\n"
        "      It goes on here.\n\n"
        "   A paragraph of prose ends here.\n"
    )
    assert [type(e) for e in elements] == [Figure, Paragraph]


def test_one_line_definition_alone() -> None:
    """A term and its text on one line, out of a list of definitions, is a paragraph."""
    elements = parse("   Token  A secret value of the client.\n")
    assert [type(e) for e in elements] == [Paragraph]


@pytest.mark.parametrize(
    "drawing",
    [
        "   +-------+\n   | box   |\n   +-------+\n",
        "   +---+---+\n   | a | b | c |\n   +---+---+\n",
        "   +---+---+\n   | a   b |\n   +---+---+\n",
    ],
    ids=["one column", "longer line", "missing separator"],
)
def test_drawings_are_not_tables(drawing: str) -> None:
    """Boxes that do not form a grid of at least two columns stay figures."""
    assert [type(e) for e in parse(drawing)] == [Figure]


def test_dashed_table_without_rows() -> None:
    """A header underlined with dashes, without rows, is not a table."""
    elements = parse(
        "   The table:\n\n   Name   Use\n   ------ ------\n\n   Some prose that follows.\n"
    )
    assert not any(isinstance(e, Table) for e in elements)


@pytest.mark.parametrize(
    "row",
    ["     POST   Creates.", "   PUT XX Replaces.", "   two words  Text."],
    ids=["indented", "text in a gap", "two words in the first cell"],
)
def test_dashed_table_rows(row: str) -> None:
    """Rows of a dashed table have the indentation of the table, blank gaps, and one word first."""
    elements = parse(f"   Name   Use\n   ------ ------\n   GET    Reads.\n\n{row}\n")
    table = elements[0]
    assert isinstance(table, Table)
    assert len(table.rows) == 1


def test_dashed_rule_first() -> None:
    """A line of dashes without a header above is not a table."""
    elements = parse("   ------ ------\n   GET    Reads.\n")
    assert not any(isinstance(e, Table) for e in elements)


def test_definitions_after_a_paragraph() -> None:
    """A term on its own line, followed by its indented text, is a definition."""
    elements = parse(
        "   The terms are as follows.\n\n   Client\n\n      A program that sends requests.\n"
    )
    assert isinstance(elements[1], DefinitionList)


def test_header_rows() -> None:
    """The header has two columns. An indented line only has a right column."""
    contents = (
        b"Internet Engineering Task Force (IETF)        A. Author\n"
        b"                                             B. Author\n"
    )
    [block] = blocks(contents, 0, len(contents), title=False)
    assert header_rows(block) == [
        ("Internet Engineering Task Force (IETF)", "A. Author"),
        ("", "B. Author"),
    ]


def test_figure_language() -> None:
    """JSON and HTTP figures are recognized from their first line."""
    assert figure_language('  {\n  "a": 1\n}') == "json"
    assert figure_language("POST /token  HTTP/1.1\nHost: a") == "http"
    assert figure_language("HTTP/1.1 200 OK") == "http"
    assert figure_language("ATTRNAME = ALPHA") is None


def test_links() -> None:
    """Sections, references, other RFCs, addresses and emails are links."""
    found = [
        (link.kind, link.target)
        for link in links(
            "See Section 3.1, Appendix A of RFC 9999, [RFC7644], RFC 2119, "
            "DOI 10.17487/RFC2119, Section 4.e of the TLP, "
            "https://example.com/a, <https://www.rfc-editor.org/info/rfc1>, "
            "a@example.org and b@yaal.coop."
        )
    ]
    assert found == [
        ("section", "section-3.1"),
        ("rfc", "9999#appendix-A"),
        ("rfc", "9999"),
        ("reference", "RFC7644"),
        ("rfc", "2119"),
        ("url", "https://www.rfc-editor.org/info/rfc1"),
        ("email", "b@yaal.coop"),
    ]


def test_page_break_after_a_figure() -> None:
    """A page break after a figure does not join it with the next paragraph."""
    contents = (
        b'1.  Title\n\n   {\n     "a": 1\n   }\n\n\n\n'
        b"Author                        Experimental                      [Page 3]\n"
        b"\f\nRFC 9998                        Layout                      October 2026\n\n\n"
        b"   The next paragraph.\n"
    )
    result = blocks(contents, contents.index(b"Title"), len(contents))
    assert len(result) == 2


def test_appendix_heading() -> None:
    """Appendices keep their name in their heading."""
    spec = specification()
    spec.section_ranges = {"appendix-A": (0, 10)}
    spec.sections = {"appendix-A": "Notes"}
    [text] = sections(spec)
    assert text.heading == "Appendix A. Notes"


def test_figure_requirements_of_other_formats() -> None:
    """Only IETF specifications have figures."""
    spec = specification()
    spec.format = "markdown"
    spec.requirements = [requirement("ABNF = DIGIT")]
    assert figure_requirements(spec) == []


def test_figure_requirements() -> None:
    """Requirements that start in a figure, even in a list or a definition, are found."""
    text = (
        "1.  Examples\n\n"
        "   The client MUST send a request.\n\n"
        "   o  An item:\n\n"
        '        { "a": "It MUST be one." }\n\n'
        "   term\n"
        "      A definition:\n\n"
        '        { "b": "It MUST be two." }\n'
    )
    contents = text.encode()
    spec = Specification(
        path="spec.txt",
        title="Examples",
        format="ietf",
        sections={"section-1": "Examples"},
        requirements=[],
        name="spec",
        contents=contents,
        section_ranges={"section-1": (contents.index(b"Examples"), len(contents))},
    )

    def rule(quote: str) -> Requirement:
        """Return a requirement on a quote of the text."""
        start = contents.index(quote.encode())
        return Requirement(
            spec="spec.txt",
            section="section-1",
            level="MUST",
            text=quote,
            ranges=[(start, start + len(quote))],
            contents=contents,
        )

    prose = rule("The client MUST send a request.")
    item = rule("It MUST be one.")
    definition = rule("It MUST be two.")
    spec.requirements = [prose, item, definition]
    assert figure_requirements(spec) == [item, definition]


def test_reference_with_a_long_label() -> None:
    """A reference label is a term, even when a single space follows it."""
    elements = parse(
        '   [RFC7644]  Hunt, P., "SCIM Protocol",\n'
        "              RFC 7644.\n\n"
        '   [Olson-TZ] Internet Assigned Numbers Authority, "IANA Time Zone\n'
        '              Database", <https://www.iana.org/time-zones>.\n'
    )
    [definitions] = elements
    assert isinstance(definitions, DefinitionList)
    terms = [d.term.lines[0].text for d in definitions.items]
    assert terms == ["[RFC7644]", "[Olson-TZ]"]


def test_centered_caption() -> None:
    """A centered line after a table is its caption. A centered line after prose is not."""
    elements = parse(
        "   +------+------+\n   | a    | b    |\n   +------+------+\n\n"
        "                    SCIM Server-Related Schema URIs\n\n"
        "   A paragraph of prose that ends here.\n\n"
        "                    A Centered Line After Prose\n"
    )
    table = elements[0]
    assert isinstance(table, Table)
    assert table.caption is not None
    assert table.caption.lines[0].text.strip() == "SCIM Server-Related Schema URIs"
    assert isinstance(elements[-1], Figure)


def test_labels_with_a_colon() -> None:
    """Labels that end with a colon are terms, even the first one, on a single line."""
    elements = parse(
        "   A schema is defined by completing the following template:\n\n"
        "   Schema URI:  A unique URI for the schema.\n\n"
        "   Schema Name:  A descriptive name of the schema (e.g.,\n"
        '      "Generic Device").\n\n'
        "   For example:\n\n"
        "      GET /Users HTTP/1.1\n"
    )
    assert [type(e) for e in elements] == [Paragraph, DefinitionList, Paragraph, Figure]
    definitions = elements[1]
    assert isinstance(definitions, DefinitionList)
    terms = [d.term.lines[0].text for d in definitions.items]
    assert terms == ["Schema URI:", "Schema Name:"]


def test_labels_on_their_own_line() -> None:
    """A label alone on its line is a term when prose follows it, not when code does."""
    elements = parse(
        "   The template:\n\n"
        "   Relevant Ancillary Documentation:\n\n"
        "      None\n\n"
        "   Scope:\n\n"
        "      Global.\n\n"
        "   For example:\n\n"
        "      GET /Users HTTP/1.1\n"
    )
    assert [type(e) for e in elements] == [Paragraph, DefinitionList, Paragraph, Figure]
    definitions = elements[1]
    assert isinstance(definitions, DefinitionList)
    assert [d.term.lines[0].text.strip() for d in definitions.items] == [
        "Relevant Ancillary Documentation:",
        "Scope:",
    ]
