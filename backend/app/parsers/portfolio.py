"""Official Excel portfolio fallback; never mixes reporting dates or derivative sheets."""
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from io import BytesIO
from pathlib import Path
import re
import zipfile
import openpyxl
from app.parsers.base import clean, number, parse_date
from app.schemas.parsed import ParsedHolding
from app.normalization.securities import normalize_name

def scheme_key(name):
    return re.sub(r'[^a-z0-9]','',normalize_name(name))

def row_security_type(industry,state):
    """The industry column identifies trust units; a sector label means listed equity."""
    if industry:
        if re.search(r'Real Estate Investment Trust|\bREITs?\b',industry,re.I):
            return 'REIT'
        if re.search(r'Infrastructure Investment Trust|\bInvITs?\b',industry,re.I):
            return 'INVIT'
        return 'EQUITY'
    return state

# The AMC replaces a weight with this marker when the legend documents the row as
# below the disclosure threshold. It is a disclosed value, not a missing one.
THRESHOLD_MARKERS = ('^', '~', '@@')
THRESHOLD_LEGEND = re.compile(r'(?:\^|~|@@)\s*(?:Value\s+)?Less than\s*([\d.]+)\s*%\s*of\s*NAV', re.I)

@dataclass
class Portfolio:
    name: str
    as_of_date: date
    holdings: list = field(default_factory=list)
    equity_pct: Decimal | None = None
    complete: bool = False
    issues: list = field(default_factory=list)
    source_sheet: str | None = None
    # Rows the AMC disclosed only as "less than X% of NAV"; stored at 0 with this note.
    below_threshold: list = field(default_factory=list)
    threshold_pct: Decimal | None = None

def workbook_sources(path):
    path=Path(path)
    if path.suffix.lower()=='.zip':
        with zipfile.ZipFile(path) as archive:
            for item in archive.infolist():
                if item.filename.lower().endswith('.xlsx'):
                    if item.file_size>100_000_000 or item.file_size/max(item.compress_size,1)>1000:
                        raise ValueError('Workbook archive entry exceeds size limits')
                    yield item.filename,BytesIO(archive.read(item))
    else:
        yield path.name,path

