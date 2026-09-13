from datetime import date
from decimal import Decimal
from typing import Literal
from pydantic import BaseModel, ConfigDict, Field

class StrictModel(BaseModel):
    model_config = ConfigDict(extra='forbid', str_strip_whitespace=True, allow_inf_nan=False)

class ParsedHolding(StrictModel):
    raw_company_name: str = Field(min_length=1)
    isin: str | None = Field(default=None, pattern=r'^[A-Z]{2}[A-Z0-9]{9}[0-9]$')
    industry: str | None = None
    weight_pct: Decimal = Field(ge=0, le=100)
    security_type: Literal['EQUITY', 'REIT', 'INVIT', 'ETF', 'OTHER'] = 'EQUITY'
    market_value_crore: Decimal | None = None
    quantity: Decimal | None = None
    source_page: int | None = Field(default=None, ge=1)
    source_document_id: int | None = None
    extraction_method: str = 'AMC_SPECIFIC_RULE'
    extraction_confidence: Decimal | None = None

class ParsedPlanMetric(StrictModel):
    plan_type: str | None = None
    option_type: str | None = None
    idcw_suboption: str | None = None
    nav: Decimal | None = Field(default=None, gt=0)
    expense_ratio_pct: Decimal | None = Field(default=None, ge=0)
    base_expense_ratio_pct: Decimal | None = Field(default=None, ge=0)

class ParsedPerformance(StrictModel):
    plan_type: str | None = None
    option_type: str | None = None
    period: str
    scheme_return_pct: Decimal | None = None
    benchmark_return_pct: Decimal | None = None
    additional_benchmark_return_pct: Decimal | None = None
    value_of_10000_scheme: Decimal | None = None
    value_of_10000_benchmark: Decimal | None = None
    value_of_10000_additional: Decimal | None = None

class ParsedSIPPerformance(StrictModel):
    plan_type: str | None = None
    option_type: str | None = None
    period: str
    total_invested: Decimal | None = None
    market_value: Decimal | None = None
    scheme_xirr_pct: Decimal | None = None
    benchmark_xirr_pct: Decimal | None = None
    additional_benchmark_xirr_pct: Decimal | None = None

class ParsedManager(StrictModel):
    name: str
    from_date: date | None = None
    to_date: date | None = None
    role: str | None = None
    experience_text: str | None = None

class ParsedSector(StrictModel):
    industry: str
    weight_pct: Decimal
    calculated: bool = False

class ParsedSnapshot(StrictModel):
    as_of_date: date
    aum_crore: Decimal | None = Field(default=None, ge=0)
    average_aum_crore: Decimal | None = Field(default=None, ge=0)
    equity_turnover_pct: Decimal | None = None
    total_turnover_pct: Decimal | None = None
    standard_deviation: Decimal | None = None
    beta: Decimal | None = None
    sharpe_ratio: Decimal | None = None
    risk_free_rate_pct: Decimal | None = None
    large_cap_pct: Decimal | None = None
    mid_cap_pct: Decimal | None = None
    small_cap_pct: Decimal | None = None
    equity_pct: Decimal | None = None
    reit_pct: Decimal | None = None
    invit_pct: Decimal | None = None
    debt_pct: Decimal | None = None
    cash_pct: Decimal | None = None
    other_pct: Decimal | None = None
    debt_cash_pct: Decimal | None = None
    scheme_riskometer: str | None = None
    benchmark_riskometer: str | None = None
    minimum_investment: Decimal | None = None
    minimum_additional: Decimal | None = None
    exit_load_text: str | None = None
    investment_objective: str | None = None
    scheme_description: str | None = None
    complete_holdings: bool = False
    # A source total/end marker is required, never infer completeness from row count.
    portfolio_end_observed: bool = False
    field_provenance: dict = Field(default_factory=dict)
    extra_fields: dict = Field(default_factory=dict)

class ParsedScheme(StrictModel):
    scheme_name: str
    scheme_code: str | None = None
    category: str | None = None
    subcategory: str | None = None
    official_description: str | None = None
    classification_evidence: str | None = None
    asset_class: str = 'UNRESOLVED'
    classification_status: str = 'REVIEW_REQUIRED'
    management_style: str | None = None
    benchmark: str | None = None
    additional_benchmark: str | None = None
    inception_date: date | None = None
    start_page: int | None = None
    end_page: int | None = None
    snapshot: ParsedSnapshot
    holdings: list[ParsedHolding] = Field(default_factory=list)
    plans: list[ParsedPlanMetric] = Field(default_factory=list)
    performance: list[ParsedPerformance] = Field(default_factory=list)
    sip_performance: list[ParsedSIPPerformance] = Field(default_factory=list)
    managers: list[ParsedManager] = Field(default_factory=list)
    sectors: list[ParsedSector] = Field(default_factory=list)
    extraction_status: str = 'EXTRACTED'
    issues: list[str] = Field(default_factory=list)
    raw_text: str = ''
