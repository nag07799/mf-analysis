"""Security identity, classification and portfolio validation rules."""
from decimal import Decimal
import pytest
from sqlalchemy import select
from app.db.models import Security, SecurityAlias
from app.normalization.securities import resolve_security, normalize_name, AmbiguousSecurity
from app.validation.classification import classify
from app.validation.portfolio import validate_portfolio
from app.schemas.parsed import ParsedHolding, ParsedScheme, ParsedSnapshot
from tests.conftest import MONTH, make_amc, parsed_scheme


def holding(name, isin=None, security_type='EQUITY', weight=1):
    return ParsedHolding(raw_company_name=name, isin=isin, weight_pct=Decimal(weight),
                         security_type=security_type)


def test_aliases_resolve_to_one_stable_security_id(session):
    amc = make_amc(session)
    first, created = resolve_security(session, holding('HDFC Bank Ltd.'), amc.id)
    assert created
    for variant in ('HDFC Bank Limited', 'HDFC BANK LTD', 'HDFC Bank Ltd', 'HDFC  Bank   Limited.'):
        again, created_again = resolve_security(session, holding(variant), amc.id)
        assert again.id == first.id and not created_again
    aliases = session.scalars(select(SecurityAlias).where(SecurityAlias.security_id == first.id)).all()
    assert len(aliases) == 5
    assert session.scalar(select(Security).where(Security.id != first.id)) is None


def test_isin_takes_priority_over_the_name(session):
    amc = make_amc(session)
    original, _ = resolve_security(session, holding('Bajaj Finance Ltd.', 'INE296A01024'), amc.id)
    renamed, created = resolve_security(session, holding('Bajaj Finance Limited (Merged)', 'INE296A01024'), amc.id)
    assert renamed.id == original.id and not created


def test_conflicting_isin_is_never_silently_merged(session):
    amc = make_amc(session)
    resolve_security(session, holding('Example Ltd.', 'INE111A01011'), amc.id)
    with pytest.raises(AmbiguousSecurity):
        resolve_security(session, holding('Example Ltd.', 'INE222A01012'), amc.id)


def test_same_name_different_security_type_stays_separate(session):
    amc = make_amc(session)
    equity, _ = resolve_security(session, holding('Embassy Office Parks'), amc.id)
    reit, created = resolve_security(session, holding('Embassy Office Parks', security_type='REIT'), amc.id)
    assert created and reit.id != equity.id


@pytest.mark.parametrize('category,description,expected_class,expected_status,style', [
    ('Flexi Cap Fund', 'An open ended dynamic equity scheme', 'EQUITY', 'INCLUDED', 'ACTIVE'),
    # Scope is actively managed domestic equity: tax savers and any passive
    # scheme (index or ETF) are out, as are debt, hybrid and fund-of-funds.
    ('ELSS', 'An open ended equity linked savings scheme', 'NON_EQUITY', 'EXCLUDED', None),
    ('Index Fund', 'An open ended scheme replicating the Nifty 50 index', 'NON_EQUITY', 'EXCLUDED', None),
    ('Equity Savings Fund', 'An open ended scheme investing in equity, arbitrage and debt',
     'NON_EQUITY', 'EXCLUDED', None),
    ('Retirement Fund', 'An open ended retirement solution oriented scheme',
     'NON_EQUITY', 'EXCLUDED', None),
    ('Silver ETF Fund of Fund', 'An open ended fund of fund investing in silver ETF',
     'NON_EQUITY', 'EXCLUDED', None),
    ('Arbitrage Fund', 'An open ended scheme investing in arbitrage opportunities', 'NON_EQUITY', 'EXCLUDED', None),
    ('Balanced Advantage', 'An open ended dynamic asset allocation fund', 'NON_EQUITY', 'EXCLUDED', None),
    ('Liquid Fund', 'An open ended liquid scheme', 'NON_EQUITY', 'EXCLUDED', None),
    ('Multi Asset Allocation', 'An open ended scheme investing in three asset classes', 'NON_EQUITY', 'EXCLUDED', None),
    ('Gold ETF', 'An open ended scheme tracking domestic gold prices', 'NON_EQUITY', 'EXCLUDED', None),
])
def test_classification_uses_the_official_product_label(category, description, expected_class, expected_status, style):
    scheme = ParsedScheme(scheme_name='Some Fund', category=category, official_description=description,
                          snapshot=ParsedSnapshot(as_of_date=MONTH))
    classify(scheme)
    assert (scheme.asset_class, scheme.classification_status) == (expected_class, expected_status)
    if style:
        assert scheme.management_style == style


def test_a_name_alone_never_establishes_equity():
    scheme = ParsedScheme(scheme_name='HDFC Large Cap Fund', snapshot=ParsedSnapshot(as_of_date=MONTH))
    classify(scheme)
    assert scheme.asset_class == 'UNRESOLVED'
    assert scheme.classification_status == 'REVIEW_REQUIRED'


def test_portfolio_total_validation():
    ok = parsed_scheme(holdings=[('A Ltd.', 60), ('B Ltd.', 38.92)])
    ok.snapshot.equity_pct = Decimal('98.92')
    ok.snapshot.reit_pct = Decimal('0.47')
    ok.snapshot.invit_pct = Decimal('0')
    ok.snapshot.debt_pct = Decimal('0')
    ok.snapshot.cash_pct = Decimal('0.61')
    assert validate_portfolio(ok) == ('VALIDATED', [])

    broken = parsed_scheme(holdings=[('A Ltd.', 60), ('B Ltd.', 30)])
    broken.snapshot.equity_pct = Decimal('95.00')
    status, errors = validate_portfolio(broken)
    assert status == 'FAILED' and 'EQUITY_TOTAL_MISMATCH' in errors


def test_incomplete_portfolio_is_review_not_silent_acceptance():
    scheme = parsed_scheme(holdings=[('A Ltd.', 100)])
    scheme.snapshot.portfolio_end_observed = False
    status, errors = validate_portfolio(scheme)
    assert status == 'REVIEW_REQUIRED' and errors == ['MISSING_COMPLETE_PORTFOLIO']


@pytest.mark.parametrize('category,description,expected', [
    # "fmcg sector" must not be read as the "g sec" of a gilt fund.
    ('Sectoral', 'An open ended equity scheme investing in fmcg sector', 'INCLUDED'),
    # An equity scheme holding commodity-sector shares is still equity.
    ('Thematic', 'An open ended equity scheme investing primarily in commodities '
                 'and commodity related sectors.', 'INCLUDED'),
    ('Sectoral', 'An open ended equity scheme investing in gold mining companies', 'INCLUDED'),
    # The genuine commodity products stay out.
    ('Gold ETF', 'An open ended scheme tracking domestic gold prices', 'EXCLUDED'),
    ('FOF', 'An open ended fund of fund investing in gold ETF', 'EXCLUDED'),
    ('Gilt Fund', 'An open ended debt scheme investing in g-sec', 'EXCLUDED'),
])
def test_a_sector_word_does_not_outrank_the_equity_product_label(category, description, expected):
    scheme = ParsedScheme(scheme_name='Some Fund', category=category,
                          official_description=description,
                          snapshot=ParsedSnapshot(as_of_date=MONTH))
    classify(scheme)
    assert scheme.classification_status == expected
