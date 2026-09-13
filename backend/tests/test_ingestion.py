"""Storage rules: idempotency, immutability of past months, NULL for unknowns, review routing."""
from datetime import date
from pathlib import Path
from decimal import Decimal
import pytest
from sqlalchemy import select, func
from app.db.models import (AMC, Industry, IngestionRun, SchemeMonthlySnapshot, Holding, Security,
                           SecurityAlias, FactsheetDocument, ReviewItem, SectorAllocation, Scheme)
from app.ingestion.service import persist_scheme, register_document, write_report
from app.downloaders.base import Document, DownloadedDocument
from app.normalization.securities import resolve_security, AmbiguousSecurity, normalize_name
from app.schemas.parsed import ParsedHolding
from tests.conftest import MONTH, make_amc, make_document, parsed_scheme


@pytest.fixture
def run(session):
    amc = make_amc(session)
    run = IngestionRun(target_month=MONTH.replace(day=1), amc_id=amc.id, status='RUNNING')
    session.add(run)
    session.flush()
    return run


def document_for(session, amc_id, sha='a' * 64, path=None):
    downloaded = DownloadedDocument(Document('https://www.hdfcfund.com/x.pdf', MONTH.replace(day=1), 'active'),
                                    Path(path or 'x.pdf'), sha, 'x.pdf')
    return register_document(session, amc_id, downloaded)


def test_holdings_are_one_row_each_and_ranked(session, run, archive):
    document = make_document(session, session.get(AMC, run.amc_id))
    parsed = parsed_scheme(holdings=[('ICICI Bank Ltd.', 20), ('HDFC Bank Ltd.', 30), ('Infosys Ltd.', 50)])
    status, count, new, matched = persist_scheme(session, run, document, parsed, archive)
    assert (status, count, new, matched) == ('SUCCESS', 3, 3, 0)
    snapshot = session.scalar(select(SchemeMonthlySnapshot))
    rows = session.scalars(select(Holding).where(Holding.scheme_snapshot_id == snapshot.id).order_by(Holding.rank)).all()
    assert [r.rank for r in rows] == [1, 2, 3]
    assert [r.weight_pct for r in rows] == [Decimal(50), Decimal(30), Decimal(20)]
    assert snapshot.validation_status == 'VALIDATED'


def test_unknown_values_are_stored_as_null(session, run, archive):
    document = make_document(session, session.get(AMC, run.amc_id))
    parsed = parsed_scheme(holdings=[('Infosys Ltd.', 100)])
    persist_scheme(session, run, document, parsed, archive)
    snapshot = session.scalar(select(SchemeMonthlySnapshot))
    for field in ('beta', 'sharpe_ratio', 'standard_deviation', 'aum_crore', 'reit_pct',
                  'minimum_investment', 'exit_load_text'):
        assert getattr(snapshot, field) is None, field
    holding = session.scalar(select(Holding))
    assert holding.market_value_crore is None and holding.quantity is None


def test_duplicate_monthly_ingestion_is_idempotent(session, run, archive):
    document = make_document(session, session.get(AMC, run.amc_id))
    parsed = parsed_scheme(holdings=[('Infosys Ltd.', 60), ('TCS Ltd.', 40)])
    assert persist_scheme(session, run, document, parsed, archive)[0] == 'SUCCESS'
    assert persist_scheme(session, run, document, parsed, archive)[0] == 'ALREADY_INGESTED'
    assert session.scalar(select(func.count(SchemeMonthlySnapshot.id))) == 1
    assert session.scalar(select(func.count(Holding.id))) == 2
    assert session.scalar(select(func.count(Scheme.id))) == 1


def test_new_month_creates_a_new_snapshot_without_touching_the_old(session, run, archive):
    amc = session.get(AMC, run.amc_id)
    july = make_document(session, amc, sha='1' * 64)
    august = make_document(session, amc, month=date(2026, 8, 1), sha='2' * 64)
    persist_scheme(session, run, july, parsed_scheme(holdings=[('Infosys Ltd.', 100)]), archive)
    parsed = parsed_scheme(holdings=[('Infosys Ltd.', 55), ('TCS Ltd.', 45)], as_of_date=date(2026, 8, 31))
    persist_scheme(session, run, august, parsed, archive)
    snapshots = session.scalars(select(SchemeMonthlySnapshot).order_by(SchemeMonthlySnapshot.as_of_date)).all()
    assert [s.as_of_date for s in snapshots] == [MONTH, date(2026, 8, 31)]
    july_rows = session.scalars(select(Holding).where(Holding.scheme_snapshot_id == snapshots[0].id)).all()
    assert len(july_rows) == 1 and july_rows[0].weight_pct == Decimal(100)


