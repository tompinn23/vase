from abc import ABC, abstractmethod

from vase.api import Journal, JournalEvent, Config

import tkinter as tk


class GuiConfigurable(ABC):
    @property
    @abstractmethod
    def name(self) -> str:
        pass

    @abstractmethod
    def configure(self, config: Config, frame: tk.Frame) -> None:
        pass

    @abstractmethod
    async def configured(self, config: Config) -> None:
        """
        Called when the processor is reconfigured via GUI
        :param config:
        :return:
        """
        pass


class Processor(ABC):
    @property
    @abstractmethod
    def internal_name(self) -> str:
        return "generic"

    @property
    @abstractmethod
    def name(self) -> str:
        return "Generic Processor"

    @abstractmethod
    async def setup(self, config: Config) -> bool:
        """
        Perform initialization required before processing events.

        This method is called once when the processor is loaded, before any journal
        entries are handled. Implementations can use it to perform tasks such as:

        - Establishing network connections
        - Loading configuration or state from disk
        - Registering with external APIs
        - Performing warm-up or handshake operations

        This coroutine should raise an exception if initialization fails; the plugin will
        not be loaded by vase if an exception is thrown and the user will be notified
        :returns: True if this plugin should be activated e.g. its activated etc.
        """
        return True

    @abstractmethod
    async def process(self, journal: Journal, entry: JournalEvent) -> None:
        """
        Handle an E:D journal event emitted by any of the journals currently tracked.

        This coroutine is called for each parsed entry from the journal stream,
        in the order events are received. It should perform whatever logic is
        needed to process the event.

        Exceptions should be allowed to propagate they are currently
        just logged and processing continues.

        :param journal: The Journal instance that produced this event.
                        Provides cmdr name may be increased in the future
        :param entry:   The parsed JournalEvent object representing the event schema.
        """
        pass
