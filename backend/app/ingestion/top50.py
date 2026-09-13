"""Rank and ingest the 50 largest eligible active domestic-equity schemes.

Ranking comes from AMFI's official scheme-wise AAUM disclosure.  Holdings come
only from official AMC month-end portfolio spreadsheets.  Plan and option rows
are consolidated into one underlying scheme before ranking.
"""
from dataclasses import dataclass
from datetime import date, datetime, timezone
from decimal import Decimal
from difflib import SequenceMatcher
from pathlib import Path
import argparse
import hashlib
import json
import re
import sys

from sqlalchemy import func, select

from app.config import settings
from app.db.models import FactsheetDocument, Holding, IngestionRun, Scheme, SchemeMonthlySnapshot
from app.db.session import SessionLocal
from app.downloaders.base import Document, DownloadedDocument
from app.ingestion.service import get_amc, persist_scheme, register_document
from app.downloaders.resolve import portfolio_downloader, supported_slugs
from app.net import client as http_client
from app.normalization.securities import normalize_name
from app.parsers.universal_portfolio import parse_universal_portfolios
from app.schemas.parsed import ParsedScheme, ParsedSnapshot


AMFI_AAUM_API = "https://www.amfiindia.com/api/average-aum-schemewise"
# Every fund house AMFI reports an equity scheme for.  The ranking must span
# all of them, otherwise "top 50" would silently mean "top 50 of a subset".
AMC_SLUGS = {
    '360 ONE Mutual Fund': '360one',
    'Abakkus Mutual Fund': 'abakkus',
    'Aditya Birla Sun Life Mutual Fund': 'absl',
    'Axis Mutual Fund': 'axis',
    'Bajaj Finserv Mutual Fund': 'bajaj',
    'Bandhan Mutual Fund': 'bandhan',
    'Bank of India Mutual Fund': 'boi',
    'Baroda BNP Paribas Mutual Fund': 'barodabnp',
    'Canara Robeco Mutual Fund': 'canara',
    'Capitalmind Mutual Fund': 'capitalmind',
    'DSP Mutual Fund': 'dsp',
    'Edelweiss Mutual Fund': 'edelweiss',
    'Franklin Templeton Mutual Fund': 'franklin',
    'Groww Mutual Fund': 'groww',
    'HDFC Mutual Fund': 'hdfc',
    'HSBC Mutual Fund': 'hsbc',
    'Helios Mutual Fund': 'helios',
    'ICICI Prudential Mutual Fund': 'icici',
    'ITI Mutual Fund': 'iti',
    'Invesco Mutual Fund': 'invesco',
    'JM Financial Mutual Fund': 'jm',
    'Jio BlackRock Mutual Fund': 'jioblackrock',
    'Kotak Mahindra Mutual Fund': 'kotak',
    'LIC Mutual Fund': 'lic',
    'Mahindra Manulife Mutual Fund': 'mahindra',
    'Mirae Asset Mutual Fund': 'mirae',
    'Motilal Oswal Mutual Fund': 'motilal',
    'NJ Mutual Fund': 'nj',
    'Navi Mutual Fund': 'navi',
    'Nippon India Mutual Fund': 'nippon',
    'Old Bridge Mutual Fund': 'oldbridge',
    'PGIM India Mutual Fund': 'pgim',
    'PPFAS Mutual Fund': 'ppfas',
    'Quantum Mutual Fund': 'quantum',
    'SBI Mutual Fund': 'sbi',
    'Samco Mutual Fund': 'samco',
    'Shriram Mutual Fund': 'shriram',
    'Sundaram Mutual Fund': 'sundaram',
    'Tata Mutual Fund': 'tata',
    'Taurus Mutual Fund': 'taurus',
    'The Wealth Company Mutual Fund': 'wealthcompany',
    'Trust Mutual Fund': 'trust',
    'UTI Mutual Fund': 'uti',
    'Unifi Mutual Fund': 'unifi',
    'Union Mutual Fund': 'union',
    'WhiteOak Capital Mutual Fund': 'whiteoak',
    'quant Mutual Fund': 'quant',
}
EXCLUDED_NAME = re.compile(
    r"\belss\b|tax saver|tax saving|\betf\b|index|passive|arbitrage|hybrid|"
    r"equity savings|multi[ -]?asset|fund of funds|fund of fund|\bfof\b|gold|silver|"
    r"commodity|debt|liquid|overnight|money market|gilt|retirement|children|"
    r'overseas|international|global fund|us bluechip|'
    # Country and region funds hold foreign listings, not domestic equity.
    r'\btaiwan\b|\bjapan\b|\bchina\b|\bkorea\b|\bbrazil\b|\basean\b|\beurope\b|'
    r'\bamerica\b|\bnasdaq\b|hang seng|emerging market|\bus equity\b|\bu\.s\. equity\b',
    re.I,
)


