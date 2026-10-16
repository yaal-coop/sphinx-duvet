"""The layout of IETF text specifications: their sections, paragraphs, lists and figures.

Every piece of text keeps its byte offsets in the specification,
so the requirements that Duvet found can be placed on it.
The structure is guessed from the indentation, with prudent rules.
A block that does not follow them keeps its layout, as a figure.
"""

import re
from collections import Counter
from collections.abc import Callable
from dataclasses import dataclass
from dataclasses import field
from urllib.parse import urlsplit

from .report import Requirement
from .report import Specification
from .report import section_number

PARAGRAPH = "paragraph"
"""A block of prose, whose lines can be joined."""

PREFORMATTED = "preformatted"
"""A block whose layout matters, such as a figure, an example or a list."""

_FOOTER = re.compile(rb"\[Page \d+\]\s*$")
_HEADER = re.compile(rb"^RFC \d+ .*\S\s*$")
_LIST_ITEM = re.compile(r"^(o|\*|-|\d+\.|[a-z]\.|\(\d+\)|\([a-z]\))\s+\S")
_MARKER = re.compile(r"(?P<marker>[o*+-]|\d+\.|[a-z]\.|\(\d+\)|\([a-zA-Z]\)) +(?=\S)")
_BULLETS = ("o", "*", "+", "-")
_LABEL = re.compile(r"\[[^\]\s]+\]( +)(?=\S)")
_KEY_WORD = re.compile(r"\b(MUST|SHALL|SHOULD|MAY|REQUIRED|RECOMMENDED|OPTIONAL)\b")
_TERM_GAP = re.compile(r"\S( {2,})(?=\S)")
_CAPTION = re.compile(r"(Figure|Table) \d+: \S")
_GRID_BORDER = re.compile(r"\+(-+\+)+|\+(=+\+)+")
_DASH_RULE = re.compile(r"-{2,}( +-{2,})+")
_TOC_NUMBER = re.compile(r"(?:Appendix +)?([0-9A-Z]+(?:\.\d+)*)\.? ")
_LINK = re.compile(
    r"(?P<section>\b(?P<kind>Section|Appendix) (?P<number>\d+(?:\.\d+)*|[A-Z](?:\.\d+)*)\b(?!\.\w))"
    r"|(?P<reference>\[(?P<label>[A-Za-z0-9][\w.+/-]*)\])"
    r"|(?P<url>https?://[^\s<>\"]*[^\s<>\".,;:)\]])"
    r"|(?P<rfc>(?<![/\w])RFC ?(?P<rfc_number>\d{3,5})\b)"
    r"|(?P<email>\b[\w.+-]+@(?P<domain>[\w-]+(?:\.[\w-]+)+)\b)"
)
_HTTP = re.compile(
    r"(GET|POST|PUT|PATCH|DELETE|HEAD|OPTIONS) +\S+( +HTTP/[\d.]+)?|HTTP/[\d.]+ \d{3}\b.*"
)
_EXAMPLE_DOMAIN = re.compile(
    r"(.*\.)?(example\.(com|net|org)|example|test|invalid|localhost)", re.IGNORECASE
)
_OF_RFC = re.compile(r" of (?:\[RFC(\d+)\]|RFC ?(\d+))")


@dataclass(frozen=True)
class Line:
    """A line of a specification, without its end of line."""

    start: int
    end: int
    text: str

    @property
    def indent(self) -> int:
        """The number of spaces before the text."""
        return len(self.text) - len(self.text.lstrip(" "))


@dataclass
class Block:
    """Lines between two blank lines: a paragraph, or a preformatted block."""

    kind: str
    lines: list[Line]

    @property
    def indent(self) -> int:
        """The indentation of the first line of the block."""
        return self.lines[0].indent

    def pieces(self) -> list[tuple[int, int]]:
        """Return the byte range of each line, without its indentation and its trailing blanks.

        Paragraphs lose the indentation of each line, as their lines are joined.
        Preformatted blocks only lose their common indentation, and can have blank lines.
        """
        indent = min(line.indent for line in self.lines if line.text.strip())
        return [
            (
                line.start + (line.indent if self.kind == PARAGRAPH else indent),
                line.start + len(line.text.rstrip().encode()),
            )
            if line.text.strip()
            else (line.start, line.start)
            for line in self.lines
        ]


