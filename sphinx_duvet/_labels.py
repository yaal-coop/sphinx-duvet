"""Labels of the states in the reports: symbols, text or any inline markup."""

import copy
from collections.abc import Callable
from typing import Any

from docutils import nodes
from sphinx.application import Sphinx
from sphinx.config import Config
from sphinx.util import logging
from sphinx.writers.html5 import HTML5Translator

from .compliance import State
from .compliance import Status

logger = logging.getLogger(__name__)

# The keys of the duvet_labels option.
_KEYS = {
    "ok": State.OK,
    "missing": State.MISSING,
    "unannotated": State.UNANNOTATED,
    "todo": State.TODO,
    "partial": State.PARTIAL,
    "exception": State.EXCEPTION,
    "not_expected": State.NOT_EXPECTED,
    "not_applicable": State.NOT_APPLICABLE,
}

_DESCRIPTIONS = {
    State.OK: "done",
    State.MISSING: "missing",
    State.UNANNOTATED: "not annotated yet",
    State.TODO: "planned",
    State.PARTIAL: "partly done",
    State.EXCEPTION: "deliberate deviation",
    State.NOT_EXPECTED: "no test expected",
    State.NOT_APPLICABLE: "not applicable",
}

_PRESETS = {
    "symbols": {
        State.OK: "✔",
        State.MISSING: "✘",
        State.UNANNOTATED: "?",
        State.TODO: "…",
        State.PARTIAL: "½",
        State.EXCEPTION: "≠",
        State.NOT_EXPECTED: "—",
        State.NOT_APPLICABLE: "∅",
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
    },
}

_CLASSES = {
    State.OK: "duvet-ok",
    State.EXCEPTION: "duvet-exception",
    State.TODO: "duvet-todo",
    State.PARTIAL: "duvet-partial",
    State.MISSING: "duvet-missing",
    State.UNANNOTATED: "duvet-unannotated",
    State.NOT_EXPECTED: "duvet-none",
    State.NOT_APPLICABLE: "duvet-na",
}


class duvet_label(nodes.inline):
    """The label of a state, with the description of the state.

    HTML pages show the description on hover. Other formats only show the label,
    as they render the node as an inline.
    """


def visit_label_html(translator: HTML5Translator, node: duvet_label) -> None:
    """Open an abbr element, with the description as its title."""
    translator.body.append(
        translator.starttag(node, "abbr", "", title=node["explanation"])
    )


def depart_label_html(translator: HTML5Translator, node: duvet_label) -> None:
    """Close the abbr element."""
    translator.body.append("</abbr>")


def label_sources(value: Any) -> tuple[dict[State, str], list[str]]:
    """Return the markup of each state from the duvet_labels option, and the problems found.

    The option is the name of a preset, or a dictionary that overrides the symbols.
    """
    if isinstance(value, str):
        if value in _PRESETS:
            return dict(_PRESETS[value]), []
        return dict(_PRESETS["symbols"]), [
            f"unknown duvet_labels preset {value!r}, expected 'symbols' or 'text'"
        ]
    sources = dict(_PRESETS["symbols"])
    problems = []
    for key, markup in value.items():
        if key not in _KEYS:
            problems.append(f"unknown duvet_labels key {key!r}")
            continue
        sources[_KEYS[key]] = markup
    return sources, problems


def check_labels(app: Sphinx, config: Config) -> None:
    """Warn once about the problems of the duvet_labels option."""
    for problem in label_sources(config.duvet_labels)[1]:
        logger.warning(problem, type="duvet")


class Labels:
    """The labels of the states, parsed once and copied in each cell."""

    def __init__(
        self, sources: dict[State, str], parse: Callable[[str], list[nodes.Node]]
    ) -> None:
        """Parse the markup of each state."""
        self._nodes = {value: parse(markup) for value, markup in sources.items()}

    def state(self, value: State) -> duvet_label:
        """Return the label of a state. Its description shows on hover."""
        node = duvet_label(
            explanation=_DESCRIPTIONS[value],
            classes=["duvet-status", _CLASSES[value]],
        )
        node.extend(copy.deepcopy(child) for child in self._nodes[value])
        return node

    def status_cell(self, status: Status) -> list[nodes.Node]:
        """Return the implementation and test states, one per line."""
        if status.implementation in (State.NOT_APPLICABLE, State.UNANNOTATED):
            return [_line(self.state(status.implementation))]
        return [
            _line(_caption("impl. "), self.state(status.implementation)),
            _line(_caption("test "), self.state(status.test)),
        ]

    def legend(self) -> nodes.paragraph:
        """Return a line that explains the labels.

        A description is left out when the label already says the same.
        """
        node = nodes.paragraph(classes=["duvet-legend"])
        for index, value in enumerate(_DESCRIPTIONS):
            if index:
                node += nodes.Text(" · ")
            label = self.state(value)
            node += label
            if label.astext() != _DESCRIPTIONS[value]:
                node += nodes.Text(f" {_DESCRIPTIONS[value]}")
        return node


def _line(*children: nodes.Node) -> nodes.paragraph:
    """Return a line of a status cell, that does not wrap."""
    return nodes.paragraph("", "", *children, classes=["duvet-state"])


def _caption(text: str) -> nodes.inline:
    """Return a small caption before a state."""
    return nodes.inline(text=text, classes=["duvet-caption"])
