"""Read the v2 JSON report of Duvet."""

import json
import re
import subprocess
import tempfile
from dataclasses import dataclass
from dataclasses import field
from pathlib import Path
from pathlib import PurePosixPath
from typing import Any

from .notes import Note
from .targets import Selector

_V2 = "https://awslabs.github.io/duvet/v2/"
_INLINE = _V2 + "sources.json#inline"
_LINKED = _V2 + "sources.json#linked"
_MARKER = re.compile(rb"([o*+-]|\d+\.|[a-z]\.|\(\d+\)|\([a-zA-Z]\))[ \t]+")
_SPECIFICATION = _V2 + "annotations.json#specification"
_SECTION = _V2 + "annotations.json#section"
_REQUIREMENT = _V2 + "annotations.json#requirement"
_CITE = _V2 + "annotations.json#cite"

Report = dict[str, Any]
"""A v2 JSON report of Duvet, as decoded by :func:`json.loads`."""


class DuvetError(RuntimeError):
    """Duvet failed to produce a report."""


class DuvetNotFound(DuvetError):
    """The Duvet executable is not installed."""


@dataclass
class Cite:
    """An annotation that quotes a part of a specification."""

    type: str
    path: str
    line: int
    ranges: list[tuple[int, int]]
    reason: str = ""
    blob_link: str | None = None
    covers: list[Selector] | None = None
    dependency: str | None = None
    version: str = ""
    link: str | None = None

    @property
    def url(self) -> str | None:
        """The link to the annotation in its repository, if it is known.

        Annotations of the project use the blob link of the Duvet report.
        Annotations of a dependency use the link of the dependency.
        """
        if self.dependency is not None:
            return self.link
        if self.blob_link is None:
            return None
        return f"{self.blob_link.rstrip('/')}/{self.path}#L{self.line}"


@dataclass
class Requirement:
    """A sentence of a specification with a level, such as MUST or SHOULD."""

    spec: str
    section: str
    level: str
    text: str
    ranges: list[tuple[int, int]]
    contents: bytes = field(repr=False, compare=False)
    cites: list[Cite] = field(default_factory=list)
    applies: list[Selector] | None = None
    notes: list[Note] = field(default_factory=list)
    id: str = ""
    """A stable identifier, such as ``rfc7643#3.1-9``: the name of the specification,
    the number of the section, and the rank of the requirement in the section."""
    quoted_ranges: list[tuple[int, int]] | None = field(default=None, repr=False)
    """The byte ranges that the cites quote, when they differ from the ranges."""

    def covered_by(self, cites: list[Cite], within: list[Cite] | None = None) -> bool:
        """Return :data:`True` if the cites quote every non-blank byte of the requirement.

        With ``within``, only the bytes that these other cites quote are checked.
        """
        quoted = [r for cite in cites for r in cite.ranges]
        scope = None if within is None else [r for cite in within for r in cite.ranges]
        # Workaround for Duvet: two adjacent quotes leave the blank between them
        # unquoted, so Duvet finds the requirement incomplete. Blanks are not checked.
        # Remove when Duvet joins adjacent quotes.
        return all(
            self.contents[offset : offset + 1].isspace()
            or any(start <= offset < end for start, end in quoted)
            for start, end in self.quoted_ranges or self.ranges
            for offset in range(start, end)
            if scope is None or any(a <= offset < b for a, b in scope)
        )

    def _overlaps(self, ranges: list[tuple[int, int]]) -> bool:
        """Return True if one of the byte ranges overlaps the requirement."""
        return any(a < d and c < b for a, b in self.ranges for c, d in ranges)


@dataclass
class Specification:
    """A specification document and its requirements."""

    path: str
    title: str
    format: str
    sections: dict[str, str]
    requirements: list[Requirement]
    name: str = ""
    """A short name, unique in the project: the file name without its extension."""
    contents: bytes = field(default=b"", repr=False, compare=False)
    """The text of the specification, encoded in UTF-8."""
    section_ranges: dict[str, tuple[int, int]] = field(default_factory=dict, repr=False)
    """The byte range of each section, from its title to its end."""

    @property
    def url(self) -> str | None:
        """The page of the RFC on rfc-editor.org, guessed from the file name.

        :data:`None` if the file name has no RFC number.
        """
        match = re.search(r"rfc(\d+)", Path(self.path).name, re.IGNORECASE)
        if not match:
            return None
        return f"https://www.rfc-editor.org/rfc/rfc{match.group(1)}"

    def section_url(self, section: str) -> str | None:
        """Return the link to a section of the RFC on rfc-editor.org."""
        if self.url is None:
            return None
        return f"{self.url}#{section}"


