Usage
=====

sphinx-duvet reads the Duvet project of your repository.
It finds the closest :file:`.duvet/config.toml` above the folder of :file:`conf.py`.

Getting the report
------------------

By default, sphinx-duvet runs ``duvet report --json-v2`` when the build starts.
Duvet must then be installed where the documentation is built.
Duvet has no prebuilt binary, so install it with cargo:

.. code-block:: shell

   cargo install duvet --locked

If Duvet is not available, produce the report elsewhere and give its path:

.. code-block:: shell

   duvet report --json-v2 compliance.json

.. code-block:: python

   duvet_report_json = "../compliance.json"

The build stops if the report cannot be read or if Duvet fails.

Read the Docs
~~~~~~~~~~~~~

Read the Docs provides Rust, so the build can install Duvet.
Pin its version, so that a new release does not change the reports.
Installing Duvet adds a few minutes to each build.

.. code-block:: yaml

   version: 2
   build:
     os: "ubuntu-24.04"
     tools:
       python: "3.14"
       rust: "latest"
     jobs:
       post_install:
         - cargo install duvet --locked --version 0.4.3

Continuous integration
~~~~~~~~~~~~~~~~~~~~~~

In the CI, :ref:`sphinx-duvet check <command-line>` fails when requirements are not done.
Cache the Duvet binary, so it is only built when its version changes.
With GitHub Actions, the hosted runners provide cargo:

.. code-block:: yaml

   - uses: actions/cache@v6
     id: duvet
     with:
       path: ~/.cargo/bin/duvet
       key: duvet-0.4.3-${{ runner.os }}
   - if: steps.duvet.outputs.cache-hit != 'true'
     run: cargo install duvet --locked --version 0.4.3
   - run: uv run sphinx-duvet check --levels MUST

Configuration
-------------

.. confval:: duvet_root

   The folder that contains :file:`.duvet/`, relative to :file:`conf.py`.
   By default, the closest parent folder that contains :file:`.duvet/config.toml`.

.. confval:: duvet_report_json

   A v2 JSON report of Duvet, relative to :file:`conf.py`.
   If it is not set, Duvet runs during the build.

.. confval:: duvet_executable

   The Duvet executable. The default is ``duvet``.

.. confval:: duvet_autoreport

   Default options of the generated pages, as a dictionary.
   If it is set, sphinx-duvet writes an index page and a page per specification.
   For instance ``{"group-by": "role", "show": "missing"}``.

.. confval:: duvet_autoreport_dir

   The folder of the generated pages, relative to the source folder.
   The default is ``compliance``. Add ``compliance/index`` to a toctree.

.. confval:: duvet_labels

   The labels of the states in the reports.
   ``"symbols"`` (the default) or ``"text"``, or a dictionary.
   See :ref:`labels`.

.. confval:: duvet_spec_highlight

   The language of the figures in :rst:dir:`duvet-spec`.
   ``"auto"`` (the default) highlights JSON and HTTP examples.
   ``"none"`` disables highlighting.
   Any other value is the name of a `Pygments lexer <https://pygments.org/docs/lexers/>`_.

Directives
----------

.. rst:directive:: .. duvet-report:: path

   A table with a row per requirement of a specification, and a column per target.
   The path is the path of the specification in :file:`.duvet/config.toml`.

   The requirements are grouped by section, under a row with the title of the section
   and a link to it in the RFC. Each row shows the level of the requirement, its text,
   the annotations that cite it and its notes.
   Each cell shows the implementation state and the test state.

   On hover, a permalink follows the text of each requirement and the title of each section,
   as for headings. ``html_permalinks`` and ``html_permalinks_icon`` apply.

   .. rst:directive:option:: targets: selectors
      :type: text

      Only show some targets. See :ref:`selectors`.

   .. rst:directive:option:: group-by: attribute
      :type: text

      One column per value of a target attribute, such as ``role``.
      The worst state of the targets of a group wins.

   .. rst:directive:option:: sections: sections
      :type: comma separated list

      Only show some sections and their subsections, such as ``4.1, 5``.

   .. rst:directive:option:: levels: levels
      :type: comma separated list

      Only show some levels, such as ``MUST, SHOULD``.

   .. rst:directive:option:: show: all, missing or unannotated
      :type: text

      With ``missing``, only show the gaps:
      the requirements with annotations, but a missing implementation or test.
      With ``unannotated``, only show the requirements without any annotation.
      The default is ``all``.

