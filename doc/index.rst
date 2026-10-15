sphinx-duvet
============

sphinx-duvet shows in a Sphinx documentation how a project complies with a
specification. It reads the reports of `Duvet <https://github.com/awslabs/duvet>`_,
which links the requirements of a specification to the code and the tests
that implement them.

.. warning::

   sphinx-duvet is at an early stage. Its options may change.

Installation
------------

.. code-block:: shell

   uv add sphinx-duvet

Then enable the extension in your ``conf.py``:

.. code-block:: python

   extensions = ["sphinx_duvet"]

.. toctree::
   :maxdepth: 1

   usage
   example
   example-text
   changelog
