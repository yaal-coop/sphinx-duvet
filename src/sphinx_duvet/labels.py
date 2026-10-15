"""Labels and descriptions of the states."""

from .compliance import State

KEYS = {
    "ok": State.OK,
    "missing": State.MISSING,
    "unannotated": State.UNANNOTATED,
    "todo": State.TODO,
    "partial": State.PARTIAL,
    "exception": State.EXCEPTION,
    "not_expected": State.NOT_EXPECTED,
    "not_applicable": State.NOT_APPLICABLE,
    "outside": State.OUTSIDE,
}
"""The name of each state in the configuration."""

DESCRIPTIONS = {
    State.OK: "done",
    State.MISSING: "missing",
    State.UNANNOTATED: "not annotated yet",
    State.TODO: "planned",
    State.PARTIAL: "partly done",
    State.EXCEPTION: "deliberate deviation",
    State.NOT_EXPECTED: "no test expected",
    State.NOT_APPLICABLE: "not applicable",
    State.OUTSIDE: "out of scope",
}
"""A short description of each state."""

PRESETS = {
    "symbols": {
        State.OK: "✔",
        State.MISSING: "✘",
        State.UNANNOTATED: "?",
        State.TODO: "…",
        State.PARTIAL: "½",
        State.EXCEPTION: "≠",
        State.NOT_EXPECTED: "—",
        State.NOT_APPLICABLE: "∅",
        State.OUTSIDE: "∅",
    },
    "text": {
        State.OK: "done",
        State.MISSING: "missing",
        State.UNANNOTATED: "not annotated",
        State.TODO: "todo",
        State.PARTIAL: "partial",
        State.EXCEPTION: "exception",
        State.NOT_EXPECTED: "not expected",
        State.NOT_APPLICABLE: "n/a",
        State.OUTSIDE: "out of scope",
    },
}
"""The label sets: ``symbols`` and ``text``."""
