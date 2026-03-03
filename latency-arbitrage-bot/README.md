# Spike ARB Bot — Latency Arbitrage for Prediction Markets

A fully async Python bot that exploits the speed differential between fast data sources
(ESPN, NWS Weather, news APIs, crypto WebSocket feeds) and slower prediction market platforms
(Polymarket, Kalshi) to identify and execute trades before markets adjust.

## Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                     SPIKE ARB BOT                                │
│                                                                  │
│  ┌──────────────────────┐    ┌─────────────────────────────┐    │
│  │   DATA SOURCES        │    │   PREDICTION MARKETS         │    │
│  │                       │    │                              │    │
│  │  ESPN (Sports)        │    │  Polymarket (CLOB/Polygon)   │    │
│  │  NWS (Weather)        │    │  Kalshi (REST/WS/FIX)       │    │
│  │  OpenWeather          │    │                              │    │
│  │  NewsAPI / GDELT      │    └──────────┬──────────────────┘    │
│  │  Binance WS (Crypto)  │               │                       │
│  │  Coinbase WS          │               │                       │
│  └──────────┬────────────┘               │                       │
│             │                            │                       │
│             ▼                            ▼                       │
│  ┌──────────────────────────────────────────────────────────┐   │
│  │                    EVENT BUS (async pub/sub)               │   │
│  └──────────────────────────┬───────────────────────────────┘   │
│                              │                                    │
│             ┌────────────────┼────────────────┐                  │
│             ▼                ▼                ▼                   │
│  ┌─────────────────┐ ┌─────────────┐ ┌──────────────────┐      │
│  │ ARBITRAGE ENGINE │ │ EXECUTION   │ │ MONITORING       │      │
│  │                  │ │ ENGINE      │ │                  │      │
│  │ - Signal mapping │ │ - Order mgmt│ │ - Live dashboard │      │
│  │ - Fair value calc│ │ - Paper/Live│ │ - Trade history  │      │
│  │ - Edge detection │ │ - Risk check│ │ - Latency stats  │      │
│  │ - Kelly sizing   │ │ - Fill track│ │ - SQLite logging │      │
│  └─────────────────┘ └─────────────┘ └──────────────────┘      │
│                                                                  │
│  ┌──────────────────────────────────────────────────────────┐   │
│  │              LATENCY TRACKER & MARKET MAPPER              │   │
│  └──────────────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────────┘
```

## Quick Start

```bash
# Clone and enter
cd latency-arbitrage-bot

# Install (creates venv, installs deps, sets up config)
bash scripts/install.sh

# Activate virtual environment
source .venv/bin/activate

# Edit your API keys
vim config/.env

# Run in paper trading mode
arb-bot run --mode paper

# Or run directly
python -m src.cli run --mode paper
```

## Project Structure

```
latency-arbitrage-bot/
├── config/
│   ├── settings.yaml        # Master configuration
│   ├── settings.local.yaml  # Local overrides (gitignored)
│   ├── .env.example         # API key template
│   └── .env                 # Your API keys (gitignored)
├── src/
│   ├── core/                # Core framework
│   │   ├── models.py        # Data models (signals, orders, positions)
│   │   ├── config.py        # Configuration management
│   │   ├── event_bus.py     # Async pub/sub event bus
│   │   ├── base.py          # Base classes for sources & connectors
│   │   └── latency_tracker.py  # Latency measurement & analysis
│   ├── data_sources/        # Fast data feeds
│   │   ├── sports/
│   │   │   └── espn.py      # ESPN live scores (500ms polling)
│   │   ├── weather/
│   │   │   └── weather_source.py  # NWS + OpenWeather
│   │   ├── news/
│   │   │   └── news_source.py     # NewsAPI + GDELT
│   │   └── crypto/
│   │       └── crypto_source.py   # Binance + Coinbase WebSocket
│   ├── markets/             # Prediction market connectors
│   │   ├── polymarket/
│   │   │   └── connector.py # Full CLOB integration
│   │   ├── kalshi/
│   │   │   └── connector.py # Full REST/WS integration
│   │   └── common/
│   │       └── market_mapper.py  # Signal→Market mapping
│   ├── strategies/          # Trading logic
│   │   ├── arbitrage_engine.py   # Main signal processing
│   │   ├── fair_value.py    # Probability estimation
│   │   └── position_sizer.py    # Kelly Criterion sizing
│   ├── execution/
│   │   └── executor.py      # Order management & execution
│   ├── monitoring/
│   │   └── monitor.py       # Dashboard & trade logging
│   ├── bot.py               # Main orchestrator
│   └── cli.py               # CLI entry point
├── tests/                   # Test suite
├── scripts/
│   ├── install.sh           # One-command setup
│   ├── run_paper.sh         # Quick paper trading start
│   └── run_live.sh          # Live trading (with safety prompt)
├── docs/
│   └── RESEARCH_RESOURCE.md # Deep research findings
├── data/                    # Trade history & logs (gitignored)
└── pyproject.toml           # Dependencies & build config
```

## Data Source → Market Flow

```
1. ESPN detects Lakers score (105-98, 4th quarter)
   ↓
