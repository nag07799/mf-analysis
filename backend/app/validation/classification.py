"""Classification uses product labels, never a name-only equity heuristic."""
import re
from app.config import settings

EXCLUDED = (
    r'arbitrage|balanced advantage|balanced fund|dynamic asset allocation|hybrid|equity savings|'
    r'multi[ -]?asset|money market|\bliquid\b|overnight|\bgilt\b|\bdebt\b|\bgold\b|\bsilver\b|'
    r'fund of funds|fund of fund|\bfof\b|\bcommodit(?:y|ies)\b|\bg[ -]?sec\b|\bsdl\b|'
    r'\belss\b|equity linked savings|tax saver|tax saving|exchange traded|\betf\b|index fund|index funds|'
    r'passive|retirement|children.?s fund|solution oriented|overseas|international|global fund'
)
# A scheme whose SEBI label is an equity scheme holds shares, so these words
# then name the sector its holdings trade in rather than the asset it owns.
SECTOR_NOT_ASSET = r'\bcommodit(?:y|ies)\b|\bgold\b|\bsilver\b'
EQUITY_CATEGORY = r'large.?cap|mid.?cap|small.?cap|multi.?cap|flexi.?cap|focused|value fund|contra|dividend yield|sectoral|thematic'

def classify(scheme, enable_etfs=None):
    etfs = settings.enable_equity_etfs if enable_etfs is None else enable_etfs
    category = scheme.category or ''
    description = scheme.official_description or ''
    evidence = f'{category} {description}'.lower()
    scheme.classification_evidence = evidence.strip() or None
    judged = evidence
    if re.search(r'equity scheme', judged):
        judged = re.sub(SECTOR_NOT_ASSET, ' ', judged)
    if re.search(EXCLUDED, judged):
        scheme.asset_class, scheme.classification_status = 'NON_EQUITY', 'EXCLUDED'
        return scheme
    is_etf = bool(re.search(r'exchange traded|\betf\b', evidence))
    if 'equity' in evidence or re.search(EQUITY_CATEGORY, category.lower()):
        scheme.asset_class = 'EQUITY'
        scheme.management_style = 'ACTIVE'
        scheme.classification_status = 'INCLUDED'
    else:
        scheme.asset_class, scheme.classification_status = 'UNRESOLVED', 'REVIEW_REQUIRED'
    return scheme
