import logging
from typing import MutableMapping, Any
from vase.config import config
import httpx

from vase.monitor import EDLogs
from vase.processor import Processor

logger = logging.getLogger(__name__)


class FleetProcessor(Processor):

    def __init__(self, auth: httpx.Auth):
        self.auth = auth
        self.base_url: str = config.get_str('api_base_url', default="https://fleets.yonside.org/")

    @property
    def name(self) -> str:
        return "Fleet Updater"

    async def process(self, journal: EDLogs, entry: MutableMapping[str, Any] | None) -> None:
        if entry is None:
            return

        event_type = entry["event"].lower()
        if event_type == "carrierstats" and entry["CarrierType"] == "FleetCarrier":
            logger.info(f"Updating carrier statistics for {entry['Name']} {entry['Callsign']}")
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
                response = await client.post(f"{self.base_url}v1/carrier/{entry['Callsign']}/stats", json=req)
                if response.status_code == 403:
                    logger.error(f"This user is not allowed to update {entry['Callsign']}")
                    return
                elif response.status_code != 200:
                    logger.error(f"Failed to update {entry['Callsign']} {response.text}")
                    return
        elif event_type == "carrierjumprequest":
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
                response = await client.post(f"{self.base_url}v1/carrier/{entry['Callsign']}/jump", json=req)
                if response.status_code == 403:
                    logger.error(f"This user is not allowed to update {entry['Callsign']}")
                    return
                elif response.status_code != 201:
                    logger.error(f"Failed to update {entry['Callsign']} {response.text}")
                    return
        elif event_type == "carrierjumpcancelled":
            logger.info(f"Processing jump cancellation for {entry['Callsign']}")
            req = {
                "timestamp": entry["timestamp"],
                "replay": False,
                "action": "cancel",
            }
            async with httpx.AsyncClient(auth=self.auth) as client:
                response = await client.post(f"{self.base_url}v1/carrier/{entry['Callsign']}/jump", json=req)
                if response.status_code == 403:
                    logger.error(f"This user is not allowed to update {entry['Callsign']}")
                    return
                elif response.status_code != 200:
                    logger.error(f"Failed to update {entry['Callsign']} {response.text}")
                    return
        elif event_type == "carrierlocation":
            logger.info(f"Processing location update for {entry['Callsign']}")
            req = {
                "timestamp": entry["timestamp"],
                "replay": False,
                "system": entry["StarSystem"]
            }
            async with httpx.AsyncClient(auth=self.auth) as client:
                response = await client.post(f"{self.base_url}v1/carrier/{entry['Callsign']}/location", json=req)
                if response.status_code == 403:
                    logger.error(f"This user is not allowed to update {entry['Callsign']}")
                    return
                elif response.status_code != 200:
                    logger.error(f"Failed to update {entry['Callsign']} {response.text}")
                    return
        elif event_type == "startup" and entry["Docked"] == True and entry["StationType"] == "FleetCarrier":
            logger.info(f"Processing startup update for {entry['StationName']}")
            req = {
                "timestamp": entry["timestamp"],
                "replay": False,
                "system": entry["StarSystem"]
            }
            async with httpx.AsyncClient(auth=self.auth) as client:
                response = await client.post(f"{self.base_url}v1/carrier/{entry['StationName']}/location", json=req)
                if response.status_code == 403:
                    logger.warning(f"This user is not allowed to update {entry['StationName']} (Probably docked on someone else's carrier)")
                    return
                elif response.status_code != 200:
                    logger.error(f"Failed to update {entry['StationName']} {response.text}")
                    return
        elif event_type == "carrierjump":
            pass
