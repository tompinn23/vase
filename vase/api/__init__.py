from typing import MutableMapping, Any

JournalEvent = MutableMapping[str, Any]

from .journal import Journal
from .processor import Processor

