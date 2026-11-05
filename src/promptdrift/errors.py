"""Exceptions with safe, actionable messages for PromptDrift users."""


class PromptDriftError(Exception):
    """Base class for expected application errors."""


class ConfigError(PromptDriftError):
    """Configuration is invalid or unavailable."""


class TemplateError(PromptDriftError):
    """A prompt template cannot be safely rendered."""


class ProviderError(PromptDriftError):
    """A provider request could not be completed."""


class ProviderAuthError(ProviderError):
    """Provider authentication failed or API key is missing (non-retryable)."""


class ProviderRateLimitError(ProviderError):
    """Provider rate limit reached, e.g. HTTP 429 (retryable)."""


class ProviderTransportError(ProviderError):
    """Network connection, DNS, or transient server error 502/503/504 (retryable)."""


# Alias for backward compatibility with ProviderConnectionError
ProviderConnectionError = ProviderTransportError


class ProviderTimeoutError(ProviderError):
    """Per-request timeout expired or cumulative timeout budget exceeded."""


class ProviderResponseError(ProviderError):
    """Provider returned malformed, invalid, or client-error response (non-retryable)."""


class ProviderBudgetExceededError(ProviderError):
    """Planned or actual requests exceeded the configured request budget."""


class EvaluationError(PromptDriftError):
    """An evaluator received invalid input."""


class BaselineError(PromptDriftError):
    """A baseline could not be read or safely written."""
