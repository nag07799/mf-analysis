"""Config-driven discovery of official monthly portfolio disclosures.

Most fund houses publish the SEBI monthly portfolio as a workbook linked from a
single disclosure page, so the only thing that really varies between them is the
page URL, the domains to trust and whether the page needs JavaScript to render.
Those differences live in AMC_SOURCES; the logic below is shared.

A downloader here deliberately implements portfolio discovery only.  Factsheet
PDFs remain the job of the hand-written per-AMC downloaders, because their
layouts require a bespoke parser anyway.
"""
from dataclasses import dataclass, field
from datetime import date
from urllib.parse import unquote
import calendar
import re

from app.downloaders.base import BaseAMCDownloader, Document, SourceUnavailable

# Bot protection on some official sites rejects the default automation agent.
BROWSER_UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
              "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36")
# Month-end holdings only: fortnightly statements, debt-only extracts, overlap
# and risk tables share the same pages and would otherwise be ingested as if
# they were the month-end portfolio.
NOT_MONTH_END = re.compile(
    r"fortnight|overlap|risk\s*-?\s*parameter|riskometer|debt[-_ ]portfolio|"
    r"half[-_ ]?year|\bhy\b|tracking|expense|ter\b",
    re.I,
)
WORKBOOK = re.compile(r"\.(xlsx|xlsm|xls|zip)(\?|$)", re.I)
URL_IN_TEXT = re.compile(r'https?://[^\s"<>\\\')]+')
MONTHS = {name.lower(): index for index, name in enumerate(calendar.month_name) if name}
MONTHS.update({name.lower(): index for index, name in enumerate(calendar.month_abbr) if name})
MONTH_WORD = "|".join(sorted(MONTHS, key=len, reverse=True))

# "31st May 2026", "May 31 2026", "May-2026" - a day may or may not be present.
NAMED_DATE = re.compile(
    rf"(?P<day>\d{{1,2}})(?:st|nd|rd|th)?[\s_/.-]*(?P<month>{MONTH_WORD})[\s_/.,-]*(?P<year>20\d{{2}})"
    rf"|(?P<month2>{MONTH_WORD})[\s_/.,-]*(?P<day2>\d{{1,2}})(?:st|nd|rd|th)?[\s_/.,-]*(?P<year2>20\d{{2}})"
    rf"|(?P<month3>{MONTH_WORD})[\s_/.,-]*(?P<year3>20\d{{2}})",
    re.I,
)
# "31-Aug-25" - a two-digit year is unambiguous next to a month name.
NAMED_DMY_SHORT = re.compile(
    rf"(?P<day>\d{{1,2}})[\s_/.-](?P<month>{MONTH_WORD})[\s_/.-](?P<year>\d{{2}})(?!\d)",
    re.I,
)
# A CMS may carry the month only in the path, as ".../2026/jul/".
YEAR_THEN_MONTH = re.compile(rf"(?P<year>20\d{{2}})[\s_/.-](?P<month>{MONTH_WORD})(?![a-z])", re.I)
NUMERIC_DMY = re.compile(r"\b(?P<day>\d{1,2})[-_/.](?P<month>\d{1,2})[-_/.](?P<year>20\d{2})\b")
NUMERIC_YM = re.compile(r"\b(?P<year>20\d{2})[-_/.](?P<month>0[1-9]|1[0-2])\b")


def months_in(text: str) -> set[tuple[int, int]]:
    """Every (year, month) a filename or link text plausibly refers to."""
    text = unquote(text or "")
    found: set[tuple[int, int]] = set()
    for match in NAMED_DATE.finditer(text):
        name = match.group("month") or match.group("month2") or match.group("month3")
        year = match.group("year") or match.group("year2") or match.group("year3")
        found.add((int(year), MONTHS[name.lower()]))
    for match in NAMED_DMY_SHORT.finditer(text):
        found.add((2000 + int(match.group("year")), MONTHS[match.group("month").lower()]))
    for match in YEAR_THEN_MONTH.finditer(text):
        found.add((int(match.group("year")), MONTHS[match.group("month").lower()]))
    for match in NUMERIC_DMY.finditer(text):
        month = int(match.group("month"))
        if 1 <= month <= 12:
            found.add((int(match.group("year")), month))
    for match in NUMERIC_YM.finditer(text):
        found.add((int(match.group("year")), int(match.group("month"))))
    return found


def refers_to_month(text: str, target: date) -> bool:
    return (target.year, target.month) in months_in(text)


def link_refers_to_month(href: str, target: date, extra: str = "") -> bool:
    """Judge a link by its file name first.

    A CMS often files a document under the folder of the month it was *published*
    (May's portfolio lands in .../2026-06/), so the surrounding path would match
    the wrong month.  The file name states the month the portfolio is *as on*,
    so when it carries a date at all, it alone decides.
    """
    basename = unquote(href.split("?")[0]).rsplit("/", 1)[-1]
    stamped = months_in(basename) or months_in(extra)
    if stamped:
        return (target.year, target.month) in stamped
    return refers_to_month(f"{href} {extra}", target)


@dataclass(frozen=True)
class AMCSource:
    """Where one fund house publishes its monthly portfolio disclosure."""
    slug: str
    amfi_name: str
    domains: tuple[str, ...]
    portfolio_pages: tuple[str, ...]
    # Sites that build the document list in the browser need a real render.
    render: bool = False
    # Some pages label the link with the month and put a hash in the file name.
    match_link_text: bool = False
    # A few fund houses serve 403 to headless Chromium but not to a real window.
    headed: bool = False
    website: str | None = None


