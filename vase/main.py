import asyncio

from typing import Iterable, MutableMapping, Any, Tuple

from datetime import datetime

import httpx
import time

from vase.auth import AsyncJWTAuth
from vase.config import config
from vase.fleets import FleetProcessor
from vase.monitor import EDLogs
from colorama import Fore, Style, init

import logging

from vase.processor import Processor

init(autoreset=True)  # reset colors automatically after each print
PROGRAM_START = time.monotonic()


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
    default_pattern = "{color}[{levelname}]{Style.RESET_ALL} {timestamp} {logger_name}: {msg}"

    def __init__(self, fmt=None, datefmt="%H:%M:%S", style="{"):
        super().__init__(fmt or self.default_pattern, datefmt=datefmt, style=style)

    def format(self, record):
        elapsed = time.monotonic() - PROGRAM_START
        seconds = int(elapsed)
        millis = int((elapsed - seconds) * 1000)
        hours, remainder = divmod(seconds, 3600)
        minutes, seconds = divmod(remainder, 60)
        timestamp = "{:02d}:{:02d}:{:02d}.{:03d}".format(hours, minutes, seconds, millis)
        logger_name = record.name.split(".")[-1]
        color = self.LEVEL_COLORS.get(record.levelno, "")
        return f"{color}{timestamp} [{self.LEVEL_NAMES.get(record.levelno, record.levelname.upper())}] {logger_name} - {record.threadName}: {record.getMessage()}"


ch = logging.StreamHandler()
ch.setFormatter(ColoredFormatter())
logging.basicConfig(level=config.get_str("logging_level", default="INFO"), handlers=[ch])

auth = AsyncJWTAuth()



async def wait_any_journal(journals: Iterable[EDLogs]) -> Tuple[EDLogs | None, MutableMapping[str, Any] | None]:
    """Wait until any queue has an item, return (queue, item)."""
    # Create a list of pending get() coroutines
    getters = [asyncio.create_task(j.get_entry()) for j in journals]

    # Wait for the first one to complete
    done, pending = await asyncio.wait(getters, return_when=asyncio.FIRST_COMPLETED)

    # Retrieve the result
    done_task = done.pop()
    item = await done_task

    # Cancel remaining unfinished get()s
    for task in pending:
        task.cancel()

    # Figure out which queue this came from
    for q, t in zip(journals, getters):
        if t is done_task:
            return q, item
    return None, None

async def loop(processors: list[Processor], journals: Iterable[EDLogs]):
    while True:
        journal, entry = await wait_any_journal(journals)
        logging.debug(f"{journal.cmdr}, {entry}")
        tasks = [x.process(journal, entry) for x in processors]
        results = await asyncio.gather(*tasks, return_exceptions=True)
        for i, result in enumerate(results):
            if isinstance(result, Exception):
                logging.error(f"Exception in processor \"{processors[i].name}\" ex:{result}")


async def main():
    async with httpx.AsyncClient(auth=auth) as client:
        resp = await client.get("https://fleets.yonside.org/v1/auth/ping")
        if resp.status_code != 200:
            return


    journal = EDLogs()
    ed2 = EDLogs()
    evloop = asyncio.get_event_loop()
    journal.start(evloop,"C:\\Users\\pooh\\Saved Games\\Frontier Developments\\Elite Dangerous")
    ed2.start(evloop, "C:\\Users\\ED1\\Saved Games\\Frontier Developments\\Elite Dangerous")

    fleet_processor = FleetProcessor(auth)

    try:
        await loop([fleet_processor],[journal, ed2])
    except asyncio.CancelledError:
        pass
    finally:
        ed2.stop()
        journal.stop()

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
