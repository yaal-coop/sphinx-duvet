"""Free text about requirements, written in reStructuredText."""

import re
from dataclasses import dataclass
from pathlib import Path

_NOTE_PATTERN = re.compile(r"^\.\. duvet-note::\s+(\S+)\s*$")
_OPTION_PATTERN = re.compile(r"^\s+:(\w+):\s*(.*)$")


@dataclass
class Note:
    """A note about the requirements of a section that match a quote."""

    target: str
    quote: str
    body: list[str]
    source: Path
    line: int


def load_notes(folder: Path, prefix: str = "") -> list[Note]:
    """Read the duvet-note directives of the .rst files of a folder.

    Each note starts with ``.. duvet-note:: spec#section``, has a ``:quote:``
    option, then an indented body. The prefix is added to the specification paths.
    """
    if not folder.is_dir():
        return []
    notes = []
    for path in sorted(folder.glob("**/*.rst")):
        for note in parse_notes(path.read_text(), path):
            note.target = prefix + note.target
            notes.append(note)
    return notes


def parse_notes(text: str, source: Path) -> list[Note]:
    """Read the duvet-note directives of a reStructuredText document."""
    notes = []
    lines = text.splitlines()
    index = 0
    while index < len(lines):
        match = _NOTE_PATTERN.match(lines[index])
        index += 1
        if not match:
            continue
        start = index
        options = {}
        while index < len(lines) and (option := _OPTION_PATTERN.match(lines[index])):
            options[option.group(1)] = option.group(2)
            index += 1
        body = []
        while index < len(lines) and (
            not lines[index].strip() or lines[index].startswith(" ")
        ):
            body.append(lines[index])
            index += 1
        notes.append(
            Note(
                target=match.group(1),
                quote=options.get("quote", ""),
                body=_dedent(body),
                source=source,
                line=start,
            )
        )
    return notes


def _dedent(lines: list[str]) -> list[str]:
    """Remove the blank lines around a block of lines, and their common indentation."""
    while lines and not lines[0].strip():
        lines = lines[1:]
    while lines and not lines[-1].strip():
        lines = lines[:-1]
    indent = min(
        (len(line) - len(line.lstrip()) for line in lines if line.strip()), default=0
    )
    return [line[indent:] for line in lines]
