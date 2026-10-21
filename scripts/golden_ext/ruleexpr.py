# SPDX-License-Identifier: EUPL-1.2
"""Golden references of the rule expression language (``foresprint.ruleexpr``): parsed trees,
syntax errors with their position, the text form of a rule, and which facts a rule matches.

Written to ``golden/expected/ruleexpr/cases.json``. The Go port is ``go/internal/ruleexpr``."""

from __future__ import annotations

from foresprint.model import RULE_SOURCES, Rule, rule_sources
from foresprint.ruleexpr import RuleSyntaxError, format_rule, parse_rule

CONFIGURED = rule_sources({"customer": "Customer"})

# Valid expressions (they are parsed, formatted, parsed again and evaluated on FACTS).
VALID = [
    "epic = A",
    "epic = A OR component = B AND label = c",
    "epic = a or component = b and label = c",
    'component = Database AND NOT label IN (maintenance, "hot fix")',
    "status != Done",
    "status NOT IN (Done, Closed)",
    "(epic = A or epic = B) and not (status = Done)",
    "epic = A AND component = B OR NOT label IN (x, y)",
    'label IN ("a b", c) AND (status != Done OR epic = X)',
    "NOT (epic = A AND label = b)",
    "NOT (epic = A OR label = b)",
    "NOT NOT epic = A",
    "in_sprint = true",
    "in_sprint = True",
    "in_sprint IN (True, FALSE, other)",
    "label ~ pay AND epic !~ old",
    "label IN (a, b) AND label IN (c, d) AND epic = x",
    "(epic = A AND label = b) AND component = c",
    "epic = A AND (label = b OR (component = c AND status = Open))",
    "priority IN (High, Highest)",
    "priority = Low",
    "EPIC = A",
    'label = "and"',
    'label = "or" OR label = "not" OR label = "in"',
    'label = ""',
    'label = "a\\"b"',
    'label = "a\\\\b"',
    'label = "c\nd"',
    "label = a-b_c.d",
    "label = ünï",
    "  epic   =   A  ",
    "customer IN (Acme, Beta) AND customer !~ test",
    "epic = A OR epic = B OR epic = C",
    "epic = A AND epic = B AND epic = C",
    "((epic = A))",
    "NOT (label IN (a, b))",
    "NOT (label ~ a)",
    "NOT (epic = A AND label = b OR status = c)",
]

# (text, sources) pairs that must fail; the Go port reproduces message and position.
INVALID = [
    "",
    "   ",
    "epic =",
    "foo = 1",
    "lable = a",
    "epic = A AND",
    "(epic = A",
    "epic = A)",
    'epic = "A',
    "epic",
    "epic A",
    "epic NOT = A",
    "epic IN A",
    "epic IN (A",
    "epic IN ()",
    "epic IN (A,)",
    "epic = AND",
    "AND epic = A",
    "epic = A OR",
    "epic = A epic = B",
    "NOT",
    "( )",
    "epic = (A)",
    "epic !! A",
    "epic == A",
    "customer = a",
    "epic = A, label = b",
    "= A",
    "epic = A AND AND label = b",
    "epic ~",
    "label = a\u00a0b",
    "label = a\u2003b",
    "epic !~ ",
]

FACTS = [
    {},
    {"epic": ["A"]},
    {"epic": ["B"], "status": ["Open"]},
    {"epic": ["B"], "status": ["Done"]},
    {"component": ["B"], "label": ["c"]},
    {"component": ["Database"]},
    {"component": ["Database"], "label": ["hot fix"]},
    {"label": ["a b"], "status": ["Open"]},
    {"label": ["Payment"], "epic": ["ABC"]},
    {"label": ["Payment"], "epic": ["Old-1"]},
    {"label": ["payroll"], "epic": ["X"]},
    {"status": ["Closed"]},
    {"priority": ["High"]},
    {"priority": ["Low"]},
    {"in_sprint": ["true"]},
    {"in_sprint": ["false"]},
    {"customer": ["Acme"]},
    {"label": ["a", "c"], "epic": ["x"]},
    {"label": ["and"]},
    {"label": [""]},
]


def tree(rule: Rule) -> dict:
    return {
        "op": rule.op,
        "source": rule.source,
        "values": rule.values,
        "children": [tree(c) for c in rule.children],
        "short": rule.short,
        "contains": rule.contains,
    }


def generate(ctx) -> None:
    valid = []
    for text in VALID:
        rule = parse_rule(text, CONFIGURED)
        formatted = format_rule(rule)
        again = parse_rule(formatted, CONFIGURED)
        valid.append(
            {
                "text": text,
                "tree": tree(rule),
                "formatted": formatted,
                "reparsed": tree(again),
                "matches": [rule.matches(f) for f in FACTS],
                "matched_sources": [sorted(rule.matched_sources(f)) for f in FACTS],
                "leaf_sources": sorted(rule.leaf_sources()),
            }
        )
    invalid = []
    for text in INVALID:
        try:
            parse_rule(text, RULE_SOURCES)
        except RuleSyntaxError as err:
            invalid.append({"text": text, "message": str(err), "position": err.position})
        else:
            invalid.append({"text": text, "ok": True})
    built = [
        Rule(op="any", children=[Rule(source="epic", values=["A", "B"]),
                                 Rule(source="label", values=["x"])], short=True),
        Rule(source="label", values=["a", "b"], contains=True),
        Rule(op="none", children=[Rule(source="label", values=["a", "b"], contains=True)]),
        Rule(op="none", children=[Rule(source="epic", values=["a", "b"])]),
        Rule(op="none", children=[Rule(source="epic", values=["a"]),
                                  Rule(source="label", values=["b"])]),
        Rule(op="all", children=[Rule(source="epic", values=["a"])]),
        Rule(source="label", values=["a b", "c\nd", 'q"uote', "back\\slash", "and"]),
    ]
    formatted = [{"tree": tree(r), "text": format_rule(r)} for r in built]
    ctx.write(
        "ruleexpr/cases.json",
        ctx.dump_json(
            {"facts": FACTS, "valid": valid, "invalid": invalid, "formatted": formatted,
             "format_none": format_rule(None)}  # fmt: skip
        ),
    )
