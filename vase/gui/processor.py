import pathlib

from vase.api import Journal, JournalEvent, Processor
from vase.config import Config
from vase.gui.main import Window


class GuiProcessor(Processor):
    window: Window

    def __init__(self, window: Window):
        self.window = window

    @property
    def internal_name(self) -> str:
        return "vase_gui"

    @property
    def name(self) -> str:
        return "Vase GUI"

    async def setup(self, config: Config) -> bool:
        return True

    async def process(self, journal: Journal, entry: JournalEvent) -> None:
        event = entry["event"].lower()
        # status updating events

        if event in ["commander", "loadgame", "startup"]:
            journals = self.window.conf.get_journals()
            if "<unknown>" in [x["name"] for x in journals]:
                for x in journals:
                    if pathlib.Path(x["path"]) == journal.directory:
                        x["name"] = journal.cmdr
                self.window.conf.set_journals(journals)
        if event in [
            "loadgame",
            "location",
            "fsdjump",
            "docked",
            "undocked",
            "approachbody",
            "startup",
            "leavebody",
            "carrierjump",
        ]:
            self.window.update_cmdr(
                journal.cmdr,
                journal.state["ShipType"],
                {
                    "system": journal.state["SystemName"],
                    "body": journal.state["Body"],
                    "station": journal.state["StationName"],
                },
            )
