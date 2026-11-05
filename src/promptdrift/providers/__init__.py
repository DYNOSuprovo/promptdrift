from .base import Provider
from .mock import MockProvider
from .ollama import OllamaProvider
from .openai import OpenAIProvider
from .resilience import ResilienceExecutor

__all__ = [
    "MockProvider",
    "OllamaProvider",
    "OpenAIProvider",
    "Provider",
    "ResilienceExecutor",
    "create_provider",
]


def create_provider(config):
    providers = {"openai": OpenAIProvider, "ollama": OllamaProvider, "mock": MockProvider}
    return providers[config.type](config)
