Changelog
=========

[0.1.0] - Unreleased
--------------------

Added
^^^^^
- ``duvet-report`` shows the requirements of a specification,
  with the implementation and test state of each target.
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
- The documentation explains how to install Duvet on Read the Docs and in the CI.
- ``duvet_labels`` shows the states as symbols, as text, or with any inline markup such as icons.
