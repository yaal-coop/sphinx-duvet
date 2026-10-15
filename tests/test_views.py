import pytest

from sphinx_duvet.compliance import Project
from sphinx_duvet.targets import ConfigError
from sphinx_duvet.targets import parse_selectors
from sphinx_duvet.views import View


def test_parse() -> None:
    """Options are read from strings. Blank items are ignored and levels are case insensitive."""
    view = View.parse(
        targets="role=server",
        group_by="role",
        sections="2, 3.1,,",
        levels="must, Should",
        show="missing",
    )
    assert view == View(
        selectors=parse_selectors("role=server"),
        group_by="role",
        sections=["2", "3.1"],
        levels={"MUST", "SHOULD"},
        show="missing",
    )
    assert View.parse() == View()
    assert View.parse(group_by="", levels=" , ") == View()


def test_parse_invalid() -> None:
    """Invalid show values and selectors are reported."""
    with pytest.raises(ConfigError, match="Invalid show value 'gaps'"):
        View.parse(show="gaps")
    with pytest.raises(ConfigError, match="Invalid selector"):
        View.parse(targets="role")


def test_rows(project: Project) -> None:
    """Rows keep the requirements of the selected sections and levels that apply to a column."""
    spec = project.specifications["spec/rfc9999.txt"]
    view = View.parse(targets="role=client", sections="2", levels="MUST")
    rows = view.rows(project, spec)
    assert [row.requirement.text for row in rows] == [
        "The client MUST send the token.",
        "The server MUST validate the café parameter and the response MUST be encoded as JSON.",
    ]
    assert [str(status.implementation) for status in rows[0].statuses] == ["ok"]


@pytest.mark.parametrize(
    "show,count",
    [("all", 11), ("missing", 5), ("unannotated", 3)],
)
def test_show(project: Project, show: str, count: int) -> None:
    """Gaps and unannotated requirements are shown apart."""
    spec = project.specifications["spec/rfc9999.txt"]
    assert len(View.parse(show=show).rows(project, spec)) == count


def test_requirements(project: Project) -> None:
    """The requirements of several specifications are filtered by section and level."""
    view = View.parse(levels="SHOULD")
    texts = [r.text for r in view.requirements(project.specifications.values())]
    assert texts == [
        'The server SHOULD publish its "metadata".',
        "The server SHOULD log the request.",
        "Servers SHOULD rotate their keys.",
    ]
