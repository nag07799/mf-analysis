"""Parse SEBI-format monthly portfolio spreadsheets published by Indian AMCs.

The layout varies by fund house, but the disclosure contract is stable: a scheme
title, an explicit reporting date, ISIN, instrument, industry, market value and a
percentage-of-NAV column.  This parser deliberately requires those source markers
and an explicit total row before a portfolio can be marked complete.
"""
from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal
from io import BytesIO
from pathlib import Path
import re
import zipfile

import openpyxl

from app.parsers.base import clean, number, parse_date
from app.schemas.parsed import ParsedHolding


# BIFF (.xls) files start with the OLE2 compound-document signature.
OLE2_MAGIC = bytes((0xD0, 0xCF, 0x11, 0xE0))
ISIN = re.compile(r"^[A-Z]{2}[A-Z0-9]{9}[0-9]$")
THRESHOLD = re.compile(r"(?:\*|->|\^|~|@@|@|#)\s*(?:Value\s+)?Less than\s*[\d.]+\s*%\s*[.]?(?:\s*(?:of\s*)?(?:NAV|AUM))?", re.I)
TEMP_SECURITY_ID = re.compile(r"^IN[A-Z0-9]{10}$")
DATE_TEXT = re.compile(
    r"(?:portfolio(?: statement)?\s+as\s+(?:on|at)|as\s+on)\s*:?\s*"
    r"((?:\d{1,2}[- /])?(?:Jan(?:uary)?|Feb(?:ruary)?|Mar(?:ch)?|Apr(?:il)?|May|Jun(?:e)?|Jul(?:y)?|Aug(?:ust)?|"
    r"Sep(?:tember)?|Oct(?:ober)?|Nov(?:ember)?|Dec(?:ember)?)"
    r"(?:[- /]\d{1,2},?|[- /])\s*20\d{2})",
    re.I,
)
TRUST_REIT = re.compile(r"\breits?\b|real estate (?:investment )?trust", re.I)
TRUST_INVIT = re.compile(r"\binvits?\b|infrastructure (?:investment )?trust", re.I)
PROSE = re.compile(
    r"suitable for|should consult|risk-?o-?meter|investors (?:should|are)|"
    r"this product|capital appreciation|investment in|long term|riskometer|"
    r"please refer|disclaimer|"
    # The AMC entity block sits above the scheme title in several layouts.
    r"investment manager|asset management|registered office|trustee company|"
    r"\bcin\b|^[(]|^\*|^[•●]",
    re.I,
)
# Several fund houses state the reporting date numerically ("as on 31-07-26"),
# so the month name cannot be required.  Day-first is the Indian convention and
# parse_date already applies it.
NUMERIC_DATE_TEXT = re.compile(
    r"(?:portfolio(?: statement)?\s+as\s+(?:on|at|of)|as\s+(?:on|of))\s*:?\s*"
    r"(\d{1,2}[-/.]\d{1,2}[-/.](?:20)?\d{2})(?!\d)",
    re.I,
)


@dataclass
class UniversalPortfolio:
    name: str
    as_of_date: date
    holdings: list[ParsedHolding] = field(default_factory=list)
    equity_pct: Decimal | None = None
    aum_crore: Decimal | None = None
    complete: bool = False
    source_sheet: str | None = None
    issues: list[str] = field(default_factory=list)


def _sources(path: Path):
    if path.suffix.lower() == ".zip":
        with zipfile.ZipFile(path) as archive:
            for item in archive.infolist():
                if not item.filename.lower().endswith((".xlsx", ".xlsm", ".xls")):
                    continue
                if item.file_size > 100_000_000 or item.file_size / max(item.compress_size, 1) > 1000:
                    raise ValueError("Workbook archive entry exceeds size limits")
                yield item.filename, BytesIO(archive.read(item))
    else:
        # Passing bytes also lets openpyxl read OOXML workbooks published with a
        # legacy .xls filename, which several AMCs still do.
        yield path.name, BytesIO(path.read_bytes())


def _cell_text(value) -> str:
    return clean(str(value)) if value is not None else ""