@dataclass
class RankedScheme:
    rank: int
    amc_name: str
    amc_slug: str
    scheme_name: str
    category: str
    aaum_crore: Decimal
    amfi_codes: list[int]


def underlying_name(name: str) -> str:
    value = " ".join(name.split()).strip(" -–")
    # AMFI carries the rename history in the scheme name itself
    # ("... Fund (erstwhile ... Fund)"); the AMC's portfolio uses the new name.
    value = re.sub(r"\s*\((?:erstwhile|formerly|earlier)\b[^)]*\)?", "", value, flags=re.I)
    # AMC naming is inconsistent, so remove option/plan suffixes from the right.
    suffixes = (
        r"\s*[-–:]?\s*(?:Direct|Regular)\s+(?:Plan|Option)\b.*$",
        # AMFI writes the plan as "- Direct Plan", "- REGULAR" or "-Direct"
        # alike; a bare word still marks a plan when a separator precedes it.
        r"\s*[-–:]\s*(?:Direct|Regular)\b.*$",
        r"\s+(?:Direct|Regular)(?:\s+(?:Plan|Option))?$",
        r"\s*[-–:]\s*(?:Growth|IDCW|Dividend|Cumulative)(?:\s+(?:Plan|Option))?\b.*$",
        r"\s+(?:Growth|IDCW|Dividend|Cumulative)(?:\s+(?:Plan|Option))?$",
        # Legacy share classes and IDCW wordings name the same portfolio.
        r"\s*[-–:]?\s*(?:Payout|Reinvestment)\s+of\s+Income\s+Distribution.*$",
        r"\s*[-–:]?\s*Income\s+Distribution\s+cum\s*\s*Capital\s+Withdrawal.*$",
        r"\s*[-–:]?\s*(?:Standard|Institutional|Retail|Eco)\s+Plan\b.*$",
        r"\s*[-–:]\s*Plan\s+[A-Z]\b.*$",
        r"\s*[-–:]?\s*(?:Bonus|Payout|Reinvestment)(?:\s+Option)?$",
    )
    previous = None
    while previous != value:
        previous = value
        for pattern in suffixes:
            value = re.sub(pattern, "", value, flags=re.I).strip(" -–")
    return value


def is_eligible_category(category: str) -> bool:
    return category.startswith(("Equity Scheme -", "Equity Schemes -")) and not re.search(
        r"ELSS|Tax Saver", category, re.I
    )


def rank_top_schemes(payload: dict, limit=50):
    combined = {}
    for group in payload["data"]:
        category = group["SchemeCat_Desc"]
        amc_name = group["Mfname"]
        if not is_eligible_category(category) or amc_name not in AMC_SLUGS:
            continue
        for row in group["schemes"]:
            name = underlying_name(row["SchemeNAVName"])
            if EXCLUDED_NAME.search(name):
                continue
            key = (amc_name, scheme_key(name))
            amount = row["AverageAumForTheMonth"][
                "ExcludingFundOfFundsDomesticButIncludingFundOfFundsOverseas"
            ] or 0
            item = combined.setdefault(
                key, {"name": name, "category": category, "amount": Decimal(0), "codes": []})
            # AMFI expresses scheme AAUM in lakh rupees; database values are crore.
            item["amount"] += Decimal(str(amount)) / 100
            item["codes"].append(int(row["AMFI_Code"]))
    ordered = sorted(combined.items(), key=lambda item: item[1]["amount"], reverse=True)[:limit]
    return [RankedScheme(
        rank=index,
        amc_name=key[0],
        amc_slug=AMC_SLUGS[key[0]],
        scheme_name=value["name"],
        category=value["category"],
        aaum_crore=value["amount"],
        amfi_codes=value["codes"],
    ) for index, (key, value) in enumerate(ordered, 1)]


