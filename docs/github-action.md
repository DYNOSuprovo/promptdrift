# GitHub Action

The composite Action supports two modes:

- **`check` (default):** Git-aware behavioral regression checks, including selective execution with `base-ref`. Existing workflows keep this mode.
- **`monitor` (opt-in):** Repeat each case against an **existing, reviewed canonical baseline**, even without a code change. Changed-but-valid outputs do not fail the run. Monitoring never creates, accepts or replaces a baseline.

Both modes write a Step Summary and a JSON report **before enforcing the CLI exit code**. Artifact upload and optional GitHub publication run even when the CLI reports a failure.

## Version compatibility and installation

The Action source and installed Python package are separate version choices. **Do not assume an existing `@v1` Action tag or the current PyPI release implements `monitor`.** Use a released Action commit and a released `promptdrift-ci` version that both document monitoring, once available. Pin immutable Action SHAs for production. Do not invent an unreleased PyPI pin.

To try the source in this repository now:

```yaml
steps:
  - uses: actions/checkout@v4
    with:
      fetch-depth: 0
      persist-credentials: false
  - uses: actions/setup-python@v5
    with:
      python-version: '3.12'
  - uses: ./action
    with:
      version: .  # Install this checkout, not an older PyPI package.
      config: examples/customer-support/promptdrift.yaml
```

In a different repository, either use a compatible released Action/package pair or check out a reviewed PromptDrift source commit into a separate folder. Use that local Action and install that source explicitly, then pass `install: 'false'` to avoid replacing it. A local `version` path resolves relative to `working-directory`, not to the Action's own directory. Python 3.11+ and Bash must be available; the examples use Ubuntu runners and `actions/setup-python`.

## Inputs

| Input | Default | Description |
| --- | --- | --- |
| `mode` | `check` | `check` or `monitor`; other values fail before execution |
| `config` | `promptdrift.yaml` | Config path relative to `working-directory` |
| `working-directory` | `.` | Execution/install directory, relative to `github.workspace` |
| `version` | `promptdrift-ci` | One pip package spec or local project path; e.g. `.` for this checkout |
| `install` | `true` | Set `false` to use a previously installed `promptdrift` executable |
| `base-ref` | PR base SHA, otherwise empty | Selective check base; ignored in monitor mode |
| `samples` | `3` | Monitor probes per case; integer from **1 to 20** |
| `upload-report` | `true` | Upload the generated JSON artifact |
| `artifact-name` | `promptdrift-report` | Use distinct names for multiple invocations/matrix jobs |
| `comment` | `false` | Create/update one PR comment; same-repository `pull_request` events only |
| `create-issue` | `false` | Create/update a monitor failure issue; `schedule` / `workflow_dispatch` only |
| `issue-scope` | empty | Additional stable namespace for jobs sharing the same configuration path |

Boolean inputs are strings (`'true'` / `'false'`). Package inputs are one argument, not shell commands or extra pip options. Treat the Action, installed package, configuration and checked-out code as trusted executable inputs; argument escaping does not make untrusted packages safe.

## Outputs and failure handling

| Output | Description |
| --- | --- |
| `result` | **Absolute** JSON report path in a unique runner-temp directory, including CLI errors |
| `exit-code` | CLI exit code, or `2` for Action input/install errors and malformed successful output |

The report is not written into or overwritten by the working directory. Nested directories and spaces work for execution, artifact upload and PR publication. Disabling upload does **not** disable report creation or the Step Summary.

Monitor exits:

| Code | Meaning | GitHub issue with `create-issue: 'true'`? |
| --- | --- | --- |
| `0` | Healthy or changed-but-valid behavior | No |
| `1` | Contract failure | Yes |
| `2` | Config, baseline or input error | No |
| `3` | Provider failure | Yes |

Nonzero CLI codes are preserved, including when stdout is empty or malformed. Invalid JSON from an otherwise successful CLI is converted to an Action error (`2`), never a green result. The Action emits a safe error envelope rather than uploading raw stdout/stderr. Installation errors are also reported as `2`. GitHub API notification failures produce a generic warning and do not replace the CLI verdict; verify permissions if a failing run has no alert. Artifact upload failures still fail their own step.

