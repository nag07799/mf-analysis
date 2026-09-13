from datetime import date
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.orm import Session
from app.db.session import get_session
from app.db.models import Scheme, SchemeMonthlySnapshot, AMC
from app.comparison.service import (list_funds, available_months, latest_common_month,
                                    _holdings, _snapshot, ComparisonError)

router = APIRouter(prefix='/api/v1', tags=['funds'])


@router.get('/funds')
def funds(q: str | None = None, as_of_date: date | None = None,
          limit: int = Query(200, ge=1, le=1000), session: Session = Depends(get_session)):
    """Equity-only fund universe for both selectors."""
    return {'funds': list_funds(session, q, as_of_date, limit)}


@router.get('/months')
def months(scheme_ids: list[int] = Query(default=[]), session: Session = Depends(get_session)):
    values = available_months(session, scheme_ids)
    return {'months': values,
            'latest_common_month': latest_common_month(session, scheme_ids) if scheme_ids else
                                   (values[0] if values else None)}


@router.get('/funds/{scheme_id}')
def fund_detail(scheme_id: int, session: Session = Depends(get_session)):
    scheme = session.get(Scheme, scheme_id)
    if scheme is None:
        raise HTTPException(404, 'Unknown scheme')
    amc = session.get(AMC, scheme.amc_id)
    snapshots = session.scalars(select(SchemeMonthlySnapshot)
                                .where(SchemeMonthlySnapshot.scheme_id == scheme_id)
                                .order_by(SchemeMonthlySnapshot.as_of_date.desc()))
    return {'scheme_id': scheme.id, 'amc': amc.name, 'name': scheme.scheme_name,
            'category': scheme.category, 'subcategory': scheme.subcategory,
            'management_style': scheme.management_style, 'benchmark': scheme.benchmark,
            'additional_benchmark': scheme.additional_benchmark,
            'inception_date': scheme.inception_date, 'asset_class': scheme.asset_class,
            'classification_status': scheme.classification_status,
            'months': [s.as_of_date for s in snapshots]}


@router.get('/funds/{scheme_id}/holdings')
def holdings(scheme_id: int, as_of_date: date | None = None, session: Session = Depends(get_session)):
    if as_of_date is None:
        as_of_date = latest_common_month(session, [scheme_id])
        if as_of_date is None:
            raise HTTPException(404, 'No snapshot available for this scheme')
    try:
        scheme, snapshot = _snapshot(session, scheme_id, as_of_date)
    except ComparisonError as exc:
        raise HTTPException(404, str(exc)) from None
    rows = _holdings(session, snapshot.id)
    return {'scheme_id': scheme.id, 'name': scheme.scheme_name, 'as_of_date': as_of_date,
            'holding_count': len(rows), 'validation_status': snapshot.validation_status,
            'complete_holdings': snapshot.complete_holdings,
            'equity_pct': snapshot.equity_pct, 'reit_pct': snapshot.reit_pct,
            'invit_pct': snapshot.invit_pct, 'debt_pct': snapshot.debt_pct,
            'cash_pct': snapshot.cash_pct, 'debt_cash_pct': snapshot.debt_cash_pct,
            'holdings': [{k: v for k, v in row.items() if k != 'security_id'} for row in rows]}
