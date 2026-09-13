from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
import hashlib
import json
from sqlalchemy import select, func
from app.config import settings
from app.db.models import (AMC, Scheme, FactsheetDocument, SchemeFactsheetSection, SchemeMonthlySnapshot,
    SchemePlan, PlanMonthlyMetric, Holding, SectorAllocation, FundManager, SchemeManagerHistory,
    Performance, SIPPerformance, IngestionRun, ReviewItem, Security)
from app.normalization.securities import normalize_name, resolve_security, AmbiguousSecurity
from app.normalization.industries import resolve_industry
from app.validation.portfolio import validate_portfolio
from app.parsers.base import PARSER_VERSION

AMC_INFO = {
 'absl':('Aditya Birla Sun Life Mutual Fund','https://mutualfund.adityabirlacapital.com','https://mutualfund.adityabirlacapital.com/forms-and-downloads/factsheets'),
 'axis':('Axis Mutual Fund','https://www.axismf.com','https://www.axismf.com/downloads'),
 'bandhan':('Bandhan Mutual Fund','https://bandhanmutual.com','https://bandhanmutual.com/downloads/factsheets'),
 'canara':('Canara Robeco Mutual Fund','https://www.canararobeco.com','https://www.canararobeco.com/documents/forms-downloads/forms-information-documents/information-documents/factsheets/'),
 'dsp':('DSP Mutual Fund','https://www.dspim.com','https://www.dspim.com/downloads?category=Information%20Documents&sub_category=Factsheets'),
 'edelweiss':('Edelweiss Mutual Fund','https://www.edelweissmf.com','https://www.edelweissmf.com/downloads/factsheets'),
 'hdfc':('HDFC Mutual Fund','https://www.hdfcfund.com','https://www.hdfcfund.com/mutual-funds/factsheets'),
 'icici':('ICICI Prudential Mutual Fund','https://www.icicipruamc.com','https://digitalfactsheet.icicipruamc.com/fact/'),
 'invesco':('Invesco Mutual Fund','https://invescomutualfund.com','https://invescomutualfund.com/literature-and-form?tab=Factsheets'),
 'kotak':('Kotak Mahindra Mutual Fund','https://www.kotakmf.com','https://www.kotakmf.com/Information/forms-and-downloads/Information'),
 'mirae':('Mirae Asset Mutual Fund','https://www.miraeassetmf.co.in','https://www.miraeassetmf.co.in/downloads/factsheet'),
 'motilal':('Motilal Oswal Mutual Fund','https://www.motilaloswalmf.com','https://www.motilaloswalmf.com/downloads/factsheets'),
 'nippon':('Nippon India Mutual Fund','https://mf.nipponindiaim.com','https://mf.nipponindiaim.com/investor-service/downloads/factsheet-portfolio-and-other-disclosures'),
 'ppfas':('PPFAS Mutual Fund','https://amc.ppfas.com','https://amc.ppfas.com/downloads/factsheet/'),
 'quant':('quant Mutual Fund','https://quantmutual.com','https://quantmutual.com/downloads/factsheet'),
 'sbi':('SBI Mutual Fund','https://www.sbimf.com','https://www.sbimf.com/factsheets'),
 }

def get_amc(session,slug,name=None):
    """Fetch or create the AMC row.

    AMC_INFO only carries the fund houses with a hand-written factsheet
    downloader.  The ranking now spans every AMFI fund house, so an unknown slug
    falls back to the name AMFI itself publishes instead of failing.
    """
    amc=session.scalar(select(AMC).where(AMC.slug==slug))
    if not amc:
        if slug in AMC_INFO:
            amc_name,website,page=AMC_INFO[slug]
        else:
            amc_name,website,page=(name or slug.upper()),None,None
        amc=AMC(slug=slug,name=amc_name,official_website=website,factsheet_page_url=page)
        session.add(amc);session.flush()
    return amc

