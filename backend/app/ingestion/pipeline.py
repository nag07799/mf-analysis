"""Document -> schemes -> snapshot orchestration.

Extraction order follows the specification: deterministic parsing first, the official
portfolio disclosure when the factsheet lacks complete constituents, Gemini only after
both, and a review item when all three fail. No stage may invent a value.
"""
from datetime import date, datetime, timezone
from pathlib import Path
import hashlib
from app.db.models import IngestionRun
from app.downloaders.base import BaseAMCDownloader, Document, DownloadedDocument, SourceUnavailable
from app.downloaders.hdfc import HDFCDownloader
from app.downloaders.icici import ICICIDownloader
from app.parsers.hdfc import HDFCParser
from app.parsers.icici import ICICIParser
from app.parsers.portfolio import parse_portfolios, apply_portfolio, scheme_key
from app.extraction.orchestrator import fallback
from app.ingestion.service import get_amc, register_document, persist_scheme, review

DOWNLOADERS = {'hdfc': HDFCDownloader, 'icici': ICICIDownloader}
PARSERS = {'hdfc': HDFCParser, 'icici': ICICIParser}


def previous_month(today=None):
    """The 10th of September targets the August factsheet."""
    today = today or date.today()
    return date(today.year - 1, 12, 1) if today.month == 1 else date(today.year, today.month - 1, 1)


def detect_file_month(path):
    import pymupdf
    from app.parsers.base import detect_month
    with pymupdf.open(path) as pdf:
        return detect_month(pdf)


def local_document(path, target_month, document_type='FACTSHEET', document_key='local'):
    """Wrap a manually supplied file so the CLI path shares the archive bookkeeping."""
    path = Path(path).resolve()
    content = path.read_bytes()
    return DownloadedDocument(Document('', target_month, document_key, document_type), path,
                              hashlib.sha256(content).hexdigest(), path.name)


def load_portfolios(session, run, amc, downloads, target_month):
    """Parse every official portfolio disclosure once, keyed by normalized scheme name."""
    portfolios = {}
    for downloaded in downloads:
        document, _ = register_document(session, amc.id, downloaded)
        try:
            portfolios.update(parse_portfolios(downloaded.path, target_month, document.id))
        except Exception as exc:
            review(session, run, document, None, 'REGEX_PARSE_FAILURE',
                   f'Portfolio workbook unreadable: {type(exc).__name__}: {exc}'[:1000])
    return portfolios


def ingest_document(session, run, amc, downloaded, portfolios=None, extractor=None, use_gemini=True):
    """Ingest one factsheet document. Returns a per-document coverage dictionary."""
    portfolios = portfolios or {}
    document, is_new_version = register_document(session, amc.id, downloaded)
    coverage = {'document': downloaded.filename, 'sha256': downloaded.sha256,
                'new_version': is_new_version, 'schemes': 0, 'equity': 0,
                'success': 0, 'review': 0, 'excluded': 0, 'already': 0,
                'holdings': 0, 'gemini': 0, 'portfolio_fallback': 0}
    parser = PARSERS[amc.slug]()
    try:
        schemes = parser.parse(downloaded.path, downloaded.document.target_month or None)
    except Exception as exc:
        reason = str(exc).split(':')[0] if ':' in str(exc) else 'REGEX_PARSE_FAILURE'
        reason = reason if reason in ('AMC_LAYOUT_CHANGED', 'DOCUMENT_MONTH_MISMATCH') else 'REGEX_PARSE_FAILURE'
        review(session, run, document, None, reason, str(exc)[:1000])
        coverage['error'] = f'{type(exc).__name__}: {exc}'[:500]
        run.schemes_failed += 1
        return coverage

    coverage['schemes'] = len(schemes)
    run.schemes_detected += len(schemes)
    for scheme in schemes:
        if scheme.classification_status != 'INCLUDED':
            persist_scheme(session, run, document, scheme)
            coverage['excluded'] += 1
            continue
        coverage['equity'] += 1
        run.equity_schemes_detected += 1
        # Fallback 1 - the AMC's own monthly portfolio disclosure.
        if not scheme.snapshot.complete_holdings:
            portfolio = portfolios.get(scheme_key(scheme.scheme_name))
            if portfolio and portfolio.as_of_date == scheme.snapshot.as_of_date:
                apply_portfolio(scheme, portfolio)
                if scheme.snapshot.complete_holdings:
                    coverage['portfolio_fallback'] += 1
        # Fallback 2 - Gemini, strictly schema-validated, never for arithmetic.
        if use_gemini and not scheme.snapshot.complete_holdings:
            scheme, used = fallback(scheme, extractor)
            if used:
                coverage['gemini'] += 1
                run.gemini_fallbacks_used += 1
        status, holdings, new, matched = persist_scheme(session, run, document, scheme)
        run.new_securities += new
        run.matched_securities += matched
        if status == 'SUCCESS':
            coverage['success'] += 1
            coverage['holdings'] += holdings
            run.schemes_successful += 1
            run.holdings_inserted += holdings
        elif status == 'ALREADY_INGESTED':
            coverage['already'] += 1
        elif status == 'REVIEW_REQUIRED':
            coverage['review'] += 1
            run.schemes_failed += 1
    return coverage


