# SPDX-License-Identifier: EUPL-1.2
"""Velocity and capacity forecast for Scrum teams with Git as the data store."""

__version__ = "0.7.0"

from sprintforecast.compat import adopt_legacy_environment

adopt_legacy_environment()  # SPRINTFORECAST_* variables from before the rename still work


def main() -> None:
    from sprintforecast.cli import app

    app()


# Log file when started without a console (double-click); `web` redirects the server there.
LOG_ENV = "FORESPRINT_LOG"


def app_main() -> None:
    """Double-click start: web UI as an app window (`sprintforecast web --app`)."""
    import os
    import sys

    from sprintforecast.config import config_dir

    log = config_dir() / "app.log"
    # The log is a convenience: if it cannot be created (folder not writable, file locked),
    # the app starts anyway, just without a log.
    try:
        log.parent.mkdir(parents=True, exist_ok=True)
        out = open(log, "w", encoding="utf-8", buffering=1)  # noqa: SIM115 – stays open until exit
    except OSError:
        out = open(os.devnull, "w", encoding="utf-8")  # noqa: SIM115 – stays open until exit
    else:
        os.environ[LOG_ENV] = str(log)
    # Without a console (pythonw) there is no stdout/stderr; send output to the log.
    sys.stdout = out if sys.stdout is None else sys.stdout
    sys.stderr = out if sys.stderr is None else sys.stderr
    import json

    from sprintforecast.updater import LAUNCHER_ENV

    # For "Update and restart now": call this launcher again, not the CLI.
    os.environ[LAUNCHER_ENV] = json.dumps([sys.argv[0], *sys.argv[1:]])
    from sprintforecast.cli import app

    app(args=["web", "--app", *sys.argv[1:]], prog_name="sprintforecast")