AMC_SOURCES: dict[str, AMCSource] = {
    "ppfas": AMCSource(
        slug="ppfas", amfi_name="PPFAS Mutual Fund", domains=("ppfas.com",),
        portfolio_pages=("https://amc.ppfas.com/downloads/portfolio-disclosure/",),
        website="https://amc.ppfas.com",
    ),
    "absl": AMCSource(
        slug="absl", amfi_name="Aditya Birla Sun Life Mutual Fund",
        domains=("adityabirlacapital.com",),
        portfolio_pages=(
            "https://mutualfund.adityabirlacapital.com/forms-and-downloads/portfolio",),
        render=True,
        website="https://mutualfund.adityabirlacapital.com",
    ),
    "hdfc": AMCSource(
        slug="hdfc", amfi_name="HDFC Mutual Fund", domains=("hdfcfund.com",),
        portfolio_pages=(
            "https://www.hdfcfund.com/statutory-disclosure/portfolio/monthly-portfolio",),
        render=True, headed=True,
        website="https://www.hdfcfund.com",
    ),
    "mirae": AMCSource(
        slug="mirae", amfi_name="Mirae Asset Mutual Fund",
        domains=("miraeassetmf.co.in",),
        portfolio_pages=("https://www.miraeassetmf.co.in/downloads/portfolio",),
        render=True,
        website="https://www.miraeassetmf.co.in",
    ),
    "motilal": AMCSource(
        slug="motilal", amfi_name="Motilal Oswal Mutual Fund",
        domains=("motilaloswalmf.com",),
        portfolio_pages=(
            "https://www.motilaloswalmf.com/downloads/scheme-portfolio-details",),
        render=True,
        website="https://www.motilaloswalmf.com",
    ),
    "nippon": AMCSource(
        slug="nippon", amfi_name="Nippon India Mutual Fund",
        domains=("nipponindiaim.com",),
        portfolio_pages=("https://mf.nipponindiaim.com/investor-service/downloads/"
                         "factsheet-portfolio-and-other-disclosures",),
        render=True,
        website="https://mf.nipponindiaim.com",
    ),
    "tata": AMCSource(
        slug="tata", amfi_name="Tata Mutual Fund",
        domains=("tatamutualfund.com",),
        portfolio_pages=("https://www.tatamutualfund.com/schemes-related/portfolio",),
        website="https://www.tatamutualfund.com",
    ),
}


class GenericPortfolioDownloader(BaseAMCDownloader):
    """Harvest month-stamped portfolio workbooks from a configured page."""

    def __init__(self, source: AMCSource, root=None, client=None):
        self.source = source
        self.slug = source.slug
        self.allowed_domains = source.domains
        super().__init__(root=root, client=client)

    def discover_documents(self, target_month):
        # Factsheet PDFs are out of scope for the config-driven path.
        return []

    def _rendered(self, url: str) -> tuple[str, list[tuple[str, str]]]:
        """Return page HTML plus (href, link text) pairs, rendering if configured."""
        if not self.source.render:
            html = self.page(url)
            pairs = [(href, "") for href in self.links(html, url)]
            return html, pairs
        from playwright.sync_api import sync_playwright

        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(
                headless=not self.source.headed,
                args=["--no-sandbox", "--disable-blink-features=AutomationControlled"])
            try:
                context = browser.new_context(
                    user_agent=BROWSER_UA, locale="en-IN",
                    viewport={"width": 1440, "height": 900},
                    extra_http_headers={"Accept-Language": "en-IN,en;q=0.9"})
                page = context.new_page()
                response = page.goto(url, wait_until="domcontentloaded", timeout=60000)
                if not response or response.status >= 400:
                    status = response.status if response else "no response"
                    raise SourceUnavailable(f"Official source returned {status}")
                page.wait_for_timeout(4000)
                html = page.content()
                pairs = [(item["h"], item["t"]) for item in page.eval_on_selector_all(
                    "a[href]", "els=>els.map(e=>({h:e.href,t:(e.innerText||'').trim()}))")
                    if item["h"]]
                return html, pairs
            finally:
                browser.close()

    def discover_portfolios(self, target_month):
        found: dict[str, Document] = {}
        for url in self.source.portfolio_pages:
            try:
                html, pairs = self._rendered(url)
            except Exception as exc:
                self.discovery_errors.append(f"{url}: {type(exc).__name__}: {exc}"[:300])
                continue
            # Links injected as plain text in scripts are still official URLs.
            candidates = list(pairs)
            candidates += [(href, "") for href in URL_IN_TEXT.findall(html)]
            for href, text in candidates:
                if not href or not WORKBOOK.search(href):
                    continue
                basename = unquote(href.split("?")[0]).rsplit("/", 1)[-1]
                if NOT_MONTH_END.search(basename):
                    continue
                extra = text if self.source.match_link_text else ""
                if not link_refers_to_month(href, target_month, extra):
                    continue
                found.setdefault(href, Document(href, target_month, "portfolio",
                                                "PORTFOLIO_DISCLOSURE"))
        return list(found.values())


def build(slug: str, root=None, client=None) -> GenericPortfolioDownloader:
    return GenericPortfolioDownloader(AMC_SOURCES[slug], root=root, client=client)
