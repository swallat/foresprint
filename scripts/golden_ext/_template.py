# SPDX-License-Identifier: EUPL-1.2
"""Template of a golden extension. Copy it to ``scripts/golden_ext/<module>.py`` (a name without
a leading underscore) to add references for one module of the Python core, for example
``validate``, ``protocol`` or ``excel``. ``scripts/golden.py`` calls ``generate`` for every such
file; the references end up below ``golden/expected/``. Keep to your own sub-folder
(``expected/<module>/...``) so that extensions never touch each other's files.

    def generate(ctx):
        for case in ctx.resolved:               # all cases, folders as absolute paths
            data = ctx.load(case)               # TeamData of the case
            ctx.write(f"module/{case.name}.json", ctx.dump_json(ctx.jsonable(result)))

``ctx.jsonable`` turns dataclasses, enums and dates into plain JSON values. Run
``uv run python scripts/golden.py`` afterwards and commit the new files; the Go test of your
module reads them with ``golden.Load`` and compares with ``golden.Compare``.
"""
