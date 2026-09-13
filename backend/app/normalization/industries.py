from sqlalchemy import select
from app.db.models import Industry
from app.normalization.securities import normalize_name

def resolve_industry(session, name):
    if not name:
        return None
    key = normalize_name(name)
    item = session.scalar(select(Industry).where(Industry.canonical_name == key))
    if not item:
        item = Industry(name=name, canonical_name=key)
        session.add(item)
        session.flush()
    return item
