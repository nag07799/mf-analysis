from datetime import date
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from app.db.session import get_session
from app.comparison.service import compare, explanation_payload, ComparisonError
from app.extraction.gemini import GeminiExtractor, GeminiUnavailable, GeminiParseFailure

router = APIRouter(prefix='/api/v1', tags=['compare'])


@router.get('/compare')
def compare_funds(fund_a_id: int, fund_b_id: int, as_of_date: date | None = None,
                  explain: bool = Query(False, description='Optional Gemini prose; never alters numbers'),
                  session: Session = Depends(get_session)):
    try:
        result = compare(session, fund_a_id, fund_b_id, as_of_date)
    except ComparisonError as exc:
        raise HTTPException(404, str(exc)) from None
    result['explanation'] = None
    result['explanation_status'] = 'NOT_REQUESTED'
    if explain:
        # The comparison response is already complete; Gemini only adds prose.
        try:
            result['explanation'] = GeminiExtractor().explain(explanation_payload(result))
            result['explanation_status'] = 'OK'
        except GeminiUnavailable:
            result['explanation_status'] = 'UNAVAILABLE'
        except GeminiParseFailure:
            result['explanation_status'] = 'WITHHELD'
    return result