def _weight(cell):
    value = number(cell.value)
    # Some published workbooks apply an Excel percent format to values that are
    # already expressed as percentage points (for example, 1.62 meaning 1.62%).
    if value is not None and abs(value) <= 1 and "%" in (cell.number_format or ""):
        value *= 100
    return value


def _scheme_name(rows, header_index):
    # Consolidated SBI/ICICI workbooks sometimes place the AMC name in the
    # title block and the actual scheme next to an explicit "SCHEME NAME"
    # label.  That labelled value is authoritative.
    for row in rows[:header_index]:
        for index, cell in enumerate(row):
            value = _cell_text(cell.value)
            labelled = re.match(r"scheme\s*:\s*(.+)", value, re.I)
            if labelled:
                return labelled.group(1).strip(" -")
            if re.fullmatch(r"scheme\s*name\s*: ?", _cell_text(cell.value), re.I):
                for following in row[index + 1:]:
                    value = _cell_text(following.value)
                    if value:
                        return value.strip(" -")
    candidates = []
    for row in rows[:header_index]:
        for cell in row[:8]:
            value = _cell_text(cell.value)
            if not value or re.search(r"portfolio|statement|disclosure", value, re.I):
                continue
            if re.search(r"\bfund\b|\betf\b", value, re.I):
                value = re.split(r"\s*\((?:An?|erstwhile|formerly)", value, flags=re.I)[0]
                value = value.strip(" -")
                # Riskometer captions and the "suitable for investors" rubric sit
                # in the same header block and can be longer than the real title,
                # so prose has to be rejected before the longest one wins.
                if PROSE.search(value) or len(value) > 90 or len(value.split()) > 14:
                    continue
                candidates.append(value)
    specific = [value for value in candidates if not re.search(r"\bmutual fund\b", value, re.I)]
    return max(specific or candidates, key=len) if candidates else None


class _RowsSheet:
    """A section of a consolidated sheet exposed as a small worksheet."""

    def __init__(self, title, rows):
        self.title = title
        self._rows = rows

    def iter_rows(self):
        return iter(self._rows)


def _portfolio_sheets(book):
    """Split AMCs' one-sheet, many-scheme disclosures at SCHEME markers."""
    for sheet in book.worksheets:
        rows = list(sheet.iter_rows())
        starts = [index for index, row in enumerate(rows)
                  if any(re.match(r"scheme\s*:\s*\S", _cell_text(cell.value), re.I)
                         for cell in row)]
        if len(starts) < 2:
            yield _RowsSheet(sheet.title, rows)
            continue
        starts.append(len(rows))
        for part, (start, end) in enumerate(zip(starts, starts[1:]), 1):
            # Keep the AMC title immediately preceding the first scheme.  The
            # scheme row itself contains everything needed by later sections.
            prefix = rows[max(0, start - 1):start] if start == starts[0] else []
            yield _RowsSheet(f"{sheet.title} #{part}", prefix + rows[start:end])


def _map_header(row):
    values = [_cell_text(c.value) for c in row]
    mapping = {}
    for index, value in enumerate(values):
        low = value.lower()
        if re.fullmatch(r"isin(?:\s*(?:code|no\.?|number))?", low):
            mapping["isin"] = index
        elif re.search(r"name.*instrument|instrument.*name|company\s*/?\s*issuer|issuer\s*name", low):
            mapping["name"] = index
        elif "industry" in low or low in ("rating/industry", "industry / rating"):
            mapping["industry"] = index
        elif ("weight" not in mapping and "%" in value
              and re.search(r"nav|net\s*assets|aum", low)):
            mapping["weight"] = index
        elif re.search(r"market|\bmkt\b|fair value", low) and re.search(r"lakh|lac", low):
            mapping["value"] = index
        elif "quantity" in low:
            mapping["quantity"] = index
    return mapping


class _LegacyCell:
    """Mimics the openpyxl cell surface the parser relies on."""
    __slots__ = ("value", "number_format")

    def __init__(self, value, number_format=""):
        self.value = value
        self.number_format = number_format


