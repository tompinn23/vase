import asyncio
import logging
import sys
import time
import webbrowser
from typing import MutableMapping, Any

import httpx
import jwt
import keyring

from vase.api import Journal, Processor, Config

logger = logging.getLogger(__name__)


if sys.platform == "win32":
    from keyring.backends.Windows import WinVaultKeyring

    keyring.set_keyring(WinVaultKeyring())


class AuthException(Exception):
    pass


class AsyncJWTAuth(httpx.Auth):
    def __init__(self, base_url: str, refresh_token: str | None = None):
        """
        token_getter: async callable returning (jwt, expiry_timestamp)
        refresh_token_func: async callable to refresh JWT, returns (jwt, expiry_timestamp)
        """
        if refresh_token is None:
            self.refresh_token = keyring.get_password("org.yonside.vase", "refresh")
        else:
            self.refresh_token = refresh_token
        self.base_url = base_url
        self.token = None
        self.expiry = 0
        self._lock = asyncio.Lock()  # prevent simultaneous refresh

    async def async_auth_flow(self, request):
        # Refresh token if missing or expired
        now = time.time()
        if self.token is None or now >= self.expiry:
            async with self._lock:
                # Double-check inside lock
                if self.token is None or time.time() >= self.expiry:
                    await self.token_refresh()

        # Attach token to request
        request.headers["Authorization"] = f"Bearer {self.token}"

        response = yield request

        # Retry once on 401 Unauthorized
        if response.status_code == 401:
            async with self._lock:
                await self.token_refresh()
            request.headers["Authorization"] = f"Bearer {self.token}"
            yield request

    async def login(self):
        async with httpx.AsyncClient() as client:
            resp = await client.get(f"{self.base_url}v1/auth/start")
            if resp.status_code != 200:
                raise AuthException("Failed to start login")
            data = resp.json()
            print(data)
            print(f"Login using the following link {data['auth_url']}")
            webbrowser.open(data["auth_url"])
            interval = data["interval"]
            poll_content = f"device_code={data['link']}"
            while True:
                resp = await client.post(
                    f"{self.base_url}v1/auth/poll",
                    content=poll_content,
                    headers={"Content-Type": "application/x-www-form-urlencoded"},
                )
                if resp.status_code != 200:
                    raise AuthException("Failed to login")
                data = resp.json()
                print(data)
                if data["status"] == "pending":
                    await asyncio.sleep(interval)
                elif data["status"] == "completed":
                    self.token = data["token"]
                    self.refresh_token = data["refresh"]
                    keyring.set_password(
                        "org.yonside.vase", "refresh", self.refresh_token
                    )
                    payload = jwt.decode(
                        self.token,
                        options={"verify_signature": False, "verify_sub": False},
                    )
                    self.expiry = float(payload.get("exp"))
                    return
                else:
                    raise AuthException("Failed to login")

    async def token_refresh(self):
        if self.refresh_token is None:
            await self.login()
            return

        async with httpx.AsyncClient() as client:
            resp = await client.post(
                f"{self.base_url}v1/auth/refresh",
                headers={"Authorization": f"Bearer {self.refresh_token}"},
            )
            if resp.status_code == 502:
                raise AuthException(f"Error contacting API code={resp.status_code}")
            data = resp.json()
            if resp.status_code != 200:
                raise AuthException(
                    f"Failed to refresh token {resp.status_code} {data.get('error')}"
                )

            self.token = data["token"]
            self.refresh_token = data["refresh"]
            keyring.set_password("org.yonside.vase", "refresh", self.refresh_token)
            payload = jwt.decode(
                self.token, options={"verify_signature": False, "verify_sub": False}
            )
            self.expiry = float(payload.get("exp"))


