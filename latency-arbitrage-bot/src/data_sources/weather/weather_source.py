"""Weather data source adapters.

Multiple weather providers for redundancy and speed. Weather data is relevant
for prediction markets on Kalshi (temperature, hurricane, snow markets).

Strategy: Poll multiple weather APIs simultaneously. The fastest response
with a significant change triggers a signal before markets can react.
"""

from __future__ import annotations

import asyncio
import time
from typing import Any

import aiohttp

from src.core.base import BaseDataSource
from src.core.event_bus import EventBus
from src.core.models import DataSignal, SignalType


class NWSWeatherSource(BaseDataSource):
    """National Weather Service API - free, no key needed, updates frequently."""

    def __init__(self, event_bus: EventBus, config: dict[str, Any]) -> None:
        super().__init__("nws_weather", event_bus, config)
        self.base_url = config.get("base_url", "https://api.weather.gov")
        self.locations = config.get("tracked_locations", [])
        self._session: aiohttp.ClientSession | None = None
        self._last_observations: dict[str, dict[str, Any]] = {}
        self._station_cache: dict[str, str] = {}  # location_key -> station_id

    async def connect(self) -> None:
        headers = {"User-Agent": "(spike-arb-bot, contact@example.com)"}
        timeout = aiohttp.ClientTimeout(total=10, connect=3)
        self._session = aiohttp.ClientSession(headers=headers, timeout=timeout)
        # Pre-resolve station IDs for tracked locations
        for loc in self.locations:
            await self._resolve_station(loc)
        self.logger.info(f"NWS weather connected, tracking {len(self._station_cache)} stations")

    async def disconnect(self) -> None:
        if self._session:
            await self._session.close()
            self._session = None

    async def _resolve_station(self, location: dict[str, Any]) -> None:
        """Find the nearest weather station for a location."""
        if not self._session:
            return
        lat, lon = location["lat"], location["lon"]
        loc_key = f"{lat},{lon}"
        try:
            url = f"{self.base_url}/points/{lat},{lon}"
            async with self._session.get(url) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    station_url = data.get("properties", {}).get("observationStations", "")
                    if station_url:
                        async with self._session.get(station_url) as station_resp:
                            if station_resp.status == 200:
                                stations = await station_resp.json()
                                features = stations.get("features", [])
                                if features:
                                    station_id = features[0]["properties"]["stationIdentifier"]
                                    self._station_cache[loc_key] = station_id
                                    self.logger.debug(f"Resolved station for {location['name']}: {station_id}")
        except Exception:
            self.logger.exception(f"Error resolving station for {location.get('name', loc_key)}")

    async def poll(self) -> list[DataSignal]:
        """Poll all tracked stations for weather changes."""
        if not self._session:
            return []

        signals: list[DataSignal] = []
        tasks = []
        for loc in self.locations:
            loc_key = f"{loc['lat']},{loc['lon']}"
            station_id = self._station_cache.get(loc_key)
            if station_id:
                tasks.append(self._poll_station(station_id, loc))

        results = await asyncio.gather(*tasks, return_exceptions=True)
        for result in results:
            if isinstance(result, list):
                signals.extend(result)

        return signals

    async def _poll_station(self, station_id: str, location: dict[str, Any]) -> list[DataSignal]:
        """Poll a single station for latest observation."""
        signals: list[DataSignal] = []
        url = f"{self.base_url}/stations/{station_id}/observations/latest"

        try:
            async with self._session.get(url) as resp:
                if resp.status != 200:
                    return signals
                data = await resp.json()
        except Exception:
            return signals

        props = data.get("properties", {})
        observation = {
            "temperature_c": self._extract_value(props.get("temperature")),
            "wind_speed_kmh": self._extract_value(props.get("windSpeed")),
            "wind_gust_kmh": self._extract_value(props.get("windGust")),
            "humidity_pct": self._extract_value(props.get("relativeHumidity")),
            "pressure_pa": self._extract_value(props.get("barometricPressure")),
            "description": props.get("textDescription", ""),
        }

        loc_name = location.get("name", station_id)
        last_obs = self._last_observations.get(station_id)

        if last_obs:
            # Check for significant temperature change
            temp_now = observation["temperature_c"]
            temp_last = last_obs.get("temperature_c")
            if temp_now is not None and temp_last is not None:
                temp_delta = abs(temp_now - temp_last)
                if temp_delta >= 1.0:  # 1°C change is significant
                    signals.append(DataSignal(
                        source="nws",
                        signal_type=SignalType.WEATHER_TEMPERATURE,
                        event_id=f"temp_{station_id}",
                        data={
                            "location": loc_name,
                            "station_id": station_id,
                            "temperature_c": temp_now,
                            "previous_temperature_c": temp_last,
                            "delta_c": round(temp_now - temp_last, 2),
                            "observation": observation,
                        },
                        confidence=0.95,
                    ))

            # Check for significant wind change
            wind_now = observation["wind_speed_kmh"]
            wind_last = last_obs.get("wind_speed_kmh")
            if wind_now is not None and wind_last is not None:
                wind_delta = abs(wind_now - wind_last)
                if wind_delta >= 15.0:  # 15 km/h change
                    signals.append(DataSignal(
                        source="nws",
                        signal_type=SignalType.WEATHER_WIND,
                        event_id=f"wind_{station_id}",
                        data={
                            "location": loc_name,
                            "station_id": station_id,
                            "wind_speed_kmh": wind_now,
                            "previous_wind_kmh": wind_last,
                            "wind_gust_kmh": observation["wind_gust_kmh"],
                            "observation": observation,
                        },
                        confidence=0.95,
                    ))

        self._last_observations[station_id] = observation
        return signals

    @staticmethod
    def _extract_value(measurement: dict | None) -> float | None:
        if measurement and isinstance(measurement, dict):
            return measurement.get("value")
        return None


