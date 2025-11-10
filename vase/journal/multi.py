import logging
import os
import pathlib
from os.path import isdir
from pathlib import Path
from typing import AsyncGenerator, Tuple, MutableMapping, Any
from datetime import date

import anyio
from anyio import AsyncFile
from watchfiles import awatch

from vase import api
from vase.journal.base import BaseJournal, IJournal

logger = logging.getLogger("journal.multi")


class JournalSession(BaseJournal):
    loghandle: AsyncFile | None
    logfile: pathlib.Path
    log_pos: int
    replay: bool
    game_was_running: bool
    first_read: bool


    def __init__(self, logfile: pathlib.Path):
        super().__init__()
        self.logfile = logfile
        self.loghandle = None
        self.log_pos = -1
        self.replay = True
        self.game_was_running = False
        self.first_read = True

    async def open(self) -> MutableMapping[str, Any] | None:
        self.loghandle = await anyio.open_file(self.logfile, "rb", 0)
        self.replay = True
        async for line in self.loghandle:
            try:
                await self.parse_entry(line)
            except Exception as e:
                logger.debug(f"Invalid journal entry:\n{line!r}\n", exc_info=e)

        self.replay = False
        self.log_pos = await self.loghandle.tell()
        self.game_was_running = self.game_running()
        if self.live:
            if self.game_was_running:
                logger.info("Game is/was running, synthesizing StartUp event")
                entry = self.synthesize_startup_event()
                return entry
            else:
                self.live = False
                return None
        return None

    async def read(self) -> MutableMapping[str, Any] | None:
        if self.first_read:
            if self.live:
                if self.game_was_running:
                    logger.info("Game is/was running, synthesizing StartUp event")
                    entry = self.synthesize_startup_event()
                    return entry
                else:
                    self.live = False
                    return None
        self.first_read = False
        line = await self.loghandle.readline()
        try:
            return await self.parse_entry(line)
        except Exception as e:
            logger.debug(
                f"Invalid journal entry:\n{line!r}\n", exc_info=e
            )
        return None

    @property
    def fid(self) -> int:
        return self.state["FID"]

    @classmethod
    async def create(cls, logfile: pathlib.Path):
        obj = cls(logfile)
        await obj.open()
        return obj



class MultiJournal(IJournal):

    journals: dict[Path, JournalSession]
    journal_dir: pathlib.Path

    def __init__(self, journal_dir: pathlib.Path):
        self.journal_dir = journal_dir
        self.journals = {}
        self.pending_journals = []

    @staticmethod
    def latest_journals(journal_dir: pathlib.Path) -> list[Path] | None:
        today = date.today().strftime("%Y-%m-%d")
        try:
            files = [
                journal_dir / x
                for x in os.listdir(journal_dir)
                if BaseJournal.RE_LOGFILE.search(x) and today in x
            ]
        except (OSError, AttributeError, TypeError) as e:
            logger.exception(f"failed to find journals {e}")
            return None
        return files

    async def events(self) -> AsyncGenerator[Tuple[api.Journal, MutableMapping[str, Any]], None]:
        if not isdir(self.journal_dir):
            logger.error(f"{self.journal_dir} is not a directory")
            return

        journals = [await JournalSession.create(i) for i in self.latest_journals(self.journal_dir)]
        for x in journals:
            self.journals[x.logfile] = x

        async for events in awatch(self.journal_dir):
            for event, file in events:
                





