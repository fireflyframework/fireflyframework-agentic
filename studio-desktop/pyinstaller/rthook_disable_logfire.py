"""PyInstaller runtime hook: disable logfire pydantic plugin.

logfire uses inspect.getsource() which fails in frozen (PyInstaller)
apps because source code is not bundled. This hook prevents logfire
from loading as a pydantic plugin.
"""

import os

os.environ["LOGFIRE_SEND_TO_LOGFIRE"] = "false"
os.environ["PYDANTIC_DISABLE_PLUGINS"] = "1"
