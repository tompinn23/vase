import asyncio
import logging
import os
import pathlib
from os.path import isdir
from pathlib import Path
from time import mktime, strptime
from typing import AsyncGenerator, Iterable, Tuple, MutableMapping, Any
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
    buffer: list[MutableMapping[str, Any]]

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
        self.buffer = []

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

    async def reopen(self, part: int, path: pathlib.Path):
        if self.loghandle is not None:
            await self.loghandle.aclose()
        self.logfile = path
        self.part = part
        self.loghandle = await anyio.open_file(self.logfile, "rb", 0)
        self.log_pos = 0

    async def read_fid(self) -> str | None:
        if self.first_read:
            if self.live:
                if self.game_was_running:
                    logger.info("Game is/was running, synthesizing StartUp event")
                    entry = self.synthesize_startup_event()
                    self.buffer.append(entry)
                else:
                    self.live = False
            self.first_read = False
        await self.loghandle.seek(self.log_pos)
        async for line in self.loghandle:
            try:
                self.buffer.append(await self.parse_entry(line))
                if self.fid:
                    break
            except Exception as e:
                logger.debug(f"Invalid journal entry:\n{line!r}\n", exc_info=e)
        self.log_pos = await self.loghandle.tell()
        return self.fid

    async def read(self) -> AsyncGenerator[MutableMapping[str, Any]]:
        if self.first_read:
            if self.live:
                if self.game_was_running:
                    logger.info("Game is/was running, synthesizing StartUp event")
                    entry = self.synthesize_startup_event()
                    yield entry
                else:
                    self.live = False
            self.first_read = False
        for item in self.buffer:
            yield item
        self.buffer.clear()
        await self.loghandle.seek(self.log_pos)
        async for line in self.loghandle:
            try:
                yield await self.parse_entry(line)
            except Exception as e:
                logger.debug(f"Invalid journal entry:\n{line!r}\n", exc_info=e)
        self.log_pos = await self.loghandle.tell()
        return

    @property
    def fid(self) -> str | None:
        return self.state["FID"]

    @classmethod
    async def create(cls, session: int, logfile: pathlib.Path):
        obj = cls(session, logfile)
        await obj.open()
        return obj


async def _multiplex(*gens):
    q = asyncio.Queue()

    async def pump(source, gen):
        async for item in gen:
            await q.put((source, item))
        await q.put((source, None))  # signals end for this source

    async with asyncio.TaskGroup() as tg:
        for s, g in gens:
            tg.create_task(pump(s, g))  # source = generator object

    # Collect until all sources have ended
    ended = 0
    total = len(gens)

    while ended < total:
        source, item = await q.get()
        if item is None:
            ended += 1
        else:
            yield source, item


class MultiJournal(IJournal):
    _journals: dict[Path, JournalSession]
    fids: set[str]
    sessions: dict[int, JournalSession]

    pending: dict[Path, JournalSession]

    journal_dir: pathlib.Path

    def __init__(self, journal_dir: pathlib.Path):
        self.journal_dir = journal_dir
        self.fids = set()
        self._journals = {}
        self.sessions = {}
        self.pending = {}

    @property
    def journals(self) -> Iterable[JournalSession]:
        return self._journals.values()

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
                if part == 1:
                    results.append((start, path))

        except (OSError, AttributeError, TypeError):
            logger.exception("failed to find journals")
            return []

        # Sort by session_start descending
        return sorted(results, key=lambda t: t[0], reverse=True)

    async def handle_new(self, path: pathlib.Path):
        parsed = MultiJournal.parse_journal(path.name)
        if parsed is None:
            return

        session, part = parsed

        if session in self.sessions:
            journal = self.sessions[session]

            if journal.part >= part:
                return

            old = journal.logfile
            del self._journals[old]

            await journal.reopen(part, path)
            self._journals[path] = journal
        else:
            journal = await JournalSession.create(session, path)
            journal.part = part

            self.sessions[session] = journal
            self.pending[path] = journal

    async def events(
        self,
    ) -> AsyncGenerator[Tuple[api.Journal, MutableMapping[str, Any]], None]:
        if not isdir(self.journal_dir):
            logger.error(f"{self.journal_dir} is not a directory")
            return

        journals = await asyncio.gather(
            *(
                JournalSession.create(session, path)
                for session, path in self.latest_journals(self.journal_dir)
            )
        )
        for x in journals:
            if x.fid is None:
                self.pending[x.logfile] = x
            elif x.fid not in self.fids:
                self._journals[x.logfile] = x
                self.sessions[x.session] = x
                self.fids.add(x.fid)

        async for events in awatch(self.journal_dir):
            written = []
            for event, file in events:
                path = pathlib.Path(file)
                if event == Change.added:
                    if path not in self._journals:
                        await self.handle_new(path)
                elif event == Change.modified:
                    if path in self._journals:
                        written.append(
                            (self._journals[path], self._journals[path].read())
                        )
                    elif path in self.pending:
                        if fid := await self.pending[path].read_fid():
                            s = self.pending[path]
                            self._journals[path] = s
                            self.sessions[s.session] = s
                            self.fids.add(fid)
                            del self.pending[path]
                            written.append(
                                (self._journals[path], self._journals[path].read())
                            )

            if written:
                async for value in _multiplex(*written):
                    yield value