@dataclass
class SectionText:
    """A section of a specification, with its depth and its blocks."""

    section: str
    number: str
    title: str
    depth: int
    blocks: list[Block] = field(default_factory=list)

    @property
    def heading(self) -> str:
        """The title of the section, with its number, as in the specification."""
        if self.section.startswith("appendix-"):
            return f"Appendix {self.number}. {self.title}"
        return f"{self.number}. {self.title}" if self.number else self.title


def front_matter(spec: Specification) -> list[Block]:
    """Return the blocks before the first section: the header of the first page and the title.

    The IETF Trust allows to reproduce a specification in full, with its indications
    of authorship, so they are kept.
    """
    starts = [start for start, _ in spec.section_ranges.values()]
    end = min(starts, default=len(spec.contents))
    # The range of the first section starts at its title, after a line break.
    end = spec.contents.rfind(b"\n", 0, end) + 1
    return [
        Block(PREFORMATTED, b.lines) for b in blocks(spec.contents, 0, end, title=False)
    ]


def sections(spec: Specification) -> list[SectionText]:
    """Return the sections of a specification in their order, with their blocks.

    Every section is kept, the table of contents too, as the IETF Trust only allows
    to reproduce a specification in full. Named sections, such as the abstract,
    are at the first level.
    """
    result = []
    ordered = sorted(spec.section_ranges.items(), key=lambda item: item[1][0])
    for section, (start, end) in ordered:
        number = section_number(section)
        numbered = section.startswith(("section-", "appendix-"))
        depth = number.count(".") + 1 if numbered else 1
        title = spec.sections.get(section, "")
        result.append(
            SectionText(
                section=section,
                number=number if numbered else "",
                title=title,
                depth=depth,
                blocks=blocks(spec.contents, start, end),
            )
        )
    return result


def blocks(contents: bytes, start: int, end: int, title: bool = True) -> list[Block]:
    """Return the blocks of a byte range, after its title line if it has one."""
    lines = _lines(contents, start, end)[1 if title else 0 :]
    groups: list[list[Line]] = [[]]
    for line in _without_page_breaks(lines):
        # The text of recent RFCs starts with a byte order mark.
        if line is None or not line.text.strip("\ufeff \t\r"):
            groups.append([])
        else:
            groups[-1].append(line)
    groups = [group for group in groups if group]
    indent = min((line.indent for group in groups for line in group), default=0)
    return [Block(_kind(group, indent), group) for group in groups]


def _lines(contents: bytes, start: int, end: int) -> list[Line]:
    """Split a byte range into lines."""
    lines = []
    offset = start
    while offset < end:
        newline = contents.find(b"\n", offset, end)
        stop = end if newline < 0 else newline
        lines.append(Line(offset, stop, contents[offset:stop].decode()))
        offset = stop + 1
    return lines


def _without_page_breaks(lines: list[Line]) -> list[Line | None]:
    """Remove the page footers, form feeds and page headers.

    A page break inside a paragraph joins its two halves. Otherwise it becomes a
    paragraph break, written as None.
    """
    # Workaround for Duvet: the v2 report does not give the content lines of the
    # sections, without their page breaks. Remove when it does (draft ticket T7).
    result: list[Line | None] = []
    index = 0
    while index < len(lines):
        line = lines[index]
        if not _FOOTER.search(line.text.encode()):
            result.append(line)
            index += 1
            continue
        index += 1
        while index < len(lines) and (
            not lines[index].text.strip("\f \t")
            or _HEADER.match(lines[index].text.encode())
        ):
            index += 1
        while result and result[-1] is not None and not result[-1].text.strip():
            result.pop()
        previous = result[-1] if result else None
        following = lines[index] if index < len(lines) else None
        if not _continues(previous, following):
            result.append(None)
    return result


def _continues(previous: Line | None, following: Line | None) -> bool:
    """Return True if a page break cuts a sentence or a table in two.

    The end of a figure, such as a closing brace, is not the start of a sentence.
    """
    if previous is None or following is None:
        return False
    if previous.indent != following.indent:
        return False
    # A table goes on over the page break.
    if previous.text.lstrip()[0] in "|+" and following.text.lstrip()[0] in "|+":
        return True
    last = previous.text.rstrip()[-1]
    first = following.text.lstrip()[0]
    return (last.isalnum() or last in ",;-\"')") and (
        first.isalnum() or first in "\"'("
    )


