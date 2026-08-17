"""Provider-agnostic LLM interface.

The Investment Agent service only knows this interface.  Transport details,
request formats and response parsing live inside concrete providers such as
DeepSeekProvider, so a future OpenAIProvider can replace it without touching
the business layer.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass


@dataclass(frozen=True)
class ProviderResult:
    """Outcome of a single provider call before schema normalization.

    ``analysis`` holds the parsed JSON object when the provider could extract
    one; ``failure_reason`` is a stable code such as ``timeout``,
    ``rate_limited``, ``http_5xx``, ``network_error``, ``invalid_json`` or
    ``invalid_response``.  ``raw_text`` is kept for internal debugging only
    and is never returned by the API.
    """

    analysis: dict | None = None
    failure_reason: str | None = None
    raw_text: str | None = None

    @property
    def succeeded(self):
        return self.failure_reason is None and isinstance(self.analysis, dict)


class LLMProviderError(Exception):
    """Base class for provider configuration and transport errors."""


class UnsupportedProviderError(LLMProviderError):
    """Raised when the configured provider name has no implementation."""


class BaseLLMProvider(ABC):
    """Uniform provider contract for structured analysis generation."""

    provider_name = 'base'
    model = ''

    @abstractmethod
    def is_configured(self):
        """Return True when the provider has everything it needs to run."""

    @abstractmethod
    def generate_structured_analysis(self, prompt):
        """Return a ProviderResult for one structured-analysis prompt.

        ``prompt`` is the provider-agnostic dict produced by the prompt
        builder with ``system`` and ``user`` keys.
        """
