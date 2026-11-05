# Architecture

PromptDrift follows a layered, modular architecture designed for local-first execution, Git-native CI workflows, and zero-telemetry privacy.

## Data Flow

```
Traffic / Interaction ───▶ Capture Ingestion ───▶ Discovery (`learn`) ───▶ Scenario Library (.promptdrift/scenarios.json)
                                                                                   │
                                                                                   ▼
promptdrift.yaml ───────▶ Config Loader ──────────────────────────────────▶ Runner Engine
                                                                                   │
                                                                           Provider Adapter (OpenAI/Ollama/Mock)
                                                                                   │
                                                                             ModelResponse
                                                                                   │
                                                                           Deterministic Contract Evaluators
                                                                                   │
                                                                                   ▼
                                                                           RegressionReport
                                                                                   │
                                           Git Context (diff/base) ───────────────┼─────────────── Baseline Store (v1/v2/v3)
                                                                                   │
                                                                                   ▼
                                                                        Impact Radius Engine
                                                                                   │
                                                                    ┌──────────────┼──────────────┐
                                                                    ▼              ▼              ▼
                                                               Terminal CLI   JSON / HTML   GitHub Step Summary / PR Comment
```

## Module Responsibilities

### `git.py` — Git Context & Diffing
Discovers git repository root, detects current branch and commit SHA, and identifies modified prompt templates relative to Git base refs (e.g. `origin/main` vs `HEAD`).

### `models/` — Data Contracts
- **`config.py`** — Validates `promptdrift.yaml` supporting `version: 1` and `version: 2`.
- **`capture.py`** — `Interaction`, `Scenario`, and `ScenarioLibrary`.
- **`baseline.py`** — Canonical schema v3 with optional per-case provenance and backward-compatible v1/v2 loading.
- **`provenance.py`**, **`monitor.py`** — Typed evidence fingerprints and versioned privacy-minimized monitoring reports.
- **`result.py`** — `ModelResponse`, `EvaluationResult`, `TestRun`, and `RegressionReport`.

### `engine/` — Core Execution & Analysis
- **`runner.py`** — Renders templates, calls providers, evaluates contracts, and aggregates runs.
- **`capture.py`** — Sanitizes and records local interactions for future learning.
- **`discovery.py`** — Deterministically clusters raw interactions into candidate scenarios (`promptdrift learn`).
- **`suggest.py`** — Automatically derives contract suggestions (JSON validity, schema, length bounds, policy rules).
- **`check.py`** — Orchestrates conservative Git-aware selective test execution and computes impact radius. Unknown changed paths cause full-suite execution.
- **`suite.py`** — Resolves YAML cases and promoted scenarios consistently across commands; rejects empty suites.
- **`provenance.py`** — Canonical per-case request/settings/provider/contract fingerprints, plus credential-stripped per-component hashes of an optional declared request envelope (system message, tool schemas, static retrieval context).
- **`monitor.py`** — Fresh full-suite repeated probes; conservative evidence-based triage independent of Git changes. Uses the same contracts as the ordinary runner, not a separate evaluator framework.

### `impact.py` — Impact Radius & Classification
Categorizes before/after behavioral deltas into `REGRESSED`, `IMPROVED`, `UNCHANGED`, `CHANGED_BUT_VALID`, `NEW`, and `MISSING`. Computes aggregate latency and cost deltas.

### `storage/` — Local State
- **`sqlite.py`** — Local SQLite storage for interaction logs and run history (never committed to Git).
- **`scenarios.py`** — Versioned JSON scenario store (`.promptdrift/scenarios.json`).
- **`history.py`** — Project-local monitoring history, 1,000 privacy-minimized reports; independent of accepted baselines.

### `reports/` — Output Formatters
- **`terminal.py`** & **`impact_report.py`** — Rich CLI tables and impact summaries.
- **`github.py`** — Markdown formatted for GitHub Action Step Summaries and deduplicating PR comments.
- **`html.py`** — Standalone, offline HTML report (contains raw evaluated data).
- **`monitor.py`** — Terminal summary without raw provider payloads.

## Monitoring path

`CLI monitor → validated baseline + resolve_suite → render all prompts → per-case fingerprints → repeated provider calls → shared deterministic contracts → conservative diagnosis → MonitorReport → local history / JSON / Action artifact`

The engine owns diagnosis; adapters only normalize responses and optional provider metadata. Transport failures never become model-drift evidence. `action/run.py` preserves the CLI's result while normalizing and redacting artifacts before failure enforcement; `action/publish.cjs` handles opt-in GitHub publication independently.

See [monitoring](monitoring.md) for attribution limits. In particular, hashes do not attest to application code or live tool/retrieval state (a request envelope records only what the test case declares), and no statistical significance or semantic-judge capability is claimed.