def register_document(session,amc_id,downloaded):
    d=downloaded.document
    existing=session.scalar(select(FactsheetDocument).where(FactsheetDocument.amc_id==amc_id,
        FactsheetDocument.factsheet_month==d.target_month,FactsheetDocument.document_type==d.document_type,
        FactsheetDocument.sha256==downloaded.sha256))
    if existing:
        return existing,False
    versions=list(session.scalars(select(FactsheetDocument).where(FactsheetDocument.amc_id==amc_id,
        FactsheetDocument.factsheet_month==d.target_month,FactsheetDocument.document_key==d.document_key)))
    for version in versions:
        version.is_current_version=False
    doc=FactsheetDocument(amc_id=amc_id,factsheet_month=d.target_month,document_type=d.document_type,
        document_key=d.document_key,source_url=d.url or None,local_path=str(downloaded.path.resolve()),
        filename=downloaded.filename,sha256=downloaded.sha256,parser_version=PARSER_VERSION,
        version_number=max([v.version_number for v in versions] or [0])+1)
    session.add(doc);session.flush()
    return doc,True

def review(session,run,document,scheme,reason,details):
    scheme_id=scheme.id if scheme else None
    existing=session.scalar(select(ReviewItem).where(ReviewItem.document_id==document.id if document else ReviewItem.document_id.is_(None),
        ReviewItem.scheme_id==scheme_id if scheme_id else ReviewItem.scheme_id.is_(None),
        ReviewItem.review_type==reason,ReviewItem.status=='OPEN'))
    if not existing:
        session.add(ReviewItem(run_id=run.id,scheme_id=scheme_id,document_id=document.id if document else None,
                              review_type=reason,details=details))

def identity_key(*values):
    return json.dumps(values,separators=(',',':'))

