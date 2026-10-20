"""Text form of assignment rules: a small JQL-like expression language.

``component = Database AND NOT label IN (maintenance, hotfix)`` is parsed into the same
:class:`~foresprint.model.Rule` tree that ``projects.yaml`` uses, and a rule is formatted
back into text. The expressions are evaluated locally on the ticket facts, so they work for
every ticket source.

Grammar (keywords are case-insensitive)::

    expr  := and (OR and)*
    and   := not (AND not)*
    not   := NOT not | '(' expr ')' | cond
    cond  := source '=' value | source '!=' value
           | source '~' value (contains) | source '!~' value
           | source IN '(' value (',' value)* ')' | source NOT IN '(' ... ')'
    value := word | "quoted text"
"""

from __future__ import annotations

import difflib
import re
from dataclasses import dataclass

from .i18n import t
from .model import RULE_SOURCES, Rule

_TOKEN = re.compile(
    r"""\s*(?:
        (?P<str>"(?:[^"\\]|\\.)*")
      | (?P<op>!=|!~|=|~|\(|\)|,)
      | (?P<word>[^\s=!~(),"]+)
    )""",
    re.VERBOSE,
)
_KEYWORDS = {"and", "or", "not", "in"}


class RuleSyntaxError(ValueError):
    """The expression is invalid; ``position`` is the character offset of the problem."""

    def __init__(self, message: str, position: int) -> None:
        super().__init__(message)
        self.position = position


@dataclass
class _Token:
    kind: str  # "str", "op", "word" or "end"
    text: str
    pos: int

    @property
    def keyword(self) -> str | None:
        return self.text.lower() if self.kind == "word" and self.text.lower() in _KEYWORDS else None


def _tokenize(text: str) -> list[_Token]:
    tokens: list[_Token] = []
    pos = 0
    while text[pos:].strip():
        m = _TOKEN.match(text, pos)
        if m is None:
            start = pos + len(text[pos:]) - len(text[pos:].lstrip())
            raise RuleSyntaxError(t("Unterminated quote or unexpected character"), start)
        kind = m.lastgroup or "word"
        raw = m.group(kind)
        if kind == "str":
            raw = re.sub(r"\\(.)", r"\1", raw[1:-1])
        tokens.append(_Token(kind, raw, m.start(kind)))
        pos = m.end()
    tokens.append(_Token("end", "", len(text)))
    return tokens


class _Parser:
    def __init__(self, text: str) -> None:
        self.tokens = _tokenize(text)
        self.i = 0

    @property
    def cur(self) -> _Token:
        return self.tokens[self.i]

    def _next(self) -> _Token:
        tok = self.cur
        self.i += 1
        return tok

    def _is_op(self, op: str) -> bool:
        return self.cur.kind == "op" and self.cur.text == op

    def _error(self, message: str) -> RuleSyntaxError:
        return RuleSyntaxError(message, self.cur.pos)

    def parse(self) -> Rule:
        if self.cur.kind == "end":
            raise self._error(t("The expression is empty"))
        rule = self._or()
        if self.cur.kind != "end":
            if self._is_op(")"):
                raise self._error(t("Closing parenthesis without an opening one"))
            raise self._error(
                t("Expected AND, OR or the end, found '{found}'", found=self.cur.text)
            )
        return rule

    def _or(self) -> Rule:
        parts = [self._and()]
        while self.cur.keyword == "or":
            self._next()
            parts.append(self._and())
        return _combine("any", parts)

    def _and(self) -> Rule:
        parts = [self._not()]
        while self.cur.keyword == "and":
            self._next()
            parts.append(self._not())
        return _combine("all", parts)

    def _not(self) -> Rule:
        if self.cur.keyword == "not":
            self._next()
            return Rule(op="none", children=[self._not()])
        if self._is_op("("):
            self._next()
            rule = self._or()
            if not self._is_op(")"):
                raise self._error(t("Missing closing parenthesis"))
            self._next()
            return rule
        return self._condition()

    def _condition(self) -> Rule:
        tok = self.cur
        if tok.kind != "word" or tok.keyword:
            raise self._error(
                t(
                    "Expected a field ({fields}), found '{found}'",
                    fields=", ".join(RULE_SOURCES),
                    found=tok.text or t("end"),
                )
            )
        source = tok.text.lower()
        if source not in RULE_SOURCES:
            close = difflib.get_close_matches(source, RULE_SOURCES, n=1)
            if close:
                raise self._error(
                    t(
                        "Unknown field '{source}', did you mean '{close}'?",
                        source=tok.text,
                        close=close[0],
                    )
                )
            raise self._error(
                t(
                    "Unknown field '{source}' (allowed: {allowed})",
                    source=tok.text,
                    allowed=", ".join(RULE_SOURCES),
                )
            )
        self._next()
        negate = False
        if self.cur.keyword == "not":
            self._next()
            negate = True
            if self.cur.keyword != "in":
                raise self._error(t("Expected IN after NOT"))
        contains = False
        if self._is_op("=") or self._is_op("!=") or self._is_op("~") or self._is_op("!~"):
            op = self._next().text
            negate = op.startswith("!")
            contains = op.endswith("~")
            values = [self._value()]
        elif self.cur.keyword == "in":
            self._next()
            values = self._value_list()
        else:
            raise self._error(
                t("Expected =, !=, ~, !~, IN or NOT IN after '{source}'", source=tok.text)
            )
        if source == "in_sprint":  # the facts carry "true"/"false" in lower case
            values = [v.lower() if v.lower() in ("true", "false") else v for v in values]
        leaf = Rule(source=source, values=values, contains=contains)
        return Rule(op="none", children=[leaf]) if negate else leaf

    def _value(self) -> str:
        tok = self.cur
        if tok.kind not in ("word", "str") or (tok.kind == "word" and tok.keyword):
            raise self._error(t("Expected a value, found '{found}'", found=tok.text or t("end")))
        self._next()
        return tok.text

    def _value_list(self) -> list[str]:
        if not self._is_op("("):
            raise self._error(t("Expected '(' after IN"))
        self._next()
        values = [self._value()]
        while self._is_op(","):
            self._next()
            values.append(self._value())
        if not self._is_op(")"):
            raise self._error(t("Missing closing parenthesis"))
        self._next()
        return values