def _kind(lines: list[Line], indent: int) -> str:
    """Return the kind of a block: prose if all its lines have the indentation of the section.

    Blocks indented more than the section, such as figures, ABNF or examples, keep
    their layout, as do lists.
    """
    if {line.indent for line in lines} != {indent} or _LIST_ITEM.match(
        lines[0].text.strip()
    ):
        return PREFORMATTED
    return PARAGRAPH


@dataclass
class Run:
    """A run of text in a block: in a requirement, or in none."""

    text: str
    owner: Requirement | None
    starts: list[Requirement] = field(default_factory=list)
    """The requirements that start in the run, even if another one owns it."""


def runs(block: Block, contents: bytes, requirements: list[Requirement]) -> list[Run]:
    """Return the text of a block as runs, each one in a requirement or in none.

    The lines of a paragraph are joined with spaces, the lines of a preformatted
    block with new lines. Blanks between two parts of the same requirement belong to it.
    When requirements overlap, the first one owns the text.
    """
    separator = " " if block.kind == PARAGRAPH else "\n"
    tokens: list[Run] = []
    for index, (start, end) in enumerate(block.pieces()):
        cuts = {start, end}
        for requirement in requirements:
            for a, b in requirement.ranges:
                cuts.update(x for x in (a, b) if start < x < end)
        points = sorted(cuts)
        if index:
            tokens.append(Run(separator, None))
        tokens += [
            Run(
                contents[a:b].decode(),
                _owner(requirements, a),
                [r for r in requirements if a <= r.ranges[0][0] < b],
            )
            for a, b in zip(points, points[1:], strict=False)
        ]
    tokens = _merge(tokens)
    for index in range(1, len(tokens) - 1):
        run = tokens[index]
        before, after = tokens[index - 1].owner, tokens[index + 1].owner
        if (
            run.owner is None
            and not run.text.strip()
            and before is not None
            and before is after
        ):
            run.owner = before
    return _merge(tokens)


def _merge(tokens: list[Run]) -> list[Run]:
    """Join the neighbor runs that belong to the same requirement, or to none."""
    merged: list[Run] = []
    for run in tokens:
        if merged and merged[-1].owner is run.owner:
            merged[-1] = Run(
                merged[-1].text + run.text, run.owner, merged[-1].starts + run.starts
            )
        else:
            merged.append(run)
    return merged


def _owner(requirements: list[Requirement], offset: int) -> Requirement | None:
    """Return the first requirement that contains an offset."""
    return next(
        (r for r in requirements if any(a <= offset < b for a, b in r.ranges)), None
    )


@dataclass
class Paragraph:
    """A paragraph of prose."""

    block: Block


@dataclass
class Figure:
    """A block that keeps its layout, such as an example or a diagram."""

    block: Block
    caption: Block | None = None


@dataclass
class Table:
    """A table, with a block of text per cell."""

    header: list[list[Block]]
    rows: list[list[Block]]
    widths: list[int]
    caption: Block | None = None


@dataclass
class Item:
    """An item of a list: its marker and its content."""

    marker: str
    body: list["Element"]


@dataclass
class ItemList:
    """Items with the same kind of marker.

    Bullets are shown as bullets. Other markers, such as ``1.`` or ``(A)``, are kept.
    """

    bullet: bool
    items: list[Item]


@dataclass
class Definition:
    """A term and its definition, such as a parameter or a reference."""

    term: Block
    body: list["Element"]


@dataclass
class DefinitionList:
    """Definitions that follow each other."""

    items: list[Definition]


Element = Paragraph | Figure | Table | ItemList | DefinitionList


def structure(spec_blocks: list[Block]) -> list[Element]:
    """Return the structure of the blocks of a section.

    Prose at the indentation of most blocks is a paragraph. Blocks indented more
    are figures, unless they are lists. A line followed by indented lines is a list
    item if it starts with a marker, and a definition otherwise. A figure followed
    by a line such as ``Figure 2: Example`` gets it as its caption.
    """
    kept, captions = _captions(spec_blocks)
    return _parse(kept, _base_indent(kept), True, captions)


