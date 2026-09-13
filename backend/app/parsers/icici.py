import re
from decimal import Decimal
import pymupdf
from app.parsers.base import BaseParser, detect_month, month_end, clean, number, spans, text_region
from app.schemas.parsed import ParsedScheme, ParsedSnapshot, ParsedHolding
from app.extraction.deterministic import extract_metrics
from app.validation.classification import classify

class ICICIParser(BaseParser):
    def sections(self,pdf):
        result=[]
        for i,page in enumerate(pdf):
            text=page.get_text()
            if 'Portfolio as on' not in text:
                continue
            ss=spans(page)
            title=[s for s in ss if s['bbox'][1]<75 and s['size']>=12 and s['bbox'][0]<480]
            name=clean(' '.join(s['text'] for s in sorted(title,key=lambda s:(s['bbox'][1],s['bbox'][0]))))
            if not name.startswith(('ICICI Prudential','BHARAT 22')):
                continue
            desc=re.search(r'\(An [\s\S]+?\)',text,re.I)
            description=clean(desc[0]) if desc else ''
            if result and result[-1][0]==name:
                result[-1]=(name,result[-1][1],i+1,description)
            else:
                result.append((name,i+1,i+1,description))
        return result

    def parse(self,path,target_month=None):
        with pymupdf.open(path) as pdf:
            month=detect_month(pdf)
            if target_month and month!=target_month:
                raise ValueError(f'DOCUMENT_MONTH_MISMATCH: {month} != {target_month}')
            results=[]
            for name,start,end,description in self.sections(pdf):
                pages=[pdf[i] for i in range(start-1,end)]
                text='\n'.join(p.get_text() for p in pages)
                ss=spans(pages[0])
                labels=[s for s in ss if clean(s['text'])=='Category' and s['bbox'][1]<80]
                category=None
                if labels:
                    label=labels[0]
                    lines=[s for s in ss if s['bbox'][0]>=label['bbox'][0]-3 and label['bbox'][3]-2<=s['bbox'][1]<75]
                    category=clean(' '.join(s['text'] for s in sorted(lines,key=lambda s:s['bbox'][1]))) or None
                scheme=ParsedScheme(scheme_name=name,official_description=description,
                    category=category,start_page=start,end_page=end,
                    snapshot=ParsedSnapshot(as_of_date=month_end(month)),raw_text=text)
                classify(scheme)
                if scheme.classification_status=='INCLUDED':
                    extract_metrics(scheme,text,'icici')
                    try:
                        self.holdings(scheme,pages)
                    except Exception as exc:
                        scheme.issues.append('REGEX_PARSE_FAILURE: '+str(exc)[:200])
                        scheme.snapshot.complete_holdings=False
                results.append(scheme)
            if not results:
                raise ValueError('AMC_LAYOUT_CHANGED: no scheme sections detected')
            return results

    def holdings(self,scheme,pages):
        state='EQUITY';industry=None;grouped=False
        for page in pages:
            text=page.get_text()
            if 'Equity Shares' in text:
                text=text[text.index('Equity Shares'):]
            elif page.number+1==scheme.start_page:
                continue
            end=text.find('Total Net Assets')
            if end>=0:
                text=text[:end+len('Total Net Assets')+40]
            # Read the PDF's embedded table order, including both portfolio columns.
            for m in re.finditer(r'([^%]+?)\s+(-?[\d.]+)%(?:[ \t]+-?[\d.]+%)?',text):
                name=clean(m[1]);val=number(m[2])
                name=re.sub(r'^(?:Company/Issuer[\s\S]*?NAV(?: Derivatives)?\s*)','',name)
                if 'Equity Shares' in name:
                    scheme.snapshot.equity_pct=val;state='EQUITY';continue
                if 'equity less than' in name.lower():
                    grouped=True;continue
                if 'Total Net Assets' in name:
                    scheme.snapshot.portfolio_end_observed=True;break
                if re.search(r'Short Term Debt|current assets',name,re.I):
                    scheme.snapshot.debt_cash_pct=val;state='OTHER';continue
                if re.search(r'Debt Holdings|Preference Shares|Treasury Bills|Units of|REITs|InvITs',name,re.I):
                    state='OTHER';continue
                if re.search(r'futures|options|derivative',name,re.I):
                    grouped=True;continue
                is_company=bool(re.search(r'\b(?:Ltd|Limited|Inc|Corp|Corporation|PLC|SA|AG|NV)\b|Bank [Oo]f',name))
                if not is_company:
                    industry=name;continue
                if state=='EQUITY' and val is not None and 0<=val<=100:
                    scheme.holdings.append(ParsedHolding(raw_company_name=name,industry=industry,weight_pct=val,source_page=page.number+1))
        total=sum((h.weight_pct for h in scheme.holdings),Decimal(0))
        snap=scheme.snapshot
        tol=max(Decimal('.10'),min(Decimal('.50'),len(scheme.holdings)*Decimal('.005')))
        snap.complete_holdings=bool(not grouped and snap.portfolio_end_observed and snap.equity_pct is not None and abs(total-snap.equity_pct)<=tol)
        if grouped:
            scheme.issues.append('MISSING_COMPLETE_PORTFOLIO')
