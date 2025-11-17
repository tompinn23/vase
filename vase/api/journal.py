import pathlib
from typing import Protocol


class Journal(Protocol):
    """
    Journal interface, the internal journal used by vase does provide more information,
    if and when the information is required by a plugin this class will be extended.
    """

    @property
    def directory(self) -> pathlib.Path: ...

    @property
    def cmdr(self) -> str: ...

    @property
    def state(self) -> dict: ...