# SPDX-License-Identifier: EUPL-1.2
"""Golden references of the arithmetic the Go core has to reproduce from Python: the compensated
``sum()`` of floats (Python 3.12 and later), ``math.fsum``, ``statistics.median``/``fmean``,
``round`` and the number formats of ``str.format`` used by the texts."""

from __future__ import annotations

import math
import random
import statistics


def generate(ctx) -> None:
    rng = random.Random(20261021)
    lists: list[list[float]] = [
        [0.1] * 10,
        [0.1, 0.2, 0.3],
        [1e16, 1.0, -1e16],
        [1e100, 1.0, -1e100, 1.0],
        [0.1, 0.7, 0.2, 0.3, 0.1, 0.05],
        [67.0 / 3, 10.2, 0.1, 29.9, 0.3],
        [16.068866571018653, 18.52941176470588, 16.32492113564669, 16.57894736842105],
        [0.06, 0.05, 0.2, 0.0, 0.1],
        [1.0],
        [-0.0, 0.0],
        [2.5, -2.5, 1e-17],
    ]
    for size in (2, 3, 4, 5, 7, 10, 26):
        lists.append([round(rng.uniform(0, 40), rng.choice((1, 2, 6))) for _ in range(size)])
        lists.append([rng.uniform(-1, 1) * 10 ** rng.randint(-8, 8) for _ in range(size)])
    sums = [
        {
            "values": values,
            "sum": sum(values),
            "fsum": math.fsum(values),
            "median": statistics.median(values),
            "fmean": statistics.fmean(values),
        }
        for values in lists
    ]
    numbers = [
        0,
        0.5,
        1.5,
        2.5,
        2.675,
        25.25,
        0.125,
        1234567.891,
        1e6,
        1e15,
        100000,
        999999.5,
        0.00001234,
        123456789.0,
        30.4375,
        -0.0,
        -1.5,
        -1234.5,
        0.1 + 0.2,
        67.0,
        12.345,
        1e-7,
        3.0,
        1.5e300,
    ]
    formats = []
    for x in numbers:
        row = {"value": x, "g": f"{x:g}"}
        for digits in (0, 1, 2, 3, 4):
            row[f"fixed{digits}"] = f"{x:.{digits}f}"
            row[f"grouped{digits}"] = f"{x:,.{digits}f}"
        for digits in (0, 1, 2, 3):
            row[f"round{digits}"] = round(x, digits)
        formats.append(row)
    ctx.write("pymath/cases.json", ctx.dump_json({"sums": sums, "formats": formats}))
