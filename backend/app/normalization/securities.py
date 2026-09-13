import re
import unicodedata
from sqlalchemy import select
from app.db.models import Security, SecurityAlias

class AmbiguousSecurity(ValueError):
    pass

def normalize_name(name: str) -> str:
    name = unicodedata.normalize('NFKC', name).casefold().replace('&', ' and ')
    name = re.sub(r"[’']", '', name)
    name = re.sub(r'\b(limited|ltd)\b\.?', '', name)
    name = re.sub(r'[^a-z0-9]+', ' ', name)
    return ' '.join(name.split())

def resolve_security(session, holding, amc_id):
    key = normalize_name(holding.raw_company_name)
    exact = session.scalar(select(Security).where(Security.isin == holding.isin)) if holding.isin else None
    candidates = list(session.scalars(select(Security).where(
        Security.id.in_(select(SecurityAlias.security_id).where(SecurityAlias.normalized_key == key))
    )))
    if not candidates:
        candidates = list(session.scalars(select(Security).where(Security.normalized_key == key)))
    candidates = [s for s in candidates if s.security_type == holding.security_type]
    if exact:
        if exact.security_type != holding.security_type:
            raise AmbiguousSecurity(f'ISIN type conflict: {holding.raw_company_name}')
        security = exact
    else:
        if len(candidates) > 1:
            raise AmbiguousSecurity(f'Multiple identities for {holding.raw_company_name}')
        security = candidates[0] if candidates else None
        if security and holding.isin and security.isin and security.isin != holding.isin:
            raise AmbiguousSecurity(f'Conflicting ISIN for {holding.raw_company_name}')
        if security and holding.isin and not security.isin:
            security.isin = holding.isin
    created = security is None
    if created:
        security = Security(canonical_name=holding.raw_company_name, normalized_key=key,
                            isin=holding.isin, security_type=holding.security_type)
        session.add(security)
        session.flush()
    if not session.scalar(select(SecurityAlias).where(SecurityAlias.security_id == security.id,
                                                      SecurityAlias.alias_name == holding.raw_company_name)):
        session.add(SecurityAlias(security_id=security.id, alias_name=holding.raw_company_name,
                                  normalized_key=key, source_amc_id=amc_id))
    return security, created
