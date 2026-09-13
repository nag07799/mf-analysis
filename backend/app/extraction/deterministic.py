import re
from decimal import Decimal
from app.parsers.base import clean, number, parse_date
from app.schemas.parsed import ParsedPlanMetric, ParsedManager, ParsedPerformance

def capture(text, pattern):
    match = re.search(pattern, text, re.I | re.S)
    return clean(match[1]) if match else None

def extract_metrics(scheme, text, amc):
    snap = scheme.snapshot
    n = r'(-?[\d,]+\.\d+|-?\d+)'
    if amc == 'hdfc':
        amounts = re.findall(r'₹\s*([\d,]+\.\d+)\s*Cr\.', text)
        if amounts:
            snap.aum_crore = number(amounts[0])
        if len(amounts) > 1:
            snap.average_aum_crore = number(amounts[1])
        risk = re.search(r'Standard Deviation\s+Beta\s+Sharpe Ratio\*?\s+'+n+r'%?\s+'+n+r'\s+'+n, text, re.I)
        if risk:
            snap.standard_deviation, snap.beta, snap.sharpe_ratio = map(number, risk.groups())
        turnover = re.search(r'Equity Turnover\s+Total Turnover\s+'+n+r'%\s+'+n+r'%', text,re.I)
        if turnover:
            snap.equity_turnover_pct, snap.total_turnover_pct = map(number, turnover.groups())
        scheme.benchmark = capture(text, r'(?<!ADDL\. )#?BENCHMARK INDEX\s*\n([^\n]+)')
        scheme.additional_benchmark = capture(text, r'ADDL\. BENCHMARK INDEX\s*\n([^\n]+)')
        scheme.inception_date = parse_date(capture(text, r'DATE OF ALLOTMENT/INCEPTION DATE\s*\n([^\n]+)'))
        snap.investment_objective = capture(text, r'INVESTMENT OBJECTIVE:\s*(.*?)(?:FUND MANAGER|DATE OF ALLOTMENT)')
        snap.exit_load_text = capture(text, r'EXIT LOAD[^\n]*\n(.*?)(?:PORTFOLIO|\.\.\.Contd|For further details|\Z)')
        for plan, option, nav in re.findall(r'(Regular|Direct) Plan\s*-\s*(Growth|IDCW) Option\s+([\d,.]+)',text,re.I):
            if number(nav) is not None:
                p = ParsedPlanMetric(plan_type=plan.upper(),option_type=option.upper(),nav=number(nav))
                ter = capture(text, rf'{plan}:\s*([\d.]+)%')
                if 'Base expense' in text or 'Base Expense' in text:
                    p.base_expense_ratio_pct = number(ter)
                else:
                    p.expense_ratio_pct = number(ter)
                scheme.plans.append(p)
        manager = capture(text,r'Name\s+Since\s+Total Exp\s+(.*?)(?:DATE OF ALLOTMENT)')
        if manager:
            m = re.match(r'(.+?)\s+([A-Za-z]+\s+\d{1,2},?\s+\d{4})\s+(Over .+)', manager)
            if m:
                scheme.managers.append(ParsedManager(name=m[1],from_date=parse_date(m[2]),experience_text=m[3]))
    else:
        snap.aum_crore = number(capture(text, r'Closing AUM[^:]*:\s*Rs\.?\s*([\d,.]+)'))
        snap.average_aum_crore = number(capture(text,r'Monthly AAUM[^:]*:\s*Rs\.?\s*([\d,.]+)'))
        snap.beta = number(capture(text, r'Portfolio Beta\s*:\s*'+n))
        snap.sharpe_ratio = number(capture(text, r'Sharpe Ratio\s*:\s*'+n))
        snap.standard_deviation = number(capture(text, r'Std Dev\s*\(Annualised\)\s*\(3yrs\)\s*:\s*'+n))
        turnover = number(capture(text,r'Annual Portfolio Turnover Ratio\s*:\s*Equity\s*-\s*'+n+r'\s*times'))
        snap.equity_turnover_pct = turnover * 100 if turnover is not None else None
        scheme.inception_date = parse_date(capture(text,r'Inception/Allotment date\s*:\s*([^\n]+)'))
        snap.exit_load_text = capture(text,r'Exit load[^\n]*:\s*(.*?)(?:Indicative Investment Horizon|Inception/Allotment|Application Amount)')
        for m in re.finditer(r'([A-Z][A-Za-z .]+)\s*\(Managing this fund since ([^)]+)\)', text):
            name, detail = clean(m[1]), clean(m[2])
            if len(name.split()) <= 5:
                # Month-only manager dates are intentionally NULL; retain the source precision.
                scheme.managers.append(ParsedManager(name=name, experience_text=detail))
        navtext = capture(text,r'NAV \(As on [^)]+\)\s*:\s*([^\n]+(?:\n[^\n]+){0,3})') or ''
        for label, val in re.findall(r'((?:Direct Plan )?(?:Growth|IDCW) Option)\s*:\s*(?:Rs\.\s*)?([\d,.]+)', navtext):
            p=ParsedPlanMetric(plan_type='DIRECT' if 'Direct' in label else 'REGULAR',option_type='GROWTH' if 'Growth' in label else 'IDCW',nav=number(val))
            ratio_label = 'Direct' if p.plan_type == 'DIRECT' else 'Other'
            expense = number(capture(text,rf'{ratio_label}\s*:\s*([\d.]+)%\s*p\.\s*a'))
            if re.search(r'Base Expense Ratio',text,re.I):
                p.base_expense_ratio_pct=expense
            else:
                p.expense_ratio_pct=expense
            scheme.plans.append(p)
        if not scheme.plans:
            value=number(capture(navtext,r'^\s*Rs\.\s*([\d,.]+)'))
            if value:
                scheme.plans.append(ParsedPlanMetric(nav=value))
        scheme.benchmark = capture(text,r'\n([^\n]+)\s*\(Benchmark\)')
        scheme.additional_benchmark = capture(text,r'\n([^\n]+)\s*\(Additional Benchmark\)')
        for field, label in [('minimum_investment','Application Amount for fresh Subscription'),('minimum_additional','Min.Addl.Investment')]:
            setattr(snap,field,number(capture(text,re.escape(label)+r'\s*:\s*Rs\.\s*([\d,.]+)')))
    snap.risk_free_rate_pct = number(capture(text,r'Risk free rate\s*:\s*'+n+r'\s*%') or capture(text,r'Risk-free rate[^\n]*?of\s+'+n+r'%'))
    for field,label in [('large_cap_pct','Large Cap'),('mid_cap_pct','Mid Cap'),('small_cap_pct','Small Cap')]:
        setattr(snap,field,number(capture(text,rf'{label}\s*[:\-]?\s*'+n+r'%')))
    for field, who in [('scheme_riskometer','scheme'),('benchmark_riskometer','Benchmark')]:
        setattr(snap,field,capture(text,rf'The risk of the {who} is ([^\n]+)'))
    for field in snap.model_fields:
        if getattr(snap,field) is not None and field not in ('field_provenance','extra_fields'):
            snap.field_provenance[field]={'page':scheme.start_page,'method':'AMC_SPECIFIC_RULE'}
