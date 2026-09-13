"""Deterministic overlap engine. Every published percentage originates here, never from an LLM."""
from decimal import Decimal
from sqlalchemy import select, func
from app.db.models import (Scheme, SchemeMonthlySnapshot, Holding, Security, Industry, AMC)

TOP_N = 10
# Comparison is restricted to listed equity; REIT/InvIT exposure stays on the snapshot.
COMPARABLE_TYPES = ('EQUITY',)


class ComparisonError(ValueError):
    pass


def _quantize(value):
    return Decimal(value).quantize(Decimal('0.01'))


def equity_universe(session):
    """Only schemes whose official product label established equity eligibility."""
    return (select(Scheme).where(Scheme.asset_class == 'EQUITY',
                                 Scheme.classification_status == 'INCLUDED',
                                 Scheme.active.is_(True)))


def list_funds(session, query=None, as_of_date=None, limit=200):
    statement = equity_universe(session).join(AMC, AMC.id == Scheme.amc_id)
    if query:
        pattern = f'%{query.lower()}%'
        statement = statement.where(func.lower(Scheme.scheme_name).like(pattern) |
                                    func.lower(AMC.name).like(pattern))
    if as_of_date:
        statement = statement.where(Scheme.id.in_(
            select(SchemeMonthlySnapshot.scheme_id).where(SchemeMonthlySnapshot.as_of_date == as_of_date)))
    statement = statement.order_by(AMC.name, Scheme.scheme_name).limit(limit)
    funds = []
    for scheme in session.scalars(statement):
        funds.append({'scheme_id': scheme.id, 'amc': session.get(AMC, scheme.amc_id).name,
                      'scheme_name': scheme.scheme_name, 'category': scheme.category,
                      'management_style': scheme.management_style})
    return funds


def available_months(session, scheme_ids=None):
    """Months that have a snapshot; when two funds are given, only months common to both."""
    statement = select(SchemeMonthlySnapshot.as_of_date).join(
        Scheme, Scheme.id == SchemeMonthlySnapshot.scheme_id).where(
        Scheme.asset_class == 'EQUITY', Scheme.classification_status == 'INCLUDED')
    ids = [i for i in (scheme_ids or []) if i]
    if ids:
        statement = statement.where(SchemeMonthlySnapshot.scheme_id.in_(ids))
        statement = statement.group_by(SchemeMonthlySnapshot.as_of_date).having(
            func.count(func.distinct(SchemeMonthlySnapshot.scheme_id)) == len(set(ids)))
    else:
        statement = statement.group_by(SchemeMonthlySnapshot.as_of_date)
    return sorted(session.scalars(statement), reverse=True)


def latest_common_month(session, scheme_ids):
    """Section 37: never silently compare two different months."""
    months = available_months(session, scheme_ids)
    return months[0] if months else None


def _snapshot(session, scheme_id, as_of_date):
    scheme = session.get(Scheme, scheme_id)
    if scheme is None:
        raise ComparisonError(f'Unknown scheme {scheme_id}')
    if scheme.asset_class != 'EQUITY' or scheme.classification_status != 'INCLUDED':
        raise ComparisonError(f'{scheme.scheme_name} is not in the equity comparison universe')
    snapshot = session.scalar(select(SchemeMonthlySnapshot).where(
        SchemeMonthlySnapshot.scheme_id == scheme_id, SchemeMonthlySnapshot.as_of_date == as_of_date))
    if snapshot is None:
        raise ComparisonError(f'{scheme.scheme_name} has no snapshot for {as_of_date}')
    return scheme, snapshot


def _holdings(session, snapshot_id):
    """Full portfolio, ordered exactly as section 39 requires."""
    rows = session.execute(
        select(Holding, Security, Industry)
        .join(Security, Security.id == Holding.security_id)
        .outerjoin(Industry, Industry.id == Holding.industry_id)
        .where(Holding.scheme_snapshot_id == snapshot_id,
               Security.security_type.in_(COMPARABLE_TYPES))
        .order_by(Holding.weight_pct.desc(), Holding.security_id.asc())).all()
    return [{'security_id': h.security_id, 'company': s.canonical_name,
             'raw_company_name': h.raw_company_name,
             'industry': i.name if i is not None else None,
             'isin': s.isin, 'weight_pct': Decimal(h.weight_pct)} for h, s, i in rows]


