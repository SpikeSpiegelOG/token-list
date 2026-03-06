"""ESPN data source adapter.

ESPN's public API delivers real-time scores and game events. It's one of the fastest
free sports data sources. We poll aggressively during live games to catch score changes,
injuries, and game status updates before prediction markets can react.

Key endpoints:
- /scoreboard: Live scores for all games in a sport
- /summary: Detailed game summary with play-by-play
- /plays: Individual play-by-play data for deep signal generation

Strategy: Poll /scoreboard every 500ms during live games to detect score changes.
When we see a score change, immediately check related prediction markets.
Emit separate signals for moneyline (score), spread (differential), and totals (combined).
"""

from __future__ import annotations

import asyncio
import time
from typing import Any

import aiohttp

from src.core.base import BaseDataSource
from src.core.event_bus import EventBus
from src.core.models import DataSignal, SignalType


class ESPNDataSource(BaseDataSource):
    """Polls ESPN's public API for real-time sports data."""

    def __init__(self, event_bus: EventBus, config: dict[str, Any]) -> None:
        super().__init__("espn", event_bus, config)
        self.base_url = config.get("base_url", "https://site.api.espn.com/apis/site/v2/sports")
        self.plays_base_url = config.get(
            "plays_base_url",
            "https://sports.core.api.espn.com/v2/sports",
        )
        self.sports = config.get("sports", [
            "football/nfl",
            "basketball/nba",
            "baseball/mlb",
            "hockey/nhl",
            "soccer/eng.1",
            "football/college-football",
            "basketball/mens-college-basketball",
            "soccer/usa.1",
        ])
        self.enable_play_by_play = config.get("enable_play_by_play", False)
        self._session: aiohttp.ClientSession | None = None
        # Track last known state to detect changes
        self._last_scores: dict[str, dict[str, Any]] = {}
        self._last_statuses: dict[str, str] = {}
        # Track totals and differentials for spread/total signals
        self._last_totals: dict[str, int] = {}           # event_id -> combined score
        self._last_differentials: dict[str, int] = {}     # event_id -> home - away
        # Track last play IDs to detect new plays
        self._last_play_ids: dict[str, str] = {}

    async def connect(self) -> None:
        timeout = aiohttp.ClientTimeout(total=5, connect=2)
        self._session = aiohttp.ClientSession(timeout=timeout)
        self.logger.info(f"ESPN source connected, tracking sports: {self.sports}")

    async def disconnect(self) -> None:
        if self._session:
            await self._session.close()
            self._session = None

    async def poll(self) -> list[DataSignal]:
        """Poll all tracked sports concurrently for score/status changes."""
        if not self._session:
            return []

        # Poll all sports in parallel for speed
        tasks = [self._poll_sport(sport) for sport in self.sports]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        signals: list[DataSignal] = []
        for i, result in enumerate(results):
            if isinstance(result, Exception):
                self.logger.exception(f"Error polling ESPN {self.sports[i]}: {result}")
            else:
                signals.extend(result)

        return signals

    async def _poll_sport(self, sport: str) -> list[DataSignal]:
        """Poll a single sport's scoreboard."""
        url = f"{self.base_url}/{sport}/scoreboard"
        signals: list[DataSignal] = []

        async with self._session.get(url) as resp:
            if resp.status != 200:
                self.logger.warning(f"ESPN {sport} returned {resp.status}")
                return signals

            data = await resp.json()

        events = data.get("events", [])
        for event in events:
            event_signals = self._process_event(event, sport)
            signals.extend(event_signals)

        return signals

    def _process_event(self, event: dict[str, Any], sport: str) -> list[DataSignal]:
        """Process a single ESPN event for score/status/spread/total changes."""
        signals: list[DataSignal] = []
        event_id = event.get("id", "")
        event_name = event.get("name", "")
        status_obj = event.get("status", {})
        status_type = status_obj.get("type", {})
        game_state = status_type.get("name", "")  # pre, in, post
        detail = status_type.get("detail", "")
        display_clock = status_obj.get("displayClock", "")

        # Extract scores from competitions
        competitions = event.get("competitions", [])
        if not competitions:
            return signals

        competition = competitions[0]
        competitors = competition.get("competitors", [])

        scores: dict[str, Any] = {}
        home_score = 0
        away_score = 0
        home_team = ""
        away_team = ""

        for comp in competitors:
            team_abbr = comp.get("team", {}).get("abbreviation", "UNK")
            team_name = comp.get("team", {}).get("displayName", team_abbr)
            score_str = comp.get("score", "0")
            score_val = int(score_str) if score_str.isdigit() else 0
            home_away = comp.get("homeAway", "")

            # Extract linescores (per-quarter/period scoring)
            linescores = []
            for ls in comp.get("linescores", []):
                linescores.append(int(ls.get("value", 0)))

            scores[team_abbr] = {
                "score": score_val,
                "home_away": home_away,
                "winner": comp.get("winner", False),
                "team_name": team_name,
                "linescores": linescores,
            }

            if home_away == "home":
                home_score = score_val
                home_team = team_abbr
            else:
                away_score = score_val
                away_team = team_abbr

        combined_total = home_score + away_score
        score_differential = home_score - away_score  # Positive = home leading

        # Common data payload used across signal types
        base_data = {
            "sport": sport,
            "event_name": event_name,
            "scores": scores,
            "game_state": game_state,
            "detail": detail,
            "display_clock": display_clock,
            "home_team": home_team,
            "away_team": away_team,
            "home_score": home_score,
            "away_score": away_score,
            "combined_total": combined_total,
            "score_differential": score_differential,
        }

        # --- Detect score changes (MONEYLINE signal) ---
        last_scores = self._last_scores.get(event_id)
        if last_scores and scores != last_scores:
            changed_teams = []
            for team, data in scores.items():
                old = last_scores.get(team, {})
                if data.get("score") != old.get("score"):
                    changed_teams.append(team)

            signals.append(DataSignal(
                source="espn",
                signal_type=SignalType.SPORTS_SCORE,
                event_id=event_id,
                data={
                    **base_data,
                    "previous_scores": last_scores,
                    "changed_teams": changed_teams,
                },
                confidence=0.99,
                raw_payload=event,
            ))
            self.logger.info(f"SCORE CHANGE: {event_name} | {home_team} {home_score} - {away_team} {away_score} | Teams: {changed_teams}")

        # --- Detect total score changes (TOTAL/O-U signal) ---
        last_total = self._last_totals.get(event_id)
        if last_total is not None and combined_total != last_total:
            points_added = combined_total - last_total
            signals.append(DataSignal(
                source="espn",
                signal_type=SignalType.SPORTS_TOTAL,
                event_id=event_id,
                data={
                    **base_data,
                    "previous_total": last_total,
                    "points_added": points_added,
                },
                confidence=0.99,
                raw_payload=event,
            ))
            self.logger.info(f"TOTAL CHANGE: {event_name} | Total: {last_total} -> {combined_total} (+{points_added})")

        # --- Detect spread/differential changes (SPREAD signal) ---
        last_diff = self._last_differentials.get(event_id)
        if last_diff is not None and score_differential != last_diff:
            diff_change = score_differential - last_diff
            signals.append(DataSignal(
                source="espn",
                signal_type=SignalType.SPORTS_SPREAD,
                event_id=event_id,
                data={
                    **base_data,
                    "previous_differential": last_diff,
                    "differential_change": diff_change,
                },
                confidence=0.99,
                raw_payload=event,
            ))
            self.logger.info(
                f"SPREAD CHANGE: {event_name} | "
                f"Differential: {last_diff:+d} -> {score_differential:+d} "
                f"({home_team} {'leading' if score_differential > 0 else 'trailing'})"
            )

        # --- Detect game status changes (start, halftime, end) ---
        last_status = self._last_statuses.get(event_id)
        if last_status and game_state != last_status:
            signals.append(DataSignal(
                source="espn",
                signal_type=SignalType.SPORTS_STATUS,
                event_id=event_id,
                data={
                    **base_data,
                    "new_status": game_state,
                    "old_status": last_status,
                },
                confidence=0.99,
                raw_payload=event,
            ))
            self.logger.info(f"STATUS CHANGE: {event_name} | {last_status} -> {game_state}")

            # Game ended — emit definitive signals for all market types
            if game_state == "post":
                self._emit_game_end_signals(signals, event_id, base_data, event)

        # Update all tracked state
        self._last_scores[event_id] = scores
        self._last_statuses[event_id] = game_state
        self._last_totals[event_id] = combined_total
        self._last_differentials[event_id] = score_differential

        return signals

    def _emit_game_end_signals(
        self,
        signals: list[DataSignal],
        event_id: str,
        base_data: dict[str, Any],
        raw_event: dict[str, Any],
    ) -> None:
        """When a game ends, emit high-confidence definitive signals for all market types."""
        end_data = {
            **base_data,
            "final": True,
            "winner": base_data["home_team"] if base_data["home_score"] > base_data["away_score"]
                      else base_data["away_team"] if base_data["away_score"] > base_data["home_score"]
                      else "tie",
            "final_margin": abs(base_data["score_differential"]),
            "final_total": base_data["combined_total"],
        }

        # Definitive moneyline signal
        signals.append(DataSignal(
            source="espn",
            signal_type=SignalType.SPORTS_SCORE,
            event_id=event_id,
            data={**end_data, "game_state": "post"},
            confidence=1.0,
            raw_payload=raw_event,
        ))

        # Definitive spread signal
        signals.append(DataSignal(
            source="espn",
            signal_type=SignalType.SPORTS_SPREAD,
            event_id=event_id,
            data={**end_data, "game_state": "post"},
            confidence=1.0,
            raw_payload=raw_event,
        ))

        # Definitive total signal
        signals.append(DataSignal(
            source="espn",
            signal_type=SignalType.SPORTS_TOTAL,
            event_id=event_id,
            data={**end_data, "game_state": "post"},
            confidence=1.0,
            raw_payload=raw_event,
        ))

        self.logger.info(
            f"GAME FINAL: {base_data['event_name']} | "
            f"Winner: {end_data['winner']} | "
            f"Margin: {end_data['final_margin']} | "
            f"Total: {end_data['final_total']}"
        )

    async def get_game_summary(self, sport: str, event_id: str) -> dict[str, Any] | None:
        """Get detailed game summary with play-by-play for deeper analysis."""
        if not self._session:
            return None

        url = f"{self.base_url}/{sport}/summary?event={event_id}"
        try:
            async with self._session.get(url) as resp:
                if resp.status == 200:
                    return await resp.json()
        except Exception:
            self.logger.exception(f"Error fetching game summary for {event_id}")
        return None

    async def get_plays(self, sport: str, league: str, event_id: str, limit: int = 50) -> list[dict[str, Any]]:
        """Get recent play-by-play data for an event.

        Uses the core API: sports.core.api.espn.com/v2/sports/{sport}/leagues/{league}/
        events/{id}/competitions/{id}/plays
        """
        if not self._session:
            return []

        url = (
            f"{self.plays_base_url}/{sport}/leagues/{league}"
            f"/events/{event_id}/competitions/{event_id}/plays?limit={limit}"
        )
        try:
            async with self._session.get(url) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    return data.get("items", [])
        except Exception:
            self.logger.exception(f"Error fetching plays for {event_id}")
        return []

    @property
    def tracked_game_count(self) -> int:
        return len(self._last_scores)

    @property
    def live_game_count(self) -> int:
        """Count of games currently in progress."""
        return sum(1 for s in self._last_statuses.values() if s == "in")

    def get_live_event_ids(self) -> list[str]:
        """Get event IDs for all currently live games."""
        return [eid for eid, status in self._last_statuses.items() if status == "in"]