def _base_indent(spec_blocks: list[Block]) -> int:
    """Return the indentation of the prose of a section.

    It is the most frequent among blocks with one indentation that end like a sentence.
    Figures can be indented less than the prose, and lists of names more.
    """
    uniform = [
        block
        for block in spec_blocks
        if all(line.indent == block.indent for line in block.lines)
    ]
    sentences = [
        block
        for block in uniform
        if block.lines[-1].text.rstrip().endswith((".", ":"))
        and sum(len(line.text.split()) for line in block.lines) >= 5
    ]
    counts = Counter(block.indent for block in sentences or uniform)
    if not counts:
        return min((block.indent for block in spec_blocks), default=0)
    return min(counts, key=lambda indent: (-counts[indent], indent))


def _captions(spec_blocks: list[Block]) -> tuple[list[Block], dict[int, Block]]:
    """Remove the captions from the blocks, and return them by the block they follow.

    A caption starts with "Figure 1:" or "Table 1:". A single centered line after
    a figure or a table is a caption too, as in older RFCs.
    """
    kept: list[Block] = []
    captions: dict[int, Block] = {}
    for block in spec_blocks:
        previous = kept[-1] if kept else None
        if previous is not None and (
            (len(block.lines) <= 2 and _CAPTION.match(block.lines[0].text.strip()))
            or (_is_figure(previous) and _is_centered(block))
        ):
            captions[id(previous)] = Block(PARAGRAPH, block.lines)
            continue
        kept.append(block)
    return kept, captions


def _is_figure(block: Block) -> bool:
    """Return True if a block looks like a figure or a table, not like prose."""
    first = block.lines[0].text.strip()
    return block.kind == PREFORMATTED or bool(_GRID_BORDER.fullmatch(first))


def _is_centered(block: Block) -> bool:
    """Return True if a block is a single short line, centered on the page of 72 columns."""
    if len(block.lines) != 1:
        return False
    line = block.lines[0]
    text = line.text.strip()
    margin = (72 - len(text)) / 2
    return (
        line.indent >= 8
        and abs(line.indent - margin) <= 3
        and not text.endswith((".", ":", ",", ";"))
    )


def _parse(
    spec_blocks: list[Block], indent: int, prose: bool, captions: dict[int, Block]
) -> list[Element]:
    """Return the structure of blocks, whose base indentation is known.

    Out of prose, such as in blocks indented more than a paragraph, only lists
    and tables are recognized. In prose, a block indented less than the paragraphs,
    such as a label, is a paragraph too.
    """
    result: list[Element | Item | Definition] = []
    index = 0
    while index < len(spec_blocks):
        block = spec_blocks[index]
        if block.indent > indent:
            end = _until(spec_blocks, index, lambda b: b.indent > indent)
            deeper = spec_blocks[index:end]
            result += _parse(deeper, min(b.indent for b in deeper), False, captions)
            index = end
            continue
        table = _table(spec_blocks, index, captions)
        if table is not None:
            element, index = table
            result.append(element)
            continue
        after = (bool(result) and isinstance(result[-1], Definition)) or (
            index + 1 < len(spec_blocks)
            and _starts_definition(spec_blocks[index + 1], prose)
        )
        nested = _nested(spec_blocks, index, prose, after, captions)
        if nested is not None:
            item, index = nested
            result.append(item)
            continue
        if (
            prose
            and all(line.indent == block.indent for line in block.lines)
            and not _looks_like_code(block.lines[0].text.strip())
        ):
            result.append(Paragraph(Block(PARAGRAPH, block.lines)))
        else:
            figure = Block(PREFORMATTED, block.lines)
            result.append(Figure(figure, captions.get(id(block))))
        index += 1
    return _merge_figures(_group(result))


def _looks_like_code(text: str) -> bool:
    """Return True if a line looks like code or a drawing, not like a sentence."""
    return (
        (" " not in text and not text.rstrip(".,").isalpha())
        or text[0] in "{}]|+"
        or text.startswith(('["', "[{"))
        or text == "["
        or bool(_HTTP.fullmatch(text))
    )


def _merge_figures(elements: list[Element]) -> list[Element]:
    """Join the figures that follow each other, with a blank line between them.

    Figures often have blank lines, and lines indented less than the rest,
    such as the braces of a JSON object. A caption ends a figure.
    """
    result: list[Element] = []
    for element in elements:
        previous = result[-1] if result else None
        if (
            isinstance(element, Figure)
            and isinstance(previous, Figure)
            and previous.caption is None
        ):
            end = previous.block.lines[-1].end
            blank = Line(end, end, "")
            lines = [*previous.block.lines, blank, *element.block.lines]
            result[-1] = Figure(Block(PREFORMATTED, lines), element.caption)
        else:
            result.append(element)
    return result


