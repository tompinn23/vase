import asyncio
import tkinter as tk
from tkinter import filedialog, messagebox

from tkinter import ttk
from typing import Iterable

from vase.api import AsyncFrame
from vase.api.processor import GuiConfigurable
from vase.config import Config


class InlineEditableTreeview(ttk.Treeview):
    """A Treeview that supports inline editing on double-click."""

    def __init__(self, master=None, **kwargs):
        super().__init__(master, **kwargs)
        self.editing_entry = None

        self.bind("<Double-1>", self._on_double_click)

    def _on_double_click(self, event):
        # Get column + row clicked
        region = self.identify("region", event.x, event.y)
        if region != "cell":
            return

        row_id = self.identify_row(event.y)
        col_id = self.identify_column(event.x)

        if not row_id:
            return

        # Column index
        col_index = int(col_id.replace("#", "")) - 1

        # Cell bounding box
        x, y, width, height = self.bbox(row_id, col_id)

        # Current value
        old_value = self.item(row_id, "values")[col_index]

        # If editing journal_path: open file dialog instead
        if col_index == 1:
            new_folder = filedialog.askdirectory(initialdir=old_value)
            if new_folder:
                values = list(self.item(row_id, "values"))
                values[col_index] = new_folder
                self.item(row_id, values=values)
            return

        # Create entry widget for editing
        self.editing_entry = tk.Entry(self, bd=1)
        self.editing_entry.place(x=x, y=y, width=width, height=height)
        self.editing_entry.insert(0, old_value)
        self.editing_entry.focus()

        # When confirmed
        def confirm_edit(event=None):
            new_value = self.editing_entry.get()
            values = list(self.item(row_id, "values"))
            values[col_index] = new_value
            self.item(row_id, values=values)
            self.editing_entry.destroy()
            self.editing_entry = None

        # Cancel
        def cancel_edit(event=None):
            self.editing_entry.destroy()
            self.editing_entry = None

        self.editing_entry.bind("<Return>", confirm_edit)
        self.editing_entry.bind("<Escape>", cancel_edit)
        self.editing_entry.bind("<FocusOut>", confirm_edit)


class JournalLocations(tk.Frame):
    def __init__(self, config: Config, master=None, **kwargs):
        super().__init__(master, **kwargs)
        self.conf = config

        # --- Table setup ---
        columns = ("commander", "journal_path")
        self.tree = InlineEditableTreeview(self, columns=columns, show="headings")
        self.tree.heading("commander", text="Commander")
        self.tree.heading("journal_path", text="Journal Path")

        self.tree.column("commander", width=180, anchor="w")
        self.tree.column("journal_path", width=480, anchor="w")

        for x in self.conf.get_journals():
            name = x["name"]
            path = x["path"]
            self.tree.insert("", tk.END, values=(name, path))

        self.tree.pack(fill="both", expand=True, pady=10)

        # --- Buttons ---
        button_frame = ttk.Frame(self)
        button_frame.pack(fill="x")

        ttk.Button(button_frame, text="Add", command=self.add_entry).pack(
            side="left", padx=5, pady=5
        )
        ttk.Button(button_frame, text="Remove", command=self.remove_entry).pack(
            side="left", padx=5, pady=5
        )
        ttk.Button(button_frame, text="Apply", command=self.save_config).pack(
            side="right", padx=5, pady=5
        )

    # ----------------------------------------
    def add_entry(self):
        commander = "<unknown>"
        folder = filedialog.askdirectory(title="Select Journal Folder")
        if not folder:
            return
        self.tree.insert("", tk.END, values=(commander, folder))

    # ----------------------------------------
    def remove_entry(self):
        for item in self.tree.selection():
            self.tree.delete(item)

    # ----------------------------------------
    def save_config(self):
        data = []
        for row in self.tree.get_children():
            commander, path = self.tree.item(row, "values")
            data.append({"name": commander, "path": path})

        if not data:
            messagebox.showerror("Error", "No entries to save.")
            return

        self.conf.set_journals(data)
        self.conf.save()


class _AFrame(AsyncFrame):
    def __init__(self, loop: asyncio.AbstractEventLoop, master=None, **kwargs):
        super().__init__(master, **kwargs)
        self.loop = loop

    def call_async(self, coro):
        self.loop.call_soon_threadsafe(asyncio.create_task, coro)


class JournalConfigApp(tk.Tk):
    def __init__(
        self,
        config: Config,
        configurables: Iterable[GuiConfigurable],
        loop: asyncio.AbstractEventLoop,
    ):
        super().__init__()
        self.conf = config
        self.title("Elite Dangerous Journal Configuration")
        self.geometry("700x350")

        self.tabs = ttk.Notebook(self)
        self.tabs.pack(fill="both", expand=True)

        self.tabs.add(JournalLocations(config, self.tabs), text="General")
        for configurable in configurables:
            frame = _AFrame(loop, self.tabs)
            configurable.configure(config, frame)
            self.tabs.add(frame, text=configurable.name)