class FleetProcessor(Processor):
    auth: AsyncJWTAuth
    base_url: str

    @property
    def internal_name(self) -> str:
        return "fleets"

    @property
    def name(self) -> str:
        return "Fleet Updater"

    async def setup(self, config: Config) -> bool:
        if not config.get("enabled", default=True):
            return False

        self.base_url = config.get("base_url", default="https://fleets.yonside.org/")
        self.auth = AsyncJWTAuth(self.base_url)

        async with httpx.AsyncClient(auth=self.auth) as client:
            resp = await client.get(f"{self.base_url}v1/auth/ping")
            if resp.status_code != 200:
                raise Exception("Failed to setup fleet")
        return True

    async def process(
        self, journal: Journal, entry: MutableMapping[str, Any] | None
    ) -> None:
        if entry is None:
            return

        event_type = entry["event"].lower()
        if event_type == "carrierstats" and entry["CarrierType"] == "FleetCarrier":
            logger.info(
                f"Updating carrier statistics for {entry['Name']} {entry['Callsign']}"
            )
            req = {
                "timestamp": entry["timestamp"],
                "replay": False,
                "name": entry["Name"],
                "fuel": entry["FuelLevel"],
                "crew_cargo": entry["SpaceUsage"]["Crew"],
                "cargo": entry["SpaceUsage"]["Cargo"],
                "balance": entry["Finance"]["CarrierBalance"],
            }
            async with httpx.AsyncClient(auth=self.auth) as client:
                response = await client.post(
                    f"{self.base_url}v1/carrier/{entry['Callsign']}/stats", json=req
                )
                if response.status_code == 403:
                    logger.error(
                        f"This user is not allowed to update {entry['Callsign']}"
                    )
                    return
                elif response.status_code != 200:
                    logger.error(
                        f"Failed to update {entry['Callsign']} {response.text}"
                    )
                    return
        elif event_type == "carrierjumprequest":
            if entry.get("Callsign") is None:
                logger.warning(
                    f"No Callsign added for event {event_type} we cant update the API (probably just an early event before we can construct carrier ID maps)"
                )
                return
            logger.info(f"Processing jump request for {entry['Callsign']}")
            req = {
                "timestamp": entry["timestamp"],
                "replay": False,
                "action": "request",
                "system": entry["SystemName"],
                "body": entry["Body"],
                "departure": entry["DepartureTime"],
            }
            async with httpx.AsyncClient(auth=self.auth) as client:
                response = await client.post(
                    f"{self.base_url}v1/carrier/{entry['Callsign']}/jump", json=req
                )
                if response.status_code == 403:
                    logger.error(
                        f"This user is not allowed to update {entry['Callsign']}"
                    )
                    return
                elif response.status_code != 201:
                    logger.error(
                        f"Failed to update {entry['Callsign']} {response.text}"
                    )
                    return
        elif event_type == "carrierjumpcancelled":
            if entry.get("Callsign") is None:
                logger.warning(
                    f"No Callsign added for event {event_type} we cant update the API (probably just an early event before we can construct carrier ID maps)"
                )
                return
            logger.info(f"Processing jump cancellation for {entry['Callsign']}")
            req = {
                "timestamp": entry["timestamp"],
                "replay": False,
                "action": "cancel",
            }
            async with httpx.AsyncClient(auth=self.auth) as client:
                response = await client.post(
                    f"{self.base_url}v1/carrier/{entry['Callsign']}/jump", json=req
                )
                if response.status_code == 403:
                    logger.error(
                        f"This user is not allowed to update {entry['Callsign']}"
                    )
                    return
                elif response.status_code != 200:
                    logger.error(
                        f"Failed to update {entry['Callsign']} {response.text}"
                    )
                    return
        elif event_type == "carrierlocation":
            if entry.get("Callsign") is None:
                logger.warning(
                    f"No Callsign added for event {event_type} we cant update the API (probably just an early event before we can construct carrier ID maps)"
                )
                return
            logger.info(f"Processing location update for {entry['Callsign']}")
            req = {
                "timestamp": entry["timestamp"],
                "replay": False,
                "system": entry["StarSystem"],
            }
            async with httpx.AsyncClient(auth=self.auth) as client:
                response = await client.post(
                    f"{self.base_url}v1/carrier/{entry['Callsign']}/location", json=req
                )
                if response.status_code == 403:
                    logger.error(
                        f"This user is not allowed to update {entry['Callsign']}"
                    )
                    return
                elif response.status_code != 200:
                    logger.error(
                        f"Failed to update {entry['Callsign']} {response.text}"
                    )
                    return
        elif (
            event_type == "startup"
            and entry["Docked"]
            and entry["StationType"] == "FleetCarrier"
        ):  # interestingly it appears squadron carriers appear as FleetCarrier
            logger.info(f"Processing startup update for {entry['StationName']}")
            req = {
                "timestamp": entry["timestamp"],
                "replay": False,
                "system": entry["StarSystem"],
            }
            async with httpx.AsyncClient(auth=self.auth) as client:
                response = await client.post(
                    f"{self.base_url}v1/carrier/{entry['StationName']}/location",
                    json=req,
                )
                if response.status_code == 403:
                    logger.warning(
                        f"This user is not allowed to update {entry['StationName']} (Probably docked on someone else's carrier)"
                    )
                    return
                elif response.status_code != 200:
                    logger.error(
                        f"Failed to update {entry['StationName']} {response.text}"
                    )
                    return
        elif event_type == "carrierjump":
            pass


def load() -> Processor:
    return FleetProcessor()
