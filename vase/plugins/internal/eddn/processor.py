import logging
import re
from typing import Tuple

import httpx
from watchdog.observers.fsevents2 import message

from vase.api import Journal, JournalEvent, Processor, Config
from vase.config import appversion
from .validator import Validator, ValidationSeverity, default_validator

logger = logging.getLogger("eddn")


_pat_cache = {}


class EDDNProcessor(Processor):

    _RE_OUTFITTING_ITEMS = re.compile(r'^hpt_|^int_|_armour_')

    validator: Validator
    actually_push: bool
    testing: bool
    eddn_url: str

    fss_signals: bool = False # When we detect an fsssignaldiscovered
    signal_list: list | None = None

    state: dict[str, dict]

    def __init__(self):
        pass

    @property
    def internal_name(self) -> str:
        return "eddn"

    @property
    def name(self) -> str:
        return "EDDN Processor"

    async def setup(self, config: Config) -> bool:
        if config.get("enabled", default=True) is False:
            return False
        self.validator = default_validator()
        self.actually_push = config.get("actually_post", True)
        self.eddn_url = config.get("eddn_url", "https://eddn.edcd.io:4430/upload/")
        self.testing = config.get("testing", True)
        return True

    @staticmethod
    def check_system_name(
        journal: Journal, event: JournalEvent, name: str = "System"
    ) -> bool:
        return journal.state["SystemName"] == event[name]

    @staticmethod
    def check_system_address(journal: Journal, event: JournalEvent) -> bool:
        return journal.state["SystemAddress"] == event["SystemAddress"]

    @staticmethod
    def check_star_pos(journal: Journal, event: JournalEvent) -> bool:
        return journal.state["StarPos"] == event["StarPos"]

    @staticmethod
    def add_optional(message: dict, event: JournalEvent, name: str) -> None:
        if name in event:
            message[name] = event[name]

    @staticmethod
    def pick_keys(source, *args: str):
        return {k: source[k] for k in args if k in source}

    @staticmethod
    def pick_not_keys(source, keys: list[str], *, regex: list[str] | None = None):
        compiled = []
        if regex:
            for r in regex:
                if r in _pat_cache:
                    comp = _pat_cache[r]
                else:
                    comp = re.compile(r)
                    _pat_cache[r] = comp
                compiled.append(comp)
        return {
            k: source[k]
            for k in source.keys()
            if k not in keys and not any(r.search(k) for r in compiled)
        }

    @staticmethod
    def deep_pattern_removal(
        source, regex: list[str] | list[re.Pattern], compiled: bool = False
    ):
        compiled: list[re.Pattern] = []
        if not compiled:
            for r in regex:
                if r in _pat_cache:
                    comp = _pat_cache[r]
                else:
                    comp = re.compile(r)
                    _pat_cache[r] = comp
                compiled.append(comp)
        else:
            compiled = regex
        if isinstance(source, dict):
            return {
                k: EDDNProcessor.deep_pattern_removal(v, compiled, True)
                for k, v in source.items()
                if not any(r.search(k) for r in compiled)
            }
        elif isinstance(source, list):
            return [
                EDDNProcessor.deep_pattern_removal(item, compiled, True)
                for item in source
            ]
        else:
            return source

    def schema_ref(self, schema: str) -> str:
        if self.testing:
            return schema + "/test"
        else:
            return schema

    def fix_commodity_name(self, name: str) -> str:
        if name[0] == '$':
            name = name[1:]
        if name.endswith("_name;"):
            return name[:-6]
        return name

    async def post_message(self, eddn: dict):
        logger.debug(f"EDDN Message: {eddn}")
        validation_result = self.validator.validate(eddn)
        if validation_result.severity != ValidationSeverity.OK:
            logger.error(
                f"EDDN Message failed validation: {validation_result.messages}"
            )
            return
        if self.actually_push:
            async with httpx.AsyncClient() as client:
                response = await client.post(self.eddn_url, json=eddn)
                if response.status_code != 200:
                    logger.error(f"Failed to post to EDDN {response.text}")

    def __process_event(self, journal: Journal, event: JournalEvent, eddn: dict) -> bool:
        event_type = event["event"].lower()

        if event_type == "codexentry":
            # failed cross validation
            if not (
                self.check_system_address(journal, event)
                and self.check_system_name(journal, event)
            ):
                return False

            message = {
                "event": "CodexEntry",
                "horizons": journal.state["Horizons"],
                "odyssey": journal.state["Odyssey"],
                "StarPos": journal.state["StarPos"],
                **self.pick_keys(
                    event,
                    "timestamp",
                    "System",
                    "SystemAddress",
                    "Latitude",
                    "Longitude",
                    "NearestDestination",
                    "Name",
                    "Region",
                    "EntryID",
                    "Category",
                    "SubCategory",
                    "VoucherAmount",
                    "Traits",
                    "BodyID",
                    "BodyName",
                ),
            }

            eddn["$schemaRef"] = self.schema_ref(
                "https://eddn.edcd.io/schemas/codexentry/1"
            )
            eddn["message"] = message

        elif event_type == "docked":
            # cross check the star system data
            if not (
                self.check_system_address(journal, event)
                and self.check_system_name(journal, event)
            ):
                return False
            message = {
                "event": "Docked",
                "horizons": journal.state["Horizons"],
                "odyssey": journal.state["Odyssey"],
                "StarPos": journal.state["StarPos"],
                **self.pick_not_keys(
                    event,
                    ["event", "Wanted", "ActiveFine", "CockpitBreach"],
                ),
            }
            eddn["$schemaRef"] = self.schema_ref(
                "https://eddn.edcd.io/schemas/journal/1"
            )
            eddn["message"] = message
        elif event_type == "fsdjump":
            message = {
                "event": "FSDJump",
                "horizons": journal.state["Horizons"],
                "odyssey": journal.state["Odyssey"],
                **self.pick_not_keys(
                    event,
                    [
                        "event",
                        "Wanted",
                        "BoostUsed",
                        "FuelLevel",
                        "FuelUsed",
                        "JumpDist",
                        "Factions",
                    ],
                ),
            }
            if "Factions" in event:
                message["Factions"] = (
                    [
                        self.pick_not_keys(
                            x,
                            [
                                "HappiestSystem",
                                "HomeSystem",
                                "MyRepuation",
                                "SquadronFaction",
                            ],
                        )
                        for x in event["Factions"]
                    ],
                )
            eddn["$schemaRef"] = self.schema_ref(
                "https://eddn.edcd.io/schemas/journal/1"
            )
            eddn["message"] = message
        elif event_type == "scan":
            # cross-check the star system data
            if not (
                self.check_system_address(journal, event)
                and self.check_system_name(journal, event)
            ):
                return False
            message = {
                "event": "Scan",
                "horizons": journal.state["Horizons"],
                "odyssey": journal.state["Odyssey"],
                **self.pick_not_keys(event, ["event"]),
            }
            eddn["$schemaRef"] = self.schema_ref(
                "https://eddn.edcd.io/schemas/journal/1"
            )
            eddn["message"] = message
        elif event_type == "location":
            message = {
                "event": "Location",
                "horizons": journal.state["Horizons"],
                "odyssey": journal.state["Odyssey"],
                **self.pick_not_keys(
                    event,
                    ["event", "Wanted", "Latitude", "Longitude", "Factions"],
                ),
            }
            if "Factions" in event:
                message["Factions"] = (
                    [
                        self.pick_not_keys(
                            x,
                            [
                                "HappiestSystem",
                                "HomeSystem",
                                "MyRepuation",
                                "SquadronFaction",
                            ],
                        )
                        for x in event["Factions"]
                    ],
                )

            eddn["$schemaRef"] = self.schema_ref(
                "https://eddn.edcd.io/schemas/journal/1"
            )
            eddn["message"] = message
        elif event_type == "saasignalsfound":
            if not self.check_system_address(journal, event):
                return False
            message = {
                "event": "SAASignalsFound",
                "horizons": journal.state["Horizons"],
                "odyssey": journal.state["Odyssey"],
                **self.pick_not_keys(event, ["event"]),
            }

            eddn["$schemaRef"] = self.schema_ref(
                "https://eddn.edcd.io/schemas/journal/1"
            )
            eddn["message"] = message
        elif event_type == "carrierjump":
            message = {
                "event": "CarrierJump",
                "horizons": journal.state["Horizons"],
                "odyssey": journal.state["Odyssey"],
                **self.pick_not_keys(event, ["event", "Factions"]),
            }
            if "Factions" in event:
                message["Factions"] = (
                    [
                        self.pick_not_keys(
                            x,
                            [
                                "HappiestSystem",
                                "HomeSystem",
                                "MyRepuation",
                                "SquadronFaction",
                            ],
                        )
                        for x in event["Factions"]
                    ],
                )
        elif event_type == "approachsettlement":
            if not self.check_system_address(journal, event):
                return False
            message = {
                "event": "ApproachSettlement",
                "horizons": journal.state["Horizons"],
                "odyssey": journal.state["Odyssey"],
                **self.pick_keys(journal.state, "StarSystem", "StarPos")
                ** self.pick_not_keys(event, ["event"]),
            }

            eddn["$schemaRef"] = self.schema_ref(
                "https://eddn.edcd.io/schemas/approachsettlement/1"
            )
            eddn["message"] = message
        elif event_type == "marketsell":
            message = {
                "systemName": journal.state["SystemName"],
                "stationName": journal.state["StationName"],
                "name": event["Type"],
                "prohibited": event["IllegalGoods"],
                "marketId": event["MarketID"],
                **self.pick_not_keys(
                    event,
                    [
                        "Type", # renamed
                        "MarketID", # renamed
                        "IllegalGoods", # renamed
                        "BlackMarket",
                        "TotalSale",
                        "AvgPricePaid",
                        "StolenGoods",
                        "BlackMarket",
                    ],
                ),
            }
            eddn["$schemaRef"] = self.schema_ref(
                "https://eddn.edcd.io/schemas/blackmarket/1"
            )
            eddn["message"] = message
        elif event_type == "market":
            message = {
                "systemName": event["StarSystem"],
                "stationName": event["StationName"],
                "stationType": event["StationType"],
                "marketId": event["MarketID"],
                "horizons": journal.state["Horizons"],
                "odyssey": journal.state["Odyssey"],
                "timestamp": event["timestamp"],
                "commodities": [
                    {
                        "name": self.fix_commodity_name(x["Name"]),
                        "meanPrice": x["MeanPrice"],
                        "buyPrice": x["BuyPrice"],
                        "stock": x["Stock"],
                        "stockBracket": x["StockBracket"],
                        "sellPrice": x["SellPrice"],
                        "demand": x["Demand"],
                        "demandBracket": x["DemandBracket"],
                    }
                    for x in event["Items"] if not (("categoryname" in x and x["categoryname"] == "NonMarketable") or ("legality" in x and x["legality"] != ""))
                ],
            }
            if "CarrierDockingAccess" in event:
                message["carrierDockingAccess"] = event["CarrierDockingAccess"]

            eddn["$schemaRef"] = self.schema_ref("https://eddn.edcd.io/schemas/commodity/3")
            eddn["message"] = message
        elif event_type == "dockingdenied":
            message = {
                "timestamp": event["timestamp"],
                "event": "DockingDenied",
                "horizons": journal.state["Horizons"],
                "odyssey": journal.state["Odyssey"],
                **self.pick_keys(event,
                                 "MarketID",
                                 "StationName",
                                 "StationType",
                                 "Reason"
                                 )
            }
            eddn["$schemaRef"] = self.schema_ref("https://eddn.edcd.io/schemas/dockingdenied/1")
            eddn["message"] = message
        elif event_type == "dockinggranted":
            message = {
                "timestamp": event["timestamp"],
                "event": "DockingGranted",
                "horizons": journal.state["Horizons"],
                "odyssey": journal.state["Odyssey"],
                **self.pick_keys(event,
                                 "MarketID",
                                 "StationName",
                                 "StationType",
                                 "LandingPad"
                                 )
            }
        elif event_type == "fcmaterials":
            message = {
                "timestamp": event["timestamp"],
                "event": "FCMaterials",
                "horizons": journal.state["Horizons"],
                "odyssey": journal.state["Odyssey"],
                **self.pick_keys(event,
                                 "MarketID",
                                 "CarrierName",
                                 "CarrierID")
            }

            if "Items" in event:
                message["Items"] = [
                    {
                        **self.pick_keys(x,
                             "id",
                             "Name",
                             "Price",
                             "Stock",
                             "Demand")
                    }
                    for x in event["Items"]
                ]
            eddn["$schemaRef"] = self.schema_ref("https://eddn.edcd.io/schemas/fcmaterials/1")
            eddn["message"] = message
        elif event_type == "fssallbodiesfound":
            # cross check the star system data
            if not (
                self.check_system_address(journal, event)
                and self.check_system_name(journal, event)
            ):
                return False
            message = {
                "event": "FSSallBodiesFound",
                "horizons": journal.state["Horizons"],
                "odyssey": journal.state["Odyssey"],
                "StarPos": journal.state["StarPos"],
                **self.pick_keys(event, "timestamp", "SystemName", "SystemAddress", "Count")
            }
            eddn["$schemaRef"] = self.schema_ref("https://eddn.edcd.io/schemas/fssallbodiesfound/1")
            eddn["message"] = message
        elif event_type == "fssbodysignals":
            if not self.check_system_address(journal, event):
                return False
            message = {
                "event": "FSSBodySignals",
                "horizons": journal.state["Horizons"],
                "odyssey": journal.state["Odyssey"],
                **self.pick_keys(event, "timestamp", "BodyName", "BodyID", "SystemAddress","Signals")
            }
            eddn["$schemaRef"] = self.schema_ref("https://eddn.edcd.io/schemas/fssbodysignals/1")
            eddn["message"] = message
        elif event_type == "navbeaconscan":
            if not self.check_system_address(journal, event):
                return False
            message = {
                "event": "NavBeaconScan",
                "horizons": journal.state["Horizons"],
                "odyssey": journal.state["Odyssey"],
                "StarPos": journal.state["StarPos"],
                "StarSystem": journal.state["StarSystem"],
                **self.pick_keys(event, "timestamp", "SystemAddress", "NumBodies")
            }
            eddn["$schemaRef"] = self.schema_ref("https://eddn.edcd.io/schemas/navbeaconscan/1")
            eddn["message"] = message
        elif event_type == "navroute":
            message = {
                "event": "NavRoute",
                "horizons": journal.state["Horizons"],
                "odyssey": journal.state["Odyssey"],
                **self.pick_keys(event, "timestamp", "Route")
            }
            eddn["$schemaRef"] = self.schema_ref("https://eddn.edcd.io/schemas/navroute/1")
            eddn["message"] = message
        elif event_type == "outfitting":
            message = {
                "systemName": event["StarSystem"],
                "stationName": event["StationName"],
                "marketId": event["MarketID"],
                "horizons": journal.state["Horizons"],
                "odyssey": journal.state["Odyssey"],
                "timestamp": event["timestamp"],
                "modules": [
                    x["Name"] for x in event["Items"] if re.search(self._RE_OUTFITTING_ITEMS, x["Name"], re.IGNORECASE)
                ]
            }
            eddn["$schemaRef"] = self.schema_ref("https://eddn.edcd.io/schemas/outfitting/2")
            eddn["message"] = message
        elif event_type == "scanbarycentre":
            if not (
                self.check_system_address(journal, event)
                and self.check_system_name(journal, event)
            ):
                return None
            message = {
                "event": "ScanBaryCentre",
                "horizons": journal.state["Horizons"],
                "odyssey": journal.state["Odyssey"],
                "StarPos": journal.state["StarPos"],
                **self.pick_keys(event, "timestamp", "StarSystem", "SystemAddress", "BodyID", "SemiMajorAxis", "Eccentricity", "OrbitalInclination", "Periapsis", "OrbitalPeriod", "AscendingNode", "MeanAnomaly")
            }
            eddn["$schemaRef"] = self.schema_ref("https://eddn.edcd.io/schemas/scanbarycentre/1")
            eddn["message"] = message
        elif event_type == "shipyard":
            message = {
                "timestamp": event["timestamp"],
                "systemName": event["StarSystem"],
                "stationName": event["StationName"],
                "marketId": event["MarketID"],
                "horizons": journal.state["Horizons"],
                "odyssey": journal.state["Odyssey"],
                "allowCobraMkIV": event["AllowCobraMkIV"],
                "ships": [
                    x["ShipType"] for x in event["PriceList"]
                ]
            }
            eddn["$schemaRef"] = self.schema_ref("https://eddn.edcd.io/schemas/shipyard/2")
            eddn["message"] = message
        else:
            return False

        return True

    def __fss_signals(self, journal: Journal, event: JournalEvent) -> Tuple[dict | None, bool]:
        event_type = event["event"].lower()
        if event_type == "fsssignaldiscovered":
            if self.signal_list is None:
                self.fss_signals = True
                self.signal_list = [event]
            else:
                self.signal_list.append(event)
        else:
            self.fss_signals = False
            if len(self.signal_list) == 0:
                self.signal_list = None
                return None, True
            message = {
                "timestamp": self.fss_signals[0]["timestamp"],
                "event": "FSSSignalDiscovered",
                "horizons": journal.state["Horizons"],
                "odyssey": journal.state["Odyssey"],
                "SystemAddress": journal.state["SystemAddress"],
                "StarSystem": journal.state["StarSystem"],
                "StarPos": journal.state["StarPos"],
                "signals": [
                    {
                        **self.pick_keys(x, "timestamp","SignalName","SignalType", "IsStation", "USSType", "SpawningState", "SpawningFaction", "SpawningPower", "OpposingPower", "ThreatLevel")
                    }
                    for x in self.signal_list if x["SystemAddress"] == journal.state["SystemAddress"] and x["USSType"] != "USS_Type_MissionTarget;"
                ]
            }
            if len(message["signals"]) == 0:
                return None, True
            return message, True
        return None, False

    async def process(self, journal: Journal, event: JournalEvent) -> None:
        if "event" not in event:
            logger.error(f"Event missing from {event}")
            return

        event_type = event["event"].lower()

        event = self.deep_pattern_removal(event, ["_Localised$"])

        eddn = {
            "$schemaRef": "",
            "header": {
                "uploaderID": journal.cmdr,
                "gameversion": journal.state["GameVersion"],
                "gamebuild": journal.state["GameBuild"],
                "softwareName": "Vase EDDN Plugin",
                "softwareVersion": appversion(),
            },
            "message": {},
        }

        if event_type == "fsssignaldiscovered" or self.fss_signals:
            message, leftover = self.__fss_signals(journal, event)
            if message is not None:
                eddn["$schemaRef"] = self.schema_ref("https://eddn.edcd.io/schemas/fsssignaldiscovered/1")
                eddn["message"] = message
                await self.post_message(eddn)
            if not leftover:
                return
        if self.__process_event(journal, event):
            await self.post_message(eddn)
