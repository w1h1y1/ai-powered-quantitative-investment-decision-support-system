"""DeepSeek chat-completions provider.

DeepSeek exposes an OpenAI-compatible chat completions API.  This provider
encapsulates the DeepSeek request/response format so the Investment Agent
service never sees a DeepSeek-specific URL, payload or response shape.
"""

import json
import logging
import urllib.error
from urllib.request import Request, urlopen

from django.conf import settings

from .base import BaseLLMProvider, ProviderResult

logger = logging.getLogger('agent')

CHAT_COMPLETIONS_PATH = '/chat/completions'


class DeepSeekRequestError(Exception):
    """HTTP-level failure carrying a stable reason code."""

    def __init__(self, reason_code):
        super().__init__(reason_code)
        self.reason_code = reason_code


def extract_json_object(content):
    """Extract the first JSON object from model output (best effort)."""
    if not content:
        return None
    start = content.find('{')
    end = content.rfind('}')
    if start < 0 or end <= start:
        return None
    try:
        parsed = json.loads(content[start:end + 1])
    except (TypeError, ValueError):
        return None
    return parsed if isinstance(parsed, dict) else None


def strip_single_json_fence(content):
    """Strip exactly one JSON code fence when it safely wraps the whole output.

    Returns the original content unchanged unless the output starts with a
    fenced block and contains exactly one opening and one closing fence.
    """

    text = content.strip()
    if not text.startswith('```'):
        return content
    if text.count('```') != 2:
        return content
    first_line, _, remainder = text.partition('\n')
    if not first_line.strip().lower().startswith('```json'):
        return content
    body, _, closing = remainder.rpartition('\n')
    if closing.strip() != '```':
        return content
    return body.strip()


class DeepSeekProvider(BaseLLMProvider):
    provider_name = 'deepseek'

    def __init__(
        self,
        *,
        api_key=None,
        model=None,
        base_url=None,
        timeout_seconds=None,
    ):
        self.api_key = (
            api_key
            if api_key is not None
            else settings.DEEPSEEK_API_KEY
        )
        self.model = model or settings.LLM_MODEL or 'deepseek-chat'
        self.base_url = (
            base_url
            or settings.DEEPSEEK_BASE_URL
            or 'https://api.deepseek.com'
        ).rstrip('/')
        self.timeout_seconds = (
            timeout_seconds
            if timeout_seconds is not None
            else settings.LLM_TIMEOUT_SECONDS
        )

    def __repr__(self):
        return (
            f'<DeepSeekProvider provider={self.provider_name} '
            f'model={self.model} configured={self.is_configured()}>'
        )

    def is_configured(self):
        return bool(self.api_key)

    def generate_structured_analysis(self, prompt):
        if not self.is_configured():
            return ProviderResult(failure_reason='api_key_missing')
        request_payload = {
            'model': self.model,
            'messages': [
                {'role': 'system', 'content': prompt['system']},
                {'role': 'user', 'content': prompt['user']},
            ],
            'temperature': 0.2,
            'response_format': {'type': 'json_object'},
        }
        try:
            response_data = self._post_chat_completion(request_payload)
        except DeepSeekRequestError as exc:
            logger.warning(
                'LLM provider failure provider=%s model=%s reason=%s',
                self.provider_name,
                self.model,
                exc.reason_code,
            )
            return ProviderResult(failure_reason=exc.reason_code)
        except TimeoutError:
            logger.warning(
                'LLM provider failure provider=%s model=%s reason=timeout',
                self.provider_name,
                self.model,
            )
            return ProviderResult(failure_reason='timeout')
        except urllib.error.URLError as exc:
            logger.warning(
                'LLM provider failure provider=%s model=%s reason=network_error',
                self.provider_name,
                self.model,
            )
            return ProviderResult(failure_reason='network_error')
        except OSError:
            logger.warning(
                'LLM provider failure provider=%s model=%s reason=network_error',
                self.provider_name,
                self.model,
            )
            return ProviderResult(failure_reason='network_error')
        return self._parse_response(response_data)

    def _post_chat_completion(self, request_payload):
        request = Request(
            f'{self.base_url}{CHAT_COMPLETIONS_PATH}',
            data=json.dumps(request_payload).encode('utf-8'),
            headers={
                'Content-Type': 'application/json',
                'Authorization': f'Bearer {self.api_key}',
            },
            method='POST',
        )
        try:
            with urlopen(request, timeout=self.timeout_seconds) as response:
                return response.read().decode('utf-8')
        except urllib.error.HTTPError as exc:
            if exc.code == 429:
                raise DeepSeekRequestError('rate_limited') from exc
            if exc.code >= 500:
                raise DeepSeekRequestError('http_5xx') from exc
            if exc.code in (401, 403):
                raise DeepSeekRequestError('auth_error') from exc
            raise DeepSeekRequestError('http_error') from exc

    def _parse_response(self, response_body):
        if not response_body or not response_body.strip():
            logger.warning(
                'LLM provider failure provider=%s model=%s reason=invalid_response',
                self.provider_name,
                self.model,
            )
            return ProviderResult(failure_reason='invalid_response')
        try:
            response_data = json.loads(response_body)
        except (TypeError, ValueError):
            logger.warning(
                'LLM provider failure provider=%s model=%s reason=invalid_json',
                self.provider_name,
                self.model,
            )
            return ProviderResult(failure_reason='invalid_json')
        try:
            content = response_data['choices'][0]['message']['content']
        except (KeyError, IndexError, TypeError):
            logger.warning(
                'LLM provider failure provider=%s model=%s reason=invalid_response',
                self.provider_name,
                self.model,
            )
            return ProviderResult(failure_reason='invalid_response')
        if not content or not str(content).strip():
            logger.warning(
                'LLM provider failure provider=%s model=%s reason=invalid_response',
                self.provider_name,
                self.model,
            )
            return ProviderResult(failure_reason='invalid_response')
        content_text = str(content)
        stripped = strip_single_json_fence(content_text)
        analysis = extract_json_object(stripped)
        if analysis is None:
            analysis = extract_json_object(content_text)
        if analysis is None:
            logger.warning(
                'LLM provider failure provider=%s model=%s reason=invalid_json',
                self.provider_name,
                self.model,
            )
            return ProviderResult(failure_reason='invalid_json')
        return ProviderResult(analysis=analysis, raw_text=content_text)
