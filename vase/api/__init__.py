from typing import MutableMapping, Any

JournalEvent = MutableMapping[str, Any]

from .config import Config
from .journal import Journal
from .processor import Processor, GuiConfigurable

from .helpers import AsyncFrame
