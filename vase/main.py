import argparse
import asyncio
import os.path
import pathlib
import sys
from argparse import Namespace

from typing import Iterable, MutableMapping, Any, Tuple
import time

import anyio

from vase.api import Config
from vase.config import config, appversion
from colorama import Fore, Style, init

import logging

from vase.journal import Journal
from vase.api.processor import Processor
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

    # Logback-style pattern: "%d{HH:mm:ss.SSS} [%thread] %-5level %logger{36} - %msg%n"
    default_pattern = (
        "{color}[{levelname}]{Style.RESET_ALL} {timestamp} {logger_name}: {msg}"
    )

    def __init__(self, fmt=None, datefmt="%H:%M:%S", style="{"):
        super().__init__(fmt or self.default_pattern, datefmt=datefmt, style=style)

    def format(self, record):
        elapsed = time.monotonic() - PROGRAM_START
        seconds = int(elapsed)
        millis = int((elapsed - seconds) * 1000)
        hours, remainder = divmod(seconds, 3600)
        minutes, seconds = divmod(remainder, 60)
        timestamp = "{:02d}:{:02d}:{:02d}.{:03d}".format(
            hours, minutes, seconds, millis
        )
        logger_name = record.name.split(".")[-1]
        color = self.LEVEL_COLORS.get(record.levelno, "")
        return f"{color}{timestamp} [{self.LEVEL_NAMES.get(record.levelno, record.levelname.upper())}] {logger_name}: {record.getMessage()}"


ch = logging.StreamHandler()
ch.setFormatter(ColoredFormatter())
logging.basicConfig(level=config.get_str("log_level", default="DEBUG"), handlers=[ch])

logging.getLogger("watchfiles.main").addFilter(IgnoreRustNotify())
logging.getLogger("httpx").setLevel(logging.WARNING)


async def loop(processors: list[Processor], journals: Iterable[Journal]):
    send, recv = anyio.create_memory_object_stream(0)

    async def pump(journal: Journal):
        async for event in journal.start():
            await send.send((journal, event))

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

    journals = []
    for x in args.journals:
        logging.info(f"loading journal {x}")
        if not os.path.exists(x):
            logging.error(f'journal director "{x}" does not exist')
            continue
        j = Journal(x)
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
        await loop(success, journals)
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

        asyncio.run(main(parser.parse_args()))
    except KeyboardInterrupt:
        pass
