"""Runtime configuration from environment (.env supported, no extra deps)."""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

PKG_DIR = Path(__file__).resolve().parent
DATA_DIR = PKG_DIR / "data"
REPO_ROOT = PKG_DIR.parent.parent


def _load_dotenv() -> None:
    for p in (Path.cwd() / ".env", REPO_ROOT / ".env"):
        if p.is_file():
            for line in p.read_text(encoding="utf-8").splitlines():
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                k, v = line.split("=", 1)
                os.environ.setdefault(k.strip(), v.strip())
            return


def _csv(name: str) -> list[str]:
    return [x.strip() for x in os.environ.get(name, "").split(",") if x.strip()]


@dataclass
class Config:
    proxy_port: int = 8080
    ws_port: int = 8787
    ollama_url: str = "http://127.0.0.1:11434"
    ollama_model: str = "qwen2.5:7b"
    nim_enabled: bool = False
    nim_url: str = ""
    nim_model: str = ""
    nim_key: str = ""
    geoip_db: str = ""
    home_country: str = "IN"
    known_emails: list[str] = field(default_factory=list)
    known_phones: list[str] = field(default_factory=list)
    known_adids: list[str] = field(default_factory=list)

    @classmethod
    def from_env(cls) -> "Config":
        _load_dotenv()
        e = os.environ.get
        return cls(
            proxy_port=int(e("AZK_PROXY_PORT", "8080")),
            ws_port=int(e("AZK_WS_PORT", "8787")),
            ollama_url=e("AZK_OLLAMA_URL", "http://127.0.0.1:11434"),
            ollama_model=e("AZK_OLLAMA_MODEL", "qwen2.5:7b"),
            nim_enabled=e("AZK_NIM_ENABLED", "0") == "1",
            nim_url=e("AZK_NIM_URL", "https://integrate.api.nvidia.com/v1/chat/completions"),
            nim_model=e("AZK_NIM_MODEL", "nvidia/llama-3.1-nemotron-70b-instruct"),
            nim_key=e("NVIDIA_API_KEY", ""),
            geoip_db=e("AZK_GEOIP_DB", str(DATA_DIR / "GeoLite2-Country.mmdb")),
            home_country=e("AZK_HOME_COUNTRY", "IN").upper(),
            known_emails=_csv("AZK_KNOWN_EMAILS"),
            known_phones=_csv("AZK_KNOWN_PHONES"),
            known_adids=_csv("AZK_KNOWN_ADIDS"),
        )
