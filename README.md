# pyproject-lens

**Run one command. Get the useful stuff first.**

`pyproject-lens` is a small, free health scanner for Python projects. Give it a folder and it looks for the easy-to-miss things that slowly turn into annoying bugs: a dependency you forgot to declare, a Python version claim that is too old, an `.env` file that is not ignored, a project with no tests, or a package that is hard to install.

It is made for that first ten seconds when you open a project and think: *is this thing okay, or is it hiding problems?*

```bash
pip install pyproject-lens
pyproject-lens .
```

No account. No config maze. No files are changed. No code is uploaded anywhere.

## What you get

The normal report is short and practical:

```text
DEPENDENCIES  90/100
  WARNING: 'requests' is imported but not declared.
    Try: Add it to project.dependencies if it is a runtime dependency.

PROJECT HEALTH: 82/100  |  3 warning(s)
```

When it can, it points to the file and line too:

```text
WARNING (src/app.py:12): 'requests' is imported but not declared.
```

The score is not a grade. It is a quick, predictable summary: every section starts at 100, the scanner deducts points only for checks it found, and the final health score is the average. The exact simple rules live in `src/pyproject_lens/analyzers.py`.

## Install

```bash
pip install pyproject-lens
```

Python 3.9 or newer is supported.

## Use it

Scan the current project:

```bash
pyproject-lens .
```

Scan another folder:

```bash
pyproject-lens ./my-project
```

Save reports for CI, a code review, or later:

```bash
pyproject-lens . --json report.json
pyproject-lens . --markdown report.md
pyproject-lens . --html report.html
```

The HTML report is one standalone file. Open it in a browser or attach it to a project review.

### CI mode

Fail a job when the score is too low:

```bash
pyproject-lens . --ci --minimum-score 75
```

Or keep the threshold in `pyproject.toml`:

```toml
[tool.pyproject-lens]
minimum_score = 75
```

Then use:

```bash
pyproject-lens . --ci
```

## What it checks

- **Packaging** — `pyproject.toml`, project name, supported Python version, and README basics.
- **Dependencies** — imports compared with `project.dependencies`, including common aliases such as `yaml` / `PyYAML`, `PIL` / `Pillow`, and `sklearn` / `scikit-learn`.
- **Python compatibility** — catches `match` / `case` code in projects that claim Python below 3.10.
- **Project structure** — `src/` layouts, packages, a crowded project root, and whether tests exist.
- **Testing** — test-file evidence without pretending it can prove coverage.
- **Security basics** — possible hard-coded secrets, `eval`, `exec`, `shell=True`, and `.env` files not clearly ignored.
- **Documentation** — README, install and usage hints, license, and contribution guide.
- **Git hygiene** — `.gitignore` and uncommitted changes when the folder is a Git repository.

This tool does not replace Ruff, pytest, Bandit, a dependency vulnerability scanner, or a human review. It is the friendly first pass before those tools.

## Python API

Use the same scanner from your own script:

```python
from pyproject_lens import analyze

report = analyze("./my-project")
print(report.score)
print(report.to_json())
report.to_html("report.html")
```

## Why it is free

This project is MIT licensed and open source. All current features are free. The goal is to make a tool developers can run on any project without signing up for anything.

## Development

```bash
python -m pip install -e .
python -m unittest discover -s tests
python -m build
```

Contributions are welcome. Keep checks useful, keep messages honest, and add a small test when fixing a bug.
