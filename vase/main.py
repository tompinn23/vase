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
from vase.journal.base import IJournal
from vase.journal.multi import MultiJournal
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


async def loop(processors: list[Processor], journals: Iterable[IJournal]):
    send, recv = anyio.create_memory_object_stream(0)

    async def pump(journal: IJournal):
        async for event in journal.events():
            await send.send(event)

    async def safe_call(processor: Processor, journal, event):
        try:
            await processor.process(journal, event)
        except Exception as e:
            logging.exception(f"Processor {processor.name} failed: {type(e)} {e}")

    async with anyio.create_task_group() as tg:
        for journal in journals:
            tg.start_soon(pump, journal)

        async for journal, event in recv:
            logging.debug(f"event received: {journal.cmdr} {event}")
            for p in processors:
                tg.start_soon(safe_call, p, journal, event)

        await send.aclose()

        # for i, result in enumerate(results):
        #     if isinstance(result, Exception):
        #         logging.error(f"Exception in processor \"{processors[i].name}\" ex:{result}")


async def main(args: Namespace):
    logging.info(f"starting vase {appversion()} Python {sys.version}")

    processors = load_plugins()

    gui.bridge.set_async_loop(asyncio.get_event_loop())

    journals = []
    for x in args.journals:
        logging.info(f"loading journal {x}")
        if not os.path.exists(x):
            logging.error(f'journal directory "{x}" does not exist')
            continue
        j = MultiJournal(x)
        journals.append(j)

    async def safe_load(proc: Processor, success: list[Processor]):
        if await proc.setup(Config(config.config, proc.internal_name)):
            success.append(proc)
        else:
            logging.debug(f"Processor: {proc.name} is not enabled")

    success = []
    try:
        async with anyio.create_task_group() as tg:
            for x in processors:
                tg.start_soon(safe_load, x, success)
    except* Exception as eg:
        for ex in eg.exceptions:
            logging.error(
                f"Exception initializing plugin {type(ex)}, {ex}", exc_info=True
            )

    config.save()

    logging.info(
        f"starting vase with the following event processors: {[x.name for x in success]}"
    )

    try:
        await loop([], journals)
    except asyncio.CancelledError:
        pass


if __name__ == "__main__":
    try:
        parser = argparse.ArgumentParser(
            prog="vase",
            description="Vase collects Multiple Elite Dangerous Journal Files",
        )
        parser.add_argument(
            "journals",
            type=pathlib.Path,
            nargs="*",
            help="journal locations to process",
            default=[config.default_journal_dir],
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

        def run():
            asyncio.run(main(parser.parse_args()))

        threading.Thread(target=run, daemon=True).start()

        gui.main()

    except KeyboardInterrupt:
        pass