def parse_portfolios(path,target_month,document_id=None):
    result={}
    for filename,source in workbook_sources(path):
        book=openpyxl.load_workbook(source,read_only=True,data_only=True)
        try:
            for sheet in book.worksheets:
                if re.search(r'deriv|riskometer',sheet.title,re.I):
                    continue
                rows=list(sheet.iter_rows())
                header=None;mapping={};name=None;as_of=None
                for i,row in enumerate(rows[:20]):
                    vals=[str(c.value).strip() if c.value is not None else '' for c in row]
                    for v in vals:
                        if re.search(r'Portfolio as (?:on|at)',v,re.I):
                            as_of=parse_date(re.split(r'Portfolio as (?:on|at)',v,flags=re.I)[-1])
                        if v.startswith(('HDFC ','ICICI Prudential ','BHARAT 22')) and 'Mutual Fund' not in v:
                            name=re.split(r'\s*\(An |\s*\(an ',v)[0].strip()
                    if 'ISIN' in vals and any('%' in v and 'nav' in v.lower() for v in vals):
                        header=i
                        for j,v in enumerate(vals):
                            if v=='ISIN':mapping['isin']=j
                            if re.search(r'name.*instrument|instrument.*name|company/issuer',v,re.I):mapping['name']=j
                            if 'industry' in v.lower():mapping['industry']=j
                            if '%' in v and 'nav' in v.lower():mapping['weight']=j
                            if 'quantity' in v.lower():mapping['quantity']=j
                            if 'value' in v.lower() and ('lakh' in v.lower() or 'lac' in v.lower()):mapping['value']=j
                        break
                if header is None or not name or not as_of or not all(k in mapping for k in ('name','isin','weight')):
                    continue
                if as_of.replace(day=1)!=target_month:
                    continue
                portfolio=Portfolio(name,as_of,source_sheet=filename+' / '+sheet.title)
                legend=THRESHOLD_LEGEND.search('\n'.join(
                    str(c.value) for r in rows[header+1:] for c in r if isinstance(c.value,str)))
                if legend:
                    portfolio.threshold_pct=number(legend[1])
                state=None;equity_subtotals=[];seen=set();end=False
                def get(row,key):
                    return row[mapping[key]] if key in mapping else None
                def weight(cell):
                    n=number(cell.value) if cell else None
                    if n is not None and '%' in cell.number_format:
                        n*=100
                    return n
                for row in rows[header+1:]:
                    vals=[str(c.value).strip() if c.value is not None else '' for c in row]
                    label=' '.join(v for v in vals[:5] if v)
                    value=weight(get(row,'weight'))
                    company=clean(str(get(row,'name').value or ''))
                    isin=clean(str(get(row,'isin').value or ''))
                    if re.search(r'Grand Total|Total Net Assets',label,re.I):
                        end=True;break
                    if re.search(r'^Equity & Equity|EQUITY & EQUITY RELATED',label,re.I):
                        state='EQUITY'
                        if value is not None:portfolio.equity_pct=value
                        continue
                    if re.search(r'Units issued by ReIT|Real Estate Investment Trust',label,re.I):state='REIT'
                    elif re.search(r'Units issued by InvIT|Infrastructure Investment Trust',label,re.I):state='INVIT'
                    elif re.search(r'DEBT|MONEY MARKET|Preference Shares|Term Deposits|TREPS|OTHERS',label,re.I) and not re.fullmatch(r'[A-Z]{2}[A-Z0-9]{10}',isin):state='OTHER'
                    if re.search(r'Sub Total',label,re.I) and state=='EQUITY' and value is not None:
                        equity_subtotals.append(value)
                    if not company or not re.fullmatch(r'[A-Z]{2}[A-Z0-9]{9}[0-9]',isin) or state not in ('EQUITY','REIT','INVIT'):
                        continue
                    if '$$' in company or re.search(r'futures|options',company,re.I):
                        continue
                    if value is None:
                        marker=clean(str(get(row,'weight').value or ''))
                        if marker in THRESHOLD_MARKERS and portfolio.threshold_pct is not None:
                            # Disclosed as below the AMC's stated threshold, so 0.00 is documented.
                            portfolio.below_threshold.append(company)
                            value=Decimal(0)
                        else:
                            portfolio.issues.append('UNREADABLE_HOLDING_WEIGHT: '+company)
                            continue
                    if isin in seen:
                        portfolio.issues.append('DUPLICATE_SECURITY: '+isin);continue
                    seen.add(isin)
                    if value<0 or value>100:
                        portfolio.issues.append('INVALID_WEIGHT: '+company);continue
                    market=get(row,'value');quantity=get(row,'quantity');industry=get(row,'industry')
                    mv=number(market.value) if market else None
                    industry_name=clean(str(industry.value)) if industry and industry.value else None
                    portfolio.holdings.append(ParsedHolding(raw_company_name=company,isin=isin,
                        industry=industry_name,
                        weight_pct=value,market_value_crore=mv/100 if mv is not None else None,
                        quantity=number(quantity.value) if quantity else None,
                        security_type=row_security_type(industry_name,state),
                        source_document_id=document_id,extraction_method='PORTFOLIO_XLSX'))
                if portfolio.equity_pct is None and equity_subtotals:
                    portfolio.equity_pct=sum(equity_subtotals)
                equity=sum((h.weight_pct for h in portfolio.holdings if h.security_type=='EQUITY'),Decimal(0))
                block=sum((h.weight_pct for h in portfolio.holdings),Decimal(0))
                tolerance=max(Decimal('.10'),min(Decimal('.50'),len(portfolio.holdings)*Decimal('.005')))
                # AMCs differ on whether REIT/InvIT units sit inside the equity subtotal; accept
                # either reading rather than rejecting a portfolio the source actually completed.
                reconciled=portfolio.equity_pct is not None and (
                    abs(equity-portfolio.equity_pct)<=tolerance or abs(block-portfolio.equity_pct)<=tolerance)
                portfolio.complete=bool(end and not portfolio.issues and reconciled)
                result[scheme_key(name)]=portfolio
        finally:
            book.close()
    return result

def apply_portfolio(scheme,portfolio):
    if portfolio.as_of_date!=scheme.snapshot.as_of_date:
        raise ValueError('Portfolio month differs from factsheet month')
    scheme.holdings=portfolio.holdings
    scheme.snapshot.equity_pct=portfolio.equity_pct
    scheme.snapshot.complete_holdings=portfolio.complete
    scheme.snapshot.portfolio_end_observed=portfolio.complete
    scheme.snapshot.field_provenance['holdings']={'method':'PORTFOLIO_XLSX','sheet':portfolio.source_sheet}
    if portfolio.below_threshold:
        scheme.snapshot.field_provenance['holdings']['below_disclosure_threshold']={
            'threshold_pct':str(portfolio.threshold_pct),'securities':portfolio.below_threshold}
    scheme.issues=portfolio.issues.copy()
    return scheme
