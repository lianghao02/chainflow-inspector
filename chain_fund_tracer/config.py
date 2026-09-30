from __future__ import annotations
import json
from dataclasses import asdict, dataclass, field
from pathlib import Path

@dataclass
class Settings:
    rpc_url: str = "https://polygon.drpc.org"
    blockscout_url: str = "https://polygon.blockscout.com/api/v2"
    etherscan_api_key: str = ""
    relay_api_key: str = ""
    orbscan_api_url: str = "https://data-api.polymarket.com/trades"
    max_hops: int = 4
    page_size: int = 20
    max_history_pages: int = 15
    core_inbound_tokens: list[str] = field(default_factory=lambda: [
        "0x3c499c542cef5e3811e1192ce70d8cc03d5c3359",  # Native USDC
        "0x2791bca1f2de4661ed88a30c99a7a9449aa84174",  # USDC.e
        "0xc011a7e12a19f7b1f670d46f03b03f3342e82dfb",  # pUSD
        "0xc2132d05d31c914a87c6611c10748aeb04b58e8f",  # USDT
    ])
    custom_labels: dict[str, dict[str, str]] = field(default_factory=dict)

    @classmethod
    def load(cls) -> Settings:
        return load_settings()

    def save(self) -> None:
        save_settings(self)

def config_path() -> Path: return Path(__file__).resolve().parent.parent / "settings.json"
def load_settings() -> Settings:
    try:
        data = json.loads(config_path().read_text(encoding="utf-8")); settings = Settings(**{key: data[key] for key in Settings.__dataclass_fields__ if key in data})
        if settings.rpc_url.rstrip("/") == "https://polygon-rpc.com": settings.rpc_url = Settings().rpc_url
        return settings
    except (json.JSONDecodeError, OSError, TypeError): return Settings()
def save_settings(settings: Settings) -> None: config_path().write_text(json.dumps(asdict(settings), ensure_ascii=False, indent=2), encoding="utf-8")
