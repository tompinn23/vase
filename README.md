# Vase

Vase dumps data from Elite: Dangerous logs and allows user defined processors to take actions upon the data.  
Vase doesn't have a GUI and just logs to the console.

## Features

The key thing about vase vs EDMC is running a single application monitoring multiple E:D instances using one application. 
Vase currently doesn't use the frontier cAPI however support maybe added in the future

## Plugins

Plugins are loaded from `%LOCALAPPDATA%/vase/plugins` and may officially only use types defined in the vase.api package
However various libraries are also provided for convenience particularly wrt. updating APIs over http

Plugins are expected to be a subclass of `vase.api.Processor` with 3 defined methods.
- name (property)
- setup()
- process(journal, event)

and a top level `load()` method which is called to get an instance of the plugin. Theres nothing to stop you acessing internal state but of course you do so at your own peril and will not be supported

### Libraries

- [httpx](https://www.python-httpx.org/)
- [pyjwt](https://pyjwt.readthedocs.io/en/stable/)
- [keyring](https://github.com/jaraco/keyring)
- [anyio](https://anyio.readthedocs.io/en/stable/index.html)

You'd probably be able to get away with most of the python standard library too.
These libraries are used by the fleets processor which updates fleet carrier statuses:
```python
import asyncio
import logging
import sys
import time
import webbrowser
from typing import MutableMapping, Any

import httpx
import jwt
import keyring

from vase.api import Journal
from vase.api.processor import Processor
```



