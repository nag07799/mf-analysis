from app.downloaders.base import BaseAMCDownloader, Document

class ICICIDownloader(BaseAMCDownloader):
    slug = 'icici'
    allowed_domains = ('icicipruamc.com',)
    factsheet_pages = ('https://digitalfactsheet.icicipruamc.com/fact/',
                       'https://digitalfactsheet.icicipruamc.com/passive/')
    portfolio_page = 'https://www.icicipruamc.com/media-center/downloads'

    def discover_documents(self, target_month):
        found = []
        try:
            found=self.api_documents(target_month, 'complete-factsheet', 'active')
        except Exception as exc:
            self.discovery_errors.append('factsheet API: '+type(exc).__name__)
        for page, key in zip(self.factsheet_pages, ('active', 'passive')):
            if any(d.document_key==key for d in found):
                continue
            try:
                html = self.page(page)
                found += [Document(u, target_month, key) for u in self.links(html, page)
                          if '.pdf' in u.lower() and self.matches_month(u, target_month)]
            except Exception as exc:
                self.discovery_errors.append(f'{key}: {type(exc).__name__}')
        # The official main-site passive file is updated independently of digital pages.
        from app.parsers.base import detect_month
        import pymupdf
        url = 'https://www.icicipruamc.com/blob/knowledgecentre/factsheet-passive/Passive.pdf'
        try:
            data = self.get(url).content
            with pymupdf.open(stream=data, filetype='pdf') as pdf:
                if detect_month(pdf) == target_month and not any(d.document_key == 'passive' for d in found):
                    found.append(Document(url, target_month, 'passive'))
        except Exception as exc:
            self.discovery_errors.append(f'passive main site: {type(exc).__name__}')
        return list(dict.fromkeys(found))

    def api_documents(self,target_month,category_name,key,document_type='FACTSHEET'):
        from urllib.parse import quote
        headers={'env':'api','source_url':'DOWNLOADS','Referer':'https://www.icicipruamc.com/'}
        response=self.client.get('https://apimf.icicipruamc.com/nms/v1/downloads/categories?userType=Investor',headers=headers)
        response.raise_for_status()
        categories=response.json()['success']['data']
        category=next(s for c in categories for s in c.get('subCategory',[]) if s['internalName']==category_name)
        documents=[]
        for page in range(1,101):
            response=self.client.post('https://apimf.icicipruamc.com/nms/v1/downloads/files',headers=headers,json={
                'categoryId':category['id'],'schemeCategory':'','userType':'Investor','fileType':'All',
                'page':str(page),'size':'100','filter':[],'categoryName':'OTHERS'})
            response.raise_for_status()
            data=response.json()['success']['data']
            for item in data['files']:
                if self.matches_month(item['title']['text'],target_month):
                    url=item['url']
                    if url.startswith('/'):
                        url='https://www.icicipruamc.com/blob'+url
                    documents.append(Document(quote(url,safe=':/?=&%'),target_month,key,document_type))
            if documents or not data.get('isNext'):
                break
        return documents

    def discover_portfolios(self, target_month):
        return self.api_documents(target_month,'monthly-portfolio-disclosures','portfolio','PORTFOLIO_DISCLOSURE')
