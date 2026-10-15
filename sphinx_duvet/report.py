"""Read the v2 JSON report of Duvet."""

import json
import re
import subprocess
import tempfile
from dataclasses import dataclass
from dataclasses import field
from pathlib import Path
from typing import Any

from .notes import Note
from .targets import Selector

_V2 = "https://awslabs.github.io/duvet/v2/"
_INLINE = _V2 + "sources.json#inline"
_LINKED = _V2 + "sources.json#linked"
_SPECIFICATION = _V2 + "annotations.json#specification"
_SECTION = _V2 + "annotations.json#section"
_REQUIREMENT = _V2 + "annotations.json#requirement"
_CITE = _V2 + "annotations.json#cite"

Report = dict[str, Any]
"""A v2 JSON report of Duvet, as decoded by :func:`json.loads`."""


class DuvetError(RuntimeError):
    """Duvet failed to produce a report."""


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

    @property
    def url(self) -> str | None:
        """The link to the annotation in the repository, if Duvet knows the blob link."""
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

    def covered_by(self, cites: list[Cite], within: list[Cite] | None = None) -> bool:
        """Return :data:`True` if the cites quote every non-blank byte of the requirement.

        With ``within``, only the bytes that these other cites quote are checked.
        """
        quoted = [r for cite in cites for r in cite.ranges]
        scope = None if within is None else [r for cite in within for r in cite.ranges]
        return all(
            self.contents[offset : offset + 1].isspace()
            or any(start <= offset < end for start, end in quoted)
            for start, end in self.ranges
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


def run_duvet(root: Path, executable: str = "duvet") -> Report:
    """Run Duvet in a project and return its v2 JSON report."""
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "report.json"
        try:
            subprocess.run(
                [executable, "report", "--json-v2", str(path)],
                cwd=root,
                check=True,
                capture_output=True,
                text=True,
            )
        except FileNotFoundError as exc:
            raise DuvetError(
                f"Duvet is not installed: {executable!r} not found"
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
        ranges = [(r["start"], r["end"]) for r in item["origin"]["ranges"]]
        text = " ".join(contents[src][a:b].decode() for a, b in ranges)
        requirements.setdefault(src, []).append(
            Requirement(
                spec=inline[src]["file_name"],
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
        for requirement in requirements.get(target["src"], []):
            if requirement._overlaps(cite.ranges):
                requirement.cites.append(cite)

    specifications = []
    for item in annotations.get(_SPECIFICATION, {}).values():
        src = item["source"]["src"]
        path = inline[src]["file_name"]
        specifications.append(
            Specification(
                path=path,
                title=item.get("title") or ietf_title(contents[src].decode()) or path,
                format=item.get("format", ""),
                sections={short: long for _, _, short, long in sections.get(src, [])},
                requirements=sorted(
                    requirements.get(src, []), key=lambda r: r.ranges[0]
                ),
            )
        )
    return {spec.path: spec for spec in sorted(specifications, key=lambda s: s.path)}


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
