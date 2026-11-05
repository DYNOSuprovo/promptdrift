# PromptDrift

[![CI](https://github.com/tanveer-arch/promptdrift/actions/workflows/ci.yml/badge.svg)](https://github.com/tanveer-arch/promptdrift/actions/workflows/ci.yml)
[![PyPI](https://img.shields.io/pypi/v/promptdrift-ci?color=blue)](https://pypi.org/project/promptdrift-ci/)
[![Python](https://img.shields.io/pypi/pyversions/promptdrift-ci)](https://pypi.org/project/promptdrift-ci/)
[![License: MIT](https://img.shields.io/badge/license-MIT-green.svg)](LICENSE)

**Your prompt didn't change. Your tests didn't change. So why did your AI behavior change?**

PromptDrift is a Git-native, privacy-conscious CLI and GitHub Action that detects behavioral regression and model drift. It repeatedly probes your unchanged prompts on a schedule, distinguishing actual contract regressions from harmless wording changes, and gathering evidence before you blame a model update.

## The Core Problem

LLM behavior isn't static. Providers update routing, system prompts, or safety filters silently. Traditional testing only runs when *your code* changes.

| State | Prompt | Config | Behavior | Diagnosis |
| :--- | :--- | :--- | :--- | :--- |
| **Traditional CI** | Changed | Changed | Changed | `prompt_changed` |
| **PromptDrift Monitor** | Same | Same | **Changed** | `observed_model_drift` |

## See It in Action

Try a simulated drift incident locally without an API key or paid provider:

```bash
git clone https://github.com/tanveer-arch/promptdrift.git
cd promptdrift
python -m pip install .
promptdrift demo
```

> **Note:** The demo starts a temporary loopback HTTP fixture, saves a passing baseline, then changes only the fixture's response. It will report `observed_model_drift` after three contract failures. This is a synthetic demonstration, not a real model incident or benchmark.

## 60-Second Quickstart

Install the published release:

```bash
pip install promptdrift-ci
```

Initialize your project and run your first checks:

```bash
promptdrift init --directory my-monitor
cd my-monitor
promptdrift test       # Run tests against your current config
promptdrift baseline   # Save passing tests as the canonical baseline
promptdrift monitor --samples 3 # Probe 3 times to detect drift
promptdrift history    # View the results of your monitoring
```

## Example Configuration

Define your deterministic behavioral contracts in `promptdrift.yaml`.

```yaml
version: 2
provider:
  type: openai
  model: gpt-4.1-mini
  api_key_env: OPENAI_API_KEY
  # base_url: https://your-openai-compatible-endpoint.example/v1

defaults:
  temperature: 0
  max_output_tokens: 300

tests:
  - id: refund-policy
    prompt: prompts/support.txt
    variables:
      question: Can I return my order after ten days?
    assertions:
      - type: contains
        value: 30 days
      - type: not_contains
        value: guaranteed
```

## The Core Differentiator: Check vs. Monitor

PromptDrift provides two distinct workflows:

1. **`check` mode (PRs):** *Did the repository change?* Run this in CI on Pull Requests to ensure your intentional prompt or configuration changes don't break existing contracts.
2. **`monitor` mode (Scheduled):** *Did the behavior change even though the monitored inputs stayed the same?* Schedule this to run repeatedly (e.g., daily) against an idle repository to catch silent provider drift.

## What PromptDrift Detects

PromptDrift uses deterministic heuristics, not statistical guesswork. 

| Observation | Diagnosis |
| --- | --- |
| Monitored inputs match, all repeated probes fail contracts | `observed_model_drift` |
| Some repeated probes pass and others fail contracts | `stochastic_behavior` |
| Rendered prompt, settings, provider, or contracts changed | Explicit `*_changed` |
| Output wording changed, but contracts still pass | `output_changed` |
| Timeout, HTTP error, malformed completion | `provider_error` |
| Old baseline lacks provenance or evidence is insufficient | `insufficient_evidence` |

> **Note:** Provider-reported model IDs and fingerprints are treated as supporting evidence, not proof of a vendor-side model weights change.

## GitHub Actions

Run PromptDrift directly in your CI pipeline.

```yaml
name: Scheduled Monitor
on:
  schedule:
    - cron: '0 9 * * *' # Every day at 9 AM
jobs:
  monitor:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: tanveer-arch/promptdrift/action@main
        with:
          mode: monitor
          samples: 3
          create-issue: 'true' # Deduplicated alerts for drift
        env:
          OPENAI_API_KEY: ${{ secrets.OPENAI_API_KEY }}
```

## Supported Providers

- **OpenAI-Compatible:** Supports the text-response Chat Completions API. Set `base_url` for proxies, local inference, or compatible endpoints.
- **Ollama:** Completely local inference. Runs against the Generate API.
- **Mock:** A deterministic local provider for offline testing and CI onboarding. Echoes prompts back with zero cost or latency.

## Deterministic Assertions

PromptDrift evaluates behavior using strict contracts, not subjective LLM judges.

| Assertion | Behavior |
| --- | --- |
| `exact_match` | Character-for-character identical |
| `contains`, `not_contains` | Substring inclusion or exclusion |
| `regex`, `not_regex` | Regular expression matching |
| `json_valid`, `json_schema` | JSON parseability and structural validation |
| `min_length`, `max_length` | Character count boundaries |
| `max_tokens` | Provider-reported token limit |
| `latency_ms` | Maximum acceptable response time |
| `cost_usd` | Cost threshold (where supported) |

## Privacy & Security

Your data is yours. PromptDrift is designed with strict privacy boundaries:

- **No telemetry or hosted dashboard:** Your probes go directly to your configured provider.
- **Minimized history:** `monitor` JSON and SQLite history explicitly omit raw prompts, responses, and API exceptions to prevent accidental data leaks.
- **Safe credentials:** API keys are never read from configuration files, only from environment variables.
- **Hashes, not encryption:** Baselines use SHA-256 hashes of rendered inputs for comparison. *(Note: Hashes of short strings can be guessed, so repository access control still matters)*.
- **Secure Action design:** The GitHub Action prevents arbitrary execution and never exposes provider secrets to untrusted PR code. Legacy reports can contain raw data but are strictly controlled.

## Architecture

```mermaid
graph TD
    A[promptdrift.yaml Config] --> B(Suite Resolution)
    B --> C(Provider Adapter)
    C --> D[ModelResponse]
    D --> E(Assertions + Evidence)
    E --> F{Baseline Comparison}
    F --> G[Diagnosis]
    G --> H[CLI / GitHub Action / History]
```

## The Capture Workflow

Beyond static testing, PromptDrift can learn from real traffic:
1. **`capture`**: Record real or simulated interactions into local storage.
2. **`learn`**: Turn captured interactions into candidate regression scenarios.
3. **`suggest`**: Generate deterministic behavioral contracts for a scenario.
4. **`promote`**: Move candidate scenarios into your committed regression test suite.

## Is PromptDrift for you?

**Who it is for:**
- AI application developers.
- Teams consuming LLM APIs in production.
- GitHub-centric engineering teams.
- Developers running local models with Ollama.
- Projects needing strict, deterministic behavioral contracts.

**Who it is NOT for:**
- Not a general-purpose evaluator marketplace.
- Not a hosted observability dashboard.
- Not a statistical guarantee of model-weight changes.
- Not an automatic baseline approval system.

## Technologies Used

PromptDrift is built with modern, lightweight Python tooling designed for speed, type safety, and minimal dependencies:

- **Core Runtime & CLI:** [Python 3.11+](https://www.python.org/) and [Typer](https://typer.tiangolo.com/) for ergonomic, type-hinted command-line interfaces.
- **Data Validation & Schemas:** [Pydantic v2](https://docs.pydantic.dev/) (with strict `extra="forbid"` models) and [JSON Schema](https://json-schema.org/) for deterministic assertion validation.
- **Templating & Formats:** [Jinja2](https://palletsprojects.com/p/jinja/) for variable-interpolated prompt rendering, and [PyYAML](https://pyyaml.org/) for configuration parsing.
- **Terminal UI & Diagnostics:** [Rich](https://rich.readthedocs.io/) for formatted tables, progress displays, and diff reporting.
- **Local History Storage:** SQLite (`sqlite3` from Python's standard library) for privacy-minimized, zero-external-dependency local run tracking.
- **HTTP & Providers:** [HTTPX](https://www.python-httpx.org/) for provider client communication and network-isolated fixtures.
- **Packaging & Quality:** [Hatchling](https://hatch.pypa.io/) for standards-compliant builds, [Pytest](https://docs.pytest.org/) & [pytest-cov](https://pytest-cov.readthedocs.io/) for offline test suites, and [Ruff](https://docs.astral.sh/ruff/) for ultra-fast linting and formatting.

## Winter of Code Social (WoCS) 2026

PromptDrift is an official mentoring organization for **Winter of Code Social (WoCS) 2026**! We warmly welcome student and first-time open-source contributors.

### Where to Find Available Issues

All contributor tasks are tracked on GitHub Issues and tagged with the following labels:
- **`wocs`**: All issues approved and open for WoCS 2026 participants.
- **`level 1`**: Small, beginner-friendly tasks (documentation, simple assertions, isolated regex patterns, CLI smoke tests).
- **`level 2`**: Moderate implementation tasks (new reporting formats, tolerance evaluations, provider error handling, streaming wrappers).
- **`level 3`**: Substantial / complex features (new provider adapters, historical observation promotion, request-envelope provenance hashing, bounded resilience backoff).

Browse our [open WoCS issues](https://github.com/tanveer-arch/promptdrift/issues?q=is%3Aissue+is%3Aopen+label%3Awocs).

### How to Get Started

1. **Read the guides:** Review this README and read [CONTRIBUTING.md](CONTRIBUTING.md) thoroughly before beginning.
2. **Claim an issue:** Do **not** submit unassigned PRs. Comment on an open issue requesting assignment, wait for a Project Admin or Mentor to assign it to you, and work on only one issue at a time.
3. **Follow the AI Policy:** Ensure all contributions adhere to our project AI policy detailed below.

## AI Policy

> **AI allowed with restrictions:** Contributors may use AI tools (e.g. GitHub Copilot, ChatGPT, Claude) for research, ideation, drafting, or debugging. However, **all submitted code, tests, and documentation must be fully understood, verified, and tested by the author**. Pure copy-paste AI code, hallucinated dependencies, and unreviewed auto-generated pull requests are strictly prohibited and will be rejected. Contributors are expected to explain and defend every design decision in their PR review.

## Local Installation & Development Setup

To contribute or test changes locally, set up a development environment:

### Prerequisites

- Python 3.11 or higher
- Git
- (Optional) Node.js 22+ (only required if developing the GitHub Action runner in `action/`)

### Setup Instructions

1. **Fork and clone the repository:**
   ```bash
   git clone https://github.com/<your-username>/promptdrift.git
   cd promptdrift
   ```

2. **Create and activate a virtual environment:**
   ```bash
   # On macOS/Linux:
   python3 -m venv .venv
   source .venv/bin/activate

   # On Windows (PowerShell):
   python -m venv .venv
   .venv\Scripts\Activate.ps1
   ```

3. **Install editable package with development dependencies:**
   ```bash
   pip install -e ".[dev]"
   ```

4. **Verify your local setup:**
   ```bash
   python -m pytest
   ruff check src tests action
   ruff format --check src tests action
   ```

All unit tests run completely offline and use local mock fixtures—no external API keys or network connection required!

## Contributing

We welcome contributions from everyone! The PromptDrift engine, providers, and evaluators are intentionally decoupled to make adding features straightforward and safe.

- **Contribution Guide:** Please read [CONTRIBUTING.md](CONTRIBUTING.md) for full step-by-step instructions on claiming issues, code conventions, test isolation, and opening pull requests.
- **Roadmap Candidates:** Check out [docs/roadmap.md](docs/roadmap.md) for planned architectural milestones.

## Documentation

- [Getting Started](docs/getting-started.md)
- [Monitoring](docs/monitoring.md)
- [Configuration](docs/configuration.md)
- [Baselines](docs/baselines.md)
- [Providers](docs/providers.md)
- [Assertions](docs/assertions.md)
- [Architecture](docs/architecture.md)
- [Competitive Landscape](docs/competitive-landscape.md)

## License

PromptDrift is released under the [MIT License](LICENSE).
