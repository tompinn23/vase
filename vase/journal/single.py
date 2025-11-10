import os
import pathlib
from collections.abc import AsyncGenerator, MutableMapping
from os.path import isdir
from time import strftime, gmtime
from typing import Any, Tuple

import anyio
from anyio import AsyncFile
from watchfiles import Change, awatch


from .base import BaseJournal, IJournal

import logging

from vase import api

logger = logging.getLogger("journal.single")

class SingleJournal(BaseJournal, IJournal):

    def newest_journal(self, journals_dir: pathlib.Path) -> str | None:
        try:
            files = [
                journals_dir / x
                for x in os.listdir(journals_dir)
                if self.RE_LOGFILE.search(x)
            ]
        except (OSError, AttributeError, TypeError) as e:
            logger.exception(f"Failed to find latest journal in {journals_dir} {e}")
            return None

        if not files:
            return None

        return str(max(files))

    def watch_filter(self, change: Change, path: str) -> bool:
        if change == Change.modified and path == self.logfile:
            return True
        elif change == Change.added:
            return True
        return False

    async def start(self) -> AsyncGenerator[Tuple[api.Journal, MutableMapping[str, Any]], None]:
        if not isdir(self.journal_dir):
            logger.error(f"{self.journal_dir} is not a directory")
            return

        self.logfile = self.newest_journal(self.journal_dir)

        logger.debug(f"Started journal at {self.logfile}")
        log_pos = -1
        if self.logfile:
            loghandle: AsyncFile | None = await anyio.open_file(self.logfile, "rb", 0)
            self.replay = True
            async for line in loghandle:
                try:
                    if b'"event":"Location"' in line:
                        logger.debug('"Location" event in the past')
                    await self.parse_entry(line)
                except Exception as e:
                    logger.debug(f"Invalid journal entry:\n{line!r}\n", exc_info=e)

            navroute = await self.__read_navroute()
            if navroute is not None:
                self._state["NavRoute"] = navroute

            self.replay = False
            log_pos = await loghandle.tell()
        else:
            loghandle = None

        logger.debug("End of latest journal")

        self.game_was_running = self.game_running()

        if self.live:
            if self.game_was_running:
                logger.info(
                    "Game is/was running, synthesizing StartUp event for plugins"
                )
                entry = self.synthesize_startup_event()
                yield self, entry
            else:
                yield self, {}
                self.live = False

        async for events in awatch(self.journal_dir, stop_event=self.stop_event):
            for event, file in events:
                name = pathlib.Path(file).name
                if event == Change.added and self.RE_LOGFILE.search(name):
                    if file != self.logfile:  # sanity check
                        logger.info(f"New journal file: {file} was {self.logfile}")
                        self.logfile = file
                        if loghandle:
                            await loghandle.aclose()
                        loghandle = await anyio.open_file(self.logfile, "rb", 0)
                        log_pos = 0
                if event == Change.modified and file == self.logfile:
                    await loghandle.seek(log_pos, os.SEEK_SET)
                    async for line in loghandle:
                        if b'"event":"Continue"' in line:
                            logger.debug(
                                "Found a Continue event, its being added to the list, "
                                "we will finish this file up and then continue with the next"
                            )
                        try:
                            yield self, await self.parse_entry(line)
                        except Exception as e:
                            logger.debug(
                                f"Invalid journal entry:\n{line!r}\n", exc_info=e
                            )
                    log_pos = await loghandle.tell()
                if event in (Change.modified, Change.added) and name == "Status.json" and self.capture_status:
                    await self.process_status()
                    yield self, self.status
                if event in (Change.added, Change.modified) and name == "Outfitting.json":
                    entry = await self.__read_outfitting()
                    if entry is not None:
                        yield self, entry
                if event in (Change.added, Change.modified) and name == "NavRoute.json":
                    entry = await self.__read_navroute()
                    if entry is not None:
                        yield self, entry
                if event in (Change.added, Change.modified) and name == "Market.json":
                    entry = await self.__read_market()
                    if entry is not None:
                        yield self, entry
                if (
                        event in (Change.added, Change.modified)
                        and name == "FCMaterials.json"
                ):
                    entry = await self.__read_fcmaterials()
                    if entry is not None:
                        yield self, entry
                if event in (Change.added, Change.modified) and name == "Shipyard.json":
                    entry = await self.__read_shipyard()
                    if entry is not None:
                        yield self, entry
        if self.game_was_running:
            if not self.game_running():
                logger.info("Detected exit from game, synthesising ShutDown event")
                timestamp = strftime("%Y-%m-%dT%H:%M:%SZ", gmtime())
                yield self, {"timestamp": timestamp, "event": "ShutDown"}