def fetch_ranking(client=None):
    client = client or http_client(timeout=60, follow_redirects=True)
    years = client.get(AMFI_AAUM_API, params={"strType": "Categorywise", "MF_ID": 0})
    years.raise_for_status()
    latest_year = years.json()["data"][0]
    periods = client.get(AMFI_AAUM_API, params={
        "strType": "Categorywise", "MF_ID": 0, "fyId": latest_year["id"]
    })
    periods.raise_for_status()
    latest_period = periods.json()["data"]["periods"][-1]
    response = client.get(AMFI_AAUM_API, params={
        "strType": "Categorywise", "MF_ID": 0,
        "fyId": latest_year["id"], "periodId": latest_period["id"],
    })
    response.raise_for_status()
    return response.json(), latest_year["financial_year"], latest_period["period"]


CAP_TOKENS = frozenset({"large", "mid", "small", "multi", "flexi", "micro"})


def scheme_key(name: str) -> str:
    """Comparison key for a scheme name.

    AMCs and AMFI disagree on whether the cap word is joined to "cap"
    ("Midcap Fund" against "Mid Cap Fund"), which otherwise splits one fund
    into two ranking entries and stops a portfolio from matching its scheme.
    """
    key = normalize_name(name)
    for cap in CAP_TOKENS:
        key = re.sub(r"\b" + cap + r"cap\b", cap + " cap", key)
    return key


def cap_signature(name: str) -> frozenset:
    """The capitalisation words a scheme name commits to.

    "Large & Midcap" and "Midcap" are similar enough as strings to pass a fuzzy
    threshold, but they are different funds.  Comparing the cap words directly
    keeps the two apart while leaving ordinary spelling variation alone.
    """
    found = set()
    for token in normalize_name(name).split():
        for cap in CAP_TOKENS:
            # AMCs write the same thing as "mid cap" or "midcap".
            if token == cap or token == cap + "cap":
                found.add(cap)
    return frozenset(found)


def distinctive_part(name: str, amc_name: str) -> str:
    """What is left of a scheme name once the fund house's own name is removed.

    Every scheme of one AMC repeats the house name, so comparing whole names
    scores unrelated funds highly on that shared prefix alone - "ICICI
    Prudential MNC Fund" against "ICICI Prudential FMCG Fund" reaches 0.94.
    Comparing only the part that names the strategy keeps them apart.
    """
    house = set(scheme_key(amc_name).split()) | {"fund", "scheme"}
    return " ".join(token for token in scheme_key(name).split() if token not in house)


def match_portfolio(target: RankedScheme, candidates, claimed=frozenset()):
    """Best portfolio for one scheme, never one already taken by another."""
    wanted = scheme_key(target.scheme_name)
    available = [item for item in candidates if id(item) not in claimed]
    exact = [item for item in available if scheme_key(item.name) == wanted]
    if exact:
        return exact[0], 1.0
    signature = cap_signature(target.scheme_name)
    strategy = distinctive_part(target.scheme_name, target.amc_name)
    if not strategy:
        return None, 0
    scored = []
    for item in available:
        if cap_signature(item.name) != signature:
            continue
        other = distinctive_part(item.name, target.amc_name)
        if not other:
            continue
        scored.append((SequenceMatcher(None, strategy, other).ratio(), item))
    scored.sort(reverse=True, key=lambda pair: pair[0])
    return (scored[0][1], scored[0][0]) if scored else (None, 0)


def in_scope_portfolios(candidates):
    """Drop workbooks for products the ranking itself excludes.

    A fund house publishes its ETF and index portfolios beside its active ones.
    Those must never stand in for an active scheme, so they are judged by the
    same rule that keeps them out of the ranking.
    """
    return [(item, document) for item, document in candidates
            if not EXCLUDED_NAME.search(item.name or "") and not is_foreign_portfolio(item)]