.. rst:directive:: .. duvet-spec:: path

   The whole text of an IETF specification, with a section per section of the specification.
   Each requirement is highlighted by its worst state among the targets.
   A link to its row in a report follows it, and shows on hover.

   The text keeps its structure, guessed from its indentation:

   - Paragraphs are joined, so they follow the width of the page.
     Page headers and footers are removed.
   - The header of the first page is a table. The title is left out,
     as it should be the title of the page.
   - The table of contents is a list of links to the sections.
   - Lists and definitions, such as parameters and references, are HTML lists.
     Markers such as ``(A)`` or ``1.`` are kept.
   - Tables drawn with ``+---+`` borders, or with columns underlined with dashes,
     are HTML tables.
   - Figures and examples keep their layout. A caption such as ``Figure 2: Example``
     is shown below its figure or its table.
   - ``Section 3.1`` links to the section. ``[RFC7644]`` links to its entry in the references.
     ``Section 3.1 of [RFC7644]``, ``RFC 7644``, web addresses and email addresses link to
     their target. Addresses on the example domains of :rfc:`2606` are not links.

   A block that does not follow these rules keeps its layout, as a figure.

   Figures are examples, so their requirements are not highlighted.
   For instance, the JSON schemas of :rfc:`7643` repeat requirements of its section 4.
   The :rst:role:`duvet:rule` role links them to the section of their figure.

   JSON and HTTP examples are highlighted.
   The ``highlight`` option, or :confval:`duvet_spec_highlight`, sets the language.

   .. code-block:: rst

      .. duvet-spec:: rfc/rfc7643.txt
         :highlight: none

   With :confval:`duvet_autoreport`, each IETF specification gets a page with its text,
   titled as the specification, next to its compliance page, such as "RFC 7643 compliance".

   The IETF Trust allows to copy and distribute RFCs in full and without modification
   (`Trust Legal Provisions <https://trustee.ietf.org/documents/trust-legal-provisions/>`_,
   section 3.c). So the whole text is shown, with its header, its copyright notice
   and its table of contents.

.. rst:directive:: .. duvet-recap:: [path]

   A table that counts the requirements per level and per column.
   Without a path, it counts the requirements of every specification.
   It takes the same options as :rst:dir:`duvet-report`, except ``show``.

   There is no global percentage: a MUST and a MAY do not weigh the same.
   Deliberate deviations are counted apart from missing requirements.
   Requirements without any annotation are counted as "not annotated".

References
----------

Each requirement has an identifier: the name of the specification file without its extension,
the number of its section, and its rank in the section. For instance, ``rfc7643#3.1-9``
is the ninth requirement of section 3.1 of :file:`rfc7643.txt`.
Requirements outside of any section are in section ``0``.
If two specification files share a name, the identifier uses their whole path.

.. rst:role:: duvet:rule

   A link to a requirement, in the text of its specification,
   or in a report if no page shows the text:

   .. code-block:: rst

      The id is issued by the server (:duvet:rule:`rfc7643#3.1-9`).
      See :duvet:rule:`this requirement <rfc7643#3.1-9>`.

   The ``any`` role finds requirements too.

.. rst:role:: duvet:status

   A link to the row of a requirement in a report, with its states:

   .. code-block:: rst

      See the status of :duvet:status:`rfc7643#3.1-9`.

Requirements are in the inventory of the documentation,
so other documentations can refer to them with intersphinx:
``:duvet:rule:`specs:rfc7643#3.1-9```.
A documentation without a Duvet project can enable sphinx-duvet only for this role.

Rows have anchors, such as ``#duvet-rfc7643-3.1-9`` for a requirement
and ``#duvet-section-rfc7643-3.1`` for a section.
If a page shows a requirement several times, the link goes to the first one.
If several pages show it, the link goes to the first page, in alphabetical order.

