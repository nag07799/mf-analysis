"""Relational monthly factsheet store. Monetary values and weights use decimals."""
from datetime import date, datetime, timezone
from decimal import Decimal
from sqlalchemy import (BigInteger, Boolean, CheckConstraint, Date, DateTime, ForeignKey,
                        Index, Integer, JSON, Numeric, String, Text, UniqueConstraint)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

class Base(DeclarativeBase):
    pass

ID = BigInteger().with_variant(Integer, 'sqlite')
def fk(table):
    return mapped_column(ID, ForeignKey(f'{table}.id'))
def num():
    return mapped_column(Numeric(24, 8), nullable=True)
def now():
    return datetime.now(timezone.utc)

class Identity:
    id: Mapped[int] = mapped_column(ID, primary_key=True)
class Times:
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now, onupdate=now)

class AMC(Identity, Times, Base):
    __tablename__ = 'amc'
    name: Mapped[str] = mapped_column(Text)
    slug: Mapped[str] = mapped_column(String(30), unique=True)
    official_website: Mapped[str | None] = mapped_column(Text)
    factsheet_page_url: Mapped[str | None] = mapped_column(Text)
    active: Mapped[bool] = mapped_column(default=True)

class Scheme(Identity, Times, Base):
    __tablename__ = 'scheme'
    __table_args__ = (UniqueConstraint('amc_id', 'canonical_name'),)
    amc_id: Mapped[int] = mapped_column(ID, ForeignKey('amc.id'), index=True)
    scheme_name: Mapped[str] = mapped_column(Text)
    canonical_name: Mapped[str] = mapped_column(Text)
    scheme_code: Mapped[str | None] = mapped_column(Text)
    asset_class: Mapped[str] = mapped_column(String(30), index=True)
    category: Mapped[str | None] = mapped_column(Text, index=True)
    subcategory: Mapped[str | None] = mapped_column(Text)
    management_style: Mapped[str | None] = mapped_column(String(20))
    benchmark: Mapped[str | None] = mapped_column(Text)
    additional_benchmark: Mapped[str | None] = mapped_column(Text)
    inception_date: Mapped[date | None] = mapped_column(Date)
    active: Mapped[bool] = mapped_column(default=True)
    classification_status: Mapped[str] = mapped_column(String(40))
    classification_evidence: Mapped[str | None] = mapped_column(Text)

class SchemePlan(Identity, Base):
    __tablename__ = 'scheme_plan'
    __table_args__ = (UniqueConstraint('scheme_id', 'identity_key'),)
    scheme_id: Mapped[int] = fk('scheme')
    identity_key: Mapped[str] = mapped_column(String(100))
    plan_type: Mapped[str | None] = mapped_column(String(20))
    option_type: Mapped[str | None] = mapped_column(String(20))
    idcw_suboption: Mapped[str | None] = mapped_column(Text)

class FactsheetDocument(Identity, Base):
    __tablename__ = 'factsheet_document'
    __table_args__ = (UniqueConstraint('amc_id', 'factsheet_month', 'document_type', 'sha256'),
                     UniqueConstraint('amc_id', 'factsheet_month', 'document_key', 'version_number'),
                     Index('ix_document_amc_month', 'amc_id', 'factsheet_month'))
    amc_id: Mapped[int] = fk('amc')
    factsheet_month: Mapped[date] = mapped_column(Date)
    document_type: Mapped[str] = mapped_column(String(40))
    document_key: Mapped[str] = mapped_column(Text)
    source_url: Mapped[str | None] = mapped_column(Text)
    local_path: Mapped[str] = mapped_column(Text)
    filename: Mapped[str] = mapped_column(Text)
    sha256: Mapped[str] = mapped_column(String(64))
    downloaded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    parser_version: Mapped[str | None] = mapped_column(Text)
    version_number: Mapped[int] = mapped_column(default=1)
    is_current_version: Mapped[bool] = mapped_column(default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)

class SchemeFactsheetSection(Identity, Base):
    __tablename__ = 'scheme_factsheet_section'
    __table_args__ = (UniqueConstraint('factsheet_document_id', 'start_page', 'detected_scheme_name'),)
    factsheet_document_id: Mapped[int] = fk('factsheet_document')
    scheme_id: Mapped[int | None] = fk('scheme')
    detected_scheme_name: Mapped[str | None] = mapped_column(Text)
    start_page: Mapped[int | None]
    end_page: Mapped[int | None]
    extraction_status: Mapped[str] = mapped_column(String(40))
    raw_text_path: Mapped[str | None] = mapped_column(Text)
    raw_json_path: Mapped[str | None] = mapped_column(Text)
    error_message: Mapped[str | None] = mapped_column(Text)

