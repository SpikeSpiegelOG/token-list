"""Tests for sport-aware market mapping."""

from src.core.models import DataSignal, MarketState, MarketType, Platform, SignalType
from src.markets.common.market_mapper import MarketMapper, SIGNAL_MARKET_ROUTING


def test_moneyline_signal_routes_to_moneyline_market():
    """Score signal should match moneyline markets, not spread/total."""
    mapper = MarketMapper()

    moneyline_market = MarketState(
        platform=Platform.POLYMARKET,
        market_id="lakers_win",
        question="Will the Lakers win tonight?",
        yes_price=0.60,
        no_price=0.40,
        market_type=MarketType.MONEYLINE,
    )
    spread_market = MarketState(
        platform=Platform.KALSHI,
        market_id="lakers_spread",
        question="Will Lakers win by more than 5.5?",
        yes_price=0.50,
        no_price=0.50,
        market_type=MarketType.SPREAD,
    )

    mapper.register_market(moneyline_market, [SignalType.SPORTS_SCORE, SignalType.SPORTS_STATUS], ["lakers"])
    mapper.register_market(spread_market, [SignalType.SPORTS_SPREAD, SignalType.SPORTS_STATUS], ["lakers"])

    score_signal = DataSignal(
        source="espn",
        signal_type=SignalType.SPORTS_SCORE,
        event_id="game_1",
        data={"event_name": "Lakers vs Celtics", "home_team": "LAL"},
    )

    matches = mapper.find_markets(score_signal)
    assert len(matches) == 1
    assert matches[0][0].market_type == MarketType.MONEYLINE


def test_spread_signal_routes_to_spread_market():
    """Spread signal should match spread markets."""
    mapper = MarketMapper()

    moneyline_market = MarketState(
        platform=Platform.POLYMARKET,
        market_id="chiefs_win",
        question="Will the Chiefs win?",
        yes_price=0.70,
        no_price=0.30,
        market_type=MarketType.MONEYLINE,
    )
    spread_market = MarketState(
        platform=Platform.KALSHI,
        market_id="chiefs_spread",
        question="Will Chiefs win by more than 3.5?",
        yes_price=0.55,
        no_price=0.45,
        market_type=MarketType.SPREAD,
    )

    mapper.register_market(moneyline_market, [SignalType.SPORTS_SCORE, SignalType.SPORTS_STATUS], ["chiefs"])
    mapper.register_market(spread_market, [SignalType.SPORTS_SPREAD, SignalType.SPORTS_STATUS], ["chiefs"])

    spread_signal = DataSignal(
        source="espn",
        signal_type=SignalType.SPORTS_SPREAD,
        event_id="game_2",
        data={"event_name": "Chiefs vs Eagles", "home_team": "KC"},
    )

    matches = mapper.find_markets(spread_signal)
    assert len(matches) == 1
    assert matches[0][0].market_type == MarketType.SPREAD


def test_status_signal_matches_all_types():
    """Status signal (game start/end) should match all market types."""
    mapper = MarketMapper()

    for mtype, name in [(MarketType.MONEYLINE, "win"), (MarketType.SPREAD, "spread"), (MarketType.TOTAL, "total")]:
        market = MarketState(
            platform=Platform.KALSHI,
            market_id=f"chiefs_{name}",
            question=f"Chiefs {name} question",
            yes_price=0.50,
            no_price=0.50,
            market_type=mtype,
        )
        mapper.register_market(market, [SignalType.SPORTS_STATUS], ["chiefs"])

    status_signal = DataSignal(
        source="espn",
        signal_type=SignalType.SPORTS_STATUS,
        event_id="game_3",
        data={"event_name": "Chiefs vs Eagles", "new_status": "post", "home_team": "KC"},
    )

    matches = mapper.find_markets(status_signal)
    assert len(matches) == 3  # Should match all three market types


def test_auto_map_detects_market_type():
    """Auto-mapping should detect market type from question."""
    mapper = MarketMapper()

    moneyline = MarketState(
        platform=Platform.POLYMARKET,
        market_id="m1",
        question="Will the Lakers win tonight?",
        yes_price=0.60,
        no_price=0.40,
        market_type=MarketType.MONEYLINE,
    )
    mapper.auto_map_from_question(moneyline)

    spread = MarketState(
        platform=Platform.KALSHI,
        market_id="m2",
        question="Will the Chiefs win by more than 3.5 points?",
        yes_price=0.50,
        no_price=0.50,
        market_type=MarketType.SPREAD,
    )
    mapper.auto_map_from_question(spread)

    assert mapper.registered_count == 2


def test_espn_team_name_expansion():
    """ESPN abbreviations should be expanded for matching."""
    mapper = MarketMapper()

    market = MarketState(
        platform=Platform.POLYMARKET,
        market_id="lakers_win",
        question="Will the Lakers win?",
        yes_price=0.60,
        no_price=0.40,
        market_type=MarketType.MONEYLINE,
    )
    mapper.register_market(market, [SignalType.SPORTS_SCORE], ["lakers"])

    # Signal uses ESPN abbreviation "LAL"
    signal = DataSignal(
        source="espn",
        signal_type=SignalType.SPORTS_SCORE,
        event_id="game_5",
        data={
            "event_name": "LAL vs BOS",
            "home_team": "LAL",
            "away_team": "BOS",
        },
    )

    matches = mapper.find_markets(signal)
    assert len(matches) == 1  # "LAL" should expand to "lakers" and match


def test_signal_market_routing_defined():
    """Verify all expected signal types have market type routing."""
    assert SignalType.SPORTS_SCORE in SIGNAL_MARKET_ROUTING
    assert SignalType.SPORTS_SPREAD in SIGNAL_MARKET_ROUTING
    assert SignalType.SPORTS_TOTAL in SIGNAL_MARKET_ROUTING
    assert SignalType.SPORTS_STATUS in SIGNAL_MARKET_ROUTING

    # Score → moneyline only
    assert MarketType.MONEYLINE in SIGNAL_MARKET_ROUTING[SignalType.SPORTS_SCORE]
    assert MarketType.SPREAD not in SIGNAL_MARKET_ROUTING[SignalType.SPORTS_SCORE]

    # Spread → spread only
    assert MarketType.SPREAD in SIGNAL_MARKET_ROUTING[SignalType.SPORTS_SPREAD]
    assert MarketType.MONEYLINE not in SIGNAL_MARKET_ROUTING[SignalType.SPORTS_SPREAD]

    # Status → all types
    assert len(SIGNAL_MARKET_ROUTING[SignalType.SPORTS_STATUS]) >= 3
