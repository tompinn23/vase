import abc
from tkinter import ttk
from functools import wraps


class Debouncer:
    def __init__(self, widget, delay=300):
        self.widget = widget
        self.delay = delay
        self._after_id = None

    def call(self, func):
        # cancel pending callbacks
        if self._after_id is not None:
            self.widget.after_cancel(self._after_id)

        # schedule new one
        self._after_id = self.widget.after(self.delay, func)


class AsyncFrame(abc.ABC, ttk.Frame):
    @abc.abstractmethod
    def call_async(self, coro):
        pass


def after_idle(attr=None):
    def decorator(fn):
        @wraps(fn)
        def wrapper(self, *args, **kwargs):
            widget = getattr(self, attr) if attr else self
            widget.after(0, lambda: fn(self, *args, **kwargs))

        return wrapper

    return decorator
