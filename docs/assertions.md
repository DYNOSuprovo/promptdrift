# Assertions

Assertions are deterministic behavioral contracts that define what the LLM output **must** or **must not** do. Unlike cosmetic diffs, assertions only fail when a meaningful behavioral requirement is violated.

Every assertion accepts an optional `severity` field: `"fail"` (default, blocks CI) or `"warn"` (reported but non-blocking).

## Text Assertions

### `exact_match`

Passes only if the output is **character-for-character identical** to the expected value.

```yaml
- type: exact_match
  value: "Yes, you qualify for a refund."
```

**Use case:** Deterministic outputs where exact phrasing is required (e.g., status codes, fixed responses).

### `contains`

Passes if the expected string appears **anywhere** in the output.

```yaml
- type: contains
  value: "30 days"
```

**Use case:** Ensuring key information is present regardless of how the model phrases the rest.

### `not_contains`

Passes if the forbidden string does **not** appear anywhere in the output.

```yaml
- type: not_contains
  value: "guaranteed"
  severity: warn
```

**Use case:** Preventing the model from making promises, mentioning competitors, or using banned terms.

## Pattern Assertions

### `regex`

Passes if the output matches the given regular expression pattern.

```yaml
- type: regex
  value: "\\d{1,3}\\.\\d{1,2}%"
  name: percentage_format
```

**Use case:** Validating structured patterns like percentages, dates, phone numbers, or IDs.

### `not_regex`

Passes if the output does **not** match the regular expression pattern.

```yaml
- type: not_regex
  value: "(?i)\\b(sorry|apologize|unfortunately)\\b"
  name: no_hedging
```

**Use case:** Banning patterns of language like hedging, email addresses, or internal IDs.

## JSON Assertions

### `json_valid`

Passes if the output is parseable as valid JSON. No `value` is required.

```yaml
- type: json_valid
```

**Use case:** Ensuring structured outputs are valid JSON before checking their contents.

### `json_schema`

Passes if the output is valid JSON **and** conforms to the given [JSON Schema](https://json-schema.org/).

```yaml
- type: json_schema
  name: support_json
  schema:
    type: object
    required:
      - answer
      - confidence
    properties:
      answer:
        type: string
      confidence:
        type: number
        minimum: 0
        maximum: 1
```

**Use case:** Validating structured LLM responses — required fields, types, enums, nested objects.

## Length Assertions

### `min_length`

Passes if the output has **at least** this many characters.

```yaml
- type: min_length
  value: 50
```

**Use case:** Ensuring the model produces a substantive response, not a terse one-liner.

### `max_length`

Passes if the output has **at most** this many characters.

```yaml
- type: max_length
  value: 600
```

**Use case:** Preventing verbose outputs that exceed UI constraints or context windows.

## Performance Assertions

### `max_tokens`

Passes if the provider-reported output token count is at most this limit. Missing usage fails the check at the configured severity; word counts are not silently substituted for tokens.

```yaml
- type: max_tokens
  value: 150
```

### `latency_ms`

Passes if the provider response time is at or below the limit in milliseconds.

```yaml
- type: latency_ms
  value: 3000
  tolerance_percent: 15
```

### `cost_usd`

Passes if an available estimated cost is at or below the limit. OpenAI-compatible responses do not currently supply a priced cost estimate, so `cost_usd` cannot pass for them: unknown is not zero. Mock/Ollama report zero external API cost, not total infrastructure cost.

```yaml
- type: cost_usd
  value: 0.05
  severity: warn
  tolerance_percent: 10
```

Regex syntax and numeric limits are validated when loading configuration. JSON schemas may use local fragment references only (`#...`); evaluation never retrieves remote schemas. `output.format: json` on a test is also enforced as a JSON-validity contract.

## Severity Levels

| Severity | CI behavior | Report |
| --- | --- | --- |
| `fail` (default) | Exit code 1, blocks merge | Shown as ❌ |
| `warn` | Exit code 0 | Shown as ⚠️ |

## Combining Assertions

A test case can have any number of assertions. All are evaluated independently — one failure does not prevent the others from running.

```yaml
assertions:
  - type: json_valid
  - type: json_schema
    schema: { type: object, required: [answer] }
  - type: max_length
    value: 1000
  - type: not_contains
    value: "internal_id"
    severity: warn
```
