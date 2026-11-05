# Reviewed baselines and history

The canonical baseline is a Git-reviewable reference, not an automatic assertion that the captured answer is correct.

```bash
promptdrift test                        # Inspect contracts and output locally.
promptdrift baseline                    # Fresh calls; write the first reference.
promptdrift monitor --samples 3         # Observe without modifying the reference.
promptdrift baseline --force            # Deliberate replacement after review.
promptdrift baselines --config promptdrift.yaml --json
```

## Safety rules

- `baseline` refuses an existing reference unless `--force` is supplied, **before making provider calls**.
- Failed contracts prevent `baseline` and initial `accept` from writing a reference unless `--accept-regressions` is explicit. `--force` alone is not that approval.
- Monitoring requires a valid reference. A corrupt baseline fails before provider calls; `check` no longer silently ignores it.
- Replacements are written through a temporary file and atomic rename. Previous snapshots are archived beside the canonical file under `.promptdrift/baseline_history/`.
- Archives are local and ignored by Git; commit the canonical reference if you want reviewed history in Git. Concurrent writers are not supported—serialize baseline updates.

## Schema and privacy

New baselines use **schema version 3**. The loader still accepts v1 (migrated to v2) and v2. Unknown future versions are rejected rather than silently interpreted.

| Field | Purpose |
| --- | --- |
| `schema_version`, `promptdrift_version`, `generated_at` | Format and producer version/time |
| `provider` | Configured provider type and model |
| `git_sha`, `prompt_hash`, `prompt_revision` | Optional legacy revision metadata; not complete application attestation |
| `tests.<id>.output_hash` | SHA-256 of the output; wording change is not automatically a regression |
| `status`, `assertions` | Accepted contract results |
| `metrics` | Observed latency/token counts/available cost, not a statistical distribution |
| `provenance` | Per-case hashes of rendered input, settings, provider and contracts; PromptDrift version; optional response metadata hashes; optional `envelope_hashes` |

Provenance is optional for compatibility. A legacy or manually constructed baseline without it produces `insufficient_evidence` in monitoring. Review and recreate the reference to enable unchanged-input comparisons; missing evidence is never invented during migration.

No raw prompts or responses are saved in canonical baselines. **Hashes are not anonymization or encryption:** predictable content can be guessed, and case/model names may reveal information. Review the file before publishing. `baseline.store_raw_output` controls legacy local run storage, not baseline contents.

## Request envelopes

A test case can declare the rest of the request your application sends alongside the prompt template. PromptDrift hashes it for provenance only; it is **not sent to the provider** and tools are never executed.

```yaml
tests:
  - id: refund-policy
    prompt: prompts/support.txt
    request_envelope:
      system: You are a support agent.
      tools:
        - name: lookup_order
          description: Find an order by id.
          parameters: {type: object, properties: {order_id: {type: string}}}
      retrieval_context:
        policy: {refund_days: 30}
```

- `provenance.envelope_hashes` stores one SHA-256 per component: `system`, `tools` and `retrieval_context`. The template itself stays in `input_hash`, so it is never hashed twice.
- Mapping key order does not matter. Tool names must be unique, and tools are hashed in name order, so reordering tools does not change the hash. Lists inside a tool's `parameters` (such as `required` or `enum`) keep their declared order.
- Before hashing, scalar values under credential-named keys are removed at any depth (`api_key`, `x-api-key`, `token`, `access_token`, `refresh_token`, `session_token`, `secret`, `client_secret`, `password`, `private_key`, `authorization`, `credential(s)`, `cookie`, `set-cookie`). Matching ignores case, `-` and `_`, and is exact, so `max_tokens` is kept. Object values are kept, so a tool parameter schema named `password` still counts. Long `sk-…` and `Bearer …` strings are masked. Do not store real credentials in configuration regardless.
- Cases without an envelope omit `envelope_hashes` entirely; their baselines are unchanged and existing v1–v3 baselines load as before. Promoted scenarios (`scenarios.json`) cannot declare an envelope yet.

## Selective acceptance

```bash
promptdrift accept --scenario refund-policy --force
promptdrift accept --changed --force
promptdrift accept --scenario reviewed-regression --accept-regressions --force
```

Acceptance evaluates the full active suite even if Git optimization would otherwise select only modified prompts. The merge changes only allowed/selected cases and keeps per-case provenance for retained entries. It never modifies `NOT_EVALUATED` entries. `--changed` accepts changed-but-valid cases; intentional regressions require explicit authorization.

**Limitation:** acceptance currently makes fresh calls instead of promoting a specific immutable monitor run. Review the resulting canonical diff before committing. There is no built-in named-baseline rollback command; restore a reviewed snapshot/Git version manually. `baseline --force` replaces the whole suite and removes obsolete cases; selective acceptance retains existing entries.

## Three kinds of history

1. **Canonical baseline:** committed reference used for comparisons.
2. **Baseline archives:** local snapshots preserved on replacement, listed with `baselines --config PATH`. Archive location follows the canonical baseline directory, not the shell's working directory.
3. **Monitoring history:** privacy-minimized observations in `<config-directory>/.promptdrift/history.sqlite3`, listed with `history`. Retains 1,000 reports and does not change the reference.

Legacy `test`/`check` run and capture history remains at `~/.promptdrift/promptdrift.db`. Prompts, outputs, assertion expected/actual values and potentially sensitive reasons are suppressed from legacy stored reports unless `baseline.store_raw_output: true`. Legacy JSON/HTML exports can still contain raw data.

See [monitoring](monitoring.md) for attribution rules, exit codes and retention limits.
