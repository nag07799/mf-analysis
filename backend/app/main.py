from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import text
from app.config import settings
from app.db.session import engine
from app.api import funds, compare
from app.parsers.base import PARSER_VERSION

app = FastAPI(title='Indian Equity Mutual Fund Overlap', version=PARSER_VERSION)
app.add_middleware(CORSMiddleware, allow_origins=settings.cors_origins,
                   allow_methods=['GET'], allow_headers=['*'])
app.include_router(funds.router)
app.include_router(compare.router)


@app.get('/health')
def health():
    try:
        with engine.connect() as connection:
            connection.execute(text('SELECT 1'))
        database = 'UP'
    except Exception as exc:
        database = f'DOWN ({type(exc).__name__})'
    return {'status': 'ok', 'database': database, 'parser_version': PARSER_VERSION,
            'gemini_configured': bool(settings.gemini_api_key.get_secret_value())}
