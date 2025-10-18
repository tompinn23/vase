from abc import ABC, abstractmethod

class Journal(ABC):
    """
    Journal interface, the internal journal used by vase does provide more information,
    if and when the information is required by a plugin this class will be extended.
    """
    @property
    @abstractmethod
    def cmdr(self) -> str:
        pass
