import re
from decimal import Decimal
import pymupdf
from app.parsers.base import BaseParser, detect_month, month_end, clean, number, spans, text_region
from app.schemas.parsed import ParsedScheme, ParsedSnapshot, ParsedHolding
from app.extraction.deterministic import extract_metrics
from app.validation.classification import classify

class HDFCParser(BaseParser):
    def sections(self, pdf):
        found = []
        # Official TOC supports variable page ranges, including one and three page funds.
        for page in list(pdf)[:10]:
            text=page.get_text()
            if 'CONTENTS' not in text:
                continue
            for m in re.finditer(r'(HDFC[^\n]+?)\.{2,}\s*(\d+)(?:\s*[-–]\s*(\d+))?',text):
                name=clean(m[1]); a=int(m[2]); b=int(m[3] or a)
                if 1 <= a <= b <= len(pdf):
                    found.append((name,a,b))
        if found:
            return list(dict.fromkeys(found))
        # Layout fallback: prominent headings plus an official product label.
        headers=[]
        for i,page in enumerate(pdf):
            top=text_region(page,0,0,page.rect.width,150)
            m=re.search(r'(HDFC[^\n]+(?:Fund|ETF|Saver)[^\n]*)\n\s*(?:An |A )',top,re.I)
            if m and (not headers or headers[-1][0]!=clean(m[1])):
                headers.append((clean(m[1]),i+1))
        return [(n,a,headers[j+1][1]-1 if j+1<len(headers) else a) for j,(n,a) in enumerate(headers)]

    def parse(self,path,target_month=None):
        with pymupdf.open(path) as pdf:
            month=detect_month(pdf)
            if target_month and month!=target_month:
                raise ValueError(f'DOCUMENT_MONTH_MISMATCH: {month} != {target_month}')
            output=[]
            for name,start,end in self.sections(pdf):
                pages=[pdf[i] for i in range(start-1,end)]
                text='\n'.join(p.get_text() for p in pages)
                cat=re.search(r'CATEGORY OF SCHEME\s*\n([^\n]+)',text)
                description=re.search(r'\n(An open[^\n]+(?:\n(?!\s*CATEGORY)[^\n]+){0,2})',text,re.I)
                scheme=ParsedScheme(scheme_name=name,start_page=start,end_page=end,
                    category=clean(cat[1]) if cat else None,
                    official_description=clean(description[1]) if description else None,
                    snapshot=ParsedSnapshot(as_of_date=month_end(month)),raw_text=text)
                classify(scheme)
                if scheme.classification_status=='INCLUDED':
                    extract_metrics(scheme,text,'hdfc')
                    try:
                        self.holdings(scheme,pages)
                    except Exception as exc:
                        scheme.issues.append('REGEX_PARSE_FAILURE: '+str(exc)[:300])
                        scheme.snapshot.complete_holdings=False
                output.append(scheme)
            if not output:
                raise ValueError('AMC_LAYOUT_CHANGED: no scheme sections detected')
            self.recover_merged_industries(output)
            return output

    @staticmethod
    def recover_merged_industries(output):
        """Some rows render company and industry as a single PDF text span with no
        coordinate gap to split the two columns on, so the whole span is read as the
        company name. Recover the industry using the vocabulary this same document
        already disclosed on other, cleanly split rows -- nothing here is invented,
        only re-split using labels the document itself used elsewhere."""
        vocabulary = sorted({h.industry for s in output for h in s.holdings if h.industry},
                            key=len, reverse=True)
        for scheme in output:
            for holding in scheme.holdings:
                if holding.industry:
                    continue
                for label in vocabulary:
                    suffix = ' ' + label
                    if holding.raw_company_name.endswith(suffix):
                        remainder = holding.raw_company_name[:-len(suffix)].strip()
                        if remainder:
                            holding.raw_company_name = remainder
                            holding.industry = label
                        break

    def holdings(self,scheme,pages):
        state='EQUITY'
        for page in pages:
            ss=spans(page)
            # Locate each portfolio column by its Company/Instrument header.
            headers=[s for s in ss if clean(s['text']) in ('Company/', 'Company/ Instrument','Company /','Company/Instrument','Company')]
            for header in sorted(headers,key=lambda s:s['bbox'][0]):
                x0,y0=header['bbox'][:2]
                peers=[s for s in ss if 'Industry' in s['text'] and abs(s['bbox'][1]-y0)<25 and s['bbox'][0]>x0]
                if not peers:
                    continue
                ix=min(s['bbox'][0] for s in peers)
                next_x=min([s['bbox'][0] for s in headers if s['bbox'][0]>x0+20] or [page.rect.width-25])
                weights=[w for w in page.get_text('words') if ix+25<w[0]<next_x and w[1]>y0+8
                         and re.fullmatch(r'\d{1,3}\.\d{1,3}',w[4])]
                if not weights:
                    continue
                weight_headers=[s for s in ss if '% to' in s['text'] and x0<s['bbox'][0]<next_x and abs(s['bbox'][1]-y0)<20]
                if not weight_headers:
                    continue
                wx=weight_headers[0]['bbox'][2]
                weights=[w for w in weights if abs(w[2]-wx)<7]
                previous=y0+8
                for w in sorted(weights,key=lambda w:w[1]):
                    y=w[3]+0.6
                    row=[s for s in ss if x0-8<=s['bbox'][0]<wx and s['bbox'][1]>=previous-1 and s['bbox'][3]<=y+1]
                    row.sort(key=lambda s:(round(s['bbox'][1],1),s['bbox'][0]))
                    raw='\n'.join(s['text'] for s in row)
                    company='\n'.join(s['text'] for s in row if s['bbox'][0]<ix-3)
                    industry='\n'.join(s['text'] for s in row if ix-3<=s['bbox'][0]<w[0]-2)
                    previous=y
                    name=clean(company); alltext=clean(raw); val=number(w[4])
                    if re.search(r'PERFORMANCE|Outstanding exposure|Hedged position',alltext,re.I):
                        break
                    if not name:
                        continue
                    if 'EQUITY & EQUITY RELATED' in name:
                        state='EQUITY';name=clean(name.split('EQUITY & EQUITY RELATED')[-1])
                    for heading,typ in [('UNITS ISSUED BY REIT','REIT'),('UNITS ISSUED BY INVIT','INVIT'),
                                        ('DEBT & DEBT RELATED','DEBT'),('MUTUAL FUND UNITS','OTHER')]:
                        if heading in alltext.upper():
                            state=typ
                            # These rows may also contain an instrument after a multi-line heading.
                            lines=[clean(l) for l in company.splitlines() if clean(l)]
                            name=lines[-1] if lines else ''
                    if 'Grand Total' in alltext:
                        scheme.snapshot.portfolio_end_observed=True
                        break
                    if 'Cash' in alltext and 'Current Assets' in alltext:
                        scheme.snapshot.cash_pct=val;continue
                    if re.search(r'Sub\s*Total',alltext,re.I):
                        field={'EQUITY':'equity_pct','REIT':'reit_pct','INVIT':'invit_pct',
                              'DEBT':'debt_pct','OTHER':'other_pct'}.get(state)
                        if field and val is not None:
                            # A document may print more than one 'Other' style subtotal (e.g.
                            # both preference shares and fund units); accumulate rather than overwrite.
                            current=getattr(scheme.snapshot,field) or Decimal(0)
                            setattr(scheme.snapshot,field,current+val if field=='other_pct' else val)
                        continue
                    if re.search(r'\bOthers?\b|remaining|less than|balance of',name,re.I):
                        scheme.issues.append('MISSING_COMPLETE_PORTFOLIO')
                        continue
                    if re.match(r'Total\b|Outstanding|Hedged|\(% age\)',name,re.I):
                        continue
                    if state not in ('EQUITY','REIT','INVIT'):
                        continue
                    name=re.sub(r'^[•\s]+|[£]+','',name).strip()
                    if name and val is not None and 0<=val<=100:
                        scheme.holdings.append(ParsedHolding(raw_company_name=name,industry=clean(industry) or None,
                            weight_pct=val,security_type=state,source_page=page.number+1))
        snap=scheme.snapshot
        total=sum((h.weight_pct for h in scheme.holdings if h.security_type=='EQUITY'),Decimal(0))
        tolerance=max(Decimal('.10'),min(Decimal('.50'),len(scheme.holdings)*Decimal('.005')))
        snap.complete_holdings=bool(not scheme.issues and snap.portfolio_end_observed and snap.equity_pct is not None and abs(total-snap.equity_pct)<=tolerance)
