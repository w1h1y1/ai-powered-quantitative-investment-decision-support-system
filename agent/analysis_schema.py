"""Structured Investment Agent analysis schema and validation."""

ANALYSIS_VERSION = 'investment_agent_analysis_v1'

SUMMARY_FIELDS = (
    'market_summary',
    'market_regime_summary',
    'technical_summary',
    'market_context_summary',
    'historical_evidence_summary',
    'risk_assessment',
)

LIST_FIELDS = (
    'key_reasons',
    'risk_factors',
    'limitations',
)

ALL_ANALYSIS_FIELDS = SUMMARY_FIELDS + LIST_FIELDS


class AnalysisValidationError(ValueError):
    """Raised when provider output does not match the analysis schema."""

    def __init__(self, message, *, details=None):
        super().__init__(message)
        self.details = details or {}


def normalize_analysis(data):
    """Validate and normalize one structured analysis object.

    Only the allowed fields survive normalization.  Unknown keys (for example
    hallucinated action_bias or confidence values) are dropped instead of
    being passed through to the API.  All schema problems are collected before
    raising so diagnostics can report every failing field at once.
    """

    if not isinstance(data, dict):
        raise AnalysisValidationError(
            'analysis must be a JSON object',
            details={
                'validation_error_type': 'not_an_object',
                'expected_type': 'object',
                'actual_type': type(data).__name__,
            },
        )

    missing_fields = []
    wrong_type_fields = []
    normalized = {'analysis_version': ANALYSIS_VERSION}
    for field in SUMMARY_FIELDS:
        value = data.get(field)
        if not isinstance(value, str) or not value.strip():
            if field not in data or value is None:
                missing_fields.append(field)
            else:
                wrong_type_fields.append({
                    'field': field,
                    'expected_type': 'string',
                    'actual_type': type(value).__name__,
                })
            continue
        normalized[field] = value.strip()

    for field in LIST_FIELDS:
        value = data.get(field, [])
        if value is None:
            value = []
        if not isinstance(value, list) or not all(
            isinstance(item, str) for item in value
        ):
            wrong_type_fields.append({
                'field': field,
                'expected_type': 'array of strings',
                'actual_type': type(value).__name__,
            })
            continue
        normalized[field] = [item.strip() for item in value if item.strip()]

    extra_fields = [
        field
        for field in data
        if field not in ALL_ANALYSIS_FIELDS
    ]
    if missing_fields or wrong_type_fields:
        raise AnalysisValidationError(
            'structured analysis does not match the schema',
            details={
                'validation_error_type': 'schema_mismatch',
                'missing_fields': missing_fields,
                'wrong_type_fields': wrong_type_fields,
                'extra_fields': extra_fields,
            },
        )

    return normalized
