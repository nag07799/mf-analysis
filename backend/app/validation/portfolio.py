from decimal import Decimal
from app.normalization.securities import normalize_name

TOLERANCE = Decimal('0.10')

def validate_portfolio(scheme):
    errors = []
    s = scheme.snapshot
    seen = set()
    for h in scheme.holdings:
        key = h.isin or normalize_name(h.raw_company_name)
        if key in seen:
            errors.append('DUPLICATE_SECURITY')
        seen.add(key)
        if not 0 <= h.weight_pct <= 100:
            errors.append('INVALID_WEIGHT')
    equity = sum((h.weight_pct for h in scheme.holdings if h.security_type == 'EQUITY'), Decimal(0))
    # Fund houses disagree on whether REITs and InvITs belong inside the
    # disclosed "equity & equity related" total, so the extracted holdings are
    # allowed to reconcile against it either way.
    with_trusts = sum((h.weight_pct for h in scheme.holdings
                       if h.security_type in ('EQUITY', 'REIT', 'INVIT')), Decimal(0))
    # Allow per-row rounding (0.005 percentage points each), capped at 0.50.
    rounding = max(TOLERANCE, min(Decimal('0.50'), Decimal('0.005') * len(scheme.holdings)))
    if s.equity_pct is not None and min(abs(equity - s.equity_pct),
                                        abs(with_trusts - s.equity_pct)) > rounding:
        errors.append('EQUITY_TOTAL_MISMATCH')
    components = [s.equity_pct, s.reit_pct, s.invit_pct, s.debt_pct, s.cash_pct]
    if all(v is not None for v in components):
        if abs(sum(components) + (s.other_pct or Decimal(0)) - 100) > TOLERANCE:
            errors.append('PORTFOLIO_TOTAL_MISMATCH')
    if equity > 100 + rounding:
        errors.append('PORTFOLIO_TOTAL_MISMATCH')
    if not scheme.holdings or not s.complete_holdings or not s.portfolio_end_observed:
        errors.append('MISSING_COMPLETE_PORTFOLIO')
    errors = list(dict.fromkeys(errors))
    return ('FAILED' if any(x != 'MISSING_COMPLETE_PORTFOLIO' for x in errors)
            else 'REVIEW_REQUIRED' if errors else 'VALIDATED'), errors
