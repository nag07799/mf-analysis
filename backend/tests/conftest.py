import os
import sys
from datetime import date
from decimal import Decimal
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND))
# Tests must never touch the developer's PostgreSQL instance or archive.
os.environ['DATABASE_URL'] = 'sqlite+pysqlite:///:memory:'

import pytest
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker
from app.db.models import Base, AMC, Scheme, FactsheetDocument, SchemeMonthlySnapshot, Holding, Security
from app.schemas.parsed import ParsedScheme, ParsedSnapshot, ParsedHolding

MONTH = date(2026, 7, 31)


@pytest.fixture
def session(tmp_path):
    engine = create_engine('sqlite+pysqlite:///:memory:')

    @event.listens_for(engine, 'connect')
    def _fk(connection, _record):
        connection.execute('PRAGMA foreign_keys=ON')

    Base.metadata.create_all(engine)
    with sessionmaker(engine, expire_on_commit=False)() as session:
        yield session


@pytest.fixture
def archive(tmp_path):
    for name in ('raw', 'extracted', 'rejected', 'reports', 'logs'):
        (tmp_path / name).mkdir(parents=True, exist_ok=True)
    return tmp_path


def make_amc(session, slug='hdfc'):
    amc = AMC(slug=slug, name=slug.upper() + ' Mutual Fund')
    session.add(amc)
    session.flush()
    return amc


def make_document(session, amc, month=MONTH, sha='a' * 64, key='active'):
    document = FactsheetDocument(amc_id=amc.id, factsheet_month=month.replace(day=1),
                                 document_type='FACTSHEET', document_key=key, local_path='/tmp/x.pdf',
                                 filename='x.pdf', sha256=sha, parser_version='test')
    session.add(document)
    session.flush()
    return document


def make_fund(session, amc, document, name, holdings, as_of_date=MONTH):
    """Insert a scheme plus one monthly snapshot with the given {company: weight} portfolio."""
    scheme = Scheme(amc_id=amc.id, scheme_name=name, canonical_name=name.lower(),
                    asset_class='EQUITY', classification_status='INCLUDED',
                    management_style='ACTIVE', category='Flexi Cap Fund')
    session.add(scheme)
    session.flush()
    snapshot = SchemeMonthlySnapshot(scheme_id=scheme.id, as_of_date=as_of_date,
                                     source_document_id=document.id, validation_status='VALIDATED',
                                     complete_holdings=True,
                                     equity_pct=Decimal(sum(holdings.values())))
    session.add(snapshot)
    session.flush()
    rows = []
    for company, weight in holdings.items():
        security = session.query(Security).filter_by(canonical_name=company).one_or_none()
        if security is None:
            security = Security(canonical_name=company, normalized_key=company.lower(),
                                security_type='EQUITY')
            session.add(security)
            session.flush()
        rows.append(Holding(scheme_snapshot_id=snapshot.id, security_id=security.id,
                            weight_pct=Decimal(str(weight)), raw_company_name=company,
                            source_document_id=document.id, extraction_method='AMC_SPECIFIC_RULE'))
    rows.sort(key=lambda h: (-h.weight_pct, h.security_id))
    for rank, row in enumerate(rows, 1):
        row.rank = rank
    session.add_all(rows)
    session.flush()
    return scheme


def parsed_scheme(name='HDFC Test Fund', holdings=(), **snapshot_fields):
    """A minimal INCLUDED ParsedScheme carrying a complete, end-marked portfolio."""
    equity = sum(Decimal(str(w)) for _, w in holdings)
    fields = {'as_of_date': MONTH, 'equity_pct': equity, 'complete_holdings': True,
              'portfolio_end_observed': True}
    fields.update(snapshot_fields)
    return ParsedScheme(scheme_name=name, category='Flexi Cap Fund', asset_class='EQUITY',
                        classification_status='INCLUDED', management_style='ACTIVE',
                        snapshot=ParsedSnapshot(**fields),
                        holdings=[ParsedHolding(raw_company_name=c, weight_pct=Decimal(str(w)))
                                  for c, w in holdings])
