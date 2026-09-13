"""Gemini is strictly optional and may never touch a calculated number."""
from decimal import Decimal
import pytest
from app.extraction.gemini import GeminiExtractor, GeminiUnavailable, GeminiParseFailure
from app.extraction.orchestrator import fallback
from app.comparison.service import compare
from tests.conftest import MONTH, make_amc, make_document, make_fund, parsed_scheme
from tests.test_comparison import FUND_A, FUND_B


class FakeExtractor:
    """Stands in for the HTTP client; returns whatever the test supplies."""
    def __init__(self, response):
        self.response = response
        self.calls = 0

    def request(self, prompt, schema=None):
        self.calls += 1
        if isinstance(self.response, Exception):
            raise self.response
        return self.response


def extractor_with(response):
    extractor = GeminiExtractor(client=object(), api_key='test-key')
    extractor.request = FakeExtractor(response).request
    return extractor


def incomplete_scheme():
    scheme = parsed_scheme(name='HDFC Flexi Cap Fund', holdings=[('Infosys Ltd.', 20)])
    scheme.snapshot.complete_holdings = False
    scheme.snapshot.portfolio_end_observed = False
    scheme.raw_text = 'PORTFOLIO ... Infosys Ltd. 20.00'
    return scheme


def test_comparison_works_with_gemini_unavailable(session, monkeypatch):
    amc = make_amc(session)
    document = make_document(session, amc)
    a = make_fund(session, amc, document, 'Fund A', FUND_A)
    b = make_fund(session, amc, document, 'Fund B', FUND_B)
    monkeypatch.setattr('app.config.settings.gemini_api_key', type(
        'S', (), {'get_secret_value': staticmethod(lambda: '')})())
    result = compare(session, a.id, b.id, MONTH)
    assert result['comparison']['a_top10_in_b_pct'] == Decimal('74.00')
    with pytest.raises(GeminiUnavailable):
        GeminiExtractor(client=object(), api_key='').request('anything')


def test_gemini_fallback_returns_a_validated_scheme():
    scheme = incomplete_scheme()
    payload = parsed_scheme(name='HDFC Flexi Cap Fund',
                            holdings=[('Infosys Ltd.', 60), ('TCS Ltd.', 40)]).model_dump_json()
    result, used = fallback(scheme, extractor_with(payload))
    assert used
    assert [h.raw_company_name for h in result.holdings] == ['Infosys Ltd.', 'TCS Ltd.']
    assert all(h.extraction_method == 'GEMINI' for h in result.holdings)
    assert result.snapshot.complete_holdings


def test_malformed_gemini_response_goes_to_review():
    scheme = incomplete_scheme()
    result, used = fallback(scheme, extractor_with('{"not":"a scheme"}'))
    assert used
    assert result.extraction_status == 'REVIEW_REQUIRED'
    assert any(issue.startswith('GEMINI_PARSE_FAILURE') for issue in result.issues)
    # The deterministic holdings are preserved, never replaced by the bad response.
    assert [h.raw_company_name for h in result.holdings] == ['Infosys Ltd.']


def test_gemini_cannot_relabel_the_scheme_or_the_month():
    scheme = incomplete_scheme()
    wrong = parsed_scheme(name='Some Other Fund', holdings=[('Infosys Ltd.', 100)]).model_dump_json()
    result, used = fallback(scheme, extractor_with(wrong))
    assert result.extraction_status == 'REVIEW_REQUIRED'


def test_gemini_unavailable_leaves_the_deterministic_scheme_untouched():
    scheme = incomplete_scheme()
    result, used = fallback(scheme, extractor_with(GeminiUnavailable('offline')))
    assert not used
    assert result is scheme and result.extraction_status == 'EXTRACTED'


def test_a_validated_scheme_never_calls_gemini():
    scheme = parsed_scheme(holdings=[('Infosys Ltd.', 100)])
    fake = FakeExtractor('should not be used')
    extractor = GeminiExtractor(client=object(), api_key='k')
    extractor.request = fake.request
    result, used = fallback(scheme, extractor)
    assert not used and fake.calls == 0


def test_explanation_containing_numbers_is_withheld():
    extractor = extractor_with('The funds overlap by 74% on the top holdings.')
    with pytest.raises(GeminiParseFailure):
        extractor.explain({'a_top10_in_b_pct': 74})
    prose = extractor_with('Both portfolios lean heavily on large private banks and software exporters.')
    assert 'banks' in prose.explain({'a_top10_in_b_pct': 74})