def _until(spec_blocks: list[Block], start: int, keep: Callable[[Block], bool]) -> int:
    """Return the index of the first block from start that is not kept."""
    end = start
    while end < len(spec_blocks) and keep(spec_blocks[end]):
        end += 1
    return end


def _nested(
    spec_blocks: list[Block],
    index: int,
    prose: bool,
    after: bool,
    captions: dict[int, Block],
) -> tuple[Item | Definition, int] | None:
    """Return a list item or a definition with its content, and the index after it.

    Next to a definition, a definition can fit on one line.
    """
    block = spec_blocks[index]
    head = _head(block, prose, after)
    if head is None:
        head = _alone_term(spec_blocks, index, prose)
    if head is None:
        return None
    marker, term, first, body_indent = head
    end = _until(spec_blocks, index + 1, lambda b: b.indent >= body_indent)
    body: list[Element] = [Paragraph(first)] if first is not None else []
    body += _parse(spec_blocks[index + 1 : end], body_indent, True, captions)
    if marker is not None:
        return Item(marker, body), end
    assert term is not None
    return Definition(term, body), end


_Head = tuple[str | None, Block | None, Block | None, int]


def _head(block: Block, prose: bool, after: bool) -> _Head | None:
    """Return the start of a list item, or of a definition, and the indentation of its content."""
    first, rest = block.lines[0], block.lines[1:]
    text = first.text[first.indent :]
    marker = _MARKER.match(text)
    if marker is not None:
        column = first.indent + marker.end()
        body_indent = (
            rest[0].indent if rest and rest[0].indent > first.indent else column
        )
        content = Block(PARAGRAPH, [_cut(first, column, len(first.text)), *rest])
        return marker.group("marker"), None, content, body_indent
    # A reference label, such as [RFC7644], can be followed by a single space.
    gap = _LABEL.match(text) or _TERM_GAP.search(text)
    if not prose or not (rest or (after and gap)):
        return None
    body_indent = min((line.indent for line in rest), default=first.indent + 1)
    if body_indent <= first.indent:
        return None
    term_end = first.indent + gap.start(1) if gap else len(first.text.rstrip())
    if not _is_term(first.text[first.indent : term_end], label=gap is not None):
        return None
    term = Block(PARAGRAPH, [_cut(first, first.indent, term_end)])
    lines = (
        [_cut(first, first.indent + gap.end(1), len(first.text)), *rest]
        if gap
        else rest
    )
    return None, term, Block(PARAGRAPH, lines), body_indent


def _starts_definition(block: Block, prose: bool) -> bool:
    """Return True if a block starts a definition, not a list item."""
    head = _head(block, prose, False)
    return head is not None and head[0] is None


def _alone_term(spec_blocks: list[Block], index: int, prose: bool) -> _Head | None:
    """Return a term on a line of its own, if the next block is its indented definition.

    A label that ends with a colon is a term when prose follows it, not code.
    """
    block = spec_blocks[index]
    following = spec_blocks[index + 1] if index + 1 < len(spec_blocks) else None
    if not prose or len(block.lines) != 1 or following is None:
        return None
    if following.indent <= block.indent:
        return None
    prose_follows = all(
        line.indent == following.indent for line in following.lines
    ) and not _looks_like_code(following.lines[0].text.strip())
    if not _is_term(block.lines[0].text.strip(), label=prose_follows):
        return None
    return None, block, None, following.indent


def _is_term(text: str, label: bool = False) -> bool:
    """Return True if a text looks like a term, not like the start of a sentence.

    A label, followed by its text on the same line, can end with a colon.
    """
    endings = (
        (".", ",", ";", "{", "[", "=") if label else (".", ":", ",", ";", "{", "[", "=")
    )
    return (
        len(text) <= 40
        and len(text.split()) <= 5
        and any(char.isalpha() for char in text)
        and not text.endswith(endings)
    )


def _cut(line: Line, start: int, end: int) -> Line:
    """Return a part of a line, between two columns, with its byte offsets."""
    prefix = len(line.text[:start].encode())
    return Line(
        line.start + prefix,
        line.start + prefix + len(line.text[start:end].encode()),
        line.text[start:end],
    )