def persist_scheme(session,run,document,parsed,root=None):
    root=Path(root) if root else settings.archive_root()
    folder=root/'extracted'/parsed.snapshot.as_of_date.strftime('%Y-%m')/document.sha256
    folder.mkdir(parents=True,exist_ok=True)
    key=hashlib.sha256(parsed.scheme_name.encode()).hexdigest()[:16]
    json_path=folder/f'{key}.json';text_path=folder/f'{key}.txt'
    # Each parser version gets an independent extraction artifact.
    json_path=json_path.with_name(f'{key}-{PARSER_VERSION}.json')
    json_path.write_text(parsed.model_dump_json(indent=2),encoding='utf-8')
    text_path.write_text(parsed.raw_text,encoding='utf-8')
    canonical=normalize_name(parsed.scheme_name)
    scheme=session.scalar(select(Scheme).where(Scheme.amc_id==document.amc_id,Scheme.canonical_name==canonical))
    if not scheme:
        scheme=Scheme(amc_id=document.amc_id,canonical_name=canonical,scheme_name=parsed.scheme_name,
            scheme_code=parsed.scheme_code,category=parsed.category,subcategory=parsed.subcategory,
            asset_class=parsed.asset_class,classification_status=parsed.classification_status,
            classification_evidence=parsed.classification_evidence,management_style=parsed.management_style,
            benchmark=parsed.benchmark,additional_benchmark=parsed.additional_benchmark,inception_date=parsed.inception_date)
        session.add(scheme);session.flush()
    section=session.scalar(select(SchemeFactsheetSection).where(SchemeFactsheetSection.factsheet_document_id==document.id,
        SchemeFactsheetSection.detected_scheme_name==parsed.scheme_name,SchemeFactsheetSection.start_page==parsed.start_page))
    if not section:
        section=SchemeFactsheetSection(factsheet_document_id=document.id,scheme_id=scheme.id,
            detected_scheme_name=parsed.scheme_name,start_page=parsed.start_page,end_page=parsed.end_page,
            extraction_status=parsed.extraction_status)
        session.add(section)
    section.raw_text_path=str(text_path.resolve());section.raw_json_path=str(json_path.resolve())
    if parsed.classification_status!='INCLUDED':
        section.extraction_status=parsed.classification_status
        if parsed.classification_status=='REVIEW_REQUIRED':
            review(session,run,document,scheme,'UNKNOWN_EQUITY_CLASSIFICATION','Official product label could not establish eligibility')
        return 'EXCLUDED',0,0,0
    status,errors=validate_portfolio(parsed)
    if errors or parsed.extraction_status=='REVIEW_REQUIRED':
        section.extraction_status='REVIEW_REQUIRED';section.error_message='; '.join(errors+parsed.issues)
        for error in list(dict.fromkeys(errors+parsed.issues)):
            review(session,run,document,scheme,error.split(':')[0],section.error_message)
        return 'REVIEW_REQUIRED',0,0,0
    existing=session.scalar(select(SchemeMonthlySnapshot).where(SchemeMonthlySnapshot.scheme_id==scheme.id,
        SchemeMonthlySnapshot.as_of_date==parsed.snapshot.as_of_date))
    if existing:
        section.extraction_status='ALREADY_INGESTED'
        if existing.source_document_id != document.id:
            review(session,run,document,scheme,'DOCUMENT_REVISION','New document archived; the existing historical snapshot remains immutable. Review the revised source before replacing data.')
            return 'REVIEW_REQUIRED',0,0,0
        return 'ALREADY_INGESTED',0,0,0
    new=matched=0
    try:
        with session.begin_nested():
            fields=parsed.snapshot.model_dump(exclude={'portfolio_end_observed'})
            snapshot=SchemeMonthlySnapshot(scheme_id=scheme.id,source_document_id=document.id,
                                           validation_status=status,**fields)
            session.add(snapshot);session.flush()
            rows=[];seen=set()
            for h in parsed.holdings:
                security,created=resolve_security(session,h,document.amc_id)
                if security.id in seen:
                    raise AmbiguousSecurity('Duplicate security after normalization: '+h.raw_company_name)
                seen.add(security.id)
                new+=int(created);matched+=int(not created)
                industry=resolve_industry(session,h.industry)
                rows.append(Holding(scheme_snapshot_id=snapshot.id,security_id=security.id,
                    industry_id=industry.id if industry else None,weight_pct=h.weight_pct,
                    quantity=h.quantity,market_value_crore=h.market_value_crore,
                    raw_company_name=h.raw_company_name,raw_industry_name=h.industry,
                    source_document_id=h.source_document_id or document.id,source_page=h.source_page,
                    extraction_method=h.extraction_method,extraction_confidence=h.extraction_confidence))
            rows.sort(key=lambda h:(-h.weight_pct,h.security_id))
            for rank,row in enumerate(rows,1):row.rank=rank
            session.add_all(rows)
            sectors={}
            for row in rows:
                if row.industry_id:
                    sectors[row.industry_id]=sectors.get(row.industry_id,Decimal(0))+row.weight_pct
            for industry_id,weight in sectors.items():
                session.add(SectorAllocation(scheme_snapshot_id=snapshot.id,industry_id=industry_id,
                    weight_pct=weight,calculated=True,source_document_id=document.id))
            for pm in parsed.plans:
                ik=identity_key(pm.plan_type,pm.option_type,pm.idcw_suboption)
                plan=session.scalar(select(SchemePlan).where(SchemePlan.scheme_id==scheme.id,SchemePlan.identity_key==ik))
                if not plan:
                    plan=SchemePlan(scheme_id=scheme.id,identity_key=ik,plan_type=pm.plan_type,option_type=pm.option_type,idcw_suboption=pm.idcw_suboption)
                    session.add(plan);session.flush()
                session.add(PlanMonthlyMetric(scheme_plan_id=plan.id,as_of_date=snapshot.as_of_date,nav=pm.nav,
                    expense_ratio_pct=pm.expense_ratio_pct,base_expense_ratio_pct=pm.base_expense_ratio_pct,source_document_id=document.id))
            for model,values in [(Performance,parsed.performance),(SIPPerformance,parsed.sip_performance)]:
                for value in values:
                    session.add(model(scheme_id=scheme.id,as_of_date=snapshot.as_of_date,
                        identity_key=identity_key(value.plan_type,value.option_type),source_document_id=document.id,**value.model_dump()))
            for manager in parsed.managers:
                mk=normalize_name(manager.name)
                fm=session.scalar(select(FundManager).where(FundManager.canonical_name==mk))
                if not fm:
                    fm=FundManager(name=manager.name,canonical_name=mk);session.add(fm);session.flush()
                existing_manager=session.scalar(select(SchemeManagerHistory).where(SchemeManagerHistory.scheme_id==scheme.id,
                    SchemeManagerHistory.fund_manager_id==fm.id,SchemeManagerHistory.from_date==manager.from_date,
                    SchemeManagerHistory.to_date==manager.to_date))
                if not existing_manager:
                    session.add(SchemeManagerHistory(scheme_id=scheme.id,fund_manager_id=fm.id,source_document_id=document.id,
                        **manager.model_dump(exclude={'name'})))
            session.flush()
        section.extraction_status='COMPLETE'
        return 'SUCCESS',len(rows),new,matched
    except Exception as exc:
        section.extraction_status='REVIEW_REQUIRED';section.error_message=str(exc)[:1000]
        reason='AMBIGUOUS_SECURITY' if isinstance(exc,AmbiguousSecurity) else 'SNAPSHOT_TRANSACTION_FAILED'
        review(session,run,document,scheme,reason,section.error_message)
        return 'REVIEW_REQUIRED',0,0,0

