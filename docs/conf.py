# Configuration file for the Sphinx documentation builder.
#
# For the full list of built-in configuration values, see the documentation:
# https://www.sphinx-doc.org/en/master/usage/configuration.html

# -- Path setup --------------------------------------------------------------

import os
import pathlib
import re
import sys

sys.path.insert(0, os.path.abspath("../src"))

# -- Project information -----------------------------------------------------

project = "Ducta"
copyright = "2024-2026, Faustino Lopez Ramos"
author = "Faustino Lopez Ramos"


# Read version from pyproject.toml
def _get_version():
    _pyproject_path = pathlib.Path(__file__).parent.parent / "pyproject.toml"
    if not _pyproject_path.exists():
        return "unknown"
    with open(_pyproject_path, "r", encoding="utf-8") as _f:
        _match = re.search(r'^version\s*=\s*["\']([^"\']+)["\']', _f.read(), re.MULTILINE)
        return _match.group(1) if _match else "unknown"


release = _get_version()
version = release

# -- General configuration ---------------------------------------------------

rst_epilog = f".. |release| replace:: {release}"

extensions = [
    "sphinx.ext.autodoc",
    "sphinx.ext.napoleon",
    "sphinx.ext.intersphinx",
    "sphinx.ext.todo",
    "sphinx.ext.coverage",
    "sphinx.ext.ifconfig",
    "sphinx.ext.githubpages",
    "myst_parser",
    "sphinx_copybutton",
    "sphinx_design",
]

# Add any paths that contain templates here, relative to this directory.
templates_path = ["_templates"]

# List of patterns, relative to source directory, that match files and
# directories to ignore when looking for source files.
exclude_patterns = ["_build", "Thumbs.db", ".DS_Store"]

# The suffix(es) of source filenames.
source_suffix = {
    ".rst": "restructuredtext",
    ".md": "markdown",
}

# The master toctree document.
master_doc = "index"

# -- Options for HTML output -------------------------------------------------

html_theme = "furo"
html_static_path = ["_static", "img"]
html_css_files = ["custom.css"]
html_title = "Ducta"
html_favicon = "img/logo.ico"

# ---------------------------------------------------------------------------
# Brand palette — "Blueprint / Deep Petrol" theme:
# Direct parity with Web UI (src/ducta/ui/src/theme/ducta-theme.css).
#
# Light mode: "Blueprint" cool paper ground (#F4F6F7), white surfaces (#FFFFFF),
# ink text (#0F1B20), and deep Petrol accent (#0B5F73, 7.1:1 AAA on white).
#
# Dark mode: "Deep Petrol" cool charcoal ground (#0C1417), elevated surfaces
# (#141F24), bright text (#E3EDF1), and signal Cyan accent (#38BDF8, 8.4:1).
# ---------------------------------------------------------------------------

# Typography matches the UI stacks (Inter + JetBrains Mono).
_FONT_SANS = (
    "'Inter', -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif"
)
_FONT_MONO = "'JetBrains Mono', 'Fira Code', 'SFMono-Regular', Menlo, Consolas, monospace"

# Light palette (Blueprint)
_LIGHT_PALETTE = {
    "font-stack": _FONT_SANS,
    "font-stack--monospace": _FONT_MONO,
    "color-code-background": "#EAEEF0",
    "color-code-foreground": "#0F1B20",
    "color-brand-primary": "#0B5F73",
    "color-brand-content": "#0B5F73",
    "color-brand-visited": "#084453",
    "color-background-primary": "#FFFFFF",
    "color-background-secondary": "#F4F6F7",
    "color-background-hover": "#E4E9EC",
    "color-background-border": "#DDE4E7",
    "color-foreground-primary": "#0F1B20",
    "color-foreground-secondary": "#4E626A",
    "color-foreground-muted": "#5C717A",
    "color-foreground-border": "#C3CFD4",
    # Sidebar & Navigation
    "color-sidebar-background": "#F4F6F7",
    "color-sidebar-background-border": "#DDE4E7",
    "color-sidebar-brand-text": "#0F1B20",
    "color-sidebar-caption-text": "#4E626A",
    "color-sidebar-link-text": "#4E626A",
    "color-sidebar-link-text--top-level": "#0B5F73",
    "color-sidebar-item-background": "#F4F6F7",
    "color-sidebar-item-background--hover": "#E4E9EC",
    "color-sidebar-item-background--current": "#E4E9EC",
    "color-sidebar-item-expander-background": "transparent",
    "color-sidebar-search-text": "#0F1B20",
    "color-sidebar-search-background": "#FFFFFF",
    "color-sidebar-search-background--focus": "#FFFFFF",
    "color-sidebar-search-border": "#DDE4E7",
    "color-sidebar-search-icon": "#4E626A",
    "color-toc-background": "#FFFFFF",
    "color-toc-title-text": "#5C717A",
    "color-toc-item-text": "#4E626A",
    "color-toc-item-text--hover": "#0F1B20",
    "color-toc-item-text--active": "#0B5F73",
    # Semantic accents
    "color-admonition-title--note": "#0B5F73",
    "color-admonition-title--tip": "#0E7C66",
    "color-admonition-title--important": "#0E7C66",
    "color-admonition-title--warning": "#B4690E",
    "color-admonition-title--caution": "#B4690E",
    "color-admonition-title--attention": "#B4690E",
    "color-admonition-title--danger": "#BE3A34",
    "color-admonition-title--error": "#BE3A34",
    # Decorative custom tokens
    "ducta-accent": "#0B5F73",
    "ducta-accent-light": "rgba(11, 95, 115, 0.08)",
}

