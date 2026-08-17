import io
import json
import urllib.error
from unittest.mock import patch

from django.test import SimpleTestCase

from agent.llm.base import UnsupportedProviderError
from agent.llm.deepseek_provider import (
    DeepSeekProvider,
    strip_single_json_fence,
)
from agent.llm.provider_factory import get_llm_provider


class FakeHTTPResponse:
    def __init__(self, body):
        self._body = body

    def read(self):
        return self._body.encode('utf-8')

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        return False


def chat_response_with_content(content):
    return json.dumps({
        'id': 'chatcmpl-test',
        'choices': [{'message': {'role': 'assistant', 'content': content}}],
    })


def configured_provider():
    return DeepSeekProvider(
        api_key='test-secret-key',
        model='deepseek-chat',
        base_url='https://api.deepseek.com',
        timeout_seconds=10,
    )


class ProviderFactoryTests(SimpleTestCase):
    def test_factory_selects_deepseek_by_default(self):
        provider = get_llm_provider()
        self.assertIsInstance(provider, DeepSeekProvider)
        self.assertEqual(provider.provider_name, 'deepseek')

    def test_factory_selects_deepseek_by_name(self):
        provider = get_llm_provider('deepseek')
        self.assertIsInstance(provider, DeepSeekProvider)

    def test_factory_rejects_unsupported_provider(self):
        with self.assertRaises(UnsupportedProviderError):
            get_llm_provider('openai')


