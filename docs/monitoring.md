# Monitoring unchanged inputs

Available in the unreleased 0.4 development checkout. Monitoring does not depend on Git changes, and is separate from PR impact analysis.

## The loop

1. Author representative, non-sensitive cases with deterministic behavioral contracts.
2. Run `promptdrift test` and review the behavior.
3. Run `promptdrift baseline` and commit the resulting reference after review.
4. Run `promptdrift monitor --samples 3` daily/weekly or on deployment.
5. Inspect `promptdrift history --limit 20 --json` and the CI artifact if something changes.
6. Investigate before accepting a new baseline. Never auto-accept an incident.

`baseline` and `accept` currently make fresh calls; they **do not promote an immutable prior monitor run**. Model variance between review and acceptance is a known limitation. Archives preserve the prior canonical file, but rollback is a deliberate file/Git operation, not an automated recovery policy.

## CLI contract

```bash
promptdrift monitor --config path/to/promptdrift.yaml --samples 3 --json
promptdrift monitor --config path/to/promptdrift.yaml --no-history
promptdrift history --config path/to/promptdrift.yaml --limit 20 --json
promptdrift baselines --config path/to/promptdrift.yaml --json
```

- Samples default to 3, allowed range 1–20. Each case receives fresh requests without caching or automatic retries.
- Budget for **samples × active cases** requests. This is not a dollar-budget enforcer. Provider timeouts are 60 seconds for OpenAI-compatible calls and 90 seconds for Ollama, per call.
- YAML tests and promoted scenarios use the same suite resolution for baselines, tests, monitoring and PR checks. Missing explicitly configured scenario libraries and empty suites are errors.
- The canonical baseline must exist and parse successfully. Legacy v1/v2 baselines work, but cannot establish provenance equality.
- All prompt templates are rendered before monitoring requests start. A malformed later template does not leave a partially billed run.
- Individual provider errors are counted; remaining probes/cases are attempted. Provider errors take precedence in the exit code.
- Removed baseline cases are visible as warnings with zero probes. A new passing case is also a warning, not a regression.

| Exit | Meaning |
| --- | --- |
| 0 | No fail-severity violations or provider errors; may include warnings, valid output changes, or insufficient evidence |
| 1 | At least one probe failed a fail-severity contract/threshold |
| 2 | Invalid configuration, sample range, baseline, template or evaluation setup |
| 3 | At least one provider probe failed |

Validly parsed CLI invocations with `--json` emit either a versioned `MonitorReport` or `{ "error": { "type": "...", "message": "..." }, "exit_code": 2 }`. Parser-level errors such as unknown flags or a non-integer `--samples` are still handled by Typer. The Action normalizes missing/malformed JSON into a safe error artifact. Errors deliberately omit parser payloads; inspect your local config with `doctor` for details.

## What is fingerprinted

Each schema-v3 baseline case records:

| Evidence | Contents |
| --- | --- |
| `input_hash` | Canonical SHA-256 digest of the **rendered prompt**, including used template variable values |
| `configuration_hash` | Generation defaults: temperature and maximum output tokens |
| `provider_hash` | Provider type, configured model alias and effective endpoint; credential values and environment variable names excluded |
| `contract_hash` | Ordered assertions, severities/names, thresholds and output-format contract |
| `engine_version` | PromptDrift version used for the observation |
| Optional response hashes | Provider-returned resolved model ID/system fingerprint, when available |
| Optional `envelope_hashes` | One hash each for the declared [request envelope](baselines.md#request-envelopes) `system`, `tools` (in name order) and `retrieval_context`, after credential stripping |

JSON is canonicalized before hashing. Moving a project or reordering mapping keys does not by itself change these fingerprints. Whitespace changes to the rendered request do. API-key rotation under an otherwise equivalent endpoint is not considered a configuration change; different routing attached to credentials remains **unobserved context**.

Per-case provenance is retained for unaccepted cases in selective baseline updates. The top-level baseline provider/Git fields are descriptive and cannot substitute for per-case provenance.

## Diagnosis rules, in order

1. **`provider_error`:** any probe raised a safe provider error. Missing credentials, timeouts, rate limits and malformed text-completion payloads are not evidence of a model update. This version does not separately classify auth vs rate limiting vs outage in the monitor report.
2. **`new_test`:** no baseline entry for the active case.
3. **Changed monitored inputs:** prompt, generation configuration, configured provider, or contract hash differs. All differences appear in `evidence`; the first label is a triage category, not proof it caused the failure. A changed, added or removed request envelope is triaged as `prompt_changed`, with evidence naming each drifted component (for example `request_envelope.tools differs from the accepted baseline.`).
4. **`insufficient_evidence`:** missing legacy provenance, changed PromptDrift version, or an unhealthy accepted baseline prevents before/after attribution.
5. **`stochastic_behavior`:** some but not all successful repeated probes fail behavioral contracts. This is observed variability, not a diagnosis of its cause. CI still fails on any fail-severity violation.
6. **`observed_model_drift`:** at least two probes all fail behavioral contracts, the baseline was healthy, and all recorded comparison inputs match. This is a deterministic **heuristic**, not a probability or proof of changed model weights.
7. **`insufficient_evidence`:** a single failed probe, warn-severity violations, or only operational limits failed. Latency, cost and token usage alone do not become behavioral model-drift claims.
8. **`output_changed`:** one or more outputs differ but contracts pass.
9. **`stable`:** contracts pass and output hashes match.

Provider-reported fingerprint/model changes are supporting evidence, never a verdict on their own. Metadata missing on either side is reported, not treated as equality.

## History and privacy

`monitor` stores its privacy-minimized report in `<config-directory>/.promptdrift/history.sqlite3`, retaining the latest 1,000 runs. `history` reads newest first without provider calls or a config validation requirement. Separate config files in one directory share the store; each report includes its baseline path/provider/model. Use `--no-history` to disable writes.

Storage failure adds a warning without masking the behavioral result. The CLI JSON contains run ID, timestamp, case IDs, statuses, counts, diagnosis summaries and evidence, **not raw prompts, outputs, assertion values or exception messages**. IDs/model names/paths may still be sensitive. The legacy `baseline.store_raw_output` option does not enable raw monitoring storage.

CI runners are ephemeral: the Action report artifact is the durable evidence unless you separately persist the local database. `promptdrift purge` only purges the legacy home-directory capture/run store; delete the project `history.sqlite3` and archived snapshots separately when desired. SQLite is local storage, not encrypted storage or secure erasure.

## What this cannot establish

- A vendor changed weights, routing, a system prompt or safety policy; identical metadata is not proof of identical internals.
- Your application's code, tool outputs, retrieved documents, credentials, hidden context or evaluator dependencies stayed unchanged. PromptDrift currently probes rendered text prompts, not full agent traces.
- A statistically significant drift rate. Baselines contain a single accepted observation; repeated probes are not calibrated hypothesis tests and do not estimate a confidence interval.
- Semantic quality beyond the authored contracts. An insufficient suite can pass a bad answer; no assertions means only output/operational diagnostics.
- A dollar cost budget, scalable concurrent scheduling, or automatic retry policy.

Use [the scheduled Action example](github-action.md) for fresh observations and human investigation, not automatic rollback or baseline approval.
