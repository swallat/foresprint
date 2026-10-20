"""The web UI uses flat Material icons (``web/icons.py``), never emojis."""

import re
from pathlib import Path

import foresprint.web as web_pkg

# Emoji blocks and the emoji-like status symbols (check/cross marks, squares, circles, warning)
EMOJI = re.compile("[✅❌⚠⬜⬛⚪⚫⭕✔❓-❗\U0001f000-\U0001faff️]")


def test_web_sources_contain_no_emojis():
    root = Path(web_pkg.__file__).parent
    found = [
        f"{path.name}:{n}: {line.strip()}"
        for path in sorted(root.rglob("*.py"))
        for n, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1)
        if EMOJI.search(line)
    ]
    assert not found, "Use web/icons.py instead of emojis:\n" + "\n".join(found)
