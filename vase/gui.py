import asyncio
import ttkbootstrap as tk

# ==========================
# Tkinter-side bridge
# ==========================


class AsyncTkBridge:
    """Runs in the Tk thread. Exposes thread-safe scheduling for asyncio."""

    def __init__(self, root):
        self.root = root
        self.loop = None  # set by async thread later

    def set_async_loop(self, loop):
        self.loop = loop

    def tk(self, func, *args, **kwargs):
        """Schedule a Tk callback from any thread."""

        def callback():
            func(*args, **kwargs)

        self.root.after(0, callback)

    def run_in_async(self, coro):
        """Schedule a coroutine safely from Tk thread."""
        if not self.loop:
            raise RuntimeError("Async loop not set")
        asyncio.run_coroutine_threadsafe(coro, self.loop)


class Window(tk.Tk):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.bridge = AsyncTkBridge(self)


class AsyncLabel(tk.Label):
    def __init__(self, bridge, master=None, **kwargs):
        super().__init__(master, **kwargs)
        self.bridge = bridge
        self._future = None

    async def update_text(self, text: str):
        self.after_idle(lambda: self.configure(text=text))


# ==========================
# GUI thread code
# ==========================

window: Window = Window()
bridge: AsyncTkBridge = window.bridge


def main():
    window.title("Vase")
    label = tk.Label(window, text="Starting...")
    label.pack(padx=20, pady=20)

    window.mainloop()


if __name__ == "__main__":
    main()
