"""Configuration management using Pydantic settings."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, Field
from pydantic_settings import BaseSettings


def _resolve_env_vars(obj: Any) -> Any:
    """Recursively resolve ${ENV_VAR} patterns in config values."""
    if isinstance(obj, str) and obj.startswith("${") and obj.endswith("}"):
        env_var = obj[2:-1]
        return os.getenv(env_var, "")
    elif isinstance(obj, dict):
        return {k: _resolve_env_vars(v) for k, v in obj.items()}
    elif isinstance(obj, list):
        return [_resolve_env_vars(item) for item in obj]
    return obj


class BotConfig(BaseModel):
    name: str = "spike-arb"
    mode: str = "paper"
    log_level: str = "INFO"
    max_concurrent_trades: int = 5
    check_interval_ms: int = 100


class ESPNConfig(BaseModel):
    enabled: bool = True
    base_url: str = "https://site.api.espn.com/apis/site/v2/sports"
    poll_interval_ms: int = 500
    sports: list[str] = Field(default_factory=lambda: ["football/nfl", "basketball/nba", "baseball/mlb"])
    websocket_url: str | None = None


class WeatherProviderConfig(BaseModel):
    base_url: str
    api_key: str = ""
    poll_interval_ms: int = 30000


class TrackedLocation(BaseModel):
    name: str
    lat: float
    lon: float


class WeatherConfig(BaseModel):
    enabled: bool = True
    providers: dict[str, WeatherProviderConfig] = Field(default_factory=dict)
    tracked_locations: list[TrackedLocation] = Field(default_factory=list)


class NewsProviderConfig(BaseModel):
    base_url: str
    api_key: str = ""
    poll_interval_ms: int = 5000


class NewsConfig(BaseModel):
    enabled: bool = True
    providers: dict[str, NewsProviderConfig] = Field(default_factory=dict)
    tracked_keywords: list[str] = Field(default_factory=list)


class CryptoProviderConfig(BaseModel):
    ws_url: str = ""
    rest_url: str = ""


class CryptoConfig(BaseModel):
    enabled: bool = True
    providers: dict[str, CryptoProviderConfig] = Field(default_factory=dict)
    tracked_pairs: list[str] = Field(default_factory=list)


class DataSourcesConfig(BaseModel):
    espn: ESPNConfig = Field(default_factory=ESPNConfig)
    weather: WeatherConfig = Field(default_factory=WeatherConfig)
    news: NewsConfig = Field(default_factory=NewsConfig)
    crypto: CryptoConfig = Field(default_factory=CryptoConfig)


class PolymarketConfig(BaseModel):
    enabled: bool = True
    clob_url: str = "https://clob.polymarket.com"
    gamma_url: str = "https://gamma-api.polymarket.com"
    ws_url: str = "wss://ws-subscriptions-clob.polymarket.com/ws/market"
    chain_id: int = 137
    private_key: str = ""
    api_key: str = ""
    api_secret: str = ""
    api_passphrase: str = ""
    funder: str = ""
    max_position_size_usd: float = 100
    default_order_type: str = "limit"


class KalshiConfig(BaseModel):
    enabled: bool = True
    base_url: str = "https://trading-api.kalshi.com/trade-api/v2"
    ws_url: str = "wss://trading-api.kalshi.com/trade-api/ws/v2"
    email: str = ""
    password: str = ""
    api_key: str = ""
    max_position_size_usd: float = 100
    default_order_type: str = "limit"


class MarketsConfig(BaseModel):
    polymarket: PolymarketConfig = Field(default_factory=PolymarketConfig)
    kalshi: KalshiConfig = Field(default_factory=KalshiConfig)


class StrategyConfig(BaseModel):
    min_edge_threshold: float = 0.03
    max_signal_age_ms: int = 5000
    min_confidence: float = 0.65
    high_confidence: float = 0.85
    kelly_fraction: float = 0.25
    max_bet_size_usd: float = 50
    min_bet_size_usd: float = 5
    max_daily_loss_usd: float = 200
    max_open_positions: int = 10
    stop_loss_pct: float = 0.15
    track_data_source_latency: bool = True
    latency_window_size: int = 100


class MonitoringConfig(BaseModel):
    enabled: bool = True
    dashboard_port: int = 8080
    metrics_interval_s: int = 10
    alert_on_loss_usd: float = 50
    log_all_signals: bool = True
    trade_history_db: str = "data/trades.db"


class DatabaseConfig(BaseModel):
    path: str = "data/arb_bot.db"
    backup_interval_hours: int = 6


class AppConfig(BaseModel):
    bot: BotConfig = Field(default_factory=BotConfig)
    data_sources: DataSourcesConfig = Field(default_factory=DataSourcesConfig)
    markets: MarketsConfig = Field(default_factory=MarketsConfig)
    strategy: StrategyConfig = Field(default_factory=StrategyConfig)
    monitoring: MonitoringConfig = Field(default_factory=MonitoringConfig)
    database: DatabaseConfig = Field(default_factory=DatabaseConfig)


def load_config(config_path: str | Path | None = None) -> AppConfig:
    """Load configuration from YAML file with environment variable resolution."""
    if config_path is None:
        config_path = Path(__file__).parent.parent.parent / "config" / "settings.yaml"

    config_path = Path(config_path)

    # Load base config
    raw: dict[str, Any] = {}
    if config_path.exists():
        with open(config_path) as f:
            raw = yaml.safe_load(f) or {}

    # Load local overrides if they exist
    local_path = config_path.parent / "settings.local.yaml"
    if local_path.exists():
        with open(local_path) as f:
            local_raw = yaml.safe_load(f) or {}
            raw = _deep_merge(raw, local_raw)

    # Resolve environment variables
    raw = _resolve_env_vars(raw)

    return AppConfig(**raw)


def _deep_merge(base: dict, override: dict) -> dict:
    """Deep merge two dicts, with override taking precedence."""
    result = base.copy()
    for key, value in override.items():
        if key in result and isinstance(result[key], dict) and isinstance(value, dict):
            result[key] = _deep_merge(result[key], value)
        else:
            result[key] = value
    return result
