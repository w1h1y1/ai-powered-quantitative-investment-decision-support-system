"""Provider selection for the Investment Agent."""

from django.conf import settings

from .base import UnsupportedProviderError
from .deepseek_provider import DeepSeekProvider


def get_llm_provider(provider_name=None):
    """Instantiate the configured LLM provider.

    The provider name comes from ``settings.LLM_PROVIDER`` unless overridden.
    Adding a future OpenAI provider only requires registering it here; the
    Investment Agent service stays unchanged.
    """

    name = (provider_name or settings.LLM_PROVIDER or 'deepseek').strip().lower()
    if name == 'deepseek':
        return DeepSeekProvider()
    raise UnsupportedProviderError(f'Unsupported LLM provider: {name}')