class _LegacySheet:
    def __init__(self, book, sheet):
        self._book = book
        self._sheet = sheet
        self.title = sheet.name

    def _format(self, row, column):
        try:
            xf = self._book.xf_list[self._sheet.cell_xf_index(row, column)]
            return self._book.format_map[xf.format_key].format_str or ""
        except Exception:
            return ""

    def iter_rows(self):
        import xlrd

        for index in range(self._sheet.nrows):
            cells = []
            for column, cell in enumerate(self._sheet.row(index)):
                value = cell.value
                if cell.ctype == xlrd.XL_CELL_DATE:
                    value = xlrd.xldate_as_datetime(value, self._book.datemode)
                elif cell.ctype == xlrd.XL_CELL_EMPTY:
                    value = None
                elif cell.ctype == xlrd.XL_CELL_BOOLEAN:
                    value = bool(value)
                cells.append(_LegacyCell(value, self._format(index, column)))
            yield cells


class _LegacyWorkbook:
    """A BIFF (.xls) workbook presented like an openpyxl one.

    Several fund houses still publish the real legacy format, which openpyxl
    cannot read at all, so the rest of the parser stays format-agnostic.
    """

    def __init__(self, data: bytes):
        import xlrd

        self._book = xlrd.open_workbook(file_contents=data, formatting_info=False)
        self.worksheets = [_LegacySheet(self._book, sheet) for sheet in self._book.sheets()]

    def close(self):
        self._book.release_resources()


def _open_workbook(filename: str, source: BytesIO):
    data = source.getvalue()
    if data[:4] == OLE2_MAGIC:
        try:
            return _LegacyWorkbook(data)
        except Exception as exc:
            raise ValueError(f"Unsupported portfolio workbook {filename}: {exc}") from exc
    try:
        return openpyxl.load_workbook(BytesIO(data), read_only=True, data_only=True)
    except Exception as exc:
        raise ValueError(f"Unsupported portfolio workbook {filename}: {exc}") from exc


