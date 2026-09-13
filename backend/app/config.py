from pathlib import Path
from pydantic import SecretStr
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
    cors_origins: list[str] = ['http://localhost:3000', 'http://127.0.0.1:3000']

    def archive_root(self) -> Path:
        root = self.data_root if self.data_root.is_absolute() else PROJECT_ROOT / self.data_root
        for directory in ('raw', 'extracted', 'rejected', 'reports', 'logs'):
            (root / directory).mkdir(parents=True, exist_ok=True)
        return root

settings = Settings()
