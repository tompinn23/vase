from abc import ABC, abstractmethod, abstractproperty
from typing import MutableMapping, Any

from vase.monitor import EDLogs


class Processor(ABC):

    @property
    @abstractmethod
    def name(self) -> str:
        return "GenericProcessor"

    @abstractmethod
    async def process(self, journal: EDLogs, entry: MutableMapping[str, Any] | None) -> None:
        pass