def _group(elements: list[Element | Item | Definition]) -> list[Element]:
    """Gather the list items and the definitions that follow each other."""
    result: list[Element] = []
    current: ItemList | DefinitionList | None = None
    for element in elements:
        if isinstance(element, Item):
            bullet = element.marker in _BULLETS
            family = _family(element.marker)
            if (
                not isinstance(current, ItemList)
                or _family(current.items[0].marker) != family
            ):
                current = ItemList(bullet, [])
                result.append(current)
            current.items.append(element)
        elif isinstance(element, Definition):
            if not isinstance(current, DefinitionList):
                current = DefinitionList([])
                result.append(current)
            current.items.append(element)
        else:
            current = None
            result.append(element)
    return result


def _family(marker: str) -> str:
    """Return the kind of a marker: the bullet itself, or the shape of a number."""
    return re.sub(r"\d+", "1", re.sub(r"[a-z]", "a", re.sub(r"[A-Z]", "A", marker)))


def _table(
    spec_blocks: list[Block], index: int, captions: dict[int, Block]
) -> tuple[Table, int] | None:
    """Return a table that starts at a block, and the index after it."""
    block = spec_blocks[index]
    grid = _grid_table(block)
    if grid is not None:
        grid.caption = captions.get(id(block))
        return grid, index + 1
    return _dash_table(spec_blocks, index, captions)


def _grid_table(block: Block) -> Table | None:
    """Return a table drawn with "+---+" borders and "|" separators.

    A table has at least two columns. Cells that span several columns, or that
    contain a "|", are not supported: such a table stays a figure.
    """
    first = block.lines[0].text.rstrip()
    columns = [index for index, char in enumerate(first) if char == "+"]
    if not _is_border(first, columns) or not _is_border(
        block.lines[-1].text.rstrip(), columns
    ):
        return None
    if len(columns) < 3:
        return None
    groups: list[list[Line]] = [[]]
    for line in block.lines[1:-1]:
        text = line.text.rstrip()
        bars = [index for index, char in enumerate(text) if char == "|"]
        if _is_border(text, columns):
            groups.append([])
        elif len(text) == len(first) and bars == columns:
            groups[-1].append(line)
        else:
            return None
    bounds = list(zip(columns, columns[1:], strict=False))
    cells = [[_cells(line, bounds) for line in group] for group in groups]
    header = [_join_row(cells[0])] if len(groups) > 1 else []
    rows = [row for group in cells[1 if header else 0 :] for row in _split_rows(group)]
    widths = [end - start - 1 for start, end in bounds]
    return Table(header, rows, widths)


def _is_border(text: str, columns: list[int]) -> bool:
    """Return True if a line is a border with a "+" at each column.

    Borders are drawn with "-", or with "=" around the header in RFCXML v3 tables.
    """
    plus = [index for index, char in enumerate(text) if char == "+"]
    return bool(_GRID_BORDER.fullmatch(text.strip())) and plus == columns


def _cells(line: Line, bounds: list[tuple[int, int]]) -> list[Line]:
    """Return the parts of a line between column separators."""
    return [_cut(line, start + 1, end) for start, end in bounds]


def _join_row(lines: list[list[Line]]) -> list[Block]:
    """Return the cells of lines that form one row, as blocks of text."""
    columns = zip(*lines, strict=True)
    return [
        Block(PARAGRAPH, [part for part in column if part.text.strip()])
        for column in columns
    ]


def _split_rows(lines: list[list[Line]]) -> list[list[Block]]:
    """Split lines into rows: at blank lines if there are some, else at a non-empty first cell."""
    blank = [not any(part.text.strip() for part in line) for line in lines]
    rows: list[list[list[Line]]] = []
    for line, empty in zip(lines, blank, strict=True):
        starts = not rows or (empty if any(blank) else bool(line[0].text.strip()))
        if starts:
            rows.append([])
        if not empty:
            rows[-1].append(line)
    return [_join_row(row) for row in rows if row]


