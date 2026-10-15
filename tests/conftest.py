# SPDX-License-Identifier: EUPL-1.2
import shutil
from pathlib import Path

import pytest

EXAMPLES = Path(__file__).parent.parent / "examples" / "teams"


@pytest.fixture
def data_dir(tmp_path: Path) -> Path:
    """Kopie der Demo-Daten, die Tests verändern dürfen."""
    target = tmp_path / "teams"
    shutil.copytree(EXAMPLES, target)
    return target
