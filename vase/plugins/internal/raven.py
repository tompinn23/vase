import tkinter as tk
import webbrowser
from tkinter import ttk

from vase.api import Config, Journal, JournalEvent, Processor, GuiConfigurable
from vase.api.helpers import AsyncFrame, Debouncer, after_idle


class RavenGui:
    def __init__(self, config: Config, frame: AsyncFrame):
        self.frame = frame
        debouncer = Debouncer(self.frame)
        api_key_var = tk.StringVar(self.frame)

        link_frame = ttk.Frame(self.frame)
        link_frame.grid(row=0, column=0, columnspan=2, sticky="w")

        ttk.Label(link_frame, text="Get your API key at: ").pack(side="left")

        link = ttk.Label(
            link_frame,
            text="https://ravencolonial.com/user",
            foreground="blue",
            cursor="hand2",
            underline=True,
        )
        link.bind(
            "<Button-1>",
            lambda e: webbrowser.open_new_tab("https://ravencolonial.com/user"),
        )
        link.pack(side="left")

        def on_api_key_change(*args):
            debouncer.call(self.frame.call_async(self.fetch_user(api_key_var.get())))

        api_key_var.trace_add("write", on_api_key_change)

        ttk.Label(frame, text="API Key:").grid(row=1, column=0, sticky="w")
        key_entry = ttk.Entry(frame, textvariable=api_key_var, width=40)
        key_entry.grid(row=1, column=1, padx=(5, 5))

        self.username_label = ttk.Label(frame, text="Username: (none yet)")
        self.username_label.grid(
            row=2, column=0, columnspan=3, pady=(10, 0), sticky="w"
        )

    @after_idle("frame")
    def update_user(self, username: str):
        self.username_label.config(text=username)

    async def fetch_user(self, token: str):
        pass


class RavenProcessor(Processor, GuiConfigurable):
    def __init__(self):
        self.debouncer = None
        self.api_key_var = None

    @property
    def internal_name(self) -> str:
        return "raven"

    @property
    def name(self) -> str:
        return "Raven Colonial"

    async def setup(self, config: Config) -> bool:
        if not config.get("enabled", default=True):
            return False
        return True

    async def process(self, journal: Journal, entry: JournalEvent) -> None:
        pass

    def configure(self, config: Config, frame: AsyncFrame) -> None:
        RavenGui(config, frame)

    async def configured(self, config: Config) -> None:
        pass


def load() -> Processor:
    return RavenProcessor()
