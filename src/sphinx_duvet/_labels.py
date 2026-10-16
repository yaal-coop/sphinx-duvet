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
from .labels import DESCRIPTIONS
from .labels import KEYS
from .labels import PRESETS

logger = logging.getLogger(__name__)

_CLASSES = {
    State.OK: "duvet-ok",
    State.EXCEPTION: "duvet-exception",
    State.TODO: "duvet-todo",
    State.PARTIAL: "duvet-partial",
    State.MISSING: "duvet-missing",
    State.UNANNOTATED: "duvet-unannotated",
    State.NOT_EXPECTED: "duvet-none",
    State.NOT_APPLICABLE: "duvet-na",
    State.OUTSIDE: "duvet-outside",
}

# States without a test state.
SINGLE = (State.NOT_APPLICABLE, State.UNANNOTATED, State.OUTSIDE)


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
        if value in PRESETS:
            return dict(PRESETS[value]), []
        return dict(PRESETS["symbols"]), [
            f"unknown duvet_labels preset {value!r}, expected 'symbols' or 'text'"
        ]
    sources = dict(PRESETS["symbols"])
    problems = []
    for key, markup in value.items():
        if key not in KEYS:
            problems.append(f"unknown duvet_labels key {key!r}")
            continue
        sources[KEYS[key]] = markup
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
            explanation=DESCRIPTIONS[value],
            classes=["duvet-status", _CLASSES[value]],
        )
        node.extend(copy.deepcopy(child) for child in self._nodes[value])
        return node

    def status_cell(self, status: Status, tests: bool = True) -> list[nodes.Node]:
        """Return the implementation and test states, one per line.

        Without tests, only the implementation state.
        """
        if status.implementation in SINGLE or not tests:
            return [_line(self.state(status.implementation))]
        return [
            _line(_caption("impl. "), self.state(status.implementation)),
            _line(_caption("test "), self.state(status.test)),
        ]

    def summary(
        self, counts: dict[State, int], tested: tuple[int, int] | None
    ) -> nodes.paragraph:
        """Return the number of requirements in each state of a report, as chips.

        It also explains the labels: their description shows on hover,
        and in the chip when the label is a symbol. The tested requirements follow,
        as tested/expected, if some tests are expected.
        Spaces separate the chips in formats other than HTML.
        """
        node = nodes.paragraph(classes=["duvet-summary"])
        for value in _SUMMARY:
            if not counts.get(value):
                continue
            if node.children:
                node += nodes.Text(" ")
            chip = nodes.inline(classes=["duvet-summary-item"])
            chip += nodes.inline(
                text=str(counts[value]),
                classes=["duvet-summary-count", _CLASSES[value]],
            )
            chip += nodes.Text(" ")
            label = self.state(value)
            chip += label
            if not any(char.isalpha() for char in label.astext()):
                chip += nodes.Text(f" {DESCRIPTIONS[value]}")
            node += chip
        if tested is not None and tested[1]:
            node += nodes.Text(" ")
            node += nodes.inline(
                text=f"{tested[0]}/{tested[1]} tested", classes=["duvet-summary-item"]
            )
        return node

    def highlight_legend(self) -> nodes.paragraph:
        """Return a line that explains the highlight colors of the requirements in a text.

        It shows the labels as the summaries of the reports do, each one on its color.
        """
        node = nodes.paragraph(classes=["duvet-legend"])
        node += nodes.Text("Requirements: ")
        for index, value in enumerate(_HIGHLIGHTS):
            if index:
                node += nodes.Text(" · ")
            sample = nodes.inline(
                classes=["duvet-rule", f"duvet-rule-{value.name.lower()}"]
            )
            label = self.state(value)
            sample += label
            if not any(char.isalpha() for char in label.astext()):
                sample += nodes.Text(f" {DESCRIPTIONS[value]}")
            node += sample
        return node


# The states that a text highlights, in the order of its legend.
_HIGHLIGHTS = (
    State.OK,
    State.PARTIAL,
    State.TODO,
    State.MISSING,
    State.EXCEPTION,
    State.UNANNOTATED,
    State.OUTSIDE,
)

# The order of the states in a summary, from done to out of scope.
_SUMMARY = (
    State.OK,
    State.PARTIAL,
    State.TODO,
    State.MISSING,
    State.UNANNOTATED,
    State.EXCEPTION,
    State.OUTSIDE,
)


def _line(*children: nodes.Node) -> nodes.paragraph:
    """Return a line of a status cell, that does not wrap."""
    return nodes.paragraph("", "", *children, classes=["duvet-state"])


def _caption(text: str) -> nodes.inline:
    """Return a small caption before a state."""
    return nodes.inline(text=text, classes=["duvet-caption"])
