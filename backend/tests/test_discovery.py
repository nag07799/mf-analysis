"""Discovery and scheme-matching rules for the multi-AMC portfolio pipeline."""
from datetime import date

import pytest

from app.downloaders.generic import link_refers_to_month, months_in
from app.ingestion.top50 import (EXCLUDED_NAME, RankedScheme, cap_signature,
                                 match_all, match_portfolio, scheme_key,
                                 underlying_name)


class _Portfolio:
    """Minimal stand-in for a parsed portfolio; matching only reads the name."""

    def __init__(self, name):
        self.name = name


@pytest.mark.parametrize('text,expected', [
    ('Monthly Portfolio as on 31st July 2026.xlsx', (2026, 7)),
    ('PPFAS_Monthly_Portfolio_Report_July_31_2026.xls', (2026, 7)),
    ('sebi_monthly_portfolio-28-02-2025.zip', (2025, 2)),
    ('NIMF-MONTHLY-PORTFOLIO-31-Aug-26.xls', (2026, 8)),
    ('sml250_aug2026.xlsx', (2026, 8)),
    ('monthly-portfolio-nov-2012.zip', (2012, 11)),
])
def test_a_filename_states_the_month_it_reports(text, expected):
    assert expected in months_in(text)


def test_the_file_name_outranks_the_publication_folder():
    """A CMS files May's portfolio under the month it was published."""
    href = ('https://example.com/system/files/2026-06/'
            'Monthly%20Portfolio%20as%20on%2031st%20May%202026.xlsx')
    assert link_refers_to_month(href, date(2026, 5, 1))
    assert not link_refers_to_month(href, date(2026, 6, 1))


def test_a_hashed_file_name_falls_back_to_the_path():
    href = 'https://example.com/month-end-portfolio/2026/jul/a1b2c3.xlsx'
    assert link_refers_to_month(href, date(2026, 7, 1))
    assert not link_refers_to_month(href, date(2026, 8, 1))


@pytest.mark.parametrize('name,expected', [
    ('Mirae Asset Large & Midcap Fund', {'large', 'mid'}),
    ('Mirae Asset Midcap Fund', {'mid'}),
    ('NIPPON INDIA SMALL CAP FUND', {'small'}),
    ('HDFC Flexi Cap Fund', {'flexi'}),
    ('SBI CONTRA FUND', set()),
])
def test_cap_words_are_read_from_the_scheme_name(name, expected):
    assert cap_signature(name) == expected


def _target(name):
    return RankedScheme(rank=1, amc_name='X', amc_slug='x', scheme_name=name,
                        category='Equity Scheme - Large & Mid Cap Fund',
                        aaum_crore=0, amfi_codes=[])


def test_a_similar_name_with_different_cap_words_is_not_a_match():
    """"Large & Midcap" and "Midcap" pass a fuzzy threshold but differ."""
    candidates = [_Portfolio('Mirae Asset Midcap Fund')]
    matched, score = match_portfolio(_target('Mirae Asset Large & Midcap Fund'), candidates)
    assert matched is None and score == 0


def test_one_portfolio_is_never_claimed_by_two_schemes():
    portfolio = _Portfolio('Mirae Asset Midcap Fund')
    first, _ = match_portfolio(_target('Mirae Asset Midcap Fund'), [portfolio])
    assert first is portfolio
    second, score = match_portfolio(_target('Mirae Asset Midcap Fund'), [portfolio],
                                    claimed={id(portfolio)})
    assert second is None and score == 0


def test_amfi_rename_history_is_dropped_before_matching():
    assert underlying_name(
        'ICICI Prudential Value Fund (erstwhile Value Discovery Fund)'
    ) == 'ICICI Prudential Value Fund'
    assert underlying_name('HDFC Flexi Cap Fund - Growth Option') == 'HDFC Flexi Cap Fund'


@pytest.mark.parametrize('name', [
    'HDFC ELSS Tax Saver', 'HDFC NIFTY 50 ETF', 'HDFC Nifty 50 Index Fund',
    'HDFC Equity Savings Fund', 'HDFC Hybrid Debt Fund', 'HDFC Multi-Asset Active FOF',
    'HDFC Gold ETF Fund of Fund', 'HDFC Silver ETF Fund of Fund',
    'ICICI Prudential Retirement Fund', 'Bandhan Arbitrage Fund',
])
def test_out_of_scope_scheme_names_are_rejected_from_the_ranking(name):
    assert EXCLUDED_NAME.search(name)


@pytest.mark.parametrize('name', [
    'Parag Parikh Flexi Cap Fund', 'HDFC Mid Cap Fund', 'SBI CONTRA FUND',
    'ICICI Prudential Value Fund', 'Motilal Oswal Large and Midcap Fund',
])
def test_active_equity_scheme_names_stay_in_the_ranking(name):
    assert not EXCLUDED_NAME.search(name)


@pytest.mark.parametrize('raw,expected', [
    ('Aditya Birla Sun Life Digital India Fund -DIRECT',
     'Aditya Birla Sun Life Digital India Fund'),
    ('Aditya Birla Sun Life Banking and Financial Services Fund - REGULAR',
     'Aditya Birla Sun Life Banking and Financial Services Fund'),
    ('Motilal Oswal Large and Midcap Fund Regular',
     'Motilal Oswal Large and Midcap Fund'),
    ('HDFC Flexi Cap Fund - Direct Plan', 'HDFC Flexi Cap Fund'),
])
def test_a_bare_plan_word_is_still_a_plan_suffix(raw, expected):
    assert underlying_name(raw) == expected


def test_a_plan_word_inside_the_fund_name_is_kept():
    """Only a trailing or separated word is a plan marker."""
    assert underlying_name('HDFC Direct Equity Fund') == 'HDFC Direct Equity Fund'