def is_foreign_portfolio(item) -> bool:
    """True when most of the holdings are listed outside India.

    Naming alone cannot catch every country fund, but an Indian listing carries
    an IN-prefixed ISIN, so the holdings themselves settle it.  A domestic fund
    holding the odd depositary receipt stays in.
    """
    coded = [h.isin for h in getattr(item, "holdings", []) if h.isin]
    if not coded:
        return False
    foreign = sum(1 for isin in coded if not isin.upper().startswith("IN"))
    return foreign * 2 > len(coded)


def dedupe_portfolios(candidates):
    """One portfolio per scheme, even when several workbooks carry it.

    A fund house often repeats a scheme across its combined and per-scheme
    files.  Those parse into separate objects holding the same portfolio, so
    claiming one by identity would still leave its twin free for a differently
    named scheme to match.
    """
    best = {}
    for item, document in candidates:
        key = scheme_key(item.name)
        current = best.get(key)
        # A complete parse beats a truncated one; otherwise keep the first.
        if current is None or (not current[0].complete and item.complete):
            best[key] = (item, document)
    return list(best.values())


MATCH_THRESHOLD = 0.72


def match_all(targets, candidates):
    """Assign at most one portfolio per scheme, exact names first.

    Resolving every exact name before any fuzzy one matters: a scheme whose
    portfolio the AMC did not publish would otherwise fuzzy-take the workbook
    belonging to a similarly named scheme further down the ranking, and that
    scheme would then be reported missing instead.
    """
    assigned, claimed = {}, set()
    for target in targets:
        matched, score = match_portfolio(target, candidates, claimed)
        if matched is not None and score == 1.0:
            assigned[target.rank] = (matched, score)
            claimed.add(id(matched))
    for target in targets:
        if target.rank in assigned:
            continue
        matched, score = match_portfolio(target, candidates, claimed)
        if matched is not None and score >= MATCH_THRESHOLD:
            assigned[target.rank] = (matched, score)
            claimed.add(id(matched))
        else:
            assigned[target.rank] = (None, score)
    return assigned


def _downloaded(path: Path, slug: str, target_month: date, source_url=None,
                document_type="PORTFOLIO_DISCLOSURE"):
    content = path.read_bytes()
    document = Document(source_url or "", target_month, f"top50-{path.stem}", document_type)
    return DownloadedDocument(document, path, hashlib.sha256(content).hexdigest(), path.name)


