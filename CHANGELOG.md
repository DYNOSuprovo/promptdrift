# Changelog

All notable changes to PromptDrift are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased] — 0.4.0

### Added
- `monitor`: fresh full-suite repeated probes independent of Git changes, with evidence-based diagnoses and explicit provider-error handling.
- Provider error taxonomy (`ProviderAuthError`, `ProviderRateLimitError`, `ProviderTimeoutError`, `ProviderConnectionError`, `ProviderResponseError`) normalizing provider exceptions into safe, non-secret diagnostic categories (#14).
- Schema-v3 baselines with per-case request, generation, provider and contract fingerprints; v1/v2 loading remains supported without invented provenance.
- `history`: bounded project-local monitoring history; `demo`: a temporary loopback-only synthetic drift incident through the real adapter.
- Opt-in Action monitor mode and deduplicated scheduled/manual GitHub failure issues; synthetic and real-provider monitoring examples.
- Source-linked ecosystem comparison and documented attribution/privacy limits.
- Optional per-test `request_envelope` (system message, tool schemas, static retrieval context) with credential-stripped, per-component provenance hashes; monitoring evidence names the drifted component.

### Fixed
- Isolated tests from the real home directory and working tree.
- Corrupt baselines and empty suites no longer become silent green checks; baseline creation preflights overwrite protection and refuses failed contracts without explicit approval.
- Unified YAML/promoted-scenario suite resolution; acceptance always evaluates the full suite. Conservative Git filtering no longer skips cases when configuration/code paths also change.
- Atomic canonical baseline replacement and project-relative archives.
- Unknown cost/token usage no longer passes as zero or a word-count estimate; invalid numeric/regex/schema contracts fail early. Remote JSON schema retrieval is disabled.
- `output.format: json` now enforces JSON validity. Unsupported semantic/CI policy customization is rejected instead of silently ignored.
- Malformed provider payloads become safe provider errors. Legacy suppressed history also removes evaluation payloads and potentially sensitive reasons.
- Action shell/input handling, nested working-directory reports, failure artifact preservation and JSON validation.

### Development
- Expanded offline engine/CLI and Action behavior tests, formatter/build/wheel smoke checks, single-source package version and explicit sdist contents.
- Monitoring remains heuristic, not statistically calibrated; semantic embeddings/LLM judges are not usable suite features. Earlier changelog wording about semantic support described scaffolding, not a working evaluator integration.

## [0.3.1] - 2026-09-26

### Fixed
- Fixed release deployment script and CI artifacts.

## [0.3.0] - 2026-09-23

### Added
- **Production AI Interactions Capture:** `CaptureRecorder` API to capture production traffic with deduplication, redact rules, and sampling strategies.
- **OpenAI Integration Wrapper:** Optional, dependency-free wrapper for `openai` sync/async clients that seamlessly logs interactions to the capture store without crashing the host app.
- **Selective Acceptance Engine:** Human approval workflow allowing granular updates (`--changed`, `--scenario`, `--accept-regressions`) while enforcing strict promotion rules.
- **Git Revision Hashing for Baselines:** Baseline schemas (v2) now include git SHA and prompt hash to link traffic definitively to a code state.
- **Baseline History:** Archiving previous baselines automatically before updates.
- **Enhanced Impact Reporting:** Added Git revision references in `ImpactRadiusReport` and `RegressionReport` HTML output.

## [0.2.0] - 2026-09-19

### Added

- **Impact Radius:** Measure the exact blast radius of prompt changes using Git-aware selective execution (`check --base`).
- **Capture & Learn:** Automatically log example interactions and cluster them into candidate scenarios (`capture`, `learn`).
- **Assertion Suggestions:** Automatically generate deterministic contracts from captured interaction traces (`suggest`).
- **Scenario Management:** Local Git-tracked library (`.promptdrift/scenarios.json`) for promoting scenarios to the active regression suite (`scenarios`, `promote`).
- **Semantic Evaluators:** Support for basic `semantic_similarity` and a protocol for custom evaluation plugins.
- **Enhanced Action:** GitHub Action now natively supports Impact Radius reporting and intelligent PR commenting.
- **Safe baselines:** `accept` now prompts for confirmation before overwriting baselines.

## [0.1.0] - 2026-08-20

### Added

- **CLI commands:** `init`, `test`, `baseline`, `diff`, `report`, `doctor`, `version`.
- **Providers:** OpenAI (Chat Completions), Ollama (local inference), and Mock (deterministic offline).
- **Deterministic assertions:** `exact_match`, `contains`, `not_contains`, `regex`, `not_regex`, `json_valid`, `json_schema`, `min_length`, `max_length`, `max_tokens`, `latency_ms`, `cost_usd`.
- **Baseline system:** SHA-256 output hashing, metrics tracking, and regression comparison without raw output storage.
- **Performance thresholds:** `latency_ms` and `cost_usd` with configurable warn/fail levels.
- **Reports:** Rich terminal tables, offline HTML, GitHub Step Summary, and PR comment markdown.
- **GitHub Action:** Composite action with Step Summary, JSON artifact upload, and optional PR commenting.
- **CI workflows:** Automated testing with pytest + ruff on push and pull request.
- **Release workflow:** Trusted PyPI publishing via GitHub OIDC — no stored tokens.
- **Template engine:** Jinja2 sandboxed rendering with strict undefined variable detection.
- **Local history:** Optional SQLite run storage with raw output suppression by default.
- **Privacy:** No telemetry, no hosted service, API keys from environment only.
- **Examples:** Customer support, structured JSON, and summarization use cases.
- **Documentation:** Getting started, configuration reference, assertions guide, providers, baselines, GitHub Action, architecture, and FAQ.