class OpenWeatherSource(BaseDataSource):
    """OpenWeatherMap API - fast updates, requires API key."""

    def __init__(self, event_bus: EventBus, config: dict[str, Any]) -> None:
        super().__init__("openweather", event_bus, config)
        self.base_url = config.get("base_url", "https://api.openweathermap.org/data/3.0")
        self.api_key = config.get("api_key", "")
        self.locations = config.get("tracked_locations", [])
        self._session: aiohttp.ClientSession | None = None
        self._last_data: dict[str, dict[str, Any]] = {}

    async def connect(self) -> None:
        timeout = aiohttp.ClientTimeout(total=5, connect=2)
        self._session = aiohttp.ClientSession(timeout=timeout)
        if not self.api_key:
            self.logger.warning("OpenWeather API key not set — source disabled")

    async def disconnect(self) -> None:
        if self._session:
            await self._session.close()
            self._session = None

    async def poll(self) -> list[DataSignal]:
        if not self._session or not self.api_key:
            return []

        signals: list[DataSignal] = []
        tasks = [self._poll_location(loc) for loc in self.locations]
        results = await asyncio.gather(*tasks, return_exceptions=True)
        for result in results:
            if isinstance(result, list):
                signals.extend(result)
        return signals

    async def _poll_location(self, location: dict[str, Any]) -> list[DataSignal]:
        signals: list[DataSignal] = []
        lat, lon = location["lat"], location["lon"]
        loc_key = f"{lat},{lon}"

        url = f"{self.base_url}/onecall"
        params = {
            "lat": lat,
            "lon": lon,
            "appid": self.api_key,
            "units": "metric",
            "exclude": "minutely,hourly,daily",
        }

        try:
            async with self._session.get(url, params=params) as resp:
                if resp.status != 200:
                    return signals
                data = await resp.json()
        except Exception:
            return signals

        current = data.get("current", {})
        weather_data = {
            "temperature_c": current.get("temp"),
            "feels_like_c": current.get("feels_like"),
            "humidity_pct": current.get("humidity"),
            "wind_speed_ms": current.get("wind_speed"),
            "wind_gust_ms": current.get("wind_gust"),
            "uvi": current.get("uvi"),
            "description": current.get("weather", [{}])[0].get("description", ""),
        }

        loc_name = location.get("name", loc_key)
        last = self._last_data.get(loc_key)

        if last:
            temp_now = weather_data.get("temperature_c")
            temp_last = last.get("temperature_c")
            if temp_now is not None and temp_last is not None and abs(temp_now - temp_last) >= 1.0:
                signals.append(DataSignal(
                    source="openweather",
                    signal_type=SignalType.WEATHER_TEMPERATURE,
                    event_id=f"ow_temp_{loc_key}",
                    data={
                        "location": loc_name,
                        "temperature_c": temp_now,
                        "previous_temperature_c": temp_last,
                        "delta_c": round(temp_now - temp_last, 2),
                        "full_data": weather_data,
                    },
                    confidence=0.90,
                ))

        # Check for weather alerts
        alerts = data.get("alerts", [])
        for alert in alerts:
            signals.append(DataSignal(
                source="openweather",
                signal_type=SignalType.WEATHER_ALERT,
                event_id=f"ow_alert_{loc_key}_{alert.get('event', '')}",
                data={
                    "location": loc_name,
                    "event": alert.get("event", ""),
                    "sender": alert.get("sender_name", ""),
                    "description": alert.get("description", ""),
                    "start": alert.get("start"),
                    "end": alert.get("end"),
                },
                confidence=0.95,
            ))

        self._last_data[loc_key] = weather_data
        return signals
