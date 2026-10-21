# SPDX-License-Identifier: EUPL-1.2
"""Golden references of ``difflib.unified_diff`` as used by ``gitsync.unified_diff`` (the Go port
has its own SequenceMatcher and must give the same lines).
"""

from __future__ import annotations

import difflib
import random


def lines(seed: int, count: int, alphabet: int) -> list[str]:
    rng = random.Random(seed)
    return [f"line {rng.randrange(alphabet)}" for _ in range(count)]


def cases() -> list[tuple[str, list[str], list[str]]]:
    out: list[tuple[str, list[str], list[str]]] = [
        ("equal", ["a", "b"], ["a", "b"]),
        ("empty-both", [], []),
        ("empty-old", [], ["a", "b"]),
        ("empty-new", ["a", "b"], []),
        ("replace-one", ["a", "b", "c"], ["a", "x", "c"]),
        ("insert", ["a", "c"], ["a", "b", "c"]),
        ("delete", ["a", "b", "c"], ["a", "c"]),
        (
            "far-apart",
            [str(i) for i in range(30)],
            [str(i) if i not in (3, 25) else "X" for i in range(30)],
        ),
        ("move", ["a", "b", "c", "d", "e"], ["d", "e", "a", "b", "c"]),
        ("repeat", ["a", "a", "b", "a", "a"], ["a", "b", "a", "a", "a"]),
    ]
    for seed in range(1, 25):
        a = lines(seed, 20 + seed * 3, 6)
        b = lines(seed + 100, 20 + seed * 2, 6)
        out.append((f"random-{seed}", a, b))
    # long inputs: autojunk drops lines that occur more than 1% (+1) of the time
    for seed in range(1, 6):
        base = lines(seed, 350, 4)
        changed = list(base)
        rng = random.Random(seed)
        for _ in range(12):
            changed[rng.randrange(len(changed))] = f"new {rng.randrange(1000)}"
        out.append((f"long-{seed}", base, changed))
        out.append((f"long-popular-{seed}", lines(seed, 260, 3), lines(seed + 7, 240, 3)))
    return out


def generate(ctx) -> None:
    result = []
    for name, a, b in cases():
        diff = list(difflib.unified_diff(a, b, f"{name} (old)", f"{name} (new)", lineterm="", n=2))
        result.append({"name": name, "a": a, "b": b, "diff": diff})
    ctx.write("difflib/unified.json", ctx.dump_json({"cases": result}))