# Dark palette (Deep Petrol)
_DARK_PALETTE = {
    "font-stack": _FONT_SANS,
    "font-stack--monospace": _FONT_MONO,
    "color-code-background": "#10191D",
    "color-code-foreground": "#E3EDF1",
    "color-brand-primary": "#38BDF8",
    "color-brand-content": "#38BDF8",
    "color-brand-visited": "#7DD3FC",
    "color-background-primary": "#141F24",
    "color-background-secondary": "#0C1417",
    "color-background-hover": "#1B282E",
    "color-background-border": "#26353B",
    "color-foreground-primary": "#E3EDF1",
    "color-foreground-secondary": "#95A9B1",
    "color-foreground-muted": "#768B94",
    "color-foreground-border": "#374950",
    # Sidebar & Navigation
    "color-sidebar-background": "#0C1417",
    "color-sidebar-background-border": "#26353B",
    "color-sidebar-brand-text": "#E3EDF1",
    "color-sidebar-caption-text": "#95A9B1",
    "color-sidebar-link-text": "#95A9B1",
    "color-sidebar-link-text--top-level": "#38BDF8",
    "color-sidebar-item-background": "#0C1417",
    "color-sidebar-item-background--hover": "#1B282E",
    "color-sidebar-item-background--current": "#1B282E",
    "color-sidebar-item-expander-background": "transparent",
    "color-sidebar-search-text": "#E3EDF1",
    "color-sidebar-search-background": "#141F24",
    "color-sidebar-search-background--focus": "#141F24",
    "color-sidebar-search-border": "#26353B",
    "color-sidebar-search-icon": "#95A9B1",
    "color-toc-background": "#141F24",
    "color-toc-title-text": "#768B94",
    "color-toc-item-text": "#95A9B1",
    "color-toc-item-text--hover": "#E3EDF1",
    "color-toc-item-text--active": "#38BDF8",
    # Semantic accents
    "color-admonition-title--note": "#38BDF8",
    "color-admonition-title--tip": "#34D399",
    "color-admonition-title--important": "#34D399",
    "color-admonition-title--warning": "#FBBF24",
    "color-admonition-title--caution": "#FBBF24",
    "color-admonition-title--attention": "#FBBF24",
    "color-admonition-title--danger": "#F87171",
    "color-admonition-title--error": "#F87171",
    # Decorative custom tokens
    "ducta-accent": "#38BDF8",
    "ducta-accent-light": "rgba(56, 189, 248, 0.1)",
}

pygments_style = "friendly"
pygments_dark_style = "monokai"

html_theme_options = {
    "light_logo": "ducta-logo.svg",
    "dark_logo": "ducta-logo-dark.svg",
    "sidebar_hide_name": True,
    "light_css_variables": _LIGHT_PALETTE,
    "dark_css_variables": _DARK_PALETTE,
    # Edit-source links + GitHub in the footer.
    "source_repository": "https://github.com/faustinolopezramos/ducta/",
    "source_branch": "main",
    "source_directory": "docs/",
    "footer_icons": [
        {
            "name": "GitHub",
            "url": "https://github.com/faustinolopezramos/ducta",
            "html": (
                '<svg stroke="currentColor" fill="currentColor" '
                'stroke-width="0" viewBox="0 0 16 16" width="1em" height="1em">'
                '<path fill-rule="evenodd" d="M8 0C3.58 0 0 3.58 0 8c0 3.54 2.29 '
                "6.53 5.47 7.59.4.07.55-.17.55-.38 0-.19-.01-.82-.01-1.49-2.01."
                "37-2.53-.49-2.69-.94-.09-.23-.48-.94-.82-1.13-.28-.15-.68-.52-"
                ".01-.53.63-.01 1.08.58 1.23.82.72 1.21 1.87.87 2.33.66.07-.52."
                "28-.87.51-1.07-1.78-.2-3.64-.89-3.64-3.95 0-.87.31-1.59.82-2.15"
                "-.08-.2-.36-1.02.08-2.12 0 0 .67-.21 2.2.82.64-.18 1.32-.27 2-."
                "27.68 0 1.36.09 2 .27 1.53-1.04 2.2-.82 2.2-.82.44 1.1.16 1.92.0"
                "8 2.12.51.56.82 1.27.82 2.15 0 3.07-1.87 3.75-3.65 3.95.29.25.5"
                "4.73.54 1.48 0 1.07-.01 1.93-.01 2.2 0 .21.15.46.55.38A8.013 8."
                '013 0 0 0 16 8c0-4.42-3.58-8-8-8z"></path></svg>'
            ),
            "class": "",
        },
    ],
}

# -- Options for autodoc -----------------------------------------------------

add_module_names = False

autodoc_default_options = {
    "members": True,
    "member-order": "bysource",
    "special-members": "__init__",
    "undoc-members": True,
    "exclude-members": "__weakref__",
}

# -- Options for intersphinx -------------------------------------------------

intersphinx_mapping = {
    "python": ("https://docs.python.org/3", None),
    "pandas": ("https://pandas.pydata.org/docs/", None),
    "pyspark": ("https://spark.apache.org/docs/latest/api/python/", None),
}

# -- Options for napoleon ----------------------------------------------------

napoleon_google_docstring = True
napoleon_numpy_docstring = True
napoleon_include_init_with_doc = True
napoleon_include_private_with_doc = False
napoleon_include_special_with_doc = True
napoleon_use_admonition_for_examples = True
napoleon_use_admonition_for_notes = True
napoleon_use_admonition_for_references = True
napoleon_use_ivar = False
napoleon_use_param = True
napoleon_use_rtype = True

# -- Options for MyST --------------------------------------------------------

myst_enable_extensions = [
    "colon_fence",
    "deflist",
    "tasklist",
    "fieldlist",
]

myst_heading_anchors = 3

# -- Options for todo --------------------------------------------------------

todo_include_todos = True
