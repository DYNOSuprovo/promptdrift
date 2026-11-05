# Configuration

PromptDrift is configured through a single `promptdrift.yaml` file. The schema is strict and versioned — unknown fields cause a validation error rather than being silently ignored.

## Full Annotated Example

```yaml
# Both 1 and 2 are supported; version 2 supports scenario libraries.
version: 2

# LLM provider configuration
provider:
  type: openai              # "openai" | "ollama" | "mock"
  model: gpt-4.1-mini       # Model identifier
  api_key_env: OPENAI_API_KEY  # Environment variable name (OpenAI only)
  base_url: null             # Override API endpoint (optional)

# Default parameters applied to every test
defaults:
  temperature: 0             # 0–2, lower = more deterministic
  max_output_tokens: 500     # Maximum tokens in the response

# Baseline configuration
baseline:
  path: promptdrift.baseline.json  # Relative to config file
  store_raw_output: false          # If true, store raw output in local SQLite

# Failures are controlled by assertion severity and explicit thresholds.
# No semantic judge or embedding evaluator is enabled implicitly.

# Test cases
tests:
  - id: refund_request       # Unique identifier (alphanumeric, _, ., -)
    prompt: prompts/support.txt  # Jinja2 template path (relative to config)
    variables:               # Template variables
      policy: "Refunds are available within 30 days."
      question: "Can I get a refund for my order?"
    assertions:              # Behavioral contracts
      - type: contains
        value: "30 days"
      - type: not_contains
        value: guaranteed
        severity: warn       # "fail" (default) or "warn"
      - type: max_length
        value: 600
    thresholds:              # Performance thresholds
      latency_ms: 5000       # Number = failure threshold
      cost_usd:
        warn: 0.01           # Structured threshold
        fail: 0.05
```

## Field Reference

### Top Level

| Field | Type | Required | Default | Description |
| --- | --- | --- | --- | --- |
| `version` | `1` or `2` | No | `1` | Version 1 requires YAML tests; version 2 also supports promoted scenarios |
| `provider` | object | Yes | — | LLM provider configuration |
| `defaults` | object | No | See below | Default generation parameters |
| `baseline` | object | No | See below | Baseline file settings |
| `ci` | object | No | Legacy defaults | Compatibility-only; customization is rejected, not silently ignored |
| `tests` | list | Usually | `[]` | Version 1 requires at least one; all run commands reject an empty resolved suite |
| `scenarios` | object | No | default project library | Version 2: `{file: .promptdrift/scenarios.json}`; explicitly configured missing files are errors |
| `project` | object | No | — | Optional `{name: my-project}` metadata |
| `sources` | object | No | — | Legacy prompt-source metadata; does not automatically create tests |
| `policy` | object | No | `{fail_on: [regression], warn_on: []}` | Only this supported PR-check policy is accepted |
| `evaluation` | object | No | — | Semantic evaluation is unimplemented; `semantic.enabled: true` is rejected |

### Provider

| Field | Type | Required | Default | Description |
| --- | --- | --- | --- | --- |
| `type` | string | Yes | — | `"openai"`, `"ollama"`, or `"mock"` |
| `model` | string | No | `"mock"` | Model name or identifier |
| `api_key_env` | string | No | `null` | Environment variable holding the API key |
| `base_url` | string | No | `null` | Custom API endpoint URL |

### Defaults

| Field | Type | Default | Description |
| --- | --- | --- | --- |
| `temperature` | float | `0` | Sampling temperature (0–2) |
| `max_output_tokens` | int | `500` | Maximum output token count |

### Test Case

| Field | Type | Required | Default | Description |
| --- | --- | --- | --- | --- |
| `id` | string | Yes | — | Unique test identifier |
| `prompt` | string | Yes | — | Path to the Jinja2 prompt template |
| `variables` | dict | No | `{}` | Key-value pairs passed to the template |
| `request_envelope` | object | No | — | Declared `system`, `tools` and `retrieval_context` for provenance hashing only; see [baselines](baselines.md#request-envelopes) |
| `assertions` | list | No | `[]` | Deterministic behavioral contracts |
| `thresholds` | dict | No | `{}` | `latency_ms` and `cost_usd` limits; unknown cost cannot satisfy a limit |
| `output` | object | No | `{format: text}` | `format: json` adds a JSON-validity contract |
| `evaluators` | list | No | `[]` | Nonempty lists are rejected; semantic/judge evaluators are not implemented |

### Assertion

| Field | Type | Required | Default | Description |
| --- | --- | --- | --- | --- |
| `type` | string | Yes | — | Assertion type (see [Assertions](assertions.md)) |
| `value` | any | Depends | — | Expected value (not required for `json_valid`) |
| `schema` | dict | `json_schema` only | — | JSON Schema object |
| `name` | string | No | type name | Human-readable label in reports |
| `severity` | string | No | `"fail"` | `"fail"` or `"warn"` |

## Path Resolution

All paths in the configuration (`prompt`, `baseline.path`, `scenarios.file`) are resolved **relative to the config file**, not the working directory. Absolute paths are used as-is.

## Validation

PromptDrift uses Pydantic models with `extra="forbid"`. Unknown fields cause validation errors. Regex syntax, numeric assertion limits and JSON schemas are validated before provider calls. JSON schema references must be local fragments (`#...`); remote resource retrieval is disabled.

The old `ci` defaults (`fail_on: [assertion_failure]`, `warn_on: [semantic_change, latency_regression]`) are accepted only for compatibility, **not a configurable engine policy**. Use `severity: warn` or `severity: fail` and explicit numeric thresholds instead. The defaults never enable semantic evaluation or automatic latency-delta failure.

Monitoring uses these same contracts plus CLI `--samples`/`--no-history`; it does not introduce a competing configuration file. See [monitoring](monitoring.md).

## JUnit XML Reports

PromptDrift can export evaluation results in JUnit XML format for integration
with CI test reporting tools.

Use the `--junit-xml` option with either the `test` or `check` command:

```bash
promptdrift test --junit-xml test-results.xml
```

```bash
promptdrift check --junit-xml test-results.xml
```

You can also specify a custom output location:

```bash
promptdrift check --config promptdrift.yaml --junit-xml reports/test-results.xml
```

Parent directories are created automatically when they do not exist.

Each PromptDrift test is represented as a JUnit testcase. Execution times
are reported in seconds. Failed assertions include their diagnostic reason,
expected value, and actual value in the `<failure>` element.

Warnings are represented as passing testcases, with their diagnostic reasons
included in `<system-out>`. This allows CI platforms to display warnings
without treating them as test failures.

The XML report is written before the CLI returns its failure exit code,
so CI workflows can still collect test results when evaluations fail.