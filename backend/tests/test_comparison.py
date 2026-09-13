"""Overlap engine. Section 45's exact numbers are the acceptance gate for Phase 2."""
from datetime import date
from decimal import Decimal
import pytest
from app.comparison.service import compare, latest_common_month, available_months, ComparisonError
from tests.conftest import MONTH, make_amc, make_document, make_fund

FUND_A = {'ICICI Bank': 16, 'HDFC Bank': 14, 'Reliance': 12, 'Bharti Airtel': 11, 'Infosys': 10,
          'L&T': 9, 'SBI': 8, 'Axis Bank': 7, 'Maruti': 5, 'TCS': 4, 'Sun Pharma': 4}
FUND_B = {'Reliance': 15, 'HDFC Bank': 13, 'TCS': 12, 'Infosys': 11, 'Axis Bank': 10, 'ITC': 9,
          'ICICI Bank': 8, 'Sun Pharma': 7, 'Bajaj Finance': 6, 'L&T': 5, 'Nestle India': 4}


@pytest.fixture
def two_funds(session):
    amc = make_amc(session)
    document = make_document(session, amc)
    a = make_fund(session, amc, document, 'Fund A', FUND_A)
    b = make_fund(session, amc, document, 'Fund B', FUND_B)
    return session, a, b


def test_exact_eleven_stock_example(two_funds):
    session, a, b = two_funds
    result = compare(session, a.id, b.id, MONTH)
    assert result['fund_a']['holding_count'] == 11
    assert result['fund_b']['holding_count'] == 11
    assert result['fund_a']['top10_total_pct'] == Decimal('96.00')
    assert result['fund_b']['top10_total_pct'] == Decimal('96.00')
    c = result['comparison']
    assert c['a_top10_in_b_pct'] == Decimal('74.00')
    assert c['b_top10_in_a_pct'] == Decimal('76.00')
    assert c['common_security_count'] == 8
    assert c['common_weight_a_pct'] == Decimal('76.00')
    assert c['common_weight_b_pct'] == Decimal('81.00')
    assert {h['company'] for h in result['common_holdings']} == {
        'ICICI Bank', 'HDFC Bank', 'Reliance', 'Infosys', 'L&T', 'Axis Bank', 'TCS', 'Sun Pharma'}


def test_symmetric_overlap_is_reported_separately(two_funds):
    session, a, b = two_funds
    c = compare(session, a.id, b.id, MONTH)['comparison']
    # min() of each common pair: 8+13+12+10+5+7+4+4
    assert c['symmetric_weighted_overlap_pct'] == Decimal('63.00')
    assert c['common_weight_a_pct'] != c['symmetric_weighted_overlap_pct']


def test_eighteen_versus_thirty_holdings(session):
    amc = make_amc(session)
    document = make_document(session, amc)
    a = make_fund(session, amc, document, 'A18', {f'Stock {i}': 100 / 18 for i in range(18)})
    b = make_fund(session, amc, document, 'B30', {f'Stock {i}': 100 / 30 for i in range(30)})
    result = compare(session, a.id, b.id, MONTH)
    assert result['fund_a']['holding_count'] == 18
    assert result['fund_b']['holding_count'] == 30
    assert len(result['fund_a']['top10']) == 10
    assert result['comparison']['common_security_count'] == 18
    assert result['unique_to_b_count'] == 12


def test_fund_compared_with_itself_is_total_overlap(session):
    amc = make_amc(session)
    document = make_document(session, amc)
    a = make_fund(session, amc, document, 'Fund A', FUND_A)
    result = compare(session, a.id, a.id, MONTH)
    c = result['comparison']
    assert c['common_security_count'] == 11
    assert c['common_weight_a_pct'] == c['common_weight_b_pct'] == Decimal('100.00')
    assert c['a_top10_in_b_pct'] == c['b_top10_in_a_pct'] == Decimal('96.00')


def test_no_common_holdings(session):
    amc = make_amc(session)
    document = make_document(session, amc)
    a = make_fund(session, amc, document, 'A', {'Alpha': 60, 'Beta': 40})
    b = make_fund(session, amc, document, 'B', {'Gamma': 70, 'Delta': 30})
    c = compare(session, a.id, b.id, MONTH)['comparison']
    assert c['common_security_count'] == 0
    assert c['common_weight_a_pct'] == c['common_weight_b_pct'] == Decimal('0.00')
    assert c['a_top10_in_b_pct'] == Decimal('0.00')


def test_fund_with_fewer_than_ten_holdings(session):
    amc = make_amc(session)
    document = make_document(session, amc)
    small = {f'S{i}': 12.5 for i in range(8)}
    a = make_fund(session, amc, document, 'Small', small)
    b = make_fund(session, amc, document, 'Fund B', FUND_B)
    result = compare(session, a.id, b.id, MONTH)
    assert len(result['fund_a']['top10']) == 8
    assert result['fund_a']['top10_total_pct'] == Decimal('100.00')


def test_same_month_rule_and_latest_common_month(session):
    amc = make_amc(session)
    july = make_document(session, amc, sha='b' * 64)
    august = make_document(session, amc, month=date(2026, 8, 31), sha='c' * 64)
    a = make_fund(session, amc, july, 'Fund A', FUND_A)
    make_fund(session, amc, august, 'Fund A Aug', {'ICICI Bank': 50, 'TCS': 50},
              as_of_date=date(2026, 8, 31))
    session.query(type(a)).filter_by(id=a.id)  # keep the scheme attached
    b = make_fund(session, amc, july, 'Fund B', FUND_B)
    # Fund A also has August, Fund B does not; the shared month is July.
    assert latest_common_month(session, [a.id, b.id]) == MONTH
    assert compare(session, a.id, b.id)['as_of_date'] == MONTH
    with pytest.raises(ComparisonError):
        compare(session, a.id, b.id, date(2026, 8, 31))


def test_non_equity_scheme_is_not_comparable(session):
    amc = make_amc(session)
    document = make_document(session, amc)
    a = make_fund(session, amc, document, 'Fund A', FUND_A)
    debt = make_fund(session, amc, document, 'Debt Fund', {'Bond A': 100})
    debt.asset_class, debt.classification_status = 'NON_EQUITY', 'EXCLUDED'
    session.flush()
    with pytest.raises(ComparisonError):
        compare(session, a.id, debt.id, MONTH)
    assert available_months(session, [debt.id]) == []
