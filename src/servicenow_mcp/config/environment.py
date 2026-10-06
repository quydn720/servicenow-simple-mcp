"""Explicit environment-file loading for installed command-line applications."""

import os
from pathlib import Path

from dotenv import load_dotenv


def environment_file(*, remote: bool = False) -> Path:
    """Use the working directory unless the caller configured an explicit path."""
    variable = "MCP_REMOTE_ENV_FILE" if remote else "MCP_ENV_FILE"
    default = ".env.remote" if remote else ".env"
    return Path(os.getenv(variable, default)).expanduser().resolve()


def load_environment(*, remote: bool = False) -> None:
    load_dotenv(environment_file(remote=remote), override=False)