class SchemeMonthlySnapshot(Identity, Times, Base):
    __tablename__ = 'scheme_monthly_snapshot'
    __table_args__ = (UniqueConstraint('scheme_id', 'as_of_date'), CheckConstraint('aum_crore IS NULL OR aum_crore >= 0'))
    scheme_id: Mapped[int] = fk('scheme')
    as_of_date: Mapped[date] = mapped_column(Date, index=True)
    aum_crore: Mapped[Decimal | None] = num()
    average_aum_crore: Mapped[Decimal | None] = num()
    equity_turnover_pct: Mapped[Decimal | None] = num()
    total_turnover_pct: Mapped[Decimal | None] = num()
    standard_deviation: Mapped[Decimal | None] = num()
    beta: Mapped[Decimal | None] = num()
    sharpe_ratio: Mapped[Decimal | None] = num()
    risk_free_rate_pct: Mapped[Decimal | None] = num()
    large_cap_pct: Mapped[Decimal | None] = num()
    mid_cap_pct: Mapped[Decimal | None] = num()
    small_cap_pct: Mapped[Decimal | None] = num()
    equity_pct: Mapped[Decimal | None] = num()
    reit_pct: Mapped[Decimal | None] = num()
    invit_pct: Mapped[Decimal | None] = num()
    debt_pct: Mapped[Decimal | None] = num()
    cash_pct: Mapped[Decimal | None] = num()
    other_pct: Mapped[Decimal | None] = num()
    # The AMC may disclose debt and cash as a single combined component.
    debt_cash_pct: Mapped[Decimal | None] = num()
    scheme_riskometer: Mapped[str | None] = mapped_column(Text)
    benchmark_riskometer: Mapped[str | None] = mapped_column(Text)
    minimum_investment: Mapped[Decimal | None] = num()
    minimum_additional: Mapped[Decimal | None] = num()
    exit_load_text: Mapped[str | None] = mapped_column(Text)
    investment_objective: Mapped[str | None] = mapped_column(Text)
    scheme_description: Mapped[str | None] = mapped_column(Text)
    source_document_id: Mapped[int] = fk('factsheet_document')
    validation_status: Mapped[str] = mapped_column(String(40))
    complete_holdings: Mapped[bool] = mapped_column(default=False)
    field_provenance: Mapped[dict | None] = mapped_column(JSON)
    extra_fields: Mapped[dict | None] = mapped_column(JSON)

class PlanMonthlyMetric(Identity, Base):
    __tablename__ = 'plan_monthly_metric'
    __table_args__ = (UniqueConstraint('scheme_plan_id', 'as_of_date'),
        CheckConstraint('nav IS NULL OR nav > 0'), CheckConstraint('expense_ratio_pct IS NULL OR expense_ratio_pct >= 0'))
    scheme_plan_id: Mapped[int] = fk('scheme_plan')
    as_of_date: Mapped[date] = mapped_column(Date)
    nav: Mapped[Decimal | None] = num()
    expense_ratio_pct: Mapped[Decimal | None] = num()
    base_expense_ratio_pct: Mapped[Decimal | None] = num()
    source_document_id: Mapped[int] = fk('factsheet_document')

class Security(Identity, Times, Base):
    __tablename__ = 'security'
    canonical_name: Mapped[str] = mapped_column(Text, index=True)
    normalized_key: Mapped[str] = mapped_column(Text, index=True)
    isin: Mapped[str | None] = mapped_column(String(12), unique=True, index=True)
    nse_symbol: Mapped[str | None] = mapped_column(Text)
    bse_code: Mapped[str | None] = mapped_column(Text)
    security_type: Mapped[str] = mapped_column(String(20))
    active: Mapped[bool] = mapped_column(default=True)

class SecurityAlias(Identity, Base):
    __tablename__ = 'security_alias'
    __table_args__ = (UniqueConstraint('security_id', 'alias_name'),)
    security_id: Mapped[int] = fk('security')
    alias_name: Mapped[str] = mapped_column(Text)
    normalized_key: Mapped[str] = mapped_column(Text, index=True)
    source_amc_id: Mapped[int | None] = fk('amc')
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)

class Industry(Identity, Base):
    __tablename__ = 'industry'
    name: Mapped[str] = mapped_column(Text)
    canonical_name: Mapped[str] = mapped_column(Text, unique=True)

class Holding(Identity, Base):
    __tablename__ = 'holding'
    __table_args__ = (UniqueConstraint('scheme_snapshot_id', 'security_id'),
        CheckConstraint('weight_pct >= 0 AND weight_pct <= 100'),
        Index('ix_holding_snapshot_weight', 'scheme_snapshot_id', 'weight_pct'))
    scheme_snapshot_id: Mapped[int] = mapped_column(ID, ForeignKey('scheme_monthly_snapshot.id'), index=True)
    security_id: Mapped[int] = mapped_column(ID, ForeignKey('security.id'), index=True)
    industry_id: Mapped[int | None] = fk('industry')
    weight_pct: Mapped[Decimal] = mapped_column(Numeric(24, 8))
    market_value_crore: Mapped[Decimal | None] = num()
    quantity: Mapped[Decimal | None] = num()
    rank: Mapped[int | None]
    raw_company_name: Mapped[str | None] = mapped_column(Text)
    raw_industry_name: Mapped[str | None] = mapped_column(Text)
    source_document_id: Mapped[int] = fk('factsheet_document')
    source_page: Mapped[int | None]
    extraction_method: Mapped[str | None] = mapped_column(Text)
    extraction_confidence: Mapped[Decimal | None] = num()
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)

