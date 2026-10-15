"""The duvet domain: references to requirements, with the duvet:rule role."""

from collections.abc import Iterable
from collections.abc import Iterator
from typing import Any
from typing import ClassVar
from typing import NamedTuple

from docutils import nodes
from sphinx.addnodes import pending_xref
from sphinx.builders import Builder
from sphinx.domains import Domain
from sphinx.domains import ObjType
from sphinx.environment import BuildEnvironment
from sphinx.roles import XRefRole
from sphinx.util.nodes import make_refnode

RULE_PRIORITY = 1
"""The priority of a requirement in a report. Lower numbers win."""


class RuleLocation(NamedTuple):
    """A place where a requirement is shown."""

    docname: str
    anchor: str
    priority: int
    title: str


def rule_anchor(rule_id: str) -> str:
    """Return the HTML identifier of a requirement, such as duvet-rfc7643-3.1-9.

    Dots are kept, so section 2.1 and section 2 rank 1 do not collide.
    """
    return "duvet-" + "-".join(rule_id.replace("#", " ").split())


def section_anchor(spec_name: str, number: str) -> str:
    """Return the HTML identifier of a section of a specification, such as duvet-section-rfc7643-3.1."""
    return "duvet-section-" + "-".join(f"{spec_name} {number}".split())


class DuvetDomain(Domain):
    """Requirements of specifications, that documents can refer to."""

    name = "duvet"
    label = "Duvet"
    object_types = {"rule": ObjType("rule", "rule")}
    roles = {"rule": XRefRole(innernodeclass=nodes.inline, warn_dangling=True)}
    initial_data: ClassVar[dict[str, Any]] = {"rules": {}}
    dangling_warnings = {"rule": "unknown requirement %(target)s"}
    data_version = 1

    @property
    def rules(self) -> dict[str, list[RuleLocation]]:
        """The places where each requirement is shown."""
        rules: dict[str, list[RuleLocation]] = self.data["rules"]
        return rules

    def note_rule(
        self, rule_id: str, docname: str, anchor: str, title: str, priority: int
    ) -> None:
        """Record a place where a requirement is shown."""
        self.rules.setdefault(rule_id, []).append(
            RuleLocation(docname, anchor, priority, title)
        )

    def location(self, rule_id: str) -> RuleLocation | None:
        """Return the main place of a requirement: the best priority, then the first document."""
        locations = self.rules.get(rule_id)
        if not locations:
            return None
        return _best(locations)

    def clear_doc(self, docname: str) -> None:
        """Forget the requirements shown in a document."""
        for rule_id, locations in list(self.rules.items()):
            kept = [loc for loc in locations if loc.docname != docname]
            if kept:
                self.rules[rule_id] = kept
            else:
                del self.rules[rule_id]

    def merge_domaindata(
        self, docnames: Iterable[str], otherdata: dict[str, Any]
    ) -> None:
        """Add the requirements read by a parallel process."""
        docnames = set(docnames)
        for rule_id, locations in otherdata["rules"].items():
            for location in locations:
                if location.docname in docnames:
                    self.rules.setdefault(rule_id, []).append(location)

    def resolve_xref(
        self,
        env: BuildEnvironment,
        fromdocname: str,
        builder: Builder,
        typ: str,
        target: str,
        node: pending_xref,
        contnode: nodes.Element,
    ) -> nodes.reference | None:
        """Return a link to a requirement."""
        location = self.location(target)
        if location is None:
            return None
        return make_refnode(
            builder,
            fromdocname,
            location.docname,
            location.anchor,
            contnode,
            location.title,
        )

    def resolve_any_xref(
        self,
        env: BuildEnvironment,
        fromdocname: str,
        builder: Builder,
        target: str,
        node: pending_xref,
        contnode: nodes.Element,
    ) -> list[tuple[str, nodes.reference]]:
        """Return a link to a requirement for the any role."""
        reference = self.resolve_xref(
            env, fromdocname, builder, "rule", target, node, contnode
        )
        return [] if reference is None else [("duvet:rule", reference)]

    def get_objects(self) -> Iterator[tuple[str, str, str, str, str, int]]:
        """Return the requirements, for the inventory of the documentation."""
        for rule_id, locations in sorted(self.rules.items()):
            location = _best(locations)
            yield (
                rule_id,
                rule_id,
                "rule",
                location.docname,
                location.anchor,
                location.priority,
            )


def _best(locations: list[RuleLocation]) -> RuleLocation:
    """Return the location with the best priority, then the first document."""
    return min(locations, key=lambda loc: (loc.priority, loc.docname, loc.anchor))