States
------

The implementation state of a requirement for a target is one of:

- **done**: the annotations of the target cite the whole requirement;
- **exception**: the requirement is a deliberate deviation;
- **todo**: an annotation plans the requirement;
- **partial**: the annotations cite only a part of the requirement;
- **missing**: the requirement has annotations, but none for this target;
- **not annotated**: the requirement has no annotation at all;
- **n/a**: the requirement does not apply to the target.

A test is expected when a part of the requirement is cited as implemented.
The tests must cover that part. Parts cited as exceptions need no test.

.. _labels:

Labels
~~~~~~

The reports show each state with a label. On hover, a label shows the description of its state.

==================  =======  =============  ====================
Key                 Symbol   Text           Description
==================  =======  =============  ====================
``ok``              ✔        done           done
``missing``         ✘        missing        missing
``unannotated``     ?        not annotated  not annotated yet
``todo``            …        todo           planned
``partial``         ½        partial        partly done
``exception``       ≠        exception      deliberate deviation
``not_expected``    —        not expected   no test expected
``not_applicable``  ∅        n/a            not applicable
==================  =======  =============  ====================

:confval:`duvet_labels` can also be a dictionary.
Its values are inline reStructuredText, so they can use roles,
such as the icons of `sphinx-iconify <https://sphinx-iconify.lepture.com>`_.
The states that are not in the dictionary keep their symbol.

.. code-block:: python

   extensions = ["sphinx_duvet", "sphinx_iconify"]
   duvet_labels = {
       "ok": ":iconify:`mdi:check-circle`",
       "missing": ":iconify:`mdi:close-circle`",
   }

Icons take the color of their state.

Targets
-------

Without :file:`.duvet/targets.toml`, the project has a single target.
This file describes the targets of a project, such as a server and a client,
and which annotations and requirements apply to them.

.. code-block:: toml

   # Tests are checked per role only: a Flask test covers every server target.
   test-granularity = ["role"]

   [[target]]
   id = "server-flask"
   role = "server"
   framework = "flask"

   [[target]]
   id = "client"
   role = "client"

   # The targets covered by the annotations of a file. The first match wins.
   # Annotations in .duvet/ and in other files cover every target.
   [[default]]
   pattern = "src/server/flask/**"
   covers = "role=server,framework=flask"

   # The targets a requirement applies to. By default, every target.
   [[applies]]
   target = "spec/rfc9999.txt#section-2"
   quote = "The client MUST send the token."
   applies-to = "role=client"

Checkers
~~~~~~~~

Some projects do not implement the requirements: they check that other projects implement them,
like a conformance test suite. Such a target is a checker. Give it the targets it checks:

.. code-block:: toml

   [[target]]
   id = "tester"
   kind = "checker"
   checks = "role=server"

A requirement applies to a checker if it applies to one of the targets it checks.
The annotations of the checker cite the requirements that it checks,
and its column shows them as for any target.
``checks`` takes :ref:`selectors`. ``kind`` is a plain attribute,
which annotations can select with ``covers = "kind=checker"``.

With ``group-by``, a target without the attribute gets a column of its own.

.. _selectors:

Selectors
~~~~~~~~~

A selector is a list of ``key=value`` pairs separated by commas.
It matches the targets that have every attribute: ``role=server,framework=flask``.

Several selectors are separated by semicolons or new lines.
A target matches if it matches one of them: ``role=server; role=client``.

Shared configuration
~~~~~~~~~~~~~~~~~~~~

Several projects can share the specifications, the targets, the ``[[applies]]`` entries,
the requirements without key words and the notes.
Put them in a project of their own, and add it to each project as a git submodule:

.. code-block:: shell

   git submodule add https://github.com/example/specs rfc

Then include it in :file:`.duvet/targets.toml`:

.. code-block:: toml

   include = "rfc"

