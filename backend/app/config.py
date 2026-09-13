from pathlib import Path
import json
from pydantic import SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

PROJECT_ROOT = Path(__file__).resolve().parents[2]

class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=PROJECT_ROOT / '.env', extra='ignore')
    database_url: str = 'postgresql+psycopg://mf:mf_local_dev@localhost:5432/mutual_funds'
    gemini_api_key: SecretStr = SecretStr('')
    gemini_model: str = 'gemini-2.5-flash'
    data_root: Path = PROJECT_ROOT / 'data'
    enable_equity_etfs: bool = True
    browser_fallback: bool = True
    cors_origins: list[str] = ['https://mf-analysis-equity.vercel.app', 'http://localhost:3000', 'http://127.0.0.1:3000']

    @field_validator('cors_origins', mode='before')
    @classmethod
    def parse_cors_origins(cls, v):
        if isinstance(v, str):
            try:
                return json.loads(v)
            except json.JSONDecodeError:
                return [v]
        return v

    def archive_root(self) -> Path:
        root = self.data_root if self.data_root.is_absolute() else PROJECT_ROOT / self.data_root
        for directory in ('raw', 'extracted', 'rejected', 'reports', 'logs'):
            (root / directory).mkdir(parents=True, exist_ok=True)
        return root

settings = Settings()
