from django.test import SimpleTestCase

from agent.analysis_schema import (
    ALL_ANALYSIS_FIELDS,
    ANALYSIS_VERSION,
    AnalysisValidationError,
    normalize_analysis,
)
from agent.tests.fakes import valid_analysis


class AnalysisSchemaTests(SimpleTestCase):
    def test_valid_analysis_normalizes_with_version(self):
        normalized = normalize_analysis(valid_analysis())

        self.assertEqual(normalized['analysis_version'], ANALYSIS_VERSION)
        for field in ALL_ANALYSIS_FIELDS:
            self.assertIn(field, normalized)
        self.assertEqual(normalized['market_summary'], 'The market is mixed with elevated volatility.')
        self.assertEqual(normalized['key_reasons'][0], 'High volatility percentile')

    def test_missing_required_field_is_rejected(self):
        data = valid_analysis()
        del data['risk_assessment']
        with self.assertRaises(AnalysisValidationError) as raised:
            normalize_analysis(data)
        details = raised.exception.details
        self.assertIn('risk_assessment', details['missing_fields'])
        self.assertEqual(details['validation_error_type'], 'schema_mismatch')

    def test_empty_summary_is_rejected(self):
        data = valid_analysis()
        data['market_summary'] = '   '
        with self.assertRaises(AnalysisValidationError):
            normalize_analysis(data)

    def test_wrong_field_type_is_rejected(self):
        data = valid_analysis()
        data['technical_summary'] = ['not', 'a', 'string']
        with self.assertRaises(AnalysisValidationError):
            normalize_analysis(data)

    def test_list_fields_must_contain_only_strings(self):
        data = valid_analysis()
        data['key_reasons'] = 'a single string'
        with self.assertRaises(AnalysisValidationError):
            normalize_analysis(data)

        data = valid_analysis()
        data['risk_factors'] = ['ok', 42]
        with self.assertRaises(AnalysisValidationError):
            normalize_analysis(data)

    def test_non_dict_output_is_rejected(self):
        with self.assertRaises(AnalysisValidationError):
            normalize_analysis(['not', 'an', 'object'])

    def test_unknown_fields_are_dropped_not_passed_through(self):
        data = valid_analysis()
        data['action_bias'] = 'favorable'
        data['confidence'] = 95
        data['trade_signal'] = 'BUY'
        normalized = normalize_analysis(data)

        self.assertNotIn('action_bias', normalized)
        self.assertNotIn('confidence', normalized)
        self.assertNotIn('trade_signal', normalized)

    def test_whitespace_is_stripped_from_summaries(self):
        data = valid_analysis()
        data['market_summary'] = '  The market is calm.  '
        normalized = normalize_analysis(data)
        self.assertEqual(normalized['market_summary'], 'The market is calm.')

    def test_diagnostics_report_wrong_type_with_expected_and_actual(self):
        data = valid_analysis()
        data['limitations'] = 'a single prose string'
        with self.assertRaises(AnalysisValidationError) as raised:
            normalize_analysis(data)
        wrong_type = raised.exception.details['wrong_type_fields']
        self.assertEqual(wrong_type[0]['field'], 'limitations')
        self.assertEqual(wrong_type[0]['expected_type'], 'array of strings')
        self.assertEqual(wrong_type[0]['actual_type'], 'str')

    def test_diagnostics_report_extra_fields(self):
        data = valid_analysis()
        data['action_bias'] = 'favorable'
        data['confidence'] = 95
        with self.assertRaises(AnalysisValidationError) as raised:
            data['market_summary'] = None
            normalize_analysis(data)
        details = raised.exception.details
        self.assertIn('market_summary', details['missing_fields'])
        self.assertIn('action_bias', details['extra_fields'])
        self.assertIn('confidence', details['extra_fields'])

    def test_diagnostics_collect_multiple_problems_at_once(self):
        data = valid_analysis()
        del data['market_context_summary']
        data['risk_factors'] = 'not a list'
        with self.assertRaises(AnalysisValidationError) as raised:
            normalize_analysis(data)
        details = raised.exception.details
        self.assertIn('market_context_summary', details['missing_fields'])
        self.assertEqual(details['wrong_type_fields'][0]['field'], 'risk_factors')