def _dash_table(
    spec_blocks: list[Block], index: int, captions: dict[int, Block]
) -> tuple[Table, int] | None:
    """Return a table whose header is underlined with dashes, and the index after it.

    Its rows are in the next blocks, as long as they fit in its columns.
    When blank lines separate the rows, each block is a row, and its first cell
    can span several lines.
    """
    block = spec_blocks[index]
    rule = next(
        (
            i
            for i, line in enumerate(block.lines)
            if _DASH_RULE.fullmatch(line.text.strip())
        ),
        None,
    )
    if rule is None or rule == 0:
        return None
    text = block.lines[rule].text.rstrip()
    starts = [m.start() for m in re.finditer(r"-+", text)]
    ends = [m.end() for m in re.finditer(r"-+", text)]
    bounds = [
        (start - 1, end)
        for start, end in zip(starts, [*starts[1:], 10_000], strict=True)
    ]
    header_lines = [_cells(line, bounds) for line in block.lines[:rule]]
    groups = [block.lines[rule + 1 :]] if rule + 1 < len(block.lines) else []
    end = index + 1
    while end < len(spec_blocks) and _fits(
        spec_blocks[end], block.indent, starts, ends
    ):
        groups.append(spec_blocks[end].lines)
        end += 1
    if not groups:
        return None
    cells = [[_cells(line, bounds) for line in group] for group in groups]
    if len(cells) > 1:
        rows = [_join_row(group) for group in cells]
    else:
        rows = _split_rows(cells[0])
    widths = [stop - start for start, stop in zip(starts, ends, strict=True)]
    last = spec_blocks[end - 1]
    return Table([_join_row(header_lines)], rows, widths, captions.get(id(last))), end


def _fits(block: Block, indent: int, starts: list[int], ends: list[int]) -> bool:
    """Return True if a block is a row of a table with dashed columns.

    Its first cell starts with one word. Gaps between columns stay blank.
    """
    if block.indent != indent:
        return False
    for number, line in enumerate(block.lines):
        text = line.text
        if any(
            text[end:start].strip()
            for end, start in zip(ends, starts[1:], strict=False)
        ):
            return False
        first = text[: starts[1]].strip() if len(starts) > 1 else text.strip()
        if number == 0 and (not first or " " in first):
            return False
    return True


def toc_depth(text: SectionText, contents: bytes) -> int:
    """Return the depth of the sections in a table of contents."""
    numbers = [
        match.group(1)
        for block in text.blocks
        for start, end in block.pieces()
        if (match := _TOC_NUMBER.match(contents[start:end].decode().strip()))
    ]
    return max((number.count(".") + 1 for number in numbers), default=1)


@dataclass(frozen=True)
class Link:
    """A link in a text: to a section, to a reference, or to an address."""

    start: int
    end: int
    kind: str
    """``section``, ``reference``, ``rfc``, ``url`` or ``email``."""
    target: str
    """The section, the reference label, the RFC number with its section, or the address."""


def links(text: str) -> list[Link]:
    """Return the links in a text.

    ``Section 3.1 of [RFC7644]`` and ``Section 3.1 of RFC 7644`` link to the section
    of the other RFC. ``Section 3.1`` alone links to a section of the specification.
    Addresses on the example domains of RFC 2606 are not links.
    Email addresses link to a new message.
    """
    result = []
    for match in _LINK.finditer(text):
        if match["section"]:
            kind = "section" if match["kind"] == "Section" else "appendix"
            other = _OF_RFC.match(text, match.end())
            if other:
                number = other.group(1) or other.group(2)
                target = f"{number}#{kind}-{match['number']}"
                result.append(Link(match.start(), match.end(), "rfc", target))
            else:
                target = f"{kind}-{match['number']}"
                result.append(Link(match.start(), match.end(), "section", target))
        elif match["reference"]:
            result.append(Link(match.start(), match.end(), "reference", match["label"]))
        elif match["url"]:
            if not _EXAMPLE_DOMAIN.fullmatch(urlsplit(match["url"]).hostname or ""):
                result.append(Link(match.start(), match.end(), "url", match["url"]))
        elif match["rfc"]:
            result.append(Link(match.start(), match.end(), "rfc", match["rfc_number"]))
        elif not _EXAMPLE_DOMAIN.fullmatch(match["domain"]):
            result.append(Link(match.start(), match.end(), "email", match["email"]))
    return result


def header_rows(block: Block) -> list[tuple[str, str]]:
    """Return the two columns of the header of the first page, line by line."""
    rows = []
    for line in block.lines:
        text = line.text.rstrip()
        if line.indent:
            rows.append(("", text.strip()))
            continue
        left, _, right = text.partition("  ")
        rows.append((left, right.strip()))
    return rows