def parse_universal_portfolios(path, target_month: date, document_id=None):
    path = Path(path)
    portfolios = []
    for filename, source in _sources(path):
        book = _open_workbook(filename, source)
        try:
            for sheet in _portfolio_sheets(book):
                if re.search(r"index$|cover|contents|riskometer|derivative", sheet.title, re.I):
                    continue
                rows = list(sheet.iter_rows())
                header_index = None
                mapping = {}
                as_of = None
                for index, row in enumerate(rows[:30]):
                    line = " ".join(_cell_text(cell.value) for cell in row if cell.value is not None)
                    match = DATE_TEXT.search(line) or NUMERIC_DATE_TEXT.search(line)
                    if match:
                        as_of = parse_date(match.group(1))
                    if as_of is None:
                        as_of = next((cell.value.date() for cell in row
                                      if isinstance(cell.value, datetime)), None)
                    candidate = _map_header(row)
                    if all(key in candidate for key in ("isin", "name", "weight")):
                        header_index, mapping = index, candidate
                        break
                if header_index is None or as_of is None or as_of.replace(day=1) != target_month:
                    continue
                name = _scheme_name(rows, header_index)
                if not name:
                    continue
                portfolio = UniversalPortfolio(name=name, as_of_date=as_of,
                                               source_sheet=f"{filename} / {sheet.title}")
                threshold_documented = bool(THRESHOLD.search("\n".join(
                    _cell_text(cell.value) for row in rows for cell in row if isinstance(cell.value, str)
                )))
                state = None
                portfolio_total_pct = None
                equity_subtotals = []
                total_observed = False
                seen = set()
                for row in rows[header_index + 1:]:
                    values = [_cell_text(cell.value) for cell in row]
                    label = " ".join(value for value in values[:7] if value)
                    weight = _weight(row[mapping["weight"]])
                    market_value = number(row[mapping["value"]].value) if "value" in mapping else None
                    # "NET ASSETS" on its own closes the portfolio in several
                    # layouts; "net asset value per unit" is a different figure.
                    if re.search(r"grand total|total net assets|net assets at the end|^total\s*:"
                                 r"|^net assets\b(?!\s*value)", label, re.I):
                        total_observed = True
                        if market_value is not None:
                            portfolio.aum_crore = market_value / 100
                        break
                    if re.search(r"equity\s*&\s*equity|equity and equity|listed equity", label, re.I):
                        state = "EQUITY"
                        if weight is not None:
                            portfolio.equity_pct = weight
                        continue
                    if re.search(r"real estate investment trust|\breits?\b", label, re.I):
                        state = "REIT"
                    elif re.search(r"infrastructure investment trust|\binvits?\b", label, re.I):
                        state = "INVIT"
                    elif re.search(r"foreign securities", label, re.I):
                        state = "EQUITY"
                    elif re.search(r"debt|money market|treps|cash|term deposit|mutual fund units|other assets|"
                                   r"derivative|stock futures?|index futures?", label, re.I):
                        if not any(ISIN.fullmatch(value) for value in values):
                            state = "OTHER"
                    if re.search(r"sub\s*total|total equity", label, re.I) and state == "EQUITY" and weight is not None:
                        equity_subtotals.append(weight)
                    # Some layouts close the securities block with an explicit
                    # portfolio total before cash; it is a second valid check.
                    if re.match(r"portfolio total\b", label, re.I) and weight is not None:
                        portfolio_total_pct = weight
                    isin = _cell_text(row[mapping["isin"]].value).upper()
                    company = _cell_text(row[mapping["name"]].value)
                    if (not company or not (ISIN.fullmatch(isin) or TEMP_SECURITY_ID.fullmatch(isin))
                            or state not in ("EQUITY", "REIT", "INVIT")):
                        continue
                    if isin in seen:
                        portfolio.issues.append(f"DUPLICATE_SECURITY: {isin}")
                        continue
                    if weight is None or weight < 0 or weight > 100:
                        marker = _cell_text(row[mapping["weight"]].value)
                        if weight is None and market_value == 0:
                            weight = Decimal(0)
                        elif (weight is None and threshold_documented
                              and (market_value is not None
                                   or marker in ("*", "^", "~", "@@", "@", "#"))):
                            weight = Decimal(0)
                        else:
                            portfolio.issues.append(f"INVALID_WEIGHT: {company}")
                            continue
                    seen.add(isin)
                    # A trust is often listed inside the equity block but left out
                    # of the disclosed equity subtotal, so the instrument name -
                    # not the section it sits under - decides its type.
                    security_type = state
                    if TRUST_REIT.search(company):
                        security_type = "REIT"
                    elif TRUST_INVIT.search(company):
                        security_type = "INVIT"
                    industry = (_cell_text(row[mapping["industry"]].value)
                                if "industry" in mapping else None)
                    quantity = number(row[mapping["quantity"]].value) if "quantity" in mapping else None
                    portfolio.holdings.append(ParsedHolding(
                        raw_company_name=company,
                        # QIP allotments can carry an AMC temporary identifier
                        # until NSDL/CDSL issue the final ISIN. Keep the holding
                        # and let security normalisation use its raw name.
                        isin=isin if ISIN.fullmatch(isin) else None,
                        industry=industry or None,
                        weight_pct=weight,
                        market_value_crore=market_value / 100 if market_value is not None else None,
                        quantity=quantity,
                        security_type=security_type,
                        source_document_id=document_id,
                        extraction_method="OFFICIAL_PORTFOLIO_XLSX",
                    ))
                if portfolio.equity_pct is None and equity_subtotals:
                    portfolio.equity_pct = sum(equity_subtotals)
                if portfolio.equity_pct is None and portfolio.holdings:
                    portfolio.equity_pct = sum(h.weight_pct for h in portfolio.holdings)
                disclosed = sum(h.weight_pct for h in portfolio.holdings)
                disclosed_equity = sum(h.weight_pct for h in portfolio.holdings if h.security_type == "EQUITY")
                tolerance = max(Decimal("0.10"), min(Decimal("0.50"), len(portfolio.holdings) * Decimal("0.005")))
                reconciled = portfolio.equity_pct is not None and (
                    abs(disclosed - portfolio.equity_pct) <= tolerance
                    or abs(disclosed_equity - portfolio.equity_pct) <= tolerance
                )
                if not reconciled and portfolio_total_pct is not None:
                    reconciled = abs(disclosed - portfolio_total_pct) <= tolerance
                portfolio.complete = bool(total_observed and reconciled and not portfolio.issues)
                portfolios.append(portfolio)
        finally:
            book.close()
    return portfolios
