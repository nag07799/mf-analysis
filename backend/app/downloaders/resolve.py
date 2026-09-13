"""Pick the right downloader for a fund house.

Two kinds coexist.  HDFC and ICICI have hand-written downloaders because their
factsheet PDFs need bespoke parsers anyway.  Everyone else is served by the
config-driven portfolio downloader, which is enough for holdings-based work.
"""
from app.downloaders.generic import AMC_SOURCES, GenericPortfolioDownloader
from app.downloaders.hdfc import HDFCDownloader
from app.downloaders.icici import ICICIDownloader

BESPOKE = {"hdfc": HDFCDownloader, "icici": ICICIDownloader}


def supported_slugs() -> set[str]:
    return set(BESPOKE) | set(AMC_SOURCES)


def portfolio_downloader(slug: str, root=None, client=None):
    """Return a downloader able to discover monthly portfolios, or None."""
    # A configured portfolio page wins: it targets the disclosure directly,
    # while the bespoke downloaders exist mainly for factsheet PDFs.
    source = AMC_SOURCES.get(slug)
    if source is not None:
        return GenericPortfolioDownloader(source, root=root, client=client)
    if slug in BESPOKE:
        return BESPOKE[slug](root=root, client=client)
    return None
