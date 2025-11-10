import asyncio
import logging
import os
import pathlib
from os.path import isdir
from pathlib import Path
from time import mktime, strptime
from typing import AsyncGenerator, Tuple, MutableMapping, Any
from datetime import date

import anyio
from anyio import AsyncFile
from watchfiles import Change, awatch

from vase import api
from vase.journal.base import BaseJournal, IJournal

logger = logging.getLogger("journal.multi")


class JournalSession(BaseJournal):
    loghandle: AsyncFile | None
    logfile: pathlib.Path
    session: int
    part: int
    log_pos: int
    replay: bool
    game_was_running: bool
    first_read: bool

    def __init__(self, session: int, logfile: pathlib.Path):
        super().__init__()
        self.logfile = logfile
        self.loghandle = None
        self.session = session
        self.part = 1
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
            logger.debug(f"Invalid journal entry:\n{line!r}\n", exc_info=e)
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
    fids: dict[int, JournalSession]
    sessions: dict[int, JournalSession]

    pending: dict[Path, JournalSession]

    journal_dir: pathlib.Path

    def __init__(self, journal_dir: pathlib.Path):
        self.journal_dir = journal_dir
        self.fids = set()
        self.journals = {}
        self.pending_journals = []

    @staticmethod
    def parse_journal(name: str) -> Tuple[int, int] | None:
        if m := BaseJournal.RE_LOGFILE.search(name):
            start = int(mktime(strptime(m.group(1), "%Y-%m-%dT%H%M%S")))
            part = int(m.group(2))
            return start, part
        return None

    @staticmethod
    def latest_journals(journal_dir: pathlib.Path) -> list[tuple[int, pathlib.Path]]:
        today = date.today().strftime("%Y-%m-%d")
        results: list[tuple[int, pathlib.Path]] = []

        try:
            for name in os.listdir(journal_dir):
                if (
                    parsed := MultiJournal.parse_journal(name)
                ) is None or today not in name:
                    continue

                start, part = parsed

                path = journal_dir / name
                results.append((start, path))

        except (OSError, AttributeError, TypeError):
            logger.exception("failed to find journals")
            return []

        # Sort by session_start descending
        return sorted(results, key=lambda t: t[0], reverse=True)

    async def handle_new(self, path: pathlib.Path):
        if (parsed := MultiJournal.parse_journal(path.name)) is None:
            return
        session, part = parsed
        if journal := self.sessions.get(session):
            if journal.part >= part:
                return
            oldpath = journal.logfile
            del self.journals[oldpath]
            await self.sessions[session].reopen(path)
            self.journals[journal.logfile] = journal
        else:
            journal = JournalSession(path)
            self.journals[journal.logfile] = journal
            self.sessions[session] = journal
            self.pending_journals.append(journal)

    async def events(
        self,
    ) -> AsyncGenerator[Tuple[api.Journal, MutableMapping[str, Any]], None]:
        if not isdir(self.journal_dir):
            logger.error(f"{self.journal_dir} is not a directory")
            return

        journals = await asyncio.gather(
            *(JournalSession.create(i) for i in self.latest_journals(self.journal_dir))
        )
        for x in journals:
            if x.fid is None:
                self.pending_journals[x.logfile] = x
            if x.fid not in self.fids:
                self.journals[x.logfile] = x
                self.sessions[x.session] = x
                self.fids.add(x.fid)

        async for events in awatch(self.journal_dir):
            written = []
            for event, file in events:
                path = pathlib.Path(file)
                name = path
                if event == Change.added:
                    if path not in self.journals:
                        await self.handle_new(path)
                elif event == Change.modified:
                    if path in self.journals:
                        written.append(self.journals[path])
