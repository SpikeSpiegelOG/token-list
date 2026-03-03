"""ESPN data source adapter.

ESPN's public API delivers real-time scores and game events. It's one of the fastest
free sports data sources. We poll aggressively during live games to catch score changes,
injuries, and game status updates before prediction markets can react.

Key endpoints:
- /scoreboard: Live scores for all games in a sport
- /summary: Detailed game summary with play-by-play

Strategy: Poll /scoreboard every 500ms during live games to detect score changes.
When we see a score change, immediately check related prediction markets.
"""

from __future__ import annotations

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
        self.sports = config.get("sports", ["football/nfl", "basketball/nba"])
        self._session: aiohttp.ClientSession | None = None
        # Track last known state to detect changes
        self._last_scores: dict[str, dict[str, Any]] = {}
        self._last_statuses: dict[str, str] = {}

    async def connect(self) -> None:
        timeout = aiohttp.ClientTimeout(total=5, connect=2)
        self._session = aiohttp.ClientSession(timeout=timeout)
        self.logger.info(f"ESPN source connected, tracking sports: {self.sports}")

    async def disconnect(self) -> None:
        if self._session:
            await self._session.close()
            self._session = None

    async def poll(self) -> list[DataSignal]:
        """Poll all tracked sports for score/status changes."""
        if not self._session:
            return []

        signals: list[DataSignal] = []
        for sport in self.sports:
            try:
                sport_signals = await self._poll_sport(sport)
                signals.extend(sport_signals)
            except Exception:
                self.logger.exception(f"Error polling ESPN {sport}")

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
        """Process a single ESPN event for score/status changes."""
        signals: list[DataSignal] = []
        event_id = event.get("id", "")
        event_name = event.get("name", "")
        status_type = event.get("status", {}).get("type", {})
        game_state = status_type.get("name", "")  # pre, in, post
        detail = status_type.get("detail", "")

        # Extract scores from competitions
        competitions = event.get("competitions", [])
        if not competitions:
            return signals

        competition = competitions[0]
        competitors = competition.get("competitors", [])

        scores: dict[str, Any] = {}
        for comp in competitors:
            team = comp.get("team", {}).get("abbreviation", "UNK")
            score = comp.get("score", "0")
            scores[team] = {
                "score": int(score) if score.isdigit() else 0,
                "home_away": comp.get("homeAway", ""),
                "winner": comp.get("winner", False),
            }

        # Detect score changes
        last_scores = self._last_scores.get(event_id)
        if last_scores and scores != last_scores:
            # SCORE CHANGED — this is our primary signal
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
                    "sport": sport,
                    "event_name": event_name,
                    "scores": scores,
                    "previous_scores": last_scores,
                    "changed_teams": changed_teams,
                    "game_state": game_state,
                    "detail": detail,
                },
                confidence=0.99,  # ESPN scores are highly reliable
                raw_payload=event,
            ))
            self.logger.info(f"SCORE CHANGE: {event_name} | {scores} | Teams: {changed_teams}")

        # Detect game status changes (start, halftime, end)
        last_status = self._last_statuses.get(event_id)
        if last_status and game_state != last_status:
            signals.append(DataSignal(
                source="espn",
                signal_type=SignalType.SPORTS_STATUS,
                event_id=event_id,
                data={
                    "sport": sport,
                    "event_name": event_name,
                    "new_status": game_state,
                    "old_status": last_status,
                    "detail": detail,
                    "scores": scores,
                },
                confidence=0.99,
                raw_payload=event,
            ))
            self.logger.info(f"STATUS CHANGE: {event_name} | {last_status} -> {game_state}")

        # Update tracked state
        self._last_scores[event_id] = scores
        self._last_statuses[event_id] = game_state

        return signals

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

    @property
    def tracked_game_count(self) -> int:
        return len(self._last_scores)
