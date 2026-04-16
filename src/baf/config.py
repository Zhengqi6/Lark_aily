"""Configuration + credential storage.

Layout on disk:
    ~/.baf/config.json        — static config (LLM key, feishu app_id/secret, ...)
    ~/.baf/credentials.json   — OAuth user_access_token + refresh_token
    ~/.baf/mock/*.json        — Mock backend JSON tables
"""
from __future__ import annotations

import json
import os
from dataclasses import dataclass, field, asdict
from pathlib import Path

from dotenv import load_dotenv

BAF_HOME = Path(os.environ.get("BAF_HOME", Path.home() / ".baf"))
CONFIG_FILE = BAF_HOME / "config.json"
CREDENTIALS_FILE = BAF_HOME / "credentials.json"
MOCK_DIR = BAF_HOME / "mock"


@dataclass
class Config:
    # LLM
    llm_api_key: str = ""
    llm_base_url: str = "https://api.zhizengzeng.com/v1/"
    llm_model: str = "gpt-4o-mini"
    # Feishu
    feishu_app_id: str = ""
    feishu_app_secret: str = ""
    feishu_bitable_app_token: str = ""
    feishu_oauth_port: int = 18080

    # Runtime flags (not persisted)
    use_mock: bool = field(default=False, repr=False)

    @classmethod
    def load(cls) -> "Config":
        """Load from: env -> ~/.baf/config.json, env takes precedence."""
        # 1) load .env in CWD if present
        load_dotenv(override=False)
        # 2) load persisted config
        data: dict = {}
        if CONFIG_FILE.exists():
            try:
                data = json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
            except Exception:
                data = {}
        cfg = cls(**{k: v for k, v in data.items() if k in cls.__annotations__})

        # 3) env override
        cfg.llm_api_key = os.environ.get("LLM_API_KEY", cfg.llm_api_key)
        cfg.llm_base_url = os.environ.get("LLM_BASE_URL", cfg.llm_base_url)
        cfg.llm_model = os.environ.get("LLM_MODEL", cfg.llm_model)
        cfg.feishu_app_id = os.environ.get("FEISHU_APP_ID", cfg.feishu_app_id)
        cfg.feishu_app_secret = os.environ.get("FEISHU_APP_SECRET", cfg.feishu_app_secret)
        cfg.feishu_bitable_app_token = os.environ.get(
            "FEISHU_BITABLE_APP_TOKEN", cfg.feishu_bitable_app_token
        )
        port = os.environ.get("FEISHU_OAUTH_PORT")
        if port:
            cfg.feishu_oauth_port = int(port)
        return cfg

    def save(self) -> None:
        BAF_HOME.mkdir(parents=True, exist_ok=True)
        payload = {k: v for k, v in asdict(self).items() if k != "use_mock"}
        CONFIG_FILE.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
        try:
            os.chmod(CONFIG_FILE, 0o600)
        except OSError:
            pass


@dataclass
class Credentials:
    user_access_token: str = ""
    refresh_token: str = ""
    expires_at: float = 0.0  # unix timestamp seconds
    open_id: str = ""
    name: str = ""

    @classmethod
    def load(cls) -> "Credentials":
        if not CREDENTIALS_FILE.exists():
            return cls()
        try:
            data = json.loads(CREDENTIALS_FILE.read_text(encoding="utf-8"))
            return cls(**{k: v for k, v in data.items() if k in cls.__annotations__})
        except Exception:
            return cls()

    def save(self) -> None:
        BAF_HOME.mkdir(parents=True, exist_ok=True)
        CREDENTIALS_FILE.write_text(
            json.dumps(asdict(self), indent=2, ensure_ascii=False), encoding="utf-8"
        )
        try:
            os.chmod(CREDENTIALS_FILE, 0o600)
        except OSError:
            pass