2. Signal published: SPORTS_SCORE, confidence=0.99
   ↓
3. Market Mapper finds: "Will Lakers win tonight?" on Polymarket
   ↓
4. Fair Value Calculator: logistic model → P(Lakers win) = 0.82
   ↓
5. Current market price: YES = $0.65
   ↓
6. Edge = 0.82 - 0.65 = 0.17 (17% edge!)
   ↓
7. Kelly Criterion: bet $25 (quarter-Kelly on $1000 bankroll)
   ↓
8. Execution: BUY YES @ $0.65 on Polymarket CLOB
   ↓
9. Fill confirmed: 350ms total signal-to-fill latency
```

## Configuration

Edit `config/settings.yaml` for strategy parameters:

```yaml
strategy:
  min_edge_threshold: 0.03   # 3% minimum edge to trade
  kelly_fraction: 0.25       # Quarter Kelly (conservative)
  max_bet_size_usd: 50       # Max per trade
  max_daily_loss_usd: 200    # Hard daily stop
  max_open_positions: 10     # Concurrent position limit
```

## CLI Commands

```bash
# Start the bot
arb-bot run --mode paper          # Paper trading
arb-bot run --mode live           # Live trading
arb-bot run --mode paper -l DEBUG # Debug logging

# Check configuration
arb-bot status

# Search markets
arb-bot search "bitcoin"
arb-bot search "lakers" --platform polymarket

# First-time setup
arb-bot setup
```

## API Keys Required

| Service | Required | Free Tier | Purpose |
|---------|----------|-----------|---------|
| Polymarket | For trading | N/A (wallet) | Place trades |
| Kalshi | For trading | Yes | Place trades |
| OpenWeather | Optional | Yes (1K/day) | Weather data |
| NewsAPI | Optional | Yes (100/day) | News signals |
| ESPN | None | Free (unofficial) | Sports data |
| NWS | None | Free | Weather data |
| Binance | None | Free (public WS) | Crypto prices |

## Risk Management

- **Paper mode by default** — always test first
- **Quarter-Kelly sizing** — conservative position sizing
- **Daily loss limits** — automatic shutdown at threshold
- **Signal staleness** — rejects signals >5 seconds old
- **Position limits** — max 10 concurrent positions
- **Kill switch** — Ctrl+C for graceful shutdown

## For Open Claw / Spike Claw Integration

This bot is designed to be agent-friendly:

1. **Clear module boundaries** — each file has a single responsibility
2. **Async throughout** — non-blocking, plays well with other async tasks
3. **Event-driven** — components communicate via pub/sub, easy to extend
4. **Configuration-driven** — change behavior via YAML, no code changes
5. **Paper mode** — safe to run without real money
6. **Structured logging** — every action is logged for agent analysis

To integrate with your Spike Claw setup:
```python
from src.bot import SpikeArbBot

bot = SpikeArbBot(config_path="config/settings.yaml")
await bot.start()  # Non-blocking, runs in background
```

## Research

See `docs/RESEARCH_RESOURCE.md` for the full research compilation including:
- Latency benchmarks for all data sources
- API endpoint reference for Polymarket & Kalshi
- 30+ open source repos analyzed
- Risk management frameworks
- Legal/regulatory considerations
- Performance optimization techniques

## License

MIT
