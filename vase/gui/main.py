import asyncio
from tkinter import ttk
import tkinter as tk
from ttkbootstrap import constants

from vase.api.helpers import after_idle
from vase.api.processor import GuiConfigurable
from vase.config import Config, config

from ctypes import windll

from vase.gui.configure import JournalConfigApp

windll.shcore.SetProcessDpiAwareness(1)


class InfoFrame(ttk.Labelframe):
    cmdr: ttk.Label
    ship: ttk.Label
    location: ttk.Label

    def __init__(
        self,
        parent,
        cmdr: str,
        ship: str | None = None,
        location: dict[str, str] | None = None,
        *args,
        **kwargs,
    ):
        super().__init__(parent, *args, **kwargs)
        self.config(text="Status")
        self.cmdr = ttk.Label(self, text=f"Cmdr: {cmdr}")
        self.ship = ttk.Label(self, text=f"Ship: {ship or '<unknown>'}")
        self.location = ttk.Label(
            self, text=f"Location: {self.format_location(location or {})}"
        )
        self.cmdr.pack(padx=5, anchor=constants.W, side=constants.TOP)
        self.ship.pack(padx=5, anchor=constants.W, side=constants.TOP)
        self.location.pack(padx=5, anchor=constants.W, side=constants.TOP)

    @staticmethod
    def format_location(location: dict[str, str] | None) -> str:
        if not location or "system" not in location:
            return "<unknown>"

        parts = []

        # Always show system
        parts.append(f"  ├─ System: {location['system']}")

        # Optional fields
        if "body" in location:
            parts.append(f"  ├─ Body: {location['body']}")
        if "station" in location:
            parts.append(f"  └─ Station: {location['station']}")
        else:
            # If there's no station but body exists, fix the last prefix:
            if parts[-1].startswith("  ├─"):
                parts[-1] = parts[-1].replace("├", "└", 1)

        return "\n" + "\n".join(parts)

    def update_cmdr(self, ship: str | None, location: dict[str, str] | None) -> None:
        self.ship.config(text=f"Ship: {ship or '<unknown>'}")
        self.location.config(text=f"Location: {self.format_location(location or {})}")


class Window(tk.Tk):
    cmdr_frames: dict[str, InfoFrame] = {}
    conf: Config
    configurables: list[GuiConfigurable]
    loop: asyncio.AbstractEventLoop | None = None

    def __init__(self, config, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.configurables = []
        self.conf = config
        self.menubar = tk.Menu(self)

        config_menu = tk.Menu(self.menubar, tearoff=0)
        config_menu.add_command(
            label="Journal Settings...", command=self.open_journal_config
        )
        self.menubar.add_cascade(label="Config", menu=config_menu)

        self.config(menu=self.menubar)
        self.notebook = ttk.Notebook(self)
        self.notebook.pack(fill="both", expand=True)

    def open_journal_config(self):
        # Open as independent window
        config_window = JournalConfigApp(self.conf, self.configurables, self.loop)
        config_window.grab_set()  # Modal (optional)
        self.wait_window(config_window)
        self.conf.save()

    @after_idle()
    def update_cmdr(
        self, cmdr: str, ship: str | None = None, location: dict[str, str] | None = None
    ):
        # 1. Remove placeholder if we now have real data
        if cmdr != "unknown" and "unknown" in self.cmdr_frames:
            unknown_frame = self.cmdr_frames.pop("unknown")
            self.notebook.forget(unknown_frame)  # remove tab from notebook

        # 2. Create frame if new commander
        if cmdr not in self.cmdr_frames:
            frame = InfoFrame(self, cmdr, ship, location)
            self.cmdr_frames[cmdr] = frame
            self.notebook.add(frame, text=cmdr)
            return

        # 3. Update existing commander frame
        self.cmdr_frames[cmdr].update_cmdr(ship, location)

    def post_init(self, loop: asyncio.AbstractEventLoop, processors: list):
        self.loop = loop
        self.configurables = [x for x in processors if isinstance(x, GuiConfigurable)]


def setup(config) -> Window:
    window = Window(config)
    window.title("Vase")
    window.update_cmdr("unknown")
    # window.geometry("300x200")

    return window


if __name__ == "__main__":
    window = setup(config)
    window.mainloop()
