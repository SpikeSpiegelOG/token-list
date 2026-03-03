"""CLI entry point for the latency arbitrage bot."""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

import click


@click.group()
@click.version_option(version="0.1.0")
def cli():
    """Spike ARB Bot - Latency Arbitrage for Prediction Markets."""
    pass


@cli.command()
@click.option("--config", "-c", default=None, help="Path to settings.yaml")
@click.option("--mode", "-m", type=click.Choice(["paper", "live"]), default=None, help="Trading mode")
@click.option("--log-level", "-l", type=click.Choice(["DEBUG", "INFO", "WARNING"]), default=None)
def run(config: str | None, mode: str | None, log_level: str | None):
    """Start the arbitrage bot."""
    from src.bot import SpikeArbBot
    from src.core.config import load_config

    # Load config
    app_config = load_config(config)

    # CLI overrides
    if mode:
        app_config.bot.mode = mode
    if log_level:
        app_config.bot.log_level = log_level

    click.echo(f"Starting Spike ARB Bot in {app_config.bot.mode} mode...")

    bot = SpikeArbBot(config=app_config)
    asyncio.run(bot.run_forever())


@cli.command()
@click.option("--config", "-c", default=None, help="Path to settings.yaml")
def status(config: str | None):
    """Show bot configuration and connection status."""
    from src.core.config import load_config

    app_config = load_config(config)

    click.echo("=== Spike ARB Bot Configuration ===\n")
    click.echo(f"Bot Name: {app_config.bot.name}")
    click.echo(f"Mode: {app_config.bot.mode}")
    click.echo(f"Log Level: {app_config.bot.log_level}")
    click.echo()

    click.echo("--- Data Sources ---")
    click.echo(f"ESPN: {'Enabled' if app_config.data_sources.espn.enabled else 'Disabled'}")
    click.echo(f"  Sports: {', '.join(app_config.data_sources.espn.sports)}")
    click.echo(f"Weather: {'Enabled' if app_config.data_sources.weather.enabled else 'Disabled'}")
    click.echo(f"  Providers: {', '.join(app_config.data_sources.weather.providers.keys())}")
    click.echo(f"News: {'Enabled' if app_config.data_sources.news.enabled else 'Disabled'}")
    click.echo(f"Crypto: {'Enabled' if app_config.data_sources.crypto.enabled else 'Disabled'}")
    click.echo()

    click.echo("--- Markets ---")
    click.echo(f"Polymarket: {'Enabled' if app_config.markets.polymarket.enabled else 'Disabled'}")
    pm_key = app_config.markets.polymarket.api_key
    click.echo(f"  API Key: {'Set' if pm_key else 'NOT SET'}")
    click.echo(f"Kalshi: {'Enabled' if app_config.markets.kalshi.enabled else 'Disabled'}")
    k_key = app_config.markets.kalshi.api_key or app_config.markets.kalshi.email
    click.echo(f"  Credentials: {'Set' if k_key else 'NOT SET'}")
    click.echo()

    click.echo("--- Strategy ---")
    click.echo(f"Min Edge: {app_config.strategy.min_edge_threshold}")
    click.echo(f"Kelly Fraction: {app_config.strategy.kelly_fraction}")
    click.echo(f"Max Bet: ${app_config.strategy.max_bet_size_usd}")
    click.echo(f"Daily Loss Limit: ${app_config.strategy.max_daily_loss_usd}")


@cli.command()
@click.argument("query")
@click.option("--platform", "-p", type=click.Choice(["polymarket", "kalshi", "both"]), default="both")
def search(query: str, platform: str):
    """Search for prediction markets."""
    from src.core.config import load_config
    from src.core.event_bus import EventBus
    from src.core.models import Platform

    async def _search():
        app_config = load_config()
        event_bus = EventBus()

        results = []

        if platform in ("polymarket", "both") and app_config.markets.polymarket.enabled:
            from src.markets.polymarket.connector import PolymarketConnector
            poly = PolymarketConnector(event_bus, app_config.markets.polymarket.model_dump())
            await poly.connect()
            markets = await poly.search_markets(query)
            results.extend(markets)
            await poly.disconnect()

        if platform in ("kalshi", "both") and app_config.markets.kalshi.enabled:
            from src.markets.kalshi.connector import KalshiConnector
            kalshi = KalshiConnector(event_bus, app_config.markets.kalshi.model_dump())
            await kalshi.connect()
            markets = await kalshi.search_markets(query)
            results.extend(markets)
            await kalshi.disconnect()

        if not results:
            click.echo("No markets found.")
            return

        click.echo(f"\nFound {len(results)} markets:\n")
        for m in results:
            click.echo(f"  [{m.platform.value}] {m.market_id}")
            click.echo(f"    Q: {m.question}")
            click.echo(f"    YES: {m.yes_price:.2f} | NO: {m.no_price:.2f} | Vol: ${m.volume_24h:.0f}")
            click.echo()

    asyncio.run(_search())


@cli.command()
def setup():
    """Interactive setup wizard for first-time configuration."""
    click.echo("=== Spike ARB Bot Setup Wizard ===\n")

    # Check for .env
    env_path = Path("config/.env")
    if env_path.exists():
        click.echo("Found existing .env file.")
    else:
        click.echo("No .env file found. Creating from template...")
        template = Path("config/.env.example")
        if template.exists():
            import shutil
            shutil.copy(template, env_path)
            click.echo(f"Created {env_path} — please fill in your API keys.")
        else:
            click.echo("ERROR: .env.example not found.")

    click.echo("\nSetup complete! Next steps:")
    click.echo("1. Edit config/.env with your API keys")
    click.echo("2. Edit config/settings.yaml to customize strategy")
    click.echo("3. Run: arb-bot run --mode paper")
    click.echo("4. Monitor the dashboard and verify signals")
    click.echo("5. When ready: arb-bot run --mode live")


def main():
    cli()


if __name__ == "__main__":
    main()
