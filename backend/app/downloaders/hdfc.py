from app.downloaders.base import BaseAMCDownloader, Document

class HDFCDownloader(BaseAMCDownloader):
    slug = 'hdfc'
    allowed_domains = ('hdfcfund.com',)
    factsheet_page = 'https://www.hdfcfund.com/investor-services/factsheets'
    portfolio_page = 'https://www.hdfcfund.com/statutory-disclosure/portfolio/monthly-portfolio'

    def discover_documents(self, target_month):
        html = self.page(self.factsheet_page)
        urls = self.links(html, self.factsheet_page)
        found = []
        for url in urls:
            if '.pdf' in url.lower() and 'factsheet' in url.lower() and self.matches_month(url, target_month):
                key = 'passive' if 'index' in url.lower() else 'active'
                found.append(Document(url, target_month, key))
        return found

    def discover_portfolios(self, target_month):
        html = self.page(self.portfolio_page)
        return [Document(u, target_month, 'portfolio', 'PORTFOLIO_DISCLOSURE')
                for u in self.links(html, self.portfolio_page)
                if any(e in u.lower() for e in ('.xlsx', '.xls', '.zip')) and self.matches_month(u, target_month)]