def _fund_block(scheme, snapshot, holdings, amc_name):
    top = holdings[:TOP_N]
    return {'scheme_id': scheme.id, 'name': scheme.scheme_name, 'amc': amc_name,
            'category': scheme.category, 'management_style': scheme.management_style,
            'holding_count': len(holdings),
            'top10_total_pct': _quantize(sum((h['weight_pct'] for h in top), Decimal(0))),
            'top10': [{'company': h['company'], 'industry': h['industry'],
                       'weight_pct': _quantize(h['weight_pct'])} for h in top],
            'equity_pct': snapshot.equity_pct, 'aum_crore': snapshot.aum_crore,
            'validation_status': snapshot.validation_status,
            'complete_holdings': snapshot.complete_holdings}


def compare(session, fund_a_id, fund_b_id, as_of_date=None):
    if as_of_date is None:
        as_of_date = latest_common_month(session, [fund_a_id, fund_b_id])
        if as_of_date is None:
            raise ComparisonError('The two funds have no factsheet month in common')
    scheme_a, snap_a = _snapshot(session, fund_a_id, as_of_date)
    scheme_b, snap_b = _snapshot(session, fund_b_id, as_of_date)
    holdings_a = _holdings(session, snap_a.id)
    holdings_b = _holdings(session, snap_b.id)
    weights_a = {h['security_id']: h['weight_pct'] for h in holdings_a}
    weights_b = {h['security_id']: h['weight_pct'] for h in holdings_b}

    top_a_ids = [h['security_id'] for h in holdings_a[:TOP_N]]
    top_b_ids = [h['security_id'] for h in holdings_b[:TOP_N]]
    # Sections 40-41: a fund's own Top 10 valued using the *other* fund's complete portfolio.
    a_top10_in_b = sum((weights_b.get(i, Decimal(0)) for i in top_a_ids), Decimal(0))
    b_top10_in_a = sum((weights_a.get(i, Decimal(0)) for i in top_b_ids), Decimal(0))

    # Sections 42-43: full-portfolio intersection, measured against each side's own weights.
    common_ids = set(weights_a) & set(weights_b)
    common_weight_a = sum((weights_a[i] for i in common_ids), Decimal(0))
    common_weight_b = sum((weights_b[i] for i in common_ids), Decimal(0))
    symmetric = sum((min(weights_a[i], weights_b[i]) for i in common_ids), Decimal(0))

    by_id = {h['security_id']: h for h in holdings_a}
    by_id_b = {h['security_id']: h for h in holdings_b}
    common_holdings = [{'security_id': i, 'company': by_id[i]['company'],
                        'industry': by_id[i]['industry'] or by_id_b[i]['industry'],
                        'isin': by_id[i]['isin'],
                        'fund_a_pct': _quantize(weights_a[i]), 'fund_b_pct': _quantize(weights_b[i]),
                        'difference_pct': _quantize(weights_a[i] - weights_b[i])} for i in common_ids]
    common_holdings.sort(key=lambda r: (-(r['fund_a_pct'] + r['fund_b_pct']), r['company']))

    amc_a = session.get(AMC, scheme_a.amc_id)
    amc_b = session.get(AMC, scheme_b.amc_id)
    return {
        'as_of_date': as_of_date,
        'fund_a': _fund_block(scheme_a, snap_a, holdings_a, amc_a.name),
        'fund_b': _fund_block(scheme_b, snap_b, holdings_b, amc_b.name),
        'comparison': {
            'a_top10_in_b_pct': _quantize(a_top10_in_b),
            'b_top10_in_a_pct': _quantize(b_top10_in_a),
            'common_security_count': len(common_ids),
            'common_weight_a_pct': _quantize(common_weight_a),
            'common_weight_b_pct': _quantize(common_weight_b),
            'symmetric_weighted_overlap_pct': _quantize(symmetric),
        },
        'common_holdings': common_holdings,
        'unique_to_a_count': len(set(weights_a) - common_ids),
        'unique_to_b_count': len(set(weights_b) - common_ids),
    }


def explanation_payload(result):
    """Structured facts handed to Gemini; the model may never alter these numbers."""
    return {'fund_a': result['fund_a']['name'], 'fund_b': result['fund_b']['name'],
            'as_of_date': result['as_of_date'],
            **{k: v for k, v in result['comparison'].items()},
            'common_holdings': [{'company': h['company'], 'industry': h['industry']}
                                for h in result['common_holdings'][:25]]}
