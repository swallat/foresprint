# SPDX-License-Identifier: EUPL-1.2
"""Names from before the rename to Foresprint that keep working.

Environment variables used to start with ``SPRINTFORECAST_``, the configuration folder was
``sprintforecast``, the Git settings of a data folder lived under ``sprintforecast.*`` and the
Jira token under the keychain service ``sprintforecast-jira``. The new names win; the old ones are
still read, and the configuration folder is copied (never deleted) on first use.
"""

from __future__ import annotations

import os
from collections.abc import MutableMapping

LEGACY_ENV_PREFIX = "SPRINTFORECAST_"
ENV_PREFIX = "FORESPRINT_"


def adopt_legacy_environment(environ: MutableMapping[str, str] | None = None) -> None:
    """Make every ``SPRINTFORECAST_X`` variable also available as ``FORESPRINT_X`` (an explicitly
    set new variable wins)."""
    env = os.environ if environ is None else environ
    for key, value in list(env.items()):
        if key.startswith(LEGACY_ENV_PREFIX):
            env.setdefault(ENV_PREFIX + key[len(LEGACY_ENV_PREFIX) :], value)
