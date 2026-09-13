from app.extraction.gemini import GeminiExtractor, GeminiParseFailure, GeminiUnavailable
from app.validation.classification import classify
from app.validation.portfolio import validate_portfolio

def fallback(scheme, extractor=None):
    if scheme.classification_status != 'INCLUDED' or validate_portfolio(scheme)[0]=='VALIDATED':
        return scheme,False
    try:
        parsed=(extractor or GeminiExtractor()).extract(scheme)
        classify(parsed)
        return parsed,True
    except GeminiUnavailable:
        return scheme,False
    except GeminiParseFailure as exc:
        scheme.extraction_status='REVIEW_REQUIRED'
        scheme.issues.append('GEMINI_PARSE_FAILURE: '+str(exc))
        return scheme,True