An error report has `{ "error": { "type": "...", "message": "..." }, "exit_code": 2 }`. The Action deliberately replaces original error text with a generic message because exceptions can contain credentials or provider payloads. Investigate sensitive details locally, not in a public issue.

Successful monitor JSON uses schema version `1`: run ID/time, provider/model, samples, baseline path, `counts`, `diagnosis_counts` and per-case test evidence. **Counts represent cases, not samples.** Schema version `1` is the only supported monitor contract; unsupported versions and malformed required fields produce a generic `invalid_report` error instead of being treated as success. Unknown top-level and per-case fields are dropped, and the Action projects only the documented public monitor fields. This allowlist lets the CLI add internal fields without exposing them through monitor artifacts or publication. Stable diagnosis labels are `stable`, `observed_model_drift`, `prompt_changed`, `configuration_changed`, `contract_changed`, `provider_changed`, `provider_error`, `insufficient_evidence`, `new_test`, `stochastic_behavior` and `output_changed`. A diagnosis is evidence, not proof of a vendor-side model update.

## PR checks and optional comments

Use `pull_request`, `contents: read`, a reviewed configuration and the mock provider for untrusted PRs. For same-repository PR comments, grant `pull-requests: write` at the job level and pass `comment: 'true'`. The Action paginates existing comments and updates the legacy `<!-- promptdrift-report -->` bot comment instead of adding another comment on each run. `fetch-depth: 0` supplies the history needed for selective checks; alternatively fetch the selected base ref explicitly.

```yaml
name: Prompt contracts
on: [pull_request]
permissions:
  contents: read
jobs:
  check:
    runs-on: ubuntu-latest
    permissions:
      contents: read
      pull-requests: write
    steps:
      - uses: actions/checkout@v4
        with:
          fetch-depth: 0
          persist-credentials: false
      - uses: actions/setup-python@v5
        with:
          python-version: '3.12'
      # Local-source example for this repository; see compatibility notes above.
      - uses: ./action
        with:
          version: .
          mode: check
          config: examples/customer-support/promptdrift.yaml
          comment: 'true'
```

Fork PR comments are disabled. **`pull_request_target` execution is refused entirely**, even when comments are disabled. Never use a privileged event to check out or execute a fork's code. Do not expose provider secrets to untrusted PR code, dependencies or configuration.

## Publishing JUnit XML test results

The PromptDrift CLI supports JUnit XML output through `--junit-xml`.
This can be used with GitHub Actions and third-party test reporting actions
to publish evaluation results directly in CI.

The following example assumes PromptDrift is already installed in the
workflow environment:

```yaml
name: PromptDrift JUnit Reports

on:
  push:
  pull_request:

permissions:
  contents: read
  actions: read
  checks: write

jobs:
  promptdrift:
    runs-on: ubuntu-latest
    steps:
      - name: Checkout repository
        uses: actions/checkout@v6

      - name: Run PromptDrift checks
        run: |
          promptdrift check \
            --config promptdrift.yaml \
            --junit-xml test-results.xml

      - name: Publish JUnit test results
        if: always()
        uses: dorny/test-reporter@v3
        with:
          name: PromptDrift Results
          path: test-results.xml
          reporter: java-junit
```

The reporting step uses `if: always()` so it runs even when PromptDrift
returns a non-zero exit code. The CLI writes the XML report before exiting
on evaluation failures.

The GitHub Check Runs API requires `checks: write` permission. Workflows
triggered by pull requests from forks receive read-only tokens, so this
publishing approach cannot create check runs for those contributions.
For public repositories, upload the XML as a workflow artifact and publish
it from a separate trusted `workflow_run` workflow instead.

Do not use `pull_request_target` to execute untrusted pull-request code.
## Opt-in scheduled monitoring

[`../.github/workflows/monitor-example.yml`](../.github/workflows/monitor-example.yml) is a manual, repository-variable-gated **offline mock** example. Its schedule is commented out; no paid provider job is enabled by this change.

1. Install this source (or a compatible released version): `python -m pip install .`.
2. Run `promptdrift baseline --config examples/monitoring/mock.yml` locally. Review the healthy baseline and commit `examples/monitoring/mock.baseline.json` with the configuration/prompts. Do not generate the baseline automatically in the monitoring workflow: that would erase the reference being monitored.
3. Verify `promptdrift monitor --config examples/monitoring/mock.yml --samples 3 --json` locally.
4. Set the repository Actions variable **`PROMPTDRIFT_MONITOR_ENABLED=true`** and run the example manually.
5. Only after reviewing results, uncomment the cron trigger on the default branch and choose an appropriate cadence.

