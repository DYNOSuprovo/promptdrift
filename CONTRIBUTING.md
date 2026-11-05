# Contributing to PromptDrift

Welcome to the PromptDrift contributor community! Whether you are participating through **Winter of Code Social (WoCS) 2026** or contributing as an independent open-source developer, we are thrilled to have your help.

This guide provides a comprehensive, step-by-step walkthrough designed for first-time open-source contributors. No prior open-source experience is assumed!

---

## Table of Contents

1. [Winter of Code Social (WoCS) 2026](#winter-of-code-social-wocs-2026)
2. [Project AI Policy](#project-ai-policy)
3. [How to Claim an Issue](#how-to-claim-an-issue)
4. [Prerequisites & Requirements](#prerequisites--requirements)
5. [Local Development Setup](#local-development-setup)
6. [Project Structure](#project-structure)
7. [Coding Standards & Project Conventions](#coding-standards--project-conventions)
8. [Running Tests & Linting](#running-tests--linting)
9. [Submitting a Pull Request](#submitting-a-pull-request)
10. [Review Process & Expectations](#review-process--expectations)
11. [Community & Getting Help](#community--getting-help)

---

## Winter of Code Social (WoCS) 2026

PromptDrift is participating in **WoCS 2026**! WoCS contributors can easily discover mentor-approved tasks using GitHub issue labels.

### Issue Difficulty Levels

Every WoCS task is tagged with the `wocs` label plus exactly one difficulty level:

- **`level 1` (Beginner-Friendly / Small):**
  - Self-contained, isolated changes.
  - Examples: Adding new deterministic string assertions (e.g. `starts_with`), expanding regex PII redaction patterns, improving terminal failure diff output, or writing cross-platform smoke tests.
- **`level 2` (Intermediate / Moderate Implementation):**
  - Changes across multiple files or modules.
  - Examples: Implementing JUnit XML report export, adding assertion tolerance thresholds, wrapping streaming responses in client adapters, or expanding SQLite history retention.
- **`level 3` (Advanced / Substantial Architecture):**
  - Substantial features affecting core engine, provider interfaces, or cryptographic provenance.
  - Examples: Implementing a full Anthropic Claude provider adapter with offline fixtures, creating a reviewed observation promotion workflow (`accept --run-id`), designing request-envelope provenance hashing, or building bounded provider retry resilience.

---

## Project AI Policy

> ### ⚠️ AI Policy: AI Allowed with Restrictions
>
> Contributors are permitted to use AI tools (such as GitHub Copilot, ChatGPT, or Claude) for research, learning, drafting initial ideas, and debugging assistance.
>
> However, the following rules are strictly enforced:
> - **Full Comprehension Required:** You must thoroughly understand every line of code, docstring, and test you submit. During PR review, mentors may ask you to explain your implementation choices.
> - **No Blind Copy-Pasting:** Verbatim copying from AI models without verification is prohibited. Submissions with hallucinated APIs, nonexistent dependencies, or fabricated parameters will be closed.
> - **No Fully Automated PRs:** Do not submit unreviewed, bot-generated pull requests or AI-generated issue comments.
> - **All Tests Must Pass Locally:** AI-suggested code must be accompanied by comprehensive, deterministic unit tests verified locally using `pytest`.

---

## How to Claim an Issue

To ensure smooth collaboration and prevent duplicate effort:

1. **Browse Available Issues:** Visit [Open Issues tagged with `wocs`](https://github.com/tanveer-arch/promptdrift/issues?q=is%3Aissue+is%3Aopen+label%3Awocs).
2. **Check Assignment:** Ensure the issue is not already assigned to another contributor and does not have an active pull request linked to it.
3. **Leave a Claim Comment:** Post a comment on the issue stating:
   - Your interest in working on the task.
   - A brief (1-3 sentence) summary of your proposed approach or starting points.
4. **Wait for Official Assignment:** Please wait for a Project Admin or Mentor to assign the issue to you before you start writing code and open a pull request.
5. **One Issue at a Time:** Contributors may only claim **one issue at a time**. Once your PR is reviewed and merged, you are welcome to claim another.
6. **Grace Period & Reassignment:** If an assigned issue receives no updates or draft PR within 5 days, it may be unassigned and reopened for other contributors.

---

## Prerequisites & Requirements

Before starting, make sure you have the following installed on your computer:

- **Python:** Version **3.11, 3.12, or 3.13**. Check with `python --version` (or `python3 --version`).
- **Git:** Version 2.25+. Check with `git --version`.
- **Node.js (Optional):** Version 22+. Only required if you are modifying the GitHub Action JavaScript bundle in `action/`.

---

## Local Development Setup

Follow these steps to set up PromptDrift on your local machine:

### 1. Fork the Repository

Click the **Fork** button at the top-right of the [promptdrift repository](https://github.com/tanveer-arch/promptdrift) to create a copy under your GitHub account.

### 2. Clone Your Fork

Clone your newly forked repository locally:

```bash
git clone https://github.com/<your-username>/promptdrift.git
cd promptdrift
```

Add the original repository as an upstream remote:

```bash
git remote add upstream https://github.com/tanveer-arch/promptdrift.git
git fetch upstream
```

### 3. Create a Virtual Environment

Always work inside an isolated Python virtual environment:

```bash
# On macOS / Linux:
python3 -m venv .venv
source .venv/bin/activate

# On Windows (Command Prompt):
python -m venv .venv
.venv\Scripts\activate.bat

# On Windows (PowerShell):
python -m venv .venv
.venv\Scripts\Activate.ps1
```

### 4. Install Editable Package with Development Dependencies

Install PromptDrift in editable mode along with development dependencies (`pytest`, `ruff`, `build`, etc.):

```bash
pip install -e ".[dev]"
```

### 5. Verify Your Setup

Verify that everything is working properly:

```bash
# Run the test suite
python -m pytest

# Run the linter and formatter check
ruff check src tests action
ruff format --check src tests action
```

All existing tests should pass!

---

## Project Structure

Here is a quick overview of how the codebase is organized:

```
promptdrift/
├── action/                     # GitHub Action runner and packaging scripts
├── docs/                       # Architectural and user-facing documentation
├── src/promptdrift/            # Main Python source package
│   ├── capture/                # Live traffic recording and PII redaction
│   ├── engine/                 # Test execution, baseline evaluation, regression logic
│   ├── evaluators/             # Pure deterministic assertion evaluators
│   ├── integrations/           # Client wrappers (e.g. OpenAI SDK capture hook)
│   ├── models/                 # Pydantic v2 data models (strict schema validation)
│   ├── providers/              # Model adapters (OpenAI, Ollama, Mock)
│   ├── reports/                # Terminal, Markdown, HTML, and JUnit formatters
│   ├── storage/                # SQLite local monitoring history
│   ├── cli.py                  # Typer command-line interface entry points
│   ├── config.py               # YAML configuration loader
│   ├── errors.py               # Standardized exception hierarchy
│   └── templates.py            # Jinja2 prompt rendering utilities
├── tests/                      # Automated test suite
│   ├── fixtures/               # Offline JSON payloads and mock responses
│   ├── integration/            # End-to-end CLI workflow tests
│   └── unit/                   # Fast, isolated unit tests
├── pyproject.toml              # Build system, dependencies, and tool settings
├── README.md                   # Project overview and quickstart
└── CONTRIBUTING.md             # Contributor guidelines (this file)
```

---

## Coding Standards & Project Conventions

PromptDrift maintains high standards for reliability, deterministic testing, and privacy. Please adhere to these core rules:

### 1. Code Style with Ruff

We use [Ruff](https://docs.astral.sh/ruff/) to enforce clean, consistent Python style.

- **Line Length:** 100 characters max.
- **Python Version Target:** 3.11+.
- **Format Code:** Automatically format your changes before committing:
  ```bash
  ruff format src tests action
  ruff check --fix src tests action
  ```

### 2. Strict Pydantic Data Models

All models in `src/promptdrift/models/` must use strict configuration:
```python
from pydantic import BaseModel, ConfigDict


class ExampleModel(BaseModel):
    model_config = ConfigDict(extra="forbid")
    ...
```
`extra="forbid"` prevents silent field drops or typos in user configuration files.

### 3. Assertion Evaluators Are Pure Functions

Evaluators in `src/promptdrift/evaluators/` must be pure functions:
- They accept an `Assertion` definition and a `ModelResponse`.
- They return an `EvaluationResult`.
- They must have zero side effects and make no network calls.

### 4. Decoupled Provider Adapters

- Providers in `src/promptdrift/providers/` inherit from the `Provider` abstract base class.
- Providers must not import engine internals.
- A new provider consists of one adapter file and its registration in `src/promptdrift/models/config.py`.

### 5. Privacy & Credential Safety (Crucial!)

- **No Secret Leakage:** Never print, log, or store API keys, tokens, or raw authorization headers in reports, error messages, or SQLite databases.
- **No Raw Content in Monitor Storage:** SQLite history deliberately excludes raw prompts and outputs to prevent accidental data leakage.

### 6. Completely Offline Tests

- **Never make live network calls in unit tests:** All tests must run offline using mock fixtures located in `tests/fixtures/`.
- Use `tmp_path` (pytest fixture) for any filesystem testing so no test files pollute the repository checkout.

---

## Running Tests & Linting

Always verify your changes locally before submitting a pull request:

```bash
# 1. Run all unit and integration tests
pytest

# 2. Run a specific test file
pytest tests/unit/test_evaluators.py

# 3. Run tests matching a keyword
pytest -k "starts_with"

# 4. Check test coverage
pytest --cov=promptdrift --cov-report=term-missing

# 5. Check linting and formatting
ruff check src tests action
ruff format --check src tests action

# 6. Verify package build (optional but recommended)
python -m build
```

---

## Submitting a Pull Request

Once your code is written and all tests pass, follow these steps to open a PR:

### 1. Create a Descriptive Branch

Create a new branch from `main`:

```bash
git checkout main
git pull upstream main
git checkout -b feat/add-starts-with-assertion
```

Use conventional branch prefixes:
- `feat/` for new features or capabilities
- `fix/` for bug fixes
- `docs/` for documentation updates
- `test/` for adding or improving test coverage

### 2. Commit Your Changes

Write concise, clear commit messages following Conventional Commits:

```bash
git add .
git commit -m "feat: add starts_with and ends_with deterministic assertions"
```

Common prefixes: `feat:`, `fix:`, `docs:`, `test:`, `refactor:`, `chore:`.

### 3. Push to Your Fork

Push your feature branch to your GitHub fork:

```bash
git push -u origin feat/add-starts-with-assertion
```

### 4. Open the Pull Request

1. Go to your fork on GitHub.
2. Click the green **Compare & pull request** button.
3. Set the base repository to `tanveer-arch/promptdrift` and the base branch to `main`.
4. Give your PR a clear, descriptive title (e.g. `feat: add starts_with and ends_with deterministic assertions`).
5. Fill out the pull request template completely:
   - Provide a concise summary of what was changed and why.
   - Reference the issue you were assigned using `Closes #XX` or `Fixes #XX`.
   - Complete the checklist (tests added, ruff passed, documentation updated).
6. Click **Create pull request**.

---

## Review Process & Expectations

- **Continuous Integration (CI):** Once opened, GitHub Actions will automatically run the test suite and Ruff linter across Python 3.11, 3.12, and 3.13 on Ubuntu and Windows.
- **Maintainer Review:** A Project Admin or Mentor will review your code, provide constructive feedback, or request small adjustments.
- **Making Revisions:** If changes are requested, simply make the adjustments locally on your branch, commit, and push again. The pull request will update automatically.
- **Celebrate:** Once approved and all CI checks pass, your pull request will be merged! 🎉

---

## Community & Getting Help

- **Have Questions about an Issue?** Ask directly in a comment on the respective GitHub issue.
- **General Discussion & Ideas:** Join our [GitHub Discussions](https://github.com/tanveer-arch/promptdrift/discussions).
- **WoCS Community Chat:** Join the official Winter of Code Social Discord server and head to the `#promptdrift` forum channel to chat with mentors and fellow contributors.
- **Code of Conduct:** Please treat all community members with kindness and respect in accordance with our [Code of Conduct](CODE_OF_CONDUCT.md).

Thank you for contributing to PromptDrift! Happy coding! 🚀
