Changelog
=========

[0.1.0] - Unreleased
--------------------

Added
^^^^^
- ``duvet-report`` shows the requirements of a specification,
  with the implementation and test state of each target.
  Below each state, chips link to the annotations behind it.
  A report with one column counts its requirements per state.
  The sections of a report are in the table of contents of its page.
- ``duvet-recap`` counts the requirements per level and per target.
- ``duvet_autoreport`` writes a page per specification.
- Targets, and the targets of annotations and requirements, are set in :file:`.duvet/targets.toml`.
- Notes in :file:`.duvet/notes/` add text to requirements.
- The ``sphinx-duvet`` command shows the reports in a terminal, and checks them in the CI.
- Projects can include a shared project, for instance a git submodule,
  with its targets, applicability, requirements and notes.
- The annotations of installed dependencies count for a project.
  ``sphinx-duvet export`` writes a report that includes them.
- Checker targets, such as a conformance test suite, show the requirements they check.
- Each requirement has an identifier, such as ``rfc7643#3.1-9``.
  The ``duvet:rule`` role links to it, also from other documentations with intersphinx.
- ``duvet-spec`` shows the whole text of an IETF specification, with its requirements highlighted.
  Lists, definitions and tables are rendered in HTML, also the tables of recent RFCs,
  figures have their caption, and references to sections, RFCs and addresses are links.
  The BCP 14 key words are marked in the whole text, as in the HTML RFCs.
  JSON and HTTP examples are highlighted, see ``duvet_spec_highlight``.
  ``duvet_autoreport`` gives each specification a page with its text.
- ``duvet_autoreport_recap`` removes the counts at the top of the generated pages.
- Requirements that Duvet finds in the figures of IETF specifications are left out.
  ``duvet_figure_requirements`` and ``--figure-requirements`` keep them.
- ``[[outside]]`` entries mark the requirements that another project implements.
  They show their reason, and are not counted.
- A requirement cited in full with a todo annotation is partly done.
- ``group-by: all`` shows every target in one column.
- ``duvet_autoreport`` writes a "Specifications" index of the texts, next to the "Compliance" index.
  A compliance page links to the text in the documentation and to the specification, as buttons.
  The navigation shows short titles, such as "RFC 7643: Core Schema". ``duvet_short_titles`` sets others.
- A report highlights the row of the requirement or section in the URL fragment.
- ``duvet-spec`` takes a ``targets`` option. ``duvet_autoreport`` sets it as for the reports.
- ``tests = false`` in :file:`.duvet/targets.toml` follows the implementation only, without tests.
- The documentation explains how to install Duvet on Read the Docs and in the CI.
- ``duvet_labels`` shows the states as symbols, as text, or with any inline markup such as icons.