def start_run(session, amc, target_month):
    run = IngestionRun(target_month=target_month, amc_id=amc.id, status='RUNNING', coverage={})
    session.add(run)
    session.flush()
    return run


def finish_run(run, documents, blocked=False):
    run.completed_at = datetime.now(timezone.utc)
    run.coverage = {'documents': documents}
    if not documents:
        # An unreachable source is a failure to retry, not evidence that nothing is published.
        run.status = 'FAILED' if blocked else 'NOT_YET_AVAILABLE'
    elif run.schemes_failed and run.schemes_successful:
        run.status = 'PARTIAL_SUCCESS'
    elif run.schemes_successful:
        run.status = 'SUCCESS'
    else:
        run.status = 'FAILED'
    return run


def run_amc(session, slug, target_month, root=None, use_gemini=True, extractor=None,
            downloader=None, include_portfolios=True):
    """Discover, download and ingest one AMC for one month. Safe to re-run."""
    amc = get_amc(session, slug)
    run = start_run(session, amc, target_month)
    downloader = downloader or DOWNLOADERS[slug](root=root)
    documents = []
    errors = list(getattr(downloader, 'discovery_errors', []))
    try:
        discovered = downloader.discover_documents(target_month)
    except Exception as exc:
        discovered = []
        errors.append(f'factsheet discovery: {type(exc).__name__}: {exc}')
    portfolio_documents = []
    if include_portfolios:
        try:
            portfolio_documents = downloader.discover_portfolios(target_month)
        except Exception as exc:
            errors.append(f'portfolio discovery: {type(exc).__name__}: {exc}')
    errors += [e for e in getattr(downloader, 'discovery_errors', []) if e not in errors]
    run.documents_discovered = len(discovered) + len(portfolio_documents)

    downloaded_portfolios = []
    for document in portfolio_documents:
        try:
            downloaded_portfolios.append(downloader.download_document(document))
            run.documents_downloaded += 1
        except Exception as exc:
            errors.append(f'portfolio download: {type(exc).__name__}: {exc}')
    portfolios = load_portfolios(session, run, amc, downloaded_portfolios, target_month)

    for document in discovered:
        try:
            downloaded = downloader.download_document(document)
            run.documents_downloaded += 1
        except Exception as exc:
            errors.append(f'download {document.document_key}: {type(exc).__name__}: {exc}')
            continue
        documents.append(ingest_document(session, run, amc, downloaded, portfolios,
                                         extractor, use_gemini))
    finish_run(run, documents, blocked=bool(errors))
    if errors:
        run.error_summary = ' | '.join(errors)[:4000]
    session.commit()
    return run


def ingest_local_file(session, slug, path, target_month=None, portfolio_path=None,
                      use_gemini=True, extractor=None, root=None):
    """Manual CLI ingestion of an already downloaded official document."""
    amc = get_amc(session, slug)
    # The document states its own month; never guess one for the archive record.
    target_month = target_month or detect_file_month(path)
    downloaded = local_document(path, target_month)
    run = start_run(session, amc, target_month)
    run.documents_discovered = run.documents_downloaded = 1
    portfolios = {}
    if portfolio_path:
        run.documents_discovered += 1
        run.documents_downloaded += 1
        portfolios = load_portfolios(session, run, amc,
                                     [local_document(portfolio_path, target_month,
                                                     'PORTFOLIO_DISCLOSURE', 'portfolio')],
                                     target_month)
    coverage = ingest_document(session, run, amc, downloaded, portfolios, extractor, use_gemini)
    finish_run(run, [coverage])
    session.commit()
    return run
