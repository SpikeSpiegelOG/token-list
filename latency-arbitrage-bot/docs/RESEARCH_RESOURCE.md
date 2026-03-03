# Latency Arbitrage in Prediction Markets — Research Resource Document

> Compiled from deep research across YouTube, X/Twitter, Reddit, Medium, GitHub, and official API docs.
> Last updated: March 2026

---

## Table of Contents

1. [Executive Summary](#1-executive-summary)
2. [Market Landscape & Scale](#2-market-landscape--scale)
3. [Core Strategies](#3-core-strategies)
4. [Data Source Latency Analysis](#4-data-source-latency-analysis)
5. [Platform API Technical Reference](#5-platform-api-technical-reference)
6. [Open Source Repos & Tools](#6-open-source-repos--tools)
7. [Infrastructure & Optimization](#7-infrastructure--optimization)
8. [Risk Management](#8-risk-management)
9. [Legal & Regulatory](#9-legal--regulatory)
10. [Key Metrics & Benchmarks](#10-key-metrics--benchmarks)

---

## 1. Executive Summary

Latency arbitrage in prediction markets exploits the time delay between when new information
appears in fast data sources (ESPN, NWS, news wires) and when prediction market prices
(Polymarket, Kalshi) update to reflect that information. This window — typically 500ms to
several seconds — is the trading opportunity.

**Key findings:**
- $40M+ in documented arbitrage profits on Polymarket alone (April 2024 - April 2025)
- One AI bot: 8,894 trades, ~$150K profit, ~$16.80/trade average
- Top single arbitrageur: $2.01M across 4,049 transactions
- Opportunity windows shrinking: 12.3s (2024) → 2.7s (2026)
- Only 7.6% of Polymarket wallets are profitable; 0.51% exceed $1,000 profit
- Weather markets remain most exploitable (70-85% win rates from NWS model data)

---

## 2. Market Landscape & Scale

### Combined Volume
| Platform | Monthly Volume (Nov 2025) |
|----------|--------------------------|
| Kalshi | $5.8 billion |
| Polymarket | $3.74 billion |
| **Combined** | **~$10 billion** |

### Platform Comparison
| Feature | Polymarket | Kalshi |
|---------|-----------|--------|
| Regulation | CFTC-approved (Nov 2025) | CFTC-regulated from inception |
| Settlement | On-chain (Polygon) | Centralized |
| Fees | 2% winner fee | 0% currently |
| API | REST + WebSocket + CLOB | REST + WebSocket + FIX |
| Rate Limits | ~60 orders/min | Tiered (Basic→Prime) |
| Python SDK | py-clob-client | kalshi-python |
| US Access | Via registered FCMs (KYC) | Full US access |
| Bot-Friendly | Yes (CLOB API) | Yes (REST + WS + FIX) |
| Order Types | GTC, FOK, FAK/IOC, GTD | GTC, FOK, IOC |

### Market Categories
- **Sports**: NFL, NBA, MLB, NHL, soccer outcomes
- **Weather**: Temperature, precipitation, hurricane paths (Kalshi specialty)
- **Politics**: Elections, legislation, court rulings
- **Crypto**: BTC/ETH price milestones, short-term price contracts
- **Economics**: Fed rate decisions, inflation data, jobs reports
- **Entertainment**: Awards, TV ratings

---

## 3. Core Strategies

### Strategy 1: Information Speed Arbitrage (PRIMARY)
**The core play**: Read fast data sources, trade before markets react.

```
ESPN score change (194ms) → Detect signal → Calculate fair value
→ Compare to market price → Place order on Polymarket/Kalshi
Total latency: ~250-450ms

vs. average human trader: 5-30 seconds
```

**Best for**: Sports scores, weather model runs, breaking news, crypto price moves

### Strategy 2: Cross-Platform Arbitrage
Buy YES on one platform + NO on another when combined cost < $1.00.

```
If Polymarket YES = $0.55 and Kalshi NO = $0.42
Total cost = $0.97 → Guaranteed $0.03 profit (3.09% gross)
```

**Risk**: Resolution divergence — platforms may settle differently on the "same" event.

### Strategy 3: Sub-$1 Rebalancing (Intra-Market)
When YES + NO < $1.00 on the same market, buy both for risk-free profit.
- Minimum spread needed: 2.5-3% (to cover Polymarket's 2% winner fee)
- Windows last 2.7 seconds on average (as of 2026)

### Strategy 4: AI-Driven Probability Trading
Use LLMs + Bayesian inference to estimate probabilities more accurately than the crowd.
- Multi-model consensus: GPT + Claude + DeepSeek + Grok
- Semantic analysis of market correlations
- News sentiment → probability estimation

### Strategy 5: Market Making
Place orders on both sides of the book, profit from bid-ask spread.
- Professional MMs report $150-300/day per market at $100K+ volume
- Requires inventory management and dynamic quote adjustment
- Polymarket offers liquidity rewards (quadratic spread function)

---

## 4. Data Source Latency Analysis

### Sports Data
| Source | Latency | Auth | WebSocket | Notes |
|--------|---------|------|-----------|-------|
| ESPN API | ~194ms | None | No (poll) | Free, unofficial, 17 sports |
| Sportradar | <50ms | API key | Yes | Enterprise, 80+ sports, official data |
| OpticOdds | ~10ms | API key | Yes | 1M+ odds/sec, Kalshi integration |
| TxODDS | 8-10ms | Enterprise | Yes | Ultra-low-latency streaming |

**ESPN Key Endpoints:**
- Scoreboard: `https://site.api.espn.com/apis/site/v2/sports/{sport}/{league}/scoreboard`
- Summary: `https://site.api.espn.com/apis/site/v2/sports/{sport}/{league}/summary?event={id}`

### Weather Data
| Source | Latency | Auth | Update Freq | Notes |
|--------|---------|------|-------------|-------|
| NWS API | ~2-5s | User-Agent only | 30-60s | Free, settlement source for Kalshi |
| Open-Meteo | <1s | None | On model run | Free, GFS ensemble (31 members) |
| Wethr.net | <1s | API key | Model-dependent | Built for prediction market traders |
| OpenWeather | ~1-3s | API key | 10min | Alerts, forecasts |
| Meteomatics | <1min | Enterprise | On model run | 33% faster than alternatives |

**Critical**: Kalshi weather markets settle on NWS Daily Climate Report (CLI), tied to specific stations (KNYC = Central Park, KORD = O'Hare).

### News Data
| Source | Latency | Auth | Notes |
|--------|---------|------|-------|
| AlphaFlash | Seconds ahead | Enterprise | Machine-readable macro data |
| Intrinio/NewsEdge | <1s | API key | Dow Jones, Reuters feeds |
| NewsAPI.org | ~2-5s | API key | 80,000+ sources, good for breadth |
| GDELT | ~15min | None | Free, global event monitoring |
| GNews | ~1-3s | API key | 80,000+ sources |

### Crypto Data
| Source | Latency | Auth | Notes |
|--------|---------|------|-------|
| Binance WS | <50ms | None (public) | Fastest for BTC/ETH |
| Coinbase WS | <100ms | None (public) | Reliable, ticker channel |
| Databento | 6.1μs | API key | Institutional grade |

---

## 5. Platform API Technical Reference

### Polymarket

**Architecture**: Hybrid-decentralized CLOB. Off-chain order matching, on-chain settlement on Polygon.

**URLs:**
- CLOB REST: `https://clob.polymarket.com`
- Gamma (discovery): `https://gamma-api.polymarket.com`
- WebSocket: `wss://ws-subscriptions-clob.polymarket.com/ws/market`
- Live data WS: `wss://ws-live-data.polymarket.com`

**Authentication (3 tiers):**
- Level 0: No auth. Market data, orderbooks, prices.
- Level 1: Private key (EIP-712 signing). Derive API keys.
- Level 2: HMAC-SHA256 with apiKey/secret/passphrase. 30s expiry.

**Rate Limits:**
- Public: ~100 req/min
- Trading: 60 orders/min per API key
- `/books`: 300 req/10s
- Batch orders: up to 15 per call

**Python SDK:**
```python
from py_clob_client.client import ClobClient

# Read-only
client = ClobClient("https://clob.polymarket.com")

# Trading
client = ClobClient(
    "https://clob.polymarket.com",
    key="<private_key>",
    chain_id=137,
    signature_type=2,
    funder="<funder_address>"
)
client.set_api_creds(client.create_or_derive_api_creds())
```

**Settlement**: UMA Optimistic Oracle. $750 USDC bond, 48-hour dispute window. ~99% undisputed.

### Kalshi

**URLs:**
- REST: `https://trading-api.kalshi.com/trade-api/v2`
- WebSocket: `wss://trading-api.kalshi.com/trade-api/ws/v2`
- Demo: `https://demo.kalshi.com/trade-api/v2`

**Authentication**: RSA-PSS key pair. Three headers per request:
- `KALSHI-ACCESS-KEY`
- `KALSHI-ACCESS-SIGNATURE`
- `KALSHI-ACCESS-TIMESTAMP`

**Rate Limits (Tiered):**
| Tier | Qualification |
|------|---------------|
| Standard | Complete signup |
| Advanced | Complete advanced API application |
| Premier | 3.75% of exchange volume/month |
| Prime | 7.5% of exchange volume/month |

**REST Latency**: 50-200ms. Prices in cents (1-99).

**Python SDK:**
```python
import kalshi_python_sync as kalshi
config = kalshi.Configuration()
config.host = "https://trading-api.kalshi.com/trade-api/v2"
api = kalshi.AuthApi(kalshi.ApiClient(config))
token = api.login(kalshi.LoginRequest(email=EMAIL, password=PWD))
```

---

## 6. Open Source Repos & Tools

### Prediction Market Trading Bots
| Repo | Stars | Strategy | Key Feature |
|------|-------|----------|-------------|
| [Polymarket/agents](https://github.com/Polymarket/agents) | Official | AI agent | LLM-driven trading framework |
| [Polymarket/py-clob-client](https://github.com/Polymarket/py-clob-client) | 834 | SDK | Official Python client |
| [ImMike/polymarket-arbitrage](https://github.com/ImMike/polymarket-arbitrage) | Active | Cross-platform arb | 10K+ markets, risk management |
| [warproxxx/poly-maker](https://github.com/warproxxx/poly-maker) | Active | Market making | Reward-optimized, Google Sheets config |
| [suislanchez/polymarket-kalshi-weather-bot](https://github.com/suislanchez/polymarket-kalshi-weather-bot) | Active | Weather trading | GFS ensemble, Kelly criterion |
| [OctagonAI/kalshi-deep-trading-bot](https://github.com/OctagonAI/kalshi-deep-trading-bot) | Active | AI research | Octagon Deep Research + OpenAI |
| [ryanfrigo/kalshi-ai-trading-bot](https://github.com/ryanfrigo/kalshi-ai-trading-bot) | Active | Multi-agent AI | 5 LLMs weighted voting |
| [nikhilnd/kalshi-market-making](https://github.com/nikhilnd/kalshi-market-making) | Active | MM | S&P 500 hedging, AWS EC2 |
| [ent0n29/polybot](https://github.com/ent0n29/polybot) | 93 | Reverse engineering | Java microservices, ClickHouse |
| [PredictionXBT/PredictOS](https://github.com/PredictionXBT/PredictOS) | Active | Multi-platform | Cross-platform arbitrage |
| [lingreerjr-eng/latency-bot](https://github.com/lingreerjr-eng/latency-bot) | Active | Latency arb | Binance → Polymarket BTC |
| [discountry/polymarket-trading-bot](https://github.com/discountry/polymarket-trading-bot) | Active | Beginner-friendly | Flash crash strategy |
| [taetaehoho/poly-kalshi-arb](https://github.com/taetaehoho/poly-kalshi-arb) | Active | Rust arb | Lock-free, circuit breaker |

### Unified SDKs
| Tool | Platforms | Notes |
|------|-----------|-------|
| [pmxt](https://github.com/pmxt-dev/pmxt) | Polymarket, Kalshi, Limitless | "CCXT for prediction markets" |
| [predmarket](https://github.com/ashercn97/predmarket) | Kalshi, Polymarket | asyncio-native unified Python |
| [aiokalshi](https://github.com/the-odds-company/aiokalshi) | Kalshi | Async REST, Pydantic models |
| [pykalshi](https://github.com/ArshKA/kalshi-client) | Kalshi | WS streaming, OrderbookManager |

### Sports Arbitrage
| Repo | Strategy | Notes |
|------|----------|-------|
| [Live-Sports-Arbitrage-Bet-Finder](https://github.com/personal-coding/Live-Sports-Arbitrage-Bet-Finder) | Live odds scraping | 10ms polling, multithreaded |
| [SureBetsBot](https://github.com/TessaRichardson/SureBetsBot) | Kelly criterion | Streamlit dashboard |
| [SportsArbFinder](https://github.com/carterlasalle/SportsArbFinder) | The Odds API | Web interface, MIT license |

### Resource Lists
- [Awesome-Prediction-Market-Tools](https://github.com/aarora4/Awesome-Prediction-Market-Tools)
- [awesome-prediction-markets](https://github.com/0xperp/awesome-prediction-markets)
- [awesome-systematic-trading](https://github.com/wangzhe3224/awesome-systematic-trading)

---

## 7. Infrastructure & Optimization

### Server Location
- **New York**: Best for both Polymarket and Kalshi (both US-based)
- **QuantVPS**: Sub-0.52ms to exchanges, from $59.99/month
- **NYCServers**: Sub-1ms to Polymarket API

### Performance Optimization Stack
| Technique | Impact |
|-----------|--------|
| `uvloop` event loop | 20-25% async improvement |
| `orjson` for JSON | 3-10x faster serialization |
| `picows` WebSocket | ~1.5-2x faster than aiohttp |
| `aiohttp[speedups]` | C-based HTTP parsing |
| HTTP/2 persistent connections | Eliminates connection overhead |
| Parallel order signing | ~7ms per order |
| Batch orders | Up to 15 per call (Polymarket) |
| Local orderbook state | Avoid repeated API calls |

### Latency Budget
```
Signal detection (ESPN poll):     ~194ms
Signal processing & decision:     ~10-50ms
Order placement (Polymarket):     ~100-200ms
────────────────────────────────────────
Total signal-to-fill:             ~300-450ms

vs. human trader:                 ~5,000-30,000ms
vs. sub-100ms bot:                ~50-100ms
```

### WebSocket vs REST
- WebSocket: 98.5% faster for real-time data
- Best-in-class WS latency: <10ms
- REST polling: 50-200ms minimum + poll interval
- **Recommendation**: Hybrid — WS for market data, REST for account operations

---

## 8. Risk Management

### Position-Level Controls
- **Fractional Kelly**: Use 25% of full Kelly criterion (quarter-Kelly)
- **Max bet size**: $50 per trade (configurable)
- **Max daily loss**: $200 hard stop
- **Stop-loss**: Exit at 15% position loss
- **Max open positions**: 10 concurrent

### System-Level Controls
- **Kill switch**: Emergency halt for all trading
- **Signal staleness**: Reject signals >5 seconds old
- **Rate limit handling**: Exponential backoff (2s, 4s, 8s, 16s)
- **Circuit breaker**: Auto-halt on 3+ consecutive failures
- **Paper trading first**: Always test in paper mode

### Key Risks
1. **Execution risk**: Polymarket arb is NOT atomic — delay between legs
2. **Resolution divergence**: Same event, different settlement criteria across platforms
3. **Slippage**: Shallow liquidity on prediction markets ($5K-$15K depth per side)
4. **Oracle manipulation**: UMA token holders can influence Polymarket resolution
5. **API changes**: ESPN is unofficial, endpoints change without notice
6. **Edge decay**: 12.3s → 2.7s opportunity windows in 2 years
7. **Measurement error**: NWS stations have 1-2°F error (critical for weather markets)

### Common Mistakes
1. Automating an unprofitable strategy
2. Over-fitting to historical data
3. Ignoring liquidity/slippage in edge calculations
4. No kill switch for runaway bots
5. Confusing wallet vs funder address (Polymarket)
6. Running without position limits on binary contracts
7. Treating liquidity rewards as primary income

---

## 9. Legal & Regulatory

### Polymarket
- **CFTC-approved** (November 2025) as designated contract market
- US users must trade through registered FCMs with KYC
- Previously fined $1.4M (2022) for operating unregistered
- State-level pushback ongoing (Tennessee, Massachusetts, Nevada)

### Kalshi
- **CFTC-regulated** from inception
- Full US access, no geographic restrictions
- 0% trading fees (current)
- Massachusetts lawsuit (Sept 2025) re: sports market classification

### Bot Trading
- Automated trading **explicitly permitted** via APIs on both platforms
- Must comply with platform Terms of Service
- No insider trading laws specific to prediction markets (gap in regulation)
- CFTC warns against fraudulent "AI trading algorithms" with guaranteed returns

---

## 10. Key Metrics & Benchmarks

### Profitability Benchmarks
| Metric | Value |
|--------|-------|
| Top Polymarket trader P&L | $2.01M (4,049 txns) |
| AI arb bot average per trade | ~$16.80 (8,894 trades) |
| Weather bot win rate | 70-85% |
| Weather bot earnings | ~$24,000 (Polymarket) |
| Market making daily (professional) | $150-300/day per market |
| Profitable wallets | 7.6% of total |
| Wallets with >$1K profit | 0.51% |

### Speed Benchmarks
| Metric | Value |
|--------|-------|
| ESPN API latency | ~194ms |
| Polymarket REST API | ~100-200ms |
| Kalshi REST API | 50-200ms |
| Binance WebSocket | <50ms |
| VPS to exchange | 1-30ms |
| QuantVPS to CME | <0.52ms |
| Average arb window (2026) | 2.7s |
| Order signing time | ~7ms |

### Minimum Edge Thresholds
| Platform | Min Edge | Reason |
|----------|----------|--------|
| Polymarket | 2.5-3% | 2% winner fee + slippage |
| Kalshi | 1% | 0% fees, just slippage |
| Cross-platform | 3% | Both sides + settlement risk |

---

## Sources

### Primary Research
- [Prediction Market Arbitrage Guide 2026](https://newyorkcityservers.com/blog/prediction-market-arbitrage-guide)
- [How AI Exploits Prediction Market Glitches - CoinDesk](https://www.coindesk.com/markets/2026/02/21/how-ai-is-helping-retail-traders-exploit-prediction-market-glitches-to-make-easy-money)
- [Beyond Simple Arbitrage: 4 Strategies - Medium](https://medium.com/illumination/beyond-simple-arbitrage-4-polymarket-strategies-bots-actually-profit-from-in-2026-ddacc92c5b4f)
- [Mathematical Execution Behind Prediction Market Alpha - Substack](https://navnoorbawa.substack.com/p/the-mathematical-execution-behind)

### API Documentation
- [Polymarket CLOB Docs](https://docs.polymarket.com/developers/CLOB/introduction)
- [Polymarket WebSocket](https://docs.polymarket.com/market-data/websocket/overview)
- [Kalshi API Docs](https://docs.kalshi.com/welcome)
- [Kalshi WebSocket](https://docs.kalshi.com/websockets/websocket-connection)
- [ESPN Hidden API Docs](https://gist.github.com/akeaswaran/b48b02f1c94f873c6655e7129910fc3b)
- [NWS API Documentation](https://www.weather.gov/documentation/services-web-api)

### GitHub Repositories
- [py-clob-client](https://github.com/Polymarket/py-clob-client)
- [Polymarket/agents](https://github.com/Polymarket/agents)
- [polymarket-kalshi-weather-bot](https://github.com/suislanchez/polymarket-kalshi-weather-bot)
- [pmxt](https://github.com/pmxt-dev/pmxt)
- [latency-bot](https://github.com/lingreerjr-eng/latency-bot)
- [Awesome-Prediction-Market-Tools](https://github.com/aarora4/Awesome-Prediction-Market-Tools)

### Infrastructure
- [QuantVPS Polymarket](https://www.quantvps.com/polymarket-vps)
- [VPS for Prediction Markets](https://newyorkcityservers.com/blog/vps-for-prediction-market-bots)
- [Market Making Guide 2026](https://newyorkcityservers.com/blog/prediction-market-making-guide)
- [Wethr.net - Weather Analytics](https://wethr.net/get-wethr)

### Community & Analysis
- [Polymarket Analytics](https://polymarketanalytics.com/)
- [Polywhaler](https://www.polywhaler.com/)
- [EventArb.com](https://www.eventarb.com/)
- [Dune Analytics Prediction Market Dashboard](https://dune.com/the_liolik/99c)