class SectorAllocation(Identity, Base):
    __tablename__ = 'sector_allocation'
    __table_args__ = (UniqueConstraint('scheme_snapshot_id', 'industry_id'),)
    scheme_snapshot_id: Mapped[int] = fk('scheme_monthly_snapshot')
    industry_id: Mapped[int] = fk('industry')
    weight_pct: Mapped[Decimal] = mapped_column(Numeric(24, 8))
    calculated: Mapped[bool]
    source_document_id: Mapped[int] = fk('factsheet_document')

class FundManager(Identity, Base):
    __tablename__ = 'fund_manager'
    name: Mapped[str] = mapped_column(Text)
    canonical_name: Mapped[str] = mapped_column(Text, unique=True)

class SchemeManagerHistory(Identity, Base):
    __tablename__ = 'scheme_manager_history'
    scheme_id: Mapped[int] = fk('scheme')
    fund_manager_id: Mapped[int] = fk('fund_manager')
    from_date: Mapped[date | None] = mapped_column(Date)
    to_date: Mapped[date | None] = mapped_column(Date)
    role: Mapped[str | None] = mapped_column(Text)
    experience_text: Mapped[str | None] = mapped_column(Text)
    source_document_id: Mapped[int] = fk('factsheet_document')

class Performance(Identity, Base):
    __tablename__ = 'performance'
    __table_args__ = (UniqueConstraint('scheme_id', 'identity_key', 'as_of_date', 'period'),)
    scheme_id: Mapped[int] = fk('scheme')
    identity_key: Mapped[str] = mapped_column(Text)
    plan_type: Mapped[str | None] = mapped_column(Text)
    option_type: Mapped[str | None] = mapped_column(Text)
    as_of_date: Mapped[date] = mapped_column(Date)
    period: Mapped[str] = mapped_column(Text)
    scheme_return_pct: Mapped[Decimal | None] = num()
    benchmark_return_pct: Mapped[Decimal | None] = num()
    additional_benchmark_return_pct: Mapped[Decimal | None] = num()
    value_of_10000_scheme: Mapped[Decimal | None] = num()
    value_of_10000_benchmark: Mapped[Decimal | None] = num()
    value_of_10000_additional: Mapped[Decimal | None] = num()
    source_document_id: Mapped[int] = fk('factsheet_document')

class SIPPerformance(Identity, Base):
    __tablename__ = 'sip_performance'
    __table_args__ = (UniqueConstraint('scheme_id', 'identity_key', 'as_of_date', 'period'),)
    scheme_id: Mapped[int] = fk('scheme')
    identity_key: Mapped[str] = mapped_column(Text)
    plan_type: Mapped[str | None] = mapped_column(Text)
    option_type: Mapped[str | None] = mapped_column(Text)
    as_of_date: Mapped[date] = mapped_column(Date)
    period: Mapped[str] = mapped_column(Text)
    total_invested: Mapped[Decimal | None] = num()
    market_value: Mapped[Decimal | None] = num()
    scheme_xirr_pct: Mapped[Decimal | None] = num()
    benchmark_xirr_pct: Mapped[Decimal | None] = num()
    additional_benchmark_xirr_pct: Mapped[Decimal | None] = num()
    source_document_id: Mapped[int] = fk('factsheet_document')

class IngestionRun(Identity, Base):
    __tablename__ = 'ingestion_run'
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    target_month: Mapped[date] = mapped_column(Date)
    amc_id: Mapped[int | None] = fk('amc')
    status: Mapped[str] = mapped_column(String(30))
    documents_discovered: Mapped[int] = mapped_column(default=0)
    documents_downloaded: Mapped[int] = mapped_column(default=0)
    schemes_detected: Mapped[int] = mapped_column(default=0)
    equity_schemes_detected: Mapped[int] = mapped_column(default=0)
    schemes_successful: Mapped[int] = mapped_column(default=0)
    schemes_failed: Mapped[int] = mapped_column(default=0)
    holdings_inserted: Mapped[int] = mapped_column(default=0)
    new_securities: Mapped[int] = mapped_column(default=0)
    matched_securities: Mapped[int] = mapped_column(default=0)
    ambiguous_securities: Mapped[int] = mapped_column(default=0)
    gemini_fallbacks_used: Mapped[int] = mapped_column(default=0)
    error_summary: Mapped[str | None] = mapped_column(Text)
    coverage: Mapped[dict | None] = mapped_column(JSON)

class ReviewItem(Identity, Base):
    __tablename__ = 'review_item'
    run_id: Mapped[int] = fk('ingestion_run')
    scheme_id: Mapped[int | None] = fk('scheme')
    document_id: Mapped[int | None] = fk('factsheet_document')
    review_type: Mapped[str] = mapped_column(Text)
    raw_value: Mapped[str | None] = mapped_column(Text)
    candidate_value: Mapped[str | None] = mapped_column(Text)
    details: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(default='OPEN')
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
