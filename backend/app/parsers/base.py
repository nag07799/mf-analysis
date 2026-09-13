from abc import ABC, abstractmethod
from collections import Counter
from datetime import date
from calendar import monthrange
from decimal import Decimal, InvalidOperation
import re
import pymupdf
from dateutil import parser as dates

PARSER_VERSION = '1.0.0'
MONTHS = '(?:January|February|March|April|May|June|July|August|September|October|November|December)'

def clean(text):
    return ' '.join(text.replace('\xa0', ' ').split()).strip(' •£¥#')

def number(value):
    if value is None:
        return None
    s = clean(str(value)).replace(',', '').replace('%', '').replace('₹', '').replace('$', '').replace('−', '-')
    if s in ('', '-', '–', 'N/A', 'NA', 'Nil', 'NIL'):
        return None
    try:
        value = Decimal(s)
        return value if value.is_finite() else None
    except InvalidOperation:
        return None

def parse_date(value):
    if not value:
        return None
    try:
        return dates.parse(clean(value), dayfirst=True).date()
    except (ValueError, TypeError, OverflowError):
        return None

def detect_month(pdf):
    values = []
    for page in pdf:
        text = page.get_text()
        for match in re.finditer(rf'(?:Portfolio\s+(?:as\s+on|as\s+at)|As\s+on)\s+({MONTHS})\s+(\d{{1,2}}),?\s+(20\d{{2}})', text, re.I):
            dt = parse_date(' '.join(match.groups()))
            if dt:
                values.append(dt.replace(day=1))
    if not values:
        for page in list(pdf)[:10]:
            for match in re.finditer(rf'({MONTHS})\s+\d{{1,2}},?\s+(20\d{{2}})', page.get_text(), re.I):
                dt = parse_date(f'{match[1]} 1 {match[2]}')
                if dt:
                    values.append(dt)
    if not values:
        raise ValueError('AMC_LAYOUT_CHANGED: no explicit factsheet month found')
    return Counter(values).most_common(1)[0][0]

def month_end(month):
    return month.replace(day=monthrange(month.year, month.month)[1])

def spans(page):
    return [s for b in page.get_text('dict')['blocks'] if 'lines' in b for l in b['lines'] for s in l['spans']]

def text_region(page, x0, y0, x1, y1):
    return page.get_text(clip=pymupdf.Rect(x0,y0,x1,y1), sort=True)

class BaseParser(ABC):
    @abstractmethod
    def parse(self, path, target_month=None): ...
