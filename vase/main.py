import argparse
import asyncio
import os.path
import pathlib
import sys
import threading
from argparse import Namespace

from typing import Iterable
import time

import anyio

from vase import gui
from vase.api import Config
from vase.config import config, appversion
from colorama import Fore, Style, init

import logging

from vase.api.processor import Processor

from vase.gui.processor import GuiProcessor
from vase.journal.base import IJournal
from vase.journal.single import SingleJournal
from vase.loader import load_plugins

init(autoreset=True)  # reset colors automatically after each print
PROGRAM_START = time.monotonic()


class IgnoreRustNotify(logging.Filter):
    def filter(self, record):
        # Return True to allow, False to ignore
        return "rust notify timeout" not in record.getMessage()


class ColoredFormatter(logging.Formatter):
    LEVEL_COLORS = {
        logging.DEBUG: Fore.CYAN,
        logging.INFO: Fore.GREEN,
        logging.WARNING: Fore.YELLOW,
        logging.ERROR: Fore.RED,
        logging.CRITICAL: Fore.MAGENTA + Style.BRIGHT,
    }

    LEVEL_NAMES = {
        logging.DEBUG: "DEBUG",
        logging.INFO: "INFO",
        logging.WARNING: "WARN",
        logging.ERROR: "ERROR",
    }

    def format(self, record):
        # Let base class build full message (including exceptions)
        super().format(record)

        # Time formatting
        elapsed = time.monotonic() - PROGRAM_START
        seconds = int(elapsed)
        millis = int((elapsed - seconds) * 1000)
        hours, remainder = divmod(seconds, 3600)
        minutes, seconds = divmod(remainder, 60)
        timestamp = f"{hours:02}:{minutes:02}:{seconds:02}.{millis:03}"

        # Color + level name
        color = self.LEVEL_COLORS.get(record.levelno, "")
        level = self.LEVEL_NAMES.get(record.levelno, record.levelname.upper())
        logger_name = record.name.split(".")[-1]

        # Recombine with formatted message (which already includes exceptions)
        return (
            f"{color}{timestamp} [{level}]{Style.RESET_ALL} "
            f"{logger_name}: {record.getMessage()}"
            f"{'' if record.exc_text is None else '\n' + record.exc_text}"
        )


ch = logging.StreamHandler()
ch.setFormatter(ColoredFormatter())
logging.basicConfig(level=config.get_str("log_level", default="DEBUG"), handlers=[ch])


watchfiles_logger = logging.getLogger("watchfiles.main")
watchfiles_logger.addFilter(IgnoreRustNotify())
watchfiles_logger.setLevel(logging.WARNING)
logging.getLogger("httpx").setLevel(logging.WARNING)


async def loop(
    window: gui.Window, processors: list[Processor], journals: Iterable[IJournal]
):
    send, recv = anyio.create_memory_object_stream(0)
    tasks = anyio.Semaphore(100)

    async def pump(journal: IJournal):
        async for event in journal.events():
            await send.send(event)

    async def safe_call(processor: Processor, journal, event):
        async with tasks:
            try:
                await processor.process(journal, event)
            except Exception:
                logging.debug(f"Processor {processor.name} failed", exc_info=True)

    async with anyio.create_task_group() as tg:
        async with send:
            for journal in journals:
                tg.start_soon(pump, journal)

            async for journal, event in recv:
                logging.debug(f"event received: {journal.cmdr} {event}")
                for p in processors:
                    tg.start_soon(safe_call, p, journal, event)


async def main(window: gui.Window, args: Namespace):
    logging.info(f"starting vase {appversion()} Python {sys.version}")

    processors = load_plugins()

    journals = []
    for x in config.get_journals():
        path = pathlib.Path(x["path"])
        if not os.path.exists(path):
            logging.error(f'journal directory "{x}" does not exist')
        j = SingleJournal(path)
        journals.append(j)

    async def safe_load(proc: Processor, success: list[Processor]):
        if await proc.setup(Config(config.config, proc.internal_name)):
            success.append(proc)
        else:
            logging.debug(f"Processor: {proc.name} is not enabled")

    enabled = [GuiProcessor(window)]
    try:
        async with anyio.create_task_group() as tg:
            for x in processors:
                tg.start_soon(safe_load, x, enabled)
    except* Exception as eg:
        for ex in eg.exceptions:
            logging.error(
                f"Exception initializing plugin {type(ex)}, {ex}", exc_info=True
            )

    window.post_init(asyncio.get_event_loop(), enabled)
    logging.info(
        f"starting vase with the following event processors: {[x.name for x in enabled]}"
    )

    try:
        await loop(window, enabled, journals)
    except asyncio.CancelledError:
        pass


if __name__ == "__main__":
    try:
        parser = argparse.ArgumentParser(
            prog="vase",
            description="Vase collects Multiple Elite Dangerous Journal Files",
        )
        parser.add_argument(
            "-d", "--debug", action="store_true", help="Enable debug mode"
        )
        parser.add_argument(
            "-s",
            "--save",
            action="store_true",
            help="Persist this config into the configuration file",
        )

        window = gui.main.setup(config)

        def run():
            asyncio.run(main(window, parser.parse_args()))

        threading.Thread(target=run, daemon=True).start()

        window.mainloop()

    except KeyboardInterrupt:
        pass