def figure_language(text: str) -> str | None:
    """Return the language of a figure: ``json``, ``http``, or None if it is neither."""
    stripped = text.lstrip()
    if stripped.startswith(("{", "[")):
        return "json"
    if _HTTP.fullmatch(stripped.split("\n", 1)[0].strip()):
        return "http"
    return None


def figure_requirements(spec: Specification) -> list[Requirement]:
    """Return the requirements that start in a figure of an IETF specification.

    Figures are examples, such as JSON schemas, so these requirements are not normative.
    """
    # Workaround for Duvet: requirements are also extracted from figures.
    # Remove when Duvet skips them (draft ticket T17).
    if spec.format != "ietf":
        return []
    figures: list[tuple[int, int]] = []
    for text in sections(spec):
        _figure_ranges(structure(text.blocks), figures)
    return [
        requirement
        for requirement in spec.requirements
        if any(start <= requirement.ranges[0][0] < end for start, end in figures)
    ]


def _figure_ranges(elements: list[Element], ranges: list[tuple[int, int]]) -> None:
    """Add the byte ranges of the figures in elements, and in their lists and definitions."""
    for element in elements:
        if isinstance(element, Figure):
            ranges.append((element.block.lines[0].start, element.block.lines[-1].end))
        elif isinstance(element, ItemList):
            for item in element.items:
                _figure_ranges(item.body, ranges)
        elif isinstance(element, DefinitionList):
            for definition in element.items:
                _figure_ranges(definition.body, ranges)


def cell_ranges(spec: Specification) -> dict[str, list[tuple[int, int]]]:
    """Return the ranges of the requirements in tables, restricted to their cell.

    Duvet reads a table line by line, so a requirement in a table mixes its columns.
    The requirement is the sentence of the cell that holds its key word.
    """
    # Workaround for Duvet: requirements in tables mix the text of the columns.
    # Remove when Duvet reads tables cell by cell (draft ticket T19).
    if spec.format != "ietf":
        return {}
    cells: list[Block] = []
    for text in sections(spec):
        _table_cells(structure(text.blocks), cells)
    result = {}
    for requirement in spec.requirements:
        start, end = requirement.ranges[0][0], requirement.ranges[-1][1]
        for cell in cells:
            ranges = _sentence(spec.contents, cell.pieces(), start, end)
            if ranges:
                result[requirement.id] = ranges
                break
    return result


def _sentence(
    contents: bytes, pieces: list[tuple[int, int]], start: int, end: int
) -> list[tuple[int, int]] | None:
    """Return the ranges of the sentence of a cell with a key word between start and end."""
    # The text of the cell, with the byte range of each character.
    # The space that joins two lines has no range.
    text = ""
    spans: list[tuple[int, int] | None] = []
    for a, b in pieces:
        if text:
            text += " "
            spans.append(None)
        position = a
        for char in contents[a:b].decode():
            size = len(char.encode())
            text += char
            spans.append((position, position + size))
            position += size
    word = next(
        (
            m
            for m in _KEY_WORD.finditer(text)
            if (span := spans[m.start()]) is not None and start <= span[0] < end
        ),
        None,
    )
    if word is None:
        return None
    ends = [m.end() for m in re.finditer(r"[.!?](?=\s|$)", text)]
    first = max((e for e in ends if e <= word.start()), default=0)
    last = min((e for e in ends if e > word.start()), default=len(text))
    ranges = []
    for a, b in pieces:
        inside = [
            span
            for span in spans[first:last]
            if span is not None
            and a <= span[0] < b
            and not contents[span[0] : span[1]].isspace()
        ]
        if inside:
            ranges.append((inside[0][0], inside[-1][1]))
    return ranges


def _table_cells(elements: list[Element], cells: list[Block]) -> None:
    """Add the cells of the tables in elements, and in their lists and definitions."""
    for element in elements:
        if isinstance(element, Table):
            cells += [cell for row in element.rows for cell in row if cell.lines]
        elif isinstance(element, ItemList):
            for item in element.items:
                _table_cells(item.body, cells)
        elif isinstance(element, DefinitionList):
            for definition in element.items:
                _table_cells(definition.body, cells)