def test_joined_and_spaced_cap_words_are_one_scheme():
    assert (scheme_key('Nippon India Vision Large & Midcap Fund')
            == scheme_key('NIPPON INDIA VISION LARGE & MID CAP FUND'))


def test_an_exact_name_outranks_a_fuzzy_one_regardless_of_order():
    """A scheme with no portfolio must not take one that another matches exactly."""
    portfolio = _Portfolio('ICICI Prudential FMCG Fund')
    no_portfolio = _target('ICICI Prudential MNC Fund')
    owner = _target('ICICI Prudential FMCG Fund')
    no_portfolio.rank, owner.rank = 1, 2
    assigned = match_all([no_portfolio, owner], [portfolio])
    assert assigned[owner.rank][0] is portfolio
    assert assigned[no_portfolio.rank][0] is None


@pytest.mark.parametrize('raw,expected', [
    ('NIPPON INDIA GROWTH MID CAP FUND - INSTITUTIONAL Plan',
     'NIPPON INDIA GROWTH MID CAP FUND'),
    ('Kotak Infrastructure & Economic Reform Fund - Standard Plan',
     'Kotak Infrastructure & Economic Reform Fund'),
    ('Kotak Flexi Cap Fund - Payout of Income Distribution cum capital withdrawal option',
     'Kotak Flexi Cap Fund'),
    ('Sundaram Multi Cap Fund- Income Distribution CUM Capital Withdrawal Option (IDCW)',
     'Sundaram Multi Cap Fund'),
    ('BANK OF INDIA Large & Mid Cap Fund Eco Plan', 'BANK OF INDIA Large & Mid Cap Fund'),
    ('Edelweiss Large Cap Fund - Plan B', 'Edelweiss Large Cap Fund'),
])
def test_a_legacy_share_class_folds_into_its_fund(raw, expected):
    """One portfolio backs every share class, so they must rank as one scheme."""
    assert underlying_name(raw) == expected


def test_a_class_word_inside_the_fund_name_is_kept():
    assert underlying_name('HDFC Retail Banking Fund') == 'HDFC Retail Banking Fund'


def test_the_same_scheme_in_two_workbooks_counts_once():
    """A twin parse must not stay free for another scheme to fuzzy-match."""
    from app.ingestion.top50 import dedupe_portfolios

    class _P(_Portfolio):
        complete = True

    first, twin = _P('ICICI Prudential Quant Fund'), _P('ICICI Prudential Quant Fund')
    other = _P('ICICI Prudential Value Fund')
    kept = dedupe_portfolios([(first, 'docA'), (twin, 'docB'), (other, 'docA')])
    assert len(kept) == 2
    assigned = match_all([_target('ICICI Prudential Quality Fund'),
                          _target('ICICI Prudential Quant Fund')],
                         [item for item, _ in kept])
    claimed = [a for a, _ in assigned.values() if a is not None]
    assert len(claimed) == len(set(id(c) for c in claimed))


@pytest.mark.parametrize('scheme,other', [
    ('ICICI Prudential MNC Fund', 'ICICI Prudential FMCG Fund'),
    ('ICICI Prudential Quant Fund', 'ICICI Prudential Quality Fund'),
    ('ICICI Prudential MNC Fund', 'ICICI Prudential Child Care Fund (Gift Plan)'),
])
def test_a_shared_house_name_does_not_make_two_funds_match(scheme, other):
    """Whole-name scoring rates these above 0.72 on the AMC prefix alone."""
    target = _target(scheme)
    target.amc_name = 'ICICI Prudential Mutual Fund'
    assigned = match_all([target], [_Portfolio(other)])
    assert assigned[target.rank][0] is None


def test_the_strategy_words_still_match_across_spelling():
    target = _target('Nippon India Large Cap Fund')
    target.amc_name = 'Nippon India Mutual Fund'
    portfolio = _Portfolio('NIPPON INDIA LARGE CAP FUND')
    assert match_all([target], [portfolio])[target.rank][0] is portfolio


def test_a_passive_portfolio_is_not_a_candidate_for_an_active_fund():
    """An AMC publishes ETF portfolios beside active ones; scope rules both."""
    from app.ingestion.top50 import in_scope_portfolios

    etf = _Portfolio('Mirae Asset Nifty Smallcap 250 ETF')
    active = _Portfolio('Mirae Asset Small Cap Fund')
    kept = in_scope_portfolios([(etf, 'doc'), (active, 'doc')])
    assert [item for item, _ in kept] == [active]


@pytest.mark.parametrize('name', [
    'Nippon India Taiwan Equity Fund', 'NIPPON INDIA - JAPAN EQUITY FUND',
    'NIPPON INDIA - US EQUITY OPPORTUNITIES FUND',
])
def test_country_funds_are_not_domestic_equity(name):
    assert EXCLUDED_NAME.search(name)


def test_an_indian_fund_named_after_a_sector_is_kept():
    for name in ('ICICI Prudential India Opportunities Fund', 'Tata Ethical Fund',
                 'HDFC Housing Opportunities Fund'):
        assert not EXCLUDED_NAME.search(name)


def test_holdings_decide_when_the_name_does_not():
    """An unenumerated country fund is still caught by where it is listed."""
    from app.ingestion.top50 import is_foreign_portfolio

    class _H:
        def __init__(self, isin): self.isin = isin

    class _P:
        def __init__(self, isins): self.holdings = [_H(i) for i in isins]

    assert is_foreign_portfolio(_P(['US02079K3059', 'US0231351067', 'INE040A01034']))
    # A domestic fund holding one depositary receipt stays in scope.
    assert not is_foreign_portfolio(_P(['INE040A01034', 'INE009A01021', 'US8740391003']))
