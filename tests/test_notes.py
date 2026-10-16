from pathlib import Path

from sphinx_duvet.notes import load_notes
from sphinx_duvet.notes import parse_notes
from sphinx_duvet.targets import Selector


def test_load_notes(basic_root: Path) -> None:
    """Each duvet-note directive gives a note with its target, quote and body."""
    notes = load_notes(basic_root / ".duvet/notes")
    assert len(notes) == 2
    note = notes[0]
    assert note.target == "spec/rfc9999.txt#section-2"
    assert note.quote == "The server SHOULD log the request."
    assert note.body == [
        "Logging uses the standard *logging* module.",
        "",
        "   Indented line.",
    ]
    assert note.source == basic_root / ".duvet/notes/rfc9999.rst"
    assert note.line == 1
    assert notes[1].line == 8


def test_without_notes_folder(tmp_path: Path) -> None:
    """A project without a notes folder has no notes."""
    assert load_notes(tmp_path / "notes") == []


def test_note_without_quote_or_body() -> None:
    """The quote and the body are optional, and other text is ignored."""
    text = "Title\n=====\n\n.. duvet-note:: spec.md#section\n\nOther text.\n"
    [note] = parse_notes(text, Path("notes.rst"))
    assert note.target == "spec.md#section"
    assert note.quote == ""
    assert note.body == []
    assert note.line == 4


def test_note_body_indentation() -> None:
    """The blank lines around the body and its common indentation are removed."""
    text = ".. duvet-note:: spec.md#section\n\n\n  a\n    b\n\n  c\n  \nOther text.\n"
    [note] = parse_notes(text, Path("notes.rst"))
    assert note.body == ["a", "  b", "", "c"]


def test_note_targets() -> None:
    """A note can be about some targets only. Without the option, it is about every target."""
    text = (
        ".. duvet-note:: spec.md#section\n   :targets: role=client\n\n   Text.\n\n"
        ".. duvet-note:: spec.md#section\n\n   Text.\n"
    )
    client, every = parse_notes(text, Path("notes.rst"))
    assert client.targets == [Selector.parse("role=client")]
    assert every.targets is None
