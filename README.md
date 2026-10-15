# sphinx-duvet

Show in a Sphinx documentation how a project complies with a specification.

sphinx-duvet reads the reports of [Duvet](https://github.com/awslabs/duvet),
which links the requirements of a specification to the code and the tests that
implement them.

For each requirement, the reports show whether each target of the project
implements and tests it, such as a server and a client.

sphinx-duvet is at an early stage. Its options may change.

## Installation

```shell
uv add sphinx-duvet
```

Then enable the extension in your `conf.py`:

```python
extensions = ["sphinx_duvet"]
```
