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
html_js_files = ["theme.js"]
html_title = "Ducta"
html_favicon = "img/logo.ico"

# ---------------------------------------------------------------------------
# Brand palette — "Lima" theme: lime green pulled from the logo's accent dot
# (#84CC16), paired with the logo's own slate blue-gray.
#
# Light-only: the same palette is applied to both of Furo's color modes so an
# OS-level dark preference cannot repaint the site. The theme toggle is hidden
# in _static/custom.css to match.
#
# The raw lime (#84CC16) is reserved for decorative use (borders, focus
# rings, rules). Text-bearing roles use a darkened shade (#6FAF0F) to clear
# WCAG AA on the light background. Slate tones carry the structural chrome.
# ---------------------------------------------------------------------------

# Typography matches the UI stacks (Inter + JetBrains Mono).
_FONT_SANS = (
    "'Inter', -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif"
)
_FONT_MONO = "'JetBrains Mono', 'Fira Code', 'SFMono-Regular', Menlo, Consolas, monospace"

# Lima: --bg (off-white cálido), --surface (blanco), --text (pizarra oscura del logo).
_BG, _SURFACE, _BORDER, _TEXT = "#F5F3F0", "#FFFFFF", "#E2DDD6", "#1E2936"

_PALETTE = {
    "font-stack": _FONT_SANS,
    "font-stack--monospace": _FONT_MONO,
    "color-code-background": "#F0EDE8",
    "color-code-foreground": _TEXT,
    # Lime darkened to 4.95:1 (brand #84CC16 is ~2.5:1 on white — fails AA).
    "color-brand-primary": "#6FAF0F",
    "color-brand-content": "#6FAF0F",
    "color-brand-visited": "#568A0A",
    # Content on white, chrome on warm off-white.
    "color-background-primary": _SURFACE,
    "color-background-secondary": _BG,
    "color-background-hover": "#EBE7E0",
    "color-background-border": _BORDER,
    "color-foreground-primary": _TEXT,
    "color-foreground-secondary": "#4A5B6E",
    "color-foreground-muted": "#7C8A9C",
    "color-foreground-border": "#D4CEC4",
    # Sidebar & TOC — slate tones from the logo gradient.
    "color-sidebar-background": _BG,
    "color-sidebar-background-border": _BORDER,
    "color-sidebar-brand-text": _TEXT,
    "color-sidebar-caption-text": "#4A5B6E",
    "color-sidebar-link-text": "#4A5B6E",
    "color-sidebar-link-text--top-level": "#6FAF0F",
    "color-sidebar-item-background": _BG,
    "color-sidebar-item-background--hover": "#EBE7E0",
    "color-sidebar-item-background--current": "#EBE7E0",
    "color-sidebar-item-expander-background": "transparent",
    "color-sidebar-search-text": _TEXT,
    "color-sidebar-search-background": _SURFACE,
    "color-sidebar-search-background--focus": _SURFACE,
    "color-sidebar-search-border": _BORDER,
    "color-sidebar-search-icon": "#4A5B6E",
    "color-toc-background": _SURFACE,
    "color-toc-title-text": "#7C8A9C",
    "color-toc-item-text": "#4A5B6E",
    "color-toc-item-text--hover": _TEXT,
    "color-toc-item-text--active": "#6FAF0F",
    # Semantic accents — teal bridges lime and slate; amber for warning.
    "color-admonition-title--note": "#6FAF0F",
    "color-admonition-title--tip": "#0D9488",
    "color-admonition-title--important": "#0D9488",
    "color-admonition-title--warning": "#D97706",
    "color-admonition-title--caution": "#D97706",
    "color-admonition-title--attention": "#D97706",
    "color-admonition-title--danger": "#DC2626",
    "color-admonition-title--error": "#DC2626",
    # Decorative-only brand accent (see custom.css).
    "ducta-accent": "#84CC16",
}

pygments_style = "friendly"
pygments_dark_style = "friendly"

html_theme_options = {
    "light_logo": "ducta-logo.svg",
    "dark_logo": "ducta-logo.svg",
    "sidebar_hide_name": True,
    "light_css_variables": _PALETTE,
    "dark_css_variables": _PALETTE,
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