def write_report(session,runs,root=None):
    root=Path(root) if root else settings.archive_root()
    counters=('documents_discovered','documents_downloaded','schemes_detected','equity_schemes_detected',
              'schemes_successful','schemes_failed','holdings_inserted','new_securities','matched_securities',
              'ambiguous_securities','gemini_fallbacks_used')
    report={'generated_at':datetime.now(timezone.utc).isoformat(),'runs':[],'overall':{}}
    for run in runs:
        data={key:getattr(run,key) for key in counters}
        data.update(run_id=run.id,amc=session.get(AMC,run.amc_id).slug,target_month=run.target_month.isoformat(),
                    status=run.status,error_summary=run.error_summary,coverage=run.coverage)
        report['runs'].append(data)
    report['overall']['unique_equity_schemes']=session.scalar(select(func.count(Scheme.id)).where(Scheme.asset_class=='EQUITY',Scheme.classification_status=='INCLUDED'))
    report['overall']['unique_securities']=session.scalar(select(func.count(Security.id)))
    report['overall']['holdings_inserted']=sum(r.holdings_inserted for r in runs)
    report['overall']['open_reviews']=session.scalar(select(func.count(ReviewItem.id)).where(ReviewItem.status=='OPEN'))
    report['overall']['null_counts']={c.name:session.scalar(select(func.count()).select_from(SchemeMonthlySnapshot).where(c.is_(None)))
        for c in SchemeMonthlySnapshot.__table__.columns if c.nullable}
    stem=datetime.now().strftime('%Y-%m-%d')+'_ingestion_report'
    folder=root/'reports';folder.mkdir(parents=True,exist_ok=True)
    # Preserve each run; the requested daily filename is the latest report for that day.
    for name in [stem,stem+'_'+('-'.join(str(r.id) for r in runs))]:
        (folder/(name+'.json')).write_text(json.dumps(report,indent=2,default=str),encoding='utf-8')
        lines=['# Monthly ingestion report','',f'Generated: {report["generated_at"]}','']
        for item in report['runs']:
            lines += [f'## {item["amc"].upper()} — {item["target_month"]}: {item["status"]}','']
            lines += [f'- {k}: {v}' for k,v in item.items() if k not in ('amc','target_month','coverage')]
            if item['coverage']:lines+=['','```json',json.dumps(item['coverage'],indent=2),'```']
            lines+=['']
        lines += ['## Overall','', '```json',json.dumps(report['overall'],indent=2),'```']
        (folder/(name+'.md')).write_text('\n'.join(lines),encoding='utf-8')
    return report