The example explicitly uses `contents: read`, `issues: write`, `persist-credentials: false`, a 15-minute job timeout and **stable concurrency with `cancel-in-progress: false`**. Keep the same concurrency group across workflows that share an issue scope. Paginated lookup deduplicates sequential runs; concurrency avoids a race where simultaneous runs could both create the first issue. GitHub issues do not provide an atomic create-if-absent API.

For a paid provider, deliberately switch to [`../examples/monitoring/openai.yml`](../examples/monitoring/openai.yml), provision/review its separate baseline and add the key only to the Action step:

```yaml
env:
  OPENAI_API_KEY: ${{ secrets.OPENAI_API_KEY }}
```

Budget for **samples × active cases** provider calls per run; repeated samples cost money and add latency. Keep provider/model/configuration stable when assessing drift. Samples default to 3 and are capped at 20; one sample cannot establish repeated drift. Monitor never automatically accepts a failing baseline or fixes a regression by updating the reference.

### Deduplicated GitHub alerts

Issues are off by default. With `create-issue: 'true'`, monitor exits `1` or `3` on `schedule` or `workflow_dispatch` create/update one open bot-authored issue. A stable hashed HTML marker is derived from the workspace-relative config path plus `issue-scope`; names, messages and model output cannot inject a different marker. Lookup paginates **all open repository issues**, excludes PRs and ignores matching markers posted by non-bot users.

Repeated failures update the issue body without posting comments. Healthy runs do **not** auto-close issues; close them after investigation. A later failure creates a new issue if the prior one was closed. This alerts on contract/provider failures, not every warning or changed output. Separate matrix dimensions targeting the same config should use different `issue-scope` values (and artifact names), unless they intentionally share an alert.

Summary/issue text contains only aggregate counts, diagnosis labels and bounded escaped test IDs, with mentions neutralized. It does not publish raw prompts/outputs, provider exception text, free-form evidence or summaries. Only validated contract/provider failures can open or update an issue; an invalid report with a provider-like exit code is not treated as a provider failure. The issue links to the workflow run. There is no Slack or external alert integration.

## Credentials and report privacy

- Use Actions secrets for keys; never put them in config, package URLs or workflow literals.
- Monitor reports contain no raw prompts/outputs. Identifiers, provider/model, baseline path and evidence metadata can still be sensitive; restrict repository/artifact access and review your naming conventions.
- For compatibility, **check-mode JSON may contain raw inputs/outputs** from the existing CLI. Disable `upload-report` for sensitive check runs and manage the local report appropriately; the Step Summary/comment does not render those raw fields.
- As defense in depth, the Action redacts values of environment variables ending in `KEY`, `TOKEN`, `SECRET` or `PASSWORD` (four or more characters) from reports. This is not a general-purpose secret scanner and cannot recognize unknown or transformed secrets.
- Raw CLI stdout/stderr and installer logs are not echoed or uploaded on error. Investigate locally with appropriate access.
- Grant `issues: write` only to trusted monitoring jobs and `pull-requests: write` only where comments are needed. Publication uses the workflow's GitHub token; no separate personal access token is necessary.

## Troubleshooting

| Symptom | Check |
| --- | --- |
| `monitor` returns an invalid report/error with exit `2` | Installed package and Action both support monitoring; baseline exists and is canonical |
| Scheduled run does not start | Variable opt-in is set; cron is uncommented and committed to the default branch |
| Provider failure (`3`) | Secret name, account/model access, endpoint and provider availability; investigate privately |
| No issue for a failing run | `create-issue`, `issues: write`, trusted scheduled/manual event, and exit `1`/`3` |
| No issue for output changes | Expected: changed-but-valid behavior is not a contract failure |
| Missing PR comment | Same-repository `pull_request`, `comment: 'true'`, `pull-requests: write` |
| Artifact name conflict | Set a different `artifact-name` for each invocation/matrix dimension |
| Unexpected pip installation failure | Use a single trusted package spec; local paths are relative to `working-directory` |
