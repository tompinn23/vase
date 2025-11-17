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
from vase.journal import Journal
from vase.journal.base import JournalSource
from vase.journal.multiplex import JournalMultiplexer
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
    window: gui.Window, processors: list[Processor], journal: JournalSource
):
    tasks = anyio.Semaphore(100)
    async def safe_call(processor: Processor, journal, event):
        try:
            await processor.process(journal, event)
        except Exception:
            logging.debug(f"Processor {processor.name} failed", exc_info=True)

    async with anyio.create_task_group() as tg:
        async for journal, event in journal.events():
            logging.debug(f"event received: {journal.cmdr} {event}")
            for p in processors:
                async with tasks:
                    tg.start_soon(safe_call, p, journal, event)


async def main(window: gui.Window, args: Namespace):
    logging.info(f"starting vase {appversion()} Python {sys.version}")

    processors = load_plugins()

    journals = []
    for x in config.get_journals():
        path = pathlib.Path(x["path"])
        if not os.path.exists(path):
            logging.error(f'journal directory "{x}" does not exist')
        j = Journal(path)
        journals.append(j)
    journal: JournalSource
    if len(journals) == 1:
        journal = journals[0]
    elif len(journals) > 1:
        journal = JournalMultiplexer(journals)
    else:
        raise RuntimeError("No journals specified")


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
    config.save()

    window.post_init(asyncio.get_event_loop(), enabled)
    logging.info(
        f"starting vase with the following event processors: {[x.name for x in enabled]}"
    )


    try:
        await loop(window, enabled, journal)
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

        threading.Thread(name="Async Worker", target=run, daemon=True).start()

        window.mainloop()

    except KeyboardInterrupt:
        pass
