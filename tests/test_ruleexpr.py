import pytest

from sprintforecast.model import Rule
from sprintforecast.ruleexpr import RuleSyntaxError, format_rule, parse_rule


def facts(**kw):
    base = {
        "epic": [],
        "component": [],
        "label": [],
        "status": [],
        "issue_type": [],
        "in_sprint": ["false"],
    }
    return {**base, **kw}


def test_precedence_and_before_or():
    rule = parse_rule("epic = A OR component = B AND label = c")
    assert rule.matches(facts(epic=["A"]))
    assert rule.matches(facts(component=["B"], label=["c"]))
    assert not rule.matches(facts(component=["B"]))


def test_not_and_in_and_negations():
    rule = parse_rule('component = Database AND NOT label IN (maintenance, "hot fix")')
    assert rule.matches(facts(component=["Database"]))
    assert not rule.matches(facts(component=["Database"], label=["hot fix"]))
    assert parse_rule("status != Done").matches(facts(status=["Open"]))
    assert not parse_rule("status NOT IN (Done, Closed)").matches(facts(status=["Closed"]))


def test_parentheses_and_case_insensitive_keywords():
    rule = parse_rule("(epic = A or epic = B) and not (status = Done)")
    assert rule.matches(facts(epic=["B"], status=["Open"]))
    assert not rule.matches(facts(epic=["B"], status=["Done"]))


@pytest.mark.parametrize(
    "text",
    [
        "epic = A AND component = B OR NOT label IN (x, y)",
        'label IN ("a b", c) AND (status != Done OR epic = X)',
        "NOT (epic = A AND label = b)",
        "in_sprint = true",
    ],
)
def test_round_trip(text):
    rule = parse_rule(text)
    again = parse_rule(format_rule(rule))
    for f in (facts(epic=["A"], label=["b"]), facts(label=["a b"], status=["Open"]), facts()):
        assert rule.matches(f) == again.matches(f)


@pytest.mark.parametrize(
    "text, position",
    [
        ("", 0),
        ("epic =", 6),
        ("foo = 1", 0),
        ("epic = A AND", 12),
        ("(epic = A", 9),
        ("epic = A)", 8),
        ('epic = "A', 7),
    ],
)
def test_syntax_errors_carry_position(text, position):
    with pytest.raises(RuleSyntaxError) as err:
        parse_rule(text)
    assert err.value.position == position


def test_format_of_existing_rules():
    assert format_rule(None) == ""
    rule = Rule(
        op="any",
        children=[Rule(source="epic", values=["A", "B"]), Rule(source="label", values=["x"])],
        short=True,
    )
    assert format_rule(rule) == "epic IN (A, B) OR label = x"


def test_contains_operator():
    rule = parse_rule(
        "label ~ pay AND summary_free = x" if False else "label ~ pay AND epic !~ old"
    )
    assert rule.matches(facts(label=["Payment"], epic=["ABC"]))
    assert not rule.matches(facts(label=["Payment"], epic=["Old-1"]))
    assert format_rule(rule) == "label ~ pay AND epic !~ old"
    again = parse_rule(format_rule(rule))
    assert again.matches(facts(label=["payroll"], epic=["X"]))


def test_review_fixes():
    assert parse_rule("in_sprint = True").values == ["true"]
    odd = Rule(source="label", values=["a\u00a0b", "c\nd"])
    assert parse_rule(format_rule(odd)).values == ["a\u00a0b", "c\nd"]
    assert "((" not in format_rule(parse_rule("NOT (epic = A OR label = b)"))