def _combine(op: str, parts: list[Rule]) -> Rule:
    if len(parts) == 1:
        return parts[0]
    flat: list[Rule] = []
    for part in parts:
        flat.extend(part.children if part.op == op and not part.short else [part])
    return Rule(op=op, children=flat)


def parse_rule(text: str) -> Rule:
    """The rule of an expression. Raises :class:`RuleSyntaxError` with a readable message."""
    return _Parser(text).parse()


# --- Formatting --------------------------------------------------------------------------------


def _quote(value: str) -> str:
    if (
        value
        and not any(c.isspace() or c in '=!~(),"' for c in value)
        and value.lower() not in _KEYWORDS
    ):
        return value
    return '"' + value.replace("\\", "\\\\").replace('"', '\\"') + '"'


def _leaf_text(leaf: Rule) -> str:
    source = leaf.source or ""
    if leaf.contains:
        parts = [f"{source} ~ {_quote(v)}" for v in leaf.values]
        return parts[0] if len(parts) == 1 else "(" + " OR ".join(parts) + ")"
    if len(leaf.values) == 1:
        return f"{source} = {_quote(leaf.values[0])}"
    return f"{source} IN ({', '.join(_quote(v) for v in leaf.values)})"


def format_rule(rule: Rule | None) -> str:
    """The expression of a rule (empty text for no rule); :func:`parse_rule` reads it back
    into an equal-meaning rule."""
    if rule is None:
        return ""
    return _format(rule, top=True)


def _format(rule: Rule, top: bool = False) -> str:
    if rule.op == "leaf":
        return _leaf_text(rule)
    if rule.op == "none":
        inner = rule.children
        if len(inner) == 1 and inner[0].op == "leaf":
            leaf = inner[0]
            if leaf.contains and len(leaf.values) == 1:
                return f"{leaf.source} !~ {_quote(leaf.values[0])}"
            if not leaf.contains and len(leaf.values) == 1:
                return f"{leaf.source} != {_quote(leaf.values[0])}"
            if not leaf.contains:
                return f"{leaf.source} NOT IN ({', '.join(_quote(v) for v in leaf.values)})"
        body = _format(inner[0], top=True) if len(inner) == 1 else " OR ".join(map(_format, inner))
        return f"NOT ({body})"
    joiner = " AND " if rule.op == "all" else " OR "
    parts = [_format(c) for c in rule.children]
    text = joiner.join(parts)
    return text if top or len(parts) == 1 else f"({text})"
