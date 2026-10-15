import datetime
from importlib import metadata

extensions = [
    "sphinx.ext.autodoc",
    "sphinx.ext.intersphinx",
    "sphinx_duvet",
]

master_doc = "index"
project = "sphinx-duvet"
year = datetime.datetime.now().strftime("%Y")
copyright = f"{year}, Yaal Coop"
author = "Yaal Coop"
source_suffix = {".rst": "restructuredtext"}

version = metadata.version("sphinx-duvet")
release = version
language = "en"

intersphinx_mapping = {
    "python": ("https://docs.python.org/3", None),
    "sphinx": ("https://www.sphinx-doc.org/en/master", None),
}

html_theme = "shibuya"
html_theme_options = {
    "github_url": "https://github.com/yaal-coop/sphinx-duvet",
}