def read_report(path: Path) -> Report:
    """Read a v2 JSON report produced by ``duvet report --json-v2``."""
    report: Report = json.loads(path.read_text())
    return report


def run_duvet(
    root: Path, executable: str = "duvet", config: str | None = None
) -> Report:
    """Run Duvet in a project and return its v2 JSON report.

    ``config`` replaces the content of :file:`.duvet/config.toml`.
    """
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "report.json"
        command = [executable, "report", "--json-v2", str(path)]
        if config is None:
            return _run(command, root, executable, path)
        # Workaround for Duvet: with --config-path, the extracted requirements are
        # written next to the configuration, but read from .duvet/requirements.
        # So the generated configuration goes in the .duvet folder.
        # Remove when Duvet reads the requirements from where it writes them.
        with tempfile.NamedTemporaryFile(
            "w", suffix=".toml", prefix=".sphinx-duvet-", dir=root / ".duvet"
        ) as config_file:
            config_file.write(config)
            config_file.flush()
            command += ["--config-path", config_file.name]
            return _run(command, root, executable, path)


def _run(command: list[str], root: Path, executable: str, path: Path) -> Report:
    """Run a Duvet command that writes a v2 JSON report, and read the report."""
    try:
        subprocess.run(
            command,
            cwd=root,
            check=True,
            capture_output=True,
            text=True,
        )
    except FileNotFoundError as exc:
        # Workaround for Duvet: it has no prebuilt binary, so it is installed with cargo.
        # Update the message when Duvet publishes binaries or Python wheels.
        raise DuvetNotFound(
            f"Duvet is not installed: {executable!r} not found. "
            "Install it with: cargo install duvet --locked"
        ) from exc
    except subprocess.CalledProcessError as exc:
        raise DuvetError(f"Duvet failed:\n{exc.stderr}") from exc
    return read_report(path)


def parse_report(report: Report) -> dict[str, Specification]:
    """Return the specifications of a report, with their requirements and cites."""
    inline = report["sources"][_INLINE]
    linked = report["sources"].get(_LINKED, {})
    annotations = report["annotations"]
    contents = {key: source["contents"].encode() for key, source in inline.items()}
    blob_links = {
        key: repository.get("blob_link")
        for key, repository in report.get("repositories", {}).items()
    }

    sections: dict[str, list[tuple[int, int, str, str]]] = {}
    for section in annotations.get(_SECTION, {}).values():
        source = section["source"]
        sections.setdefault(source["src"], []).append(
            (
                source["start"],
                source["end"],
                section["short_name"],
                section["long_name"],
            )
        )

    requirements: dict[str, list[Requirement]] = {}
    for item in annotations.get(_REQUIREMENT, {}).values():
        src = item["origin"]["src"]
        ranges = _without_marker(
            [(r["start"], r["end"]) for r in item["origin"]["ranges"]], contents[src]
        )
        text = " ".join(contents[src][a:b].decode() for a, b in ranges)
        requirements.setdefault(src, []).append(
            Requirement(
                spec=inline[src]["file_name"],
                # Workaround for Duvet: requirements do not refer to their section,
                # so the section is found from the offsets. Remove when they do.
                section=_section_at(sections.get(src, []), ranges[0][0]),
                level=item["level"],
                text=normalize(text),
                ranges=ranges,
                contents=contents[src],
            )
        )

    for item in annotations.get(_CITE, {}).values():
        source = linked[item["source"]["src"]]
        target = item["target"]
        cite = Cite(
            type=item["type"],
            path=source["file_name"],
            line=item["source"].get("line") or 0,
            ranges=[(r["start"], r["end"]) for r in target["ranges"]],
            reason=item.get("comment") or "",
            blob_link=blob_links.get(source.get("repository")),
        )
        # Workaround for Duvet: cites do not refer to the requirements they quote,
        # so they are matched by offsets. Remove when they do.
        for requirement in requirements.get(target["src"], []):
            if requirement._overlaps(cite.ranges):
                requirement.cites.append(cite)

    for src, spec_requirements in requirements.items():
        ends = {short: end for _, end, short, _ in sections.get(src, [])}
        _separate_duplicates(spec_requirements, contents[src], ends)

    specifications = []
    for item in annotations.get(_SPECIFICATION, {}).values():
        src = item["source"]["src"]
        path = inline[src]["file_name"]
        specifications.append(
            Specification(
                path=path,
                # Workaround for Duvet: the report has no title for IETF specifications,
                # so it is read from the text. Remove when Duvet fills the title.
                title=item.get("title") or ietf_title(contents[src].decode()) or path,
                format=item.get("format", ""),
                sections={short: long for _, _, short, long in sections.get(src, [])},
                contents=contents[src],
                section_ranges={
                    short: (start, end)
                    for start, end, short, _ in sections.get(src, [])
                },
                requirements=sorted(
                    requirements.get(src, []), key=lambda r: r.ranges[0]
                ),
            )
        )
    specifications.sort(key=lambda s: s.path)
    _name(specifications)
    return {spec.path: spec for spec in specifications}