def ingest_archive(target_month: date, ranking, source_manifest, root=None):
    root = Path(root or settings.archive_root())
    by_amc = {}
    for row in ranking:
        by_amc.setdefault(row.amc_slug, []).append(row)
    summary = {"target_month": target_month.isoformat(), "requested": len(ranking),
               "ingested": 0, "holdings": 0, "unmatched": [], "incomplete": [],
               "rejected": []}
    with SessionLocal() as session:
        for slug, targets in by_amc.items():
            sources = source_manifest.get(slug, [])
            if not sources:
                # No official document for this fund house this month; record the
                # affected schemes rather than opening an empty ingestion run.
                summary["unmatched"] += [{"rank": t.rank, "scheme": t.scheme_name,
                                          "amc": slug, "reason": "NO_SOURCE_DOCUMENT"}
                                         for t in targets]
                continue
            amc = get_amc(session, slug, targets[0].amc_name)
            run = IngestionRun(target_month=target_month, amc_id=amc.id, status="RUNNING")
            session.add(run)
            session.flush()
            candidates = []
            documents = {}
            for source in sources:
                # Manifests written on Windows remain portable when ingestion is
                # later run in WSL/Linux.
                path = root / Path(source["path"].replace("\\", "/"))
                if not path.exists():
                    continue
                source_month = datetime.strptime(
                    source.get("as_of_month", target_month.strftime("%Y-%m")), "%Y-%m"
                ).date().replace(day=1)
                document_type = source.get("document_type", "PORTFOLIO_DISCLOSURE")
                downloaded = _downloaded(path, slug, source_month, source.get("url"), document_type)
                document, _ = register_document(session, amc.id, downloaded)
                documents[str(path.resolve())] = document
                run.documents_discovered += 1
                run.documents_downloaded += 1
                # Factsheets are archived and registered as provenance. Complete
                # holdings still come from the official monthly disclosure.
                if document_type != "PORTFOLIO_DISCLOSURE":
                    continue
                parsed = parse_universal_portfolios(path, source_month, document.id)
                candidates.extend((item, document) for item in parsed)
            candidates = dedupe_portfolios(in_scope_portfolios(candidates))
            assigned = match_all(targets, [item for item, _ in candidates])
            for target in targets:
                matched, score = assigned[target.rank]
                if matched is None:
                    summary["unmatched"].append({"rank": target.rank, "scheme": target.scheme_name,
                                                 "amc": slug, "best_score": round(float(score), 3)})
                    run.schemes_failed += 1
                    continue
                document = next(doc for item, doc in candidates if item is matched)
                if not matched.complete:
                    summary["incomplete"].append({"rank": target.rank, "scheme": target.scheme_name,
                                                  "source_scheme": matched.name,
                                                  "issues": matched.issues})
                    run.schemes_failed += 1
                    continue
                parsed = ParsedScheme(
                    scheme_name=target.scheme_name,
                    scheme_code=",".join(map(str, target.amfi_codes)),
                    category=target.category,
                    official_description=target.category,
                    asset_class="EQUITY",
                    classification_status="INCLUDED",
                    management_style="ACTIVE",
                    snapshot=ParsedSnapshot(
                        as_of_date=matched.as_of_date,
                        aum_crore=matched.aum_crore,
                        equity_pct=matched.equity_pct,
                        complete_holdings=True,
                        portfolio_end_observed=True,
                        field_provenance={
                            "holdings": {"method": "OFFICIAL_PORTFOLIO_XLSX",
                                         "sheet": matched.source_sheet},
                            "ranking": {"method": "AMFI_SCHEME_AAUM", "rank": target.rank,
                                        "aaum_crore": str(target.aaum_crore)},
                        },
                        extra_fields={"ranking_aaum_crore": str(target.aaum_crore),
                                      "top50_rank": target.rank},
                    ),
                    holdings=matched.holdings,
                    raw_text=f"Official portfolio spreadsheet: {matched.source_sheet}",
                )
                status, holdings, new, old = persist_scheme(session, run, document, parsed, root)
                if status in ("SUCCESS", "ALREADY_INGESTED"):
                    summary["ingested"] += 1
                    summary["holdings"] += holdings
                    run.schemes_successful += 1
                    run.holdings_inserted += holdings
                    run.new_securities += new
                    run.matched_securities += old
                else:
                    summary["rejected"].append({
                        "rank": target.rank,
                        "scheme": target.scheme_name,
                        "source_scheme": matched.name,
                        "status": status,
                    })
                    run.schemes_failed += 1
            run.status = ("SUCCESS" if run.schemes_successful and not run.schemes_failed else
                          "PARTIAL_SUCCESS" if run.schemes_successful else "FAILED")
            run.completed_at = datetime.now(timezone.utc)
            session.commit()
        # Idempotent reruns return zero newly inserted holdings, which made the
        # run summary understate what PostgreSQL actually contains.  Report
        # current ranked coverage separately from this run's write counts.
        covered = []
        for target in ranking:
            amc = get_amc(session, target.amc_slug, target.amc_name)
            scheme = session.scalar(select(Scheme).where(
                Scheme.amc_id == amc.id,
                Scheme.canonical_name == normalize_name(target.scheme_name),
            ))
            if scheme is None:
                continue
            snapshot = session.scalar(select(SchemeMonthlySnapshot).where(
                SchemeMonthlySnapshot.scheme_id == scheme.id,
                SchemeMonthlySnapshot.complete_holdings.is_(True),
            ).order_by(SchemeMonthlySnapshot.as_of_date.desc()).limit(1))
            if snapshot is None:
                continue
            holding_count = session.scalar(select(func.count(Holding.id)).where(
                Holding.scheme_snapshot_id == snapshot.id
            )) or 0
            covered.append({
                "rank": target.rank,
                "scheme": target.scheme_name,
                "as_of_date": snapshot.as_of_date.isoformat(),
                "holdings": holding_count,
            })
        summary["database_coverage"] = {
            "schemes": len(covered),
            "holdings": sum(item["holdings"] for item in covered),
            "snapshots": covered,
        }
    return summary