def test_same_month_different_hash_creates_a_document_version(session, run):
    first, created_first = document_for(session, run.amc_id, sha='a' * 64)
    again, created_again = document_for(session, run.amc_id, sha='a' * 64)
    second, created_second = document_for(session, run.amc_id, sha='b' * 64)
    assert created_first and not created_again and created_second
    assert first.id == again.id
    assert (first.version_number, second.version_number) == (1, 2)
    assert first.is_current_version is False and second.is_current_version is True
    assert session.scalar(select(func.count(FactsheetDocument.id))) == 2


def test_revised_document_does_not_overwrite_an_existing_snapshot(session, run, archive):
    first, _ = document_for(session, run.amc_id, sha='1' * 64)
    persist_scheme(session, run, first, parsed_scheme(holdings=[('Infosys Ltd.', 100)]), archive)
    # A corrected republication of the same month arrives as a new document version.
    revised, _ = document_for(session, run.amc_id, sha='2' * 64)
    parsed = parsed_scheme(holdings=[('Infosys Ltd.', 40), ('TCS Ltd.', 60)])
    assert persist_scheme(session, run, revised, parsed, archive)[0] == 'REVIEW_REQUIRED'
    snapshot = session.scalar(select(SchemeMonthlySnapshot))
    assert snapshot.source_document_id == first.id
    assert session.scalar(select(func.count(Holding.id))) == 1
    assert session.scalar(select(ReviewItem).where(ReviewItem.review_type == 'DOCUMENT_REVISION')) is not None


def test_sector_allocation_is_derived_from_holdings(session, run, archive):
    document = make_document(session, session.get(AMC, run.amc_id))
    parsed = parsed_scheme(holdings=[])
    for name, industry, weight in [('HDFC Bank Ltd.', 'Banks', 30), ('ICICI Bank Ltd.', 'Banks', 25),
                                   ('Infosys Ltd.', 'IT - Software', 45)]:
        parsed.holdings.append(ParsedHolding(raw_company_name=name, industry=industry,
                                             weight_pct=Decimal(weight)))
    parsed.snapshot.equity_pct = Decimal(100)
    persist_scheme(session, run, document, parsed, archive)
    rows = {session.get(Industry, s.industry_id).name: s.weight_pct
            for s in session.scalars(select(SectorAllocation))}
    assert rows == {'Banks': Decimal(55), 'IT - Software': Decimal(45)}
    assert all(s.calculated for s in session.scalars(select(SectorAllocation)))


def test_failed_scheme_does_not_roll_back_a_successful_one(session, run, archive):
    document = make_document(session, session.get(AMC, run.amc_id))
    good = parsed_scheme(name='HDFC Good Fund', holdings=[('Infosys Ltd.', 100)])
    assert persist_scheme(session, run, document, good, archive)[0] == 'SUCCESS'
    bad = parsed_scheme(name='HDFC Bad Fund', holdings=[('HDFC Bank Ltd.', 50), ('HDFC Bank Limited', 50)])
    assert persist_scheme(session, run, document, bad, archive)[0] == 'REVIEW_REQUIRED'
    assert session.scalar(select(func.count(SchemeMonthlySnapshot.id))) == 1
    assert session.scalar(select(func.count(Holding.id))) == 1


def test_ingestion_report_counts_are_read_from_the_database(session, run, archive):
    document = make_document(session, session.get(AMC, run.amc_id))
    status, count, new, matched = persist_scheme(session, run, document,
                                                 parsed_scheme(holdings=[('Infosys Ltd.', 100)]), archive)
    run.holdings_inserted, run.new_securities, run.status = count, new, 'SUCCESS'
    session.flush()
    report = write_report(session, [run], archive)
    assert report['overall']['unique_equity_schemes'] == 1
    assert report['overall']['unique_securities'] == 1
    assert report['overall']['holdings_inserted'] == 1
    assert (archive / 'reports').glob('*_ingestion_report.md')
