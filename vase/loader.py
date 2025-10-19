import importlib
import logging
import pkgutil
from types import ModuleType

import vase.plugins.internal as internal
from vase.api import Processor
from vase.config import config

logger = logging.getLogger("vase.loader")


def load_plugins() -> list[Processor]:
    plugins = []

    for finder, name, _ in pkgutil.iter_modules(internal.__path__):
        mod = importlib.import_module(f"{internal.__name__}.{name}")
        try:
            processor = load_processor(mod)
            plugins.append(processor)
        except Exception as e:
            logger.exception(f"Failed to load internal processor {name} {e}")

    for file in config.plugins_dir.glob("*.py"):
        module_name = file.stem  # filename without .py
        spec = importlib.util.spec_from_file_location(module_name, file)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)

        try:
            processor = load_processor(mod)
            plugins.append(processor)
        except Exception as e:
            logger.exception(f"Failed to load external processor {module_name} {e}")

    return plugins


def load_processor(module: ModuleType) -> Processor:
    load_func = getattr(module, "load")
    if not callable(load_func):
        raise TypeError(f"module {module} has no load function")

    processor = load_func()

    if not issubclass(processor.__class__, Processor):
        raise TypeError(
            f"module {module.__name__}.load() did not return a valid processor"
        )

    return processor