def archived_portfolios(root: Path, slug: str, target_month: date):
    """Workbooks already downloaded for this fund house and month."""
    month = root / "raw" / target_month.strftime("%Y-%m")
    if not month.is_dir():
        return []
    found = []
    for folder in month.iterdir():
        # Folder casing differs between the bespoke and config-driven downloaders.
        if folder.is_dir() and folder.name.casefold() == slug.casefold():
            found += [path for path in sorted(folder.iterdir())
                      if path.suffix.lower() in (".xlsx", ".xlsm", ".xls", ".zip")]
    return found


def download_portfolios(ranking, target_month: date, root=None, slugs=None):
    """Fetch each fund house's official monthly portfolio into the archive.

    Returns the manifest ingest_archive expects plus a per-AMC report, so an
    AMC with no configured source is stated rather than silently dropped.
    """
    root = Path(root or settings.archive_root())
    wanted = sorted({row.amc_slug for row in ranking} if slugs is None else set(slugs))
    manifest, report = {}, {}
    for slug in wanted:
        downloader = portfolio_downloader(slug, root=root)
        if downloader is None:
            report[slug] = {"status": "NO_SOURCE_CONFIGURED", "documents": 0}
            continue
        entry = {"status": "OK", "documents": 0, "errors": []}
        try:
            documents = downloader.discover_portfolios(target_month)
        except Exception as exc:
            documents = []
            entry["errors"].append(f"discovery: {type(exc).__name__}: {exc}"[:300])
        entry["errors"] += list(getattr(downloader, "discovery_errors", []))[:3]
        for document in documents:
            try:
                downloaded = downloader.download_document(document)
            except Exception as exc:
                entry["errors"].append(f"download: {type(exc).__name__}: {exc}"[:300])
                continue
            manifest.setdefault(slug, []).append({
                "path": str(downloaded.path.relative_to(root)),
                "url": document.url,
            })
            entry["documents"] += 1
        archived = archived_portfolios(root, slug, target_month)
        known = {item["path"] for item in manifest.get(slug, [])}
        for path in archived:
            relative = str(path.relative_to(root))
            if relative in known:
                continue
            # Discovery is a live page scrape and some fund houses render theirs
            # only in a browser, so a transient failure must not discard a
            # workbook this month's archive already holds.
            manifest.setdefault(slug, []).append({"path": relative, "url": ""})
            entry["documents"] += 1
            entry["reused_from_archive"] = entry.get("reused_from_archive", 0) + 1
        if not entry["documents"]:
            entry["status"] = "NO_DOCUMENT_FOUND" if not entry["errors"] else "FAILED"
        report[slug] = entry
    return manifest, report


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--target-month", default="2026-08")
    parser.add_argument("--manifest", default=str(settings.archive_root() / "top50-sources.json"))
    parser.add_argument("--ranking-only", action="store_true")
    parser.add_argument("--download", action="store_true",
                        help="Fetch portfolios from the official AMC sites first")
    parser.add_argument("--limit", type=int, default=50)
    args = parser.parse_args(argv)
    target = datetime.strptime(args.target_month, "%Y-%m").date().replace(day=1)
    payload, financial_year, period = fetch_ranking()
    ranking = rank_top_schemes(payload, args.limit)
    result = {"financial_year": financial_year, "ranking_period": period,
              "schemes": [row.__dict__ for row in ranking]}
    if not args.ranking_only:
        if args.download:
            manifest, result["sources"] = download_portfolios(ranking, target)
            Path(args.manifest).write_text(json.dumps(manifest, indent=2), encoding="utf-8")
        else:
            manifest = json.loads(Path(args.manifest).read_text(encoding="utf-8"))
        result["ingestion"] = ingest_archive(target, ranking, manifest)
    print(json.dumps(result, indent=2, default=str))
    return 0


if __name__ == "__main__":
    sys.exit(main())
