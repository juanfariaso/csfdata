# Automatic Python Documentation with MkDocs

This guide continues after the basic MkDocs tutorial. It explains how to turn
Python modules, functions, signatures, and docstrings into HTML reference pages
automatically.

## What Is Automatic Documentation?

Suppose you have this Python file:

```text
my_project/
  calculator.py
```

Inside it is a function:

```python
def add(first: int, second: int) -> int:
    """Add two integers.

    Args:
        first: The first integer.
        second: The second integer.

    Returns:
        The sum of both integers.
    """
    return first + second
```

Normally, you would have to copy the function description into a separate
documentation page. Automatic documentation avoids that duplication.

It reads the source code and produces an HTML page showing:

- The module name.
- The function name.
- The full signature: `add(first: int, second: int) -> int`.
- The docstring description.
- Argument, return-value, and error information.

The source code remains the single source of truth.

## The Tool: mkdocstrings

[mkdocstrings](https://mkdocstrings.github.io/) is a MkDocs plugin that reads
source code and injects generated reference documentation into Markdown pages.

Install it in the same virtual environment as MkDocs:

```bash
source .venv/bin/activate
python -m pip install "mkdocstrings[python]"
```

The `[python]` part installs the Python-specific support.

## Configure MkDocs

Open `mkdocs.yml`. Add `mkdocstrings` to the `plugins` section:

```yaml
site_name: My Documentation

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
            docstring_style: google
            members_order: source
            show_source: true
```

What the options mean:

- `paths: [.]` tells the plugin to search for Python modules in the current
  project folder.
- `docstring_style: google` tells it how to read `Args`, `Returns`, and
  `Raises` sections in docstrings.
- `members_order: source` keeps functions in the same order as the Python file.
- `show_source: true` adds a link or view of the source code in the HTML site.

## Create a Reference Page

Create a Markdown file named `docs/reference/calculator.md`:

```md
# Calculator Reference

::: my_project.calculator
    options:
      members: true
```

The line beginning with `:::` is the important part. It means:

> Find the Python module `my_project.calculator` and insert its documentation
> into this page.

For this to work, this must be a valid Python package layout:

```text
my_project/
  __init__.py
  calculator.py
```

The `__init__.py` file may be empty. Its presence tells Python that
`my_project` is a package.

## Add the Page to the Website Menu

Add the reference page to `mkdocs.yml`:

```yaml
nav:
  - Home: index.md
  - Reference:
      - Calculator: reference/calculator.md
```

## Preview It

Run the local documentation server:

```bash
mkdocs serve
```

Open the local address printed in the terminal, usually:

```text
http://127.0.0.1:8000/
```

Open the **Reference** page. You should see the `add` function with its
signature and documentation.

## Write Useful Docstrings

The signature already explains types and names. The docstring should explain
meaning, errors, and side effects.

Use this template for public functions:

```python
def function_name(argument: str) -> bool:
    """One-sentence summary of what the function does.

    Longer explanation when necessary.

    Args:
        argument: What this input means.

    Returns:
        What the returned value means.

    Raises:
        ValueError: When an input is invalid.

    Side Effects:
        Describe file reads, file writes, network calls, or state changes.
    """
```

Not every function needs every section. A small pure helper may need only a
one-line description:

```python
def is_even(number: int) -> bool:
    """Return whether a number is divisible by two."""
```

## Document Modules Too

Put a docstring at the very top of every Python file:

```python
"""Functions for reading calculator input.

This module validates input. It does not perform calculations or write files.
"""
```

For a serious project, module docstrings are useful architecture documentation.
They answer:

- What does this module own?
- What should not be added here?
- What other modules may it depend on?

## One Page per Module

As a project grows, make one small Markdown page per important module:

```text
docs/
  reference/
    calculator.md
    input.md
    reports.md
```

Each page can be only three lines long:

```md
# Input Reference

::: my_project.input
```

Mkdocstrings generates the detailed content during the build.

## Check the Documentation

Before committing, run:

```bash
mkdocs build --strict
```

This creates the final HTML site and turns warnings into errors. If the command
succeeds, your documentation can be generated cleanly.

## Everyday Workflow

When adding a public Python function:

1. Write the type signature.
2. Write the docstring directly below the function definition.
3. Save the Python file.
4. Check the automatically updated reference page with `mkdocs serve`.
5. Run `mkdocs build --strict` before committing.

You document each function once, in its source file. MkDocs generates the HTML
reference from that source automatically.