class DeepSeekProviderTests(SimpleTestCase):
    def test_missing_key_returns_api_key_missing_without_network(self):
        provider = DeepSeekProvider(api_key='')
        with patch(
            'agent.llm.deepseek_provider.urlopen',
            side_effect=AssertionError('network must not be called'),
        ):
            result = provider.generate_structured_analysis({'system': 's', 'user': 'u'})

        self.assertFalse(provider.is_configured())
        self.assertEqual(result.failure_reason, 'api_key_missing')
        self.assertIsNone(result.analysis)

    def test_successful_response_parses_structured_json(self):
        content = json.dumps({
            'market_summary': 'Calm.',
            'market_regime_summary': 'Sideways.',
            'technical_summary': 'Neutral.',
            'market_context_summary': 'Broad market neutral.',
            'historical_evidence_summary': 'Completed.',
            'risk_assessment': 'Low.',
            'key_reasons': ['A'],
            'risk_factors': ['B'],
            'limitations': ['C'],
        })
        with patch(
            'agent.llm.deepseek_provider.urlopen',
            return_value=FakeHTTPResponse(chat_response_with_content(content)),
        ):
            result = configured_provider().generate_structured_analysis({
                'system': 's',
                'user': 'u',
            })

        self.assertTrue(result.succeeded)
        self.assertEqual(result.analysis['market_summary'], 'Calm.')
        self.assertEqual(result.analysis['key_reasons'], ['A'])
        self.assertEqual(json.loads(result.raw_text), json.loads(content))

    def test_markdown_fenced_json_is_extracted(self):
        content = '```json\n{"market_summary": "Fenced.", "key_reasons": []}\n```'
        with patch(
            'agent.llm.deepseek_provider.urlopen',
            return_value=FakeHTTPResponse(chat_response_with_content(content)),
        ):
            result = configured_provider().generate_structured_analysis({
                'system': 's',
                'user': 'u',
            })

        self.assertEqual(result.analysis['market_summary'], 'Fenced.')

    def test_single_json_fence_is_stripped_safely(self):
        content = '```json\n{"market_summary": "Fenced.", "key_reasons": []}\n```'
        self.assertEqual(
            strip_single_json_fence(content),
            '{"market_summary": "Fenced.", "key_reasons": []}',
        )

    def test_multi_fence_or_non_json_fence_is_left_untouched(self):
        multi = '```json\n{"a": 1}\n```\ntrailing prose'
        self.assertEqual(strip_single_json_fence(multi), multi)
        wrong_label = '```text\n{"a": 1}\n```'
        self.assertEqual(strip_single_json_fence(wrong_label), wrong_label)
        plain = '{"a": 1}'
        self.assertEqual(strip_single_json_fence(plain), plain)

    def test_fenced_output_round_trip_through_provider(self):
        content = '```json\n' + json.dumps({
            'market_summary': 'Fenced.',
            'market_regime_summary': 'R.',
            'technical_summary': 'T.',
            'market_context_summary': 'C.',
            'historical_evidence_summary': 'H.',
            'risk_assessment': 'A.',
            'key_reasons': ['K'],
            'risk_factors': ['F'],
            'limitations': ['L'],
        }) + '\n```'
        with patch(
            'agent.llm.deepseek_provider.urlopen',
            return_value=FakeHTTPResponse(chat_response_with_content(content)),
        ):
            result = configured_provider().generate_structured_analysis({
                'system': 's',
                'user': 'u',
            })
        self.assertTrue(result.succeeded)
        self.assertEqual(result.analysis['market_summary'], 'Fenced.')

    def test_http_429_maps_to_rate_limited(self):
        error = urllib.error.HTTPError(
            'https://api.deepseek.com/chat/completions',
            429,
            'Too Many Requests',
            {},
            io.BytesIO(b'{}'),
        )
        with patch(
            'agent.llm.deepseek_provider.urlopen',
            side_effect=error,
        ):
            result = configured_provider().generate_structured_analysis({
                'system': 's',
                'user': 'u',
            })

        self.assertEqual(result.failure_reason, 'rate_limited')
        self.assertIsNone(result.analysis)

    def test_http_5xx_maps_to_http_5xx(self):
        for code in (500, 503):
            with self.subTest(code=code):
                error = urllib.error.HTTPError(
                    'https://api.deepseek.com/chat/completions',
                    code,
                    'Server Error',
                    {},
                    io.BytesIO(b'{}'),
                )
                with patch(
                    'agent.llm.deepseek_provider.urlopen',
                    side_effect=error,
                ):
                    result = configured_provider().generate_structured_analysis({
                        'system': 's',
                        'user': 'u',
                    })
                self.assertEqual(result.failure_reason, 'http_5xx')

    def test_http_401_maps_to_auth_error(self):
        error = urllib.error.HTTPError(
            'https://api.deepseek.com/chat/completions',
            401,
            'Unauthorized',
            {},
            io.BytesIO(b'{}'),
        )
        with patch(
            'agent.llm.deepseek_provider.urlopen',
            side_effect=error,
        ):
            result = configured_provider().generate_structured_analysis({
                'system': 's',
                'user': 'u',
            })
        self.assertEqual(result.failure_reason, 'auth_error')

    def test_network_error_and_timeout_are_mapped(self):
        with patch(
            'agent.llm.deepseek_provider.urlopen',
            side_effect=urllib.error.URLError('socket disconnected'),
        ):
            result = configured_provider().generate_structured_analysis({
                'system': 's',
                'user': 'u',
            })
        self.assertEqual(result.failure_reason, 'network_error')

        with patch(
            'agent.llm.deepseek_provider.urlopen',
            side_effect=TimeoutError('timed out'),
        ):
            result = configured_provider().generate_structured_analysis({
                'system': 's',
                'user': 'u',
            })
        self.assertEqual(result.failure_reason, 'timeout')

    def test_invalid_json_body_is_rejected(self):
        with patch(
            'agent.llm.deepseek_provider.urlopen',
            return_value=FakeHTTPResponse('not json at all'),
        ):
            result = configured_provider().generate_structured_analysis({
                'system': 's',
                'user': 'u',
            })
        self.assertEqual(result.failure_reason, 'invalid_json')

    def test_empty_response_and_non_json_content_are_rejected(self):
        with patch(
            'agent.llm.deepseek_provider.urlopen',
            return_value=FakeHTTPResponse(''),
        ):
            result = configured_provider().generate_structured_analysis({
                'system': 's',
                'user': 'u',
            })
        self.assertEqual(result.failure_reason, 'invalid_response')

        with patch(
            'agent.llm.deepseek_provider.urlopen',
            return_value=FakeHTTPResponse(chat_response_with_content('plain prose without json')),
        ):
            result = configured_provider().generate_structured_analysis({
                'system': 's',
                'user': 'u',
            })
        self.assertEqual(result.failure_reason, 'invalid_json')

    def test_repr_never_exposes_api_key(self):
        provider = configured_provider()
        representation = repr(provider)
        self.assertIn('deepseek', representation)
        self.assertNotIn('test-secret-key', representation)