def _without_marker(
    ranges: list[tuple[int, int]], contents: bytes
) -> list[tuple[int, int]]:
    """Return the ranges of a requirement without the marker of its list item, such as "o"."""
    # Workaround for Duvet: a requirement at the start of a list item starts
    # with the marker of the item. Remove when Duvet leaves it out (draft ticket T18).
    start, end = ranges[0]
    marker = _MARKER.match(contents, start, end)
    if marker is None:
        return ranges
    return [(marker.end(), end), *ranges[1:]]


def _separate_duplicates(
    requirements: list[Requirement], contents: bytes, ends: dict[str, int]
) -> None:
    """Move the requirements that share a sentence to the next places the sentence appears.

    The cites stay with every one of them, as an annotation cannot tell them apart.
    """
    # Workaround for Duvet: requirements with the same text in a section get
    # the range of the first sentence. Remove when Duvet keeps the range of
    # each one (draft ticket T16).
    same: dict[tuple[str, tuple[tuple[int, int], ...]], list[Requirement]] = {}
    for requirement in requirements:
        same.setdefault((requirement.section, tuple(requirement.ranges)), []).append(
            requirement
        )
    for (section, ranges), duplicates in same.items():
        after = ranges[-1][1]
        for requirement in duplicates[1:]:
            found = _next_sentence(contents, list(ranges), after, ends[section])
            if found is None:
                break
            requirement.quoted_ranges = requirement.ranges
            requirement.ranges = found
            after = found[-1][1]


def _next_sentence(
    contents: bytes, ranges: list[tuple[int, int]], after: int, end: int
) -> list[tuple[int, int]] | None:
    """Return the ranges of the next place a quoted sentence appears, with any line breaks.

    The parts of the sentence are separated by blanks only.
    """
    words = b" ".join(contents[a:b] for a, b in ranges).split()
    pattern = re.compile(rb"\s+".join(re.escape(word) for word in words))
    match = pattern.search(contents, after, end)
    if match is None:
        return None
    lines = []
    for line in re.finditer(rb"[^\n]+", contents[match.start() : match.end()]):
        start = match.start() + line.start()
        stripped = line.group().strip()
        offset = line.group().index(stripped)
        lines.append((start + offset, start + offset + len(stripped)))
    return lines


def _name(specifications: list[Specification]) -> None:
    """Give a short name to each specification, and an identifier to each requirement.

    The name is the file name without its extension, or the whole path if two files
    share a name.
    """
    stems = [PurePosixPath(spec.path).stem for spec in specifications]
    for spec, stem in zip(specifications, stems, strict=True):
        spec.name = stem
        if stems.count(stem) > 1:
            spec.name = str(PurePosixPath(spec.path).with_suffix("")).replace("/", "-")
        ranks: dict[str, int] = {}
        for requirement in spec.requirements:
            ranks[requirement.section] = ranks.get(requirement.section, 0) + 1
            number = section_number(requirement.section) or "0"
            requirement.id = f"{spec.name}#{number}-{ranks[requirement.section]}"


def section_number(section: str) -> str:
    """Return the number of a section, without the ``section-`` or ``appendix-`` prefix."""
    return section.removeprefix("section-").removeprefix("appendix-")


def _section_at(sections: list[tuple[int, int, str, str]], offset: int) -> str:
    """Return the innermost section that contains an offset."""
    matches = [s for s in sections if s[0] <= offset < s[1]]
    if not matches:
        return ""
    return min(matches, key=lambda s: s[1] - s[0])[2]


def normalize(text: str) -> str:
    """Replace each sequence of whitespace by a single space."""
    return " ".join(text.split())


def ietf_title(text: str) -> str | None:
    """Return the title of an IETF text document: the centered lines before the abstract."""
    lines = text.splitlines()
    end = next((i for i, line in enumerate(lines) if line.strip() == "Abstract"), None)
    if end is None:
        return None
    block: list[str] = []
    for line in reversed(lines[:end]):
        if line.strip() and line.startswith(" " * 5):
            block.insert(0, line.strip())
        elif block:
            break
    title = " ".join(block)
    number = re.search(r"Request for Comments:\s*(\d+)", text)
    if number and title:
        return f"RFC {number.group(1)}: {title}"
    return title or None
