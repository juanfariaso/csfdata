# Automatic Python API Navigation with MkDocs

This guide explains how to automatically generate one documentation page per
Python module, with a sidebar tree that mirrors the package structure.

It uses three tools:

- [MkDocs](https://www.mkdocs.org/) builds the HTML documentation website.
- [mkdocstrings](https://mkdocstrings.github.io/) renders Python signatures,
  classes, functions, and docstrings.
- [mkdocs-api-autonav](https://github.com/tlambert03/mkdocs-api-autonav)
  discovers Python modules and generates the reference pages and navigation.

## The Goal

Starting with this Python package:

```text
my_library/
  __init__.py
  client.py
  config.py
  models.py
  adapters/
    __init__.py
    example.py
```

Generate this documentation menu automatically:

```text
My Library
  client
  config
  models
  adapters
    example
```

No hand-written Markdown reference file is needed for `client.py`, `config.py`,
or any future module.

## 1. Create and Activate a Virtual Environment

From the root of your Python project:

```bash
python3 -m venv .venv
source .venv/bin/activate
```

Install the documentation tools:

```bash
python -m pip install mkdocs "mkdocstrings[python]" mkdocs-api-autonav
```

## 2. Create Basic Documentation Files

You still need ordinary hand-written pages for introductory and architectural
documentation:

```text
docs/
  index.md
mkdocs.yml
```

For example, create `docs/index.md`:

```md
# My Library

Documentation for my Python project.
```

You do **not** create a `docs/reference/` directory. AutoNav generates those
pages virtually when MkDocs runs.

## 3. Configure MkDocs

Create `mkdocs.yml` in the project root:

```yaml
site_name: My Library

theme:
  name: readthedocs

plugins:
  - search

  - mkdocstrings:
      handlers:
        python:
          paths:
            - .
          options:
            members: true
            show_submodules: false
            show_source: false
            docstring_style: google
            members_order: source

  - api-autonav:
      modules:
        - my_library
      nav_section_title: My Library
      api_root_uri: reference
      nav_item_prefix: ""

nav:
  - Home: index.md
  - My Library
```

Replace `my_library` everywhere with the actual Python package name.

## 4. Understand the Configuration

### `modules`

```yaml
modules:
  - my_library
```

This is the package folder that AutoNav scans. The folder must contain an
`__init__.py` file so Python recognizes it as a package.

### `nav_section_title`

```yaml
nav_section_title: My Library
```

This must match the final plain-text entry in `nav`:

```yaml
nav:
  - Home: index.md
  - My Library
```

AutoNav replaces that placeholder with the generated module tree.

### `api_root_uri`

```yaml
api_root_uri: reference
```

This controls the generated website URL, such as:

```text
http://127.0.0.1:8000/reference/my_library/config/
```

It does not require a real `docs/reference/` folder.

### `members: true`

```yaml
members: true
```

Render functions, classes, and attributes inside each module page.

### `show_submodules: false`

```yaml
show_submodules: false
```

Keep this false. AutoNav creates a separate page for every submodule. Setting
it to true would also render child modules inside their parent page, duplicating
the documentation tree.

### `show_source: false`

```yaml
show_source: false
```

Hide the raw Python source code from the reference page. Set it to true only
when you want readers to see the implementation alongside the documentation.

## 5. Add Docstrings to Your Python Code

AutoNav creates the pages automatically, but the useful content comes from
docstrings in the source code.

At the top of each module:

```python
"""Tools for loading configuration files.

This module validates configuration input. It does not modify configuration
files or perform network operations.
"""
```

For each public function:

```python
def load_config(path: Path) -> Config:
    """Load and validate a configuration file.

    Args:
        path: The configuration file to read.

    Returns:
        The validated configuration.

    Raises:
        ConfigError: If the file cannot be parsed or is invalid.
    """
```

The function signature is displayed automatically. The docstring explains what
the function means, what can fail, and whether it has side effects.

## 6. Preview the Documentation

Run:

```bash
mkdocs serve
```

Open the local address printed in the terminal, usually:

```text
http://127.0.0.1:8000/
```

Edit Python files or docstrings, save, and refresh the browser. AutoNav will
discover new modules at the next documentation build.

## 7. Validate Before Committing

Run:

```bash
mkdocs build --strict
```

This builds the final HTML site and fails on warnings. The generated HTML goes
into `site/`; do not edit or commit that directory.

## What Is Automatic and What Is Manual?

Automatic:

- Discovering Python modules and submodules.
- Creating one API page per module.
- Building the nested sidebar navigation.
- Rendering signatures, type hints, and docstrings.

Manual:

- Writing `docs/index.md` and architecture/design pages.
- Writing useful module, class, and function docstrings.
- Deciding what belongs in the public API.

## Everyday Workflow

When you add `my_library/new_module.py`:

1. Give it a module docstring.
2. Give its public functions and classes docstrings.
3. Run `mkdocs serve`.
4. Find `new_module` automatically in the generated navigation.
5. Run `mkdocs build --strict` before committing.
