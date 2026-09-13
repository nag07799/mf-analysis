from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from urllib.parse import urlparse, unquote, urljoin
import hashlib
import json
import re
import httpx
from bs4 import BeautifulSoup
from app.config import settings
from app.net import client as http_client

@dataclass(frozen=True)
class Document:
    url: str
    target_month: date
    document_key: str
    document_type: str = 'FACTSHEET'

@dataclass
class DownloadedDocument:
    document: Document
    path: Path
    sha256: str
    filename: str

class SourceUnavailable(RuntimeError):
    pass

class BaseAMCDownloader(ABC):
    slug: str
    allowed_domains: tuple[str, ...]
    def __init__(self, root=None, client=None):
        self.root = Path(root) if root else settings.archive_root()
        self.client = client or http_client()
        self.discovery_errors = []

    def get(self, url):
        for _ in range(6):
            host = urlparse(url).hostname or ''
            if urlparse(url).scheme != 'https' or not any(host == d or host.endswith('.'+d) for d in self.allowed_domains):
                raise SourceUnavailable('Document URL is outside the official AMC domains')
            response = self.client.get(url)
            if response.is_redirect:
                url = urljoin(url, response.headers['location'])
                continue
            response.raise_for_status()
            return response
        raise SourceUnavailable('Too many redirects')

    def page(self, url):
        try:
            return self.get(url).text
        except httpx.HTTPError:
            if not settings.browser_fallback:
                raise
            from playwright.sync_api import sync_playwright
            with sync_playwright() as p:
                browser = p.chromium.launch(headless=True, args=['--no-sandbox'])
                try:
                    page = browser.new_page()
                    response = page.goto(url, wait_until='networkidle', timeout=60000)
                    if not response or response.status >= 400:
                        raise SourceUnavailable(f'Official source returned {response.status if response else "no response"}')
                    return page.content()
                finally:
                    browser.close()

    @abstractmethod
    def discover_documents(self, target_month): ...

    def discover_portfolios(self, target_month):
        return []

    def download_document(self, document):
        response = self.get(document.url)
        content = response.content
        if not (content.startswith(b'%PDF') or content.startswith(b'PK\x03\x04') or content.startswith(b'\xd0\xcf\x11\xe0')):
            raise SourceUnavailable('Official source did not return a PDF or portfolio workbook')
        digest = hashlib.sha256(content).hexdigest()
        filename = Path(unquote(urlparse(document.url).path)).name or 'factsheet.pdf'
        filename = re.sub(r'[^\w. -]', '_', filename)
        directory = self.root / 'raw' / document.target_month.strftime('%Y-%m') / self.slug.upper()
        directory.mkdir(parents=True, exist_ok=True)
        path = directory / f'{digest[:16]}_{filename}'
        if not path.exists():
            # Exclusive creation prevents concurrent jobs overwriting the archive.
            try:
                with path.open('xb') as stream:
                    stream.write(content)
            except FileExistsError:
                pass
        if hashlib.sha256(path.read_bytes()).hexdigest() != digest:
            raise SourceUnavailable('Archived file hash mismatch')
        return DownloadedDocument(document, path, digest, filename)

    @staticmethod
    def links(html, base):
        soup = BeautifulSoup(html, 'html.parser')
        urls = [urljoin(base, a['href']) for a in soup.select('a[href]')]
        for script in soup.find_all('script'):
            text = script.string or ''
            urls += re.findall(r'https?[^"<>\s\\]+', text.replace('\\/', '/'))
        return list(dict.fromkeys(urls))

    @staticmethod
    def matches_month(text, month):
        text = unquote(text).lower()
        return bool(re.search(rf'{month.strftime("%B").lower()}[\s_/-]*{month.year}|{month.year}[-/]{month.month:02d}\b|{month.strftime("%b").lower()}[\s_/-]*{month.year}', text))