The included project brings its targets, its ``[[applies]]`` entries,
its ``test-granularity`` and its notes.
Its specification paths get the folder of the submodule as a prefix:
``spec.md`` in the shared project is ``rfc/spec.md`` in the project.
Its ``[[default]]`` and ``[[dependency]]`` entries are its own, and are not included.

Duvet still needs the specifications and the requirements without key words
in :file:`.duvet/config.toml`:

.. code-block:: toml

   [[specification]]
   source = "rfc/rfc7643.txt"
   format = "ietf"

   [[requirement]]
   pattern = "rfc/.duvet/spec/**/*.toml"

Annotations use the path of the project: ``##= rfc/rfc7643.txt#section-3``.

Dependencies
~~~~~~~~~~~~

The annotations of the installed Python packages that a project depends on can count for it.
For instance, a Django integration can rely on the models of another package:

.. code-block:: toml

   [[dependency]]
   package = "scim2_models"
   covers = "role=server; role=client"
   link = "https://github.com/python-scim/scim2-models/blob/{version}/{path}"

``covers`` gives the targets that the annotations of the package cover, every target by default.
``link`` gives the address of a file of the package in its repository,
from its version and its path in the package, such as ``scim2_models/base.py``.
``comment-style`` sets the comment style of its annotations,
the style of the first source of the project by default.

sphinx-duvet finds the package in the current Python environment,
and adds it to the sources of Duvet.
The reports then show the annotations of the installed version.

Packages do not ship their tests. So a requirement that only a dependency implements
needs no test in the project: the dependency tests it in its own repository.
A test of the project still counts.

To use ``duvet_report_json`` or ``--report-json`` with dependencies,
produce the report with ``sphinx-duvet export`` rather than ``duvet report``.

Notes
-----

Notes add free text to a requirement, such as a design choice or a link to an issue.
Write them in reStructuredText files in :file:`.duvet/notes/`:

.. code-block:: rst

   .. duvet-note:: spec/rfc9999.txt#section-2
      :quote: The server SHOULD log the request.

      Logging uses the standard *logging* module.

The note is shown in the row of the requirement.

.. _command-line:

Command line
------------

The ``sphinx-duvet`` command shows the same reports in a terminal, and checks them in the CI.
Run it from the repository, or give the project folder with ``--root``.
Like the documentation, it runs Duvet, or reads a report given with ``--report-json``.

.. code-block:: shell

   sphinx-duvet report spec/rfc9999.txt --group-by role --show missing
   sphinx-duvet recap --levels MUST,SHOULD
   sphinx-duvet check --levels MUST

``report``
   A table per specification, with a row per requirement.
   Each target has two columns: ``impl`` for the implementation state, and ``test`` for the test state.
   In a terminal, the states are colored, unless ``NO_COLOR`` is set,
   and long requirements are cut to the width of the terminal.

``recap``
   The counts per level and per column, as :rst:dir:`duvet-recap`.

``check``
   The requirements that fail, with their identifier, their column and the reason.
   The command fails if there are some.

``export``
   Runs Duvet with the dependencies, and writes its report:
   ``sphinx-duvet export report.json``.

The ``report``, ``recap`` and ``check`` commands take the specifications to show, all by default,
and the options of the directives: ``--targets``, ``--group-by``, ``--sections``, ``--levels``,
and ``--show`` for ``report``. ``--labels`` is ``symbols`` or ``text``.

``check`` also takes:

``--fail-on``
   The states that fail, separated by commas, among
   ``missing``, ``partial``, ``todo``, ``untested`` (a missing test) and ``unannotated``.
   The default is ``missing,partial,untested``.
   Deliberate deviations never fail.

``--strict``
   Also fail if some ``[[applies]]`` entries or notes match no requirement.
   Otherwise, they only show a warning.

The exit code is 0 on success, 1 if ``check`` finds failures,
and 2 if the arguments are invalid or the report cannot be loaded.

Warnings
--------

All the warnings of sphinx-duvet have the ``duvet`` type.
The ``duvet.unused`` subtype is for ``[[applies]]`` entries and notes that match no requirement.
Silence them with :confval:`suppress_warnings`:

.. code-block:: python

   suppress_warnings = ["duvet.unused"]
