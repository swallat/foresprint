# SPDX-License-Identifier: EUPL-1.2
# ruff: noqa: E501
"""References for the storage of the Go core (go/internal/storage): small YAML documents of every
file kind, read with the Python storage and written back, or the error it reports.

Each case is ``{"kind", "name", "yaml", "ok", "error"}``. ``ok`` is the text Python writes back
(``dump_yaml`` of the ``*_to_dict`` of what it read, without the file header); ``error`` is the
message of the ``DataError`` (the file location is the fixed text ``FILE``).
"""

from __future__ import annotations

from typing import Any

import yaml

from foresprint import storage
from foresprint.model import Sprint

WHERE = "FILE"


def _team(text: str) -> str:
    d = _load(text)
    with storage._well_formed(WHERE):
        team = storage.team_from_dict("key", d, WHERE)
    return storage.dump_yaml(storage.team_to_dict(team))


def _load(text: str) -> dict[str, Any]:
    content = yaml.load(text, Loader=storage._YAML_LOADER)
    return {} if content is None else content


def _people(text: str) -> str:
    with storage._well_formed(WHERE):
        return storage.dump_yaml(
            storage.people_to_dict(storage.people_from_dict(_load(text), WHERE))
        )


def _products(text: str) -> str:
    with storage._well_formed(WHERE):
        return storage.dump_yaml(
            storage.products_to_dict(storage.products_from_dict(_load(text), WHERE))
        )


def _sprint(text: str) -> str:
    with storage._well_formed(WHERE):
        sprint: Sprint = storage.sprint_from_dict(_load(text), WHERE)
    return storage.dump_yaml(storage.sprint_to_dict(sprint))


def _projects(text: str) -> str:
    with storage._well_formed(WHERE):
        return storage.dump_yaml(
            storage.projects_to_dict(storage.projects_from_dict(_load(text), WHERE))
        )


def _tickets(text: str) -> str:
    with storage._well_formed(WHERE):
        tickets, imported, source = storage.tickets_from_dict(_load(text), WHERE)
    return storage.dump_yaml(storage.tickets_to_dict(tickets, imported, source))


def _preplan(text: str) -> str:
    with storage._well_formed(WHERE):
        return storage.dump_yaml(
            storage.preplan_to_dict(storage.preplan_from_dict(_load(text), WHERE))
        )


KINDS = {
    "team": _team,
    "people": _people,
    "products": _products,
    "sprint": _sprint,
    "projects": _projects,
    "tickets": _tickets,
    "preplan": _preplan,
}

CASES: dict[str, dict[str, str]] = {
    "team": {
        "empty": "",
        "minimal": "name: X\n",
        "full": (
            "name: Full\nunit: SP\nfeatures: {products: true, po: true, production: true, tickets: true}\n"
            "sprint: {length_days: 7, numbering: sequential, first: {id: '12', start: 2026-01-05}}\n"
            "forecast: {reference_capacity: 41.5, window: 4, roadmap_share: 0.75, rounding: 2,"
            " trend_mode: classic, horizon: 5, product_basis: roadmap}\n"
            "capacity: {overhead_share: 0.1, overhead_days: 1.5, country: us, region: CA,"
            " workweek: sun-thu, rounding: 0, absence_history: 0}\n"
            "tracker:\n  kind: jira\n  base_url: https://jira.example.com\n  query: project = X\n"
            "  fields: {estimate: Est, remaining: Rest, epic: Epic Link}\n  planning_uses: estimate\n"
            "  refined_label: refined\n  refined_also_if: {status: [Ready]}\n"
            "  project_match_order: [label, epic]\n  priority_order: []\n  dependency_gap: 0\n"
            "  budget_basis: plan\n  rough_factor: 2\n  write_labels: true\n"
            "  sprint_names: {'Sprint 1': '2026.1', Beta: '2026.2'}\n  link_type: Depends\n"
            "  rule_fields: {team: Team, area: Area}\n"
        ),
        "old-german-trend": "name: A\nforecast: {trend_mode: klassisch}\n",
        "no-features-key": "name: A\nsprint: {length_days: 14}\n",
        "features-null": "name: A\nfeatures:\n",
        "tickets-off-valid-tracker": "name: A\ntracker: {kind: jira, base_url: https://j.example.com}\n",
        "tickets-off-bad-tracker": "name: A\ntracker: {rough_factor: abc}\n",
        "tickets-off-secret": "name: A\ntracker: {token: abc}\n",
        "tickets-on-secret": "name: A\nfeatures: {tickets: true}\ntracker: {api-token: abc}\n",
        "tickets-on-nested-secret": "name: A\nfeatures: {tickets: true}\ntracker: {fields: {my_password: x}}\n",
        "tickets-on-free-key": "name: A\nfeatures: {tickets: true}\ntracker: {sprint_names: {token: '1'}}\n",
        "country-no": "name: A\ncapacity: {country: NO}\n",
        "country-no-quoted": "name: A\ncapacity: {country: 'no'}\n",
        "country-int": "name: A\ncapacity: {country: 5}\n",
        "region-on": "name: A\ncapacity: {region: ON}\n",
        "unit-bad": "name: A\nunit: XX\n",
        "unit-lower": "name: A\nunit: pt\n",
        "unit-null": "name: A\nunit:\n",
        "trend-bad": "name: A\nforecast: {trend_mode: sideways}\n",
        "numbering-bad": "name: A\nsprint: {numbering: weekly}\n",
        "basis-bad": "name: A\nforecast: {product_basis: x}\n",
        "length-string": "name: A\nsprint: {length_days: '10'}\n",
        "length-bad-string": "name: A\nsprint: {length_days: ten}\n",
        "length-float": "name: A\nsprint: {length_days: 10.7}\n",
        "length-null": "name: A\nsprint: {length_days: }\n",
        "length-list": "name: A\nsprint: {length_days: [1]}\n",
        "length-inf": "name: A\nsprint: {length_days: .inf}\n",
        "length-nan": "name: A\nsprint: {length_days: .nan}\n",
        "window-bool": "name: A\nforecast: {window: true}\n",
        "ref-capacity-nan": "name: A\nforecast: {reference_capacity: .nan}\n",
        "ref-capacity-inf": "name: A\nforecast: {reference_capacity: .inf}\n",
        "ref-capacity-string": "name: A\nforecast: {reference_capacity: '12.5'}\n",
        "ref-capacity-bad": "name: A\nforecast: {reference_capacity: lots}\n",
        "ref-capacity-null": "name: A\nforecast: {reference_capacity: }\n",
        "ref-capacity-underscore": "name: A\nforecast: {reference_capacity: '1_0'}\n",
        "ref-capacity-date": "name: A\nforecast: {reference_capacity: 2026-01-01}\n",
        "share-nan-string": "name: A\nforecast: {roadmap_share: ' nan '}\n",
        "overhead-bad": "name: A\ncapacity: {overhead_share: x}\n",
        "sprint-not-mapping": "name: A\nsprint: 5\n",
        "sprint-list": "name: A\nsprint: [1, 2]\n",
        "forecast-string": "name: A\nforecast: text\n",
        "first-float": "name: A\nsprint: {first: {id: 2026.20, start: 2026-01-01}}\n",
        "first-bad-id": "name: A\nsprint: {first: {id: 'a/b', start: 2026-01-01}}\n",
        "first-bad-start": "name: A\nsprint: {first: {id: x, start: tomorrow}}\n",
        "first-compact-date": "name: A\nsprint: {first: {id: x, start: '20260105'}}\n",
        "first-week-date": "name: A\nsprint: {first: {id: x, start: '2026-W02-3'}}\n",
        "first-start-only": "name: A\nsprint: {first: {start: 2026-01-05}}\n",
        "name-number": "name: 42\n",
        "name-bool": "name: yes\n",
        "name-list": "name: [a, b]\n",
        "unknown-keys-dropped": "name: A\nfoo: bar\nsprint: {extra: 1}\n",
        "tracker-bad-kind-number": "name: A\nfeatures: {tickets: true}\ntracker: {kind: 5}\n",
        "tracker-planning-bad": "name: A\nfeatures: {tickets: true}\ntracker: {planning_uses: nope}\n",
        "tracker-budget-bad": "name: A\nfeatures: {tickets: true}\ntracker: {budget_basis: nope}\n",
        "tracker-gap-bad": "name: A\nfeatures: {tickets: true}\ntracker: {dependency_gap: 1.5}\n",
        "tracker-rough-bad": "name: A\nfeatures: {tickets: true}\ntracker: {rough_factor: [1]}\n",
        "tracker-order-scalar": "name: A\nfeatures: {tickets: true}\ntracker: {project_match_order: label}\n",
        "tracker-order-map": "name: A\nfeatures: {tickets: true}\ntracker: {project_match_order: {a: b}}\n",
        "tracker-sprint-names-float": "name: A\nfeatures: {tickets: true}\ntracker:\n  sprint_names: {2026.20: x}\n",
        "tracker-sprint-names-float-value": "name: A\nfeatures: {tickets: true}\ntracker:\n  sprint_names: {a: 2026.20}\n",
        "tracker-link-empty": "name: A\nfeatures: {tickets: true}\ntracker: {link_type: ''}\n",
        "tracker-link-null": "name: A\nfeatures: {tickets: true}\ntracker: {link_type: }\n",
        "tracker-not-mapping": "name: A\nfeatures: {tickets: true}\ntracker: [a]\n",
        "tracker-rule-nested": (
            "name: A\nfeatures: {tickets: true}\ntracker:\n  refined_also_if:\n    all:\n"
            "      - status: [Ready, 'In Progress']\n      - none:\n          - label_contains: wip\n"
            "      - in_sprint: [true]\n"
        ),
        "tracker-rule-short": (
            "name: A\nfeatures: {tickets: true}\ntracker:\n  refined_also_if:\n"
            "    epic: [E1]\n    label: [x, y]\n"
        ),
        "tracker-rule-float": (
            "name: A\nfeatures: {tickets: true}\ntracker:\n  refined_also_if: {in_sprint: [2026.20]}\n"
        ),
        "tracker-rule-dict-value": (
            "name: A\nfeatures: {tickets: true}\ntracker:\n  refined_also_if: {epic: {a: b}}\n"
        ),
        "tracker-rule-operator-not-list": (
            "name: A\nfeatures: {tickets: true}\ntracker:\n  refined_also_if: {any: x}\n"
        ),
        "tracker-rule-mixed": (
            "name: A\nfeatures: {tickets: true}\ntracker:\n  refined_also_if:\n    any: [{epic: a}]\n    label: [b]\n"
        ),
        "tracker-rule-null-values": (
            "name: A\nfeatures: {tickets: true}\ntracker:\n  refined_also_if: {epic: }\n"
        ),
        "tracker-rule-scalar-value": (
            "name: A\nfeatures: {tickets: true}\ntracker:\n  refined_also_if: {epic: E1, label_contains: abc}\n"
        ),
        "tracker-rule-contains-only": (
            "name: A\nfeatures: {tickets: true}\ntracker:\n  refined_also_if: {_contains: x}\n"
        ),
    },
    "people": {
        "empty": "",
        "basic": (
            "people:\n  - {id: a, name: Anna, memberships: [{from: 2025-01-01}]}\n"
            "  - id: b\n    name: Ben\n    country: de\n    region: BY\n    workweek: mon-thu\n"
            "    production_access: true\n    memberships:\n      - {from: 2025-01-01, to: 2025-12-31, fte: 0.5}\n"
            "      - {from: 2026-02-01, fte: '0.8'}\n"
        ),
        "no-name": "people: [{id: x}]\n",
        "id-number": "people: [{id: 7, name: Seven}]\n",
        "no-id": "people: [{name: x}]\n",
        "entry-not-mapping": "people: [x]\n",
        "people-not-list": "people: {a: 1}\n",
        "membership-not-mapping": "people: [{id: a, memberships: [x]}]\n",
        "membership-no-from": "people: [{id: a, memberships: [{to: 2026-01-01}]}]\n",
        "membership-bad-date2": "people: [{id: a, memberships: [{from: 'soon'}]}]\n",
        "membership-datetime": "people: [{id: a, memberships: [{from: 2026-01-01 10:00:00}]}]\n",
        "fte-bool": "people: [{id: a, memberships: [{from: 2026-01-01, fte: true}]}]\n",
        "fte-string": "people: [{id: a, memberships: [{from: 2026-01-01, fte: half}]}]\n",
        "fte-null": "people: [{id: a, memberships: [{from: 2026-01-01, fte: }]}]\n",
        "fte-zero": "people: [{id: a, memberships: [{from: 2026-01-01, fte: 0}]}]\n",
        "fte-inf": "people: [{id: a, memberships: [{from: 2026-01-01, fte: .inf}]}]\n",
        "region-bool": "people: [{id: a, region: NO}]\n",
        "country-no-quoted": "people: [{id: a, country: 'no'}]\n",
        "country-number": "people: [{id: a, country: 49}]\n",
        "workweek-number": "people: [{id: a, workweek: 5}]\n",
        "access-string": "people: [{id: a, production_access: 'no'}]\n",
        "access-zero": "people: [{id: a, production_access: 0}]\n",
        "umlauts": "people: [{id: zoe, name: Zoë Äpfel}]\n",
    },
    "products": {
        "empty": "",
        "basic": (
            "products:\n  - {id: p1, name: One, po: Pat, share: 0.5, from: 2026-01-01, to: 2026-12-31}\n"
            "  - id: p2\n    match: {label: [a], epic: [E]}\n  - {id: p3, share: '0.25'}\n"
        ),
        "no-id": "products: [{name: x}]\n",
        "bad-share": "products: [{id: a, share: lots}]\n",
        "share-nan": "products: [{id: a, share: .nan}]\n",
        "share-bool": "products: [{id: a, share: true}]\n",
        "share-list": "products: [{id: a, share: [1]}]\n",
        "bad-from": "products: [{id: a, from: nope}]\n",
        "po-number": "products: [{id: a, po: 5}]\n",
        "match-bad": "products: [{id: a, match: [x]}]\n",
        "match-empty": "products: [{id: a, match: {}}]\n",
        "match-null": "products: [{id: a, match: }]\n",
    },
    "sprint": {
        "minimal": "id: '2026.1'\nstart: 2026-01-07\nend: 2026-01-21\n",
        "missing-id": "start: 2026-01-07\nend: 2026-01-21\n",
        "missing-end": "id: x\nstart: 2026-01-07\n",
        "id-float": "id: 2026.20\nstart: 2026-01-07\nend: 2026-01-21\n",
        "id-int": "id: 5\nstart: 2026-01-07\nend: 2026-01-21\n",
        "full": (
            "id: '2026.2'\nstart: 2026-01-21\nend: 2026-02-04\nabsences: {zed: 2, amy: 1.5}\n"
            "absence_state: confirmed\ncapacity: 41.5\nforecast_ist: 30\nvelocity: 28\nscope_creep: 3\n"
            "planning: {carryover: 5, backlog: 25, corrections: [2, 1.5]}\nforecast_plan: 33.3333333\n"
            "products: {b: {planned: 10, done: 8, production_done: 2}, a: {preplanned: 5}, c: {}}\n"
            "expected_absences: {q: 1, a: 2}\nproduction_planned: 4\nproduction_done: 3\n"
            "not_done: 2\nadditional_done: 1\nnote: Hello\n"
            "prognoses:\n  - {at: 2026-01-20 08:00:00, comment: Daily, forecast_ist: 30, not_done: 2,"
            " additional_done: 1, expected_done: 29, target: '2026.3', plan: 33, preplanned: {b: 2, a: 1}}\n"
            "  - {at: '2026-01-21T09:30:00.123456'}\n"
        ),
        "state-expected-derived": (
            "id: x\nstart: 2026-01-07\nend: 2026-01-21\nabsence_state: expected\nexpected_absences: {a: 1}\n"
        ),
        "state-unknown-with-velocity": (
            "id: x\nstart: 2026-01-07\nend: 2026-01-21\nabsence_state: unknown\nvelocity: 5\n"
        ),
        "state-bad": "id: x\nstart: 2026-01-07\nend: 2026-01-21\nabsence_state: maybe\n",
        "legacy-confirmed": "id: x\nstart: 2026-01-07\nend: 2026-01-21\nabsences_confirmed: true\n",
        "legacy-velocity": "id: x\nstart: 2026-01-07\nend: 2026-01-21\nvelocity: 5\n",
        "legacy-preplanned-only": (
            "id: x\nstart: 2026-01-07\nend: 2026-01-21\nproducts: {a: {preplanned: 5}}\n"
        ),
        "absences-confirmed-empty-state": (
            "id: x\nstart: 2026-01-07\nend: 2026-01-21\nabsence_state: confirmed\n"
        ),
        "absences-entered": "id: x\nstart: 2026-01-07\nend: 2026-01-21\nabsences: {a: 1}\nabsence_state: unknown\n",
        "capacity-string": "id: x\nstart: 2026-01-07\nend: 2026-01-21\ncapacity: '40'\n",
        "capacity-bool": "id: x\nstart: 2026-01-07\nend: 2026-01-21\ncapacity: true\n",
        "capacity-nan": "id: x\nstart: 2026-01-07\nend: 2026-01-21\ncapacity: .nan\n",
        "capacity-empty-string": "id: x\nstart: 2026-01-07\nend: 2026-01-21\ncapacity: ''\n",
        "capacity-fraction": "id: x\nstart: 2026-01-07\nend: 2026-01-21\ncapacity: 0.1234567891\n",
        "capacity-tiny": "id: x\nstart: 2026-01-07\nend: 2026-01-21\ncapacity: 0.0000001\n",
        "capacity-negative-tiny": "id: x\nstart: 2026-01-07\nend: 2026-01-21\ncapacity: -0.0000001\n",
        "capacity-huge": "id: x\nstart: 2026-01-07\nend: 2026-01-21\ncapacity: 1.0e+20\n",
        "capacity-rounding": "id: x\nstart: 2026-01-07\nend: 2026-01-21\ncapacity: 2.6666665\n",
        "absence-bad": "id: x\nstart: 2026-01-07\nend: 2026-01-21\nabsences: {a: lots}\n",
        "absences-list": "id: x\nstart: 2026-01-07\nend: 2026-01-21\nabsences: [a]\n",
        "absences-null-value": "id: x\nstart: 2026-01-07\nend: 2026-01-21\nabsences: {a: }\n",
        "absences-int-key": "id: x\nstart: 2026-01-07\nend: 2026-01-21\nabsences: {1: 2}\n",
        "products-bad": "id: x\nstart: 2026-01-07\nend: 2026-01-21\nproducts: {a: 5}\n",
        "products-bad-value": "id: x\nstart: 2026-01-07\nend: 2026-01-21\nproducts: {a: {done: x}}\n",
        "planning-empty": "id: x\nstart: 2026-01-07\nend: 2026-01-21\nplanning: {}\n",
        "planning-corrections-bad": (
            "id: x\nstart: 2026-01-07\nend: 2026-01-21\nplanning: {backlog: 1, corrections: {a: 1}}\n"
        ),
        "planning-zero": "id: x\nstart: 2026-01-07\nend: 2026-01-21\nplanning: {carryover: 0}\n",
        "prognosis-no-at": "id: x\nstart: 2026-01-07\nend: 2026-01-21\nprognoses: [{comment: a}]\n",
        "prognosis-bad-at": "id: x\nstart: 2026-01-07\nend: 2026-01-21\nprognoses: [{at: yesterday}]\n",
        "prognosis-date-at": "id: x\nstart: 2026-01-07\nend: 2026-01-21\nprognoses: [{at: 2026-01-05}]\n",
        "prognosis-string-date-at": "id: x\nstart: 2026-01-07\nend: 2026-01-21\nprognoses: [{at: '2026-01-05'}]\n",
        "prognosis-zone": (
            "id: x\nstart: 2026-01-07\nend: 2026-01-21\nprognoses: [{at: '2026-01-05T10:00:00+02:00'}]\n"
        ),
        "prognosis-target-number": (
            "id: x\nstart: 2026-01-07\nend: 2026-01-21\nprognoses: [{at: 2026-01-05 10:00:00, target: 5}]\n"
        ),
        "prognosis-preplanned-bad": (
            "id: x\nstart: 2026-01-07\nend: 2026-01-21\nprognoses: [{at: 2026-01-05 10:00:00, preplanned: {a: z}}]\n"
        ),
        "note-number": "id: x\nstart: 2026-01-07\nend: 2026-01-21\nnote: 5\n",
        "note-empty": "id: x\nstart: 2026-01-07\nend: 2026-01-21\nnote: ''\n",
        "note-multiline": "id: x\nstart: 2026-01-07\nend: 2026-01-21\nnote: |\n  line one\n  line two\n",
        "start-datetime": "id: x\nstart: 2026-01-07 10:00:00\nend: 2026-01-21\n",
        "start-bad": "id: x\nstart: nope\nend: 2026-01-21\n",
        "start-quoted": "id: x\nstart: '2026-01-07'\nend: '2026-01-21'\n",
    },
    "projects": {
        "empty": "",
        "basic": (
            "schema: 1\nprojects:\n  - {id: p, name: Proj, product: prod, target: 2026-06-30,"
            " priority: 2, budget_basis: plan, note: Hi, match: {epic: [E1]}}\n  - {id: q}\n"
        ),
        "schema-newer": "schema: 2\nprojects: []\n",
        "schema-bad": "schema: one\nprojects: []\n",
        "schema-float": "schema: 1.0\nprojects: []\n",
        "schema-bool": "schema: true\nprojects: []\n",
        "no-id": "projects: [{name: x}]\n",
        "basis-bad": "projects: [{id: a, budget_basis: nope}]\n",
        "priority-bad": "projects: [{id: a, priority: high}]\n",
        "priority-float": "projects: [{id: a, priority: 1.5}]\n",
        "priority-whole-float": "projects: [{id: a, priority: 2.0}]\n",
        "target-bad": "projects: [{id: a, target: soon}]\n",
    },
    "tickets": {
        "empty": "",
        "basic": (
            "schema: 1\nimported: 2026-10-14 08:00:00\nsource: export.csv\ntickets:\n"
            "  - {key: A-1, title: One, status: Open, issue_type: Story, estimate: 5, remaining: 3,"
            " estimate_source: refined, in_sprint: '2026.5', sprint_name: Sprint 5, rank: '0|i0000:',"
            " epic: E1, labels: [x, y], components: [c], depends_on: [A-2], priority: High, project: p,"
            " project_candidates: [p, q], done: true, refined_unclear: true,"
            " fields: {team: [t1], area: a}}\n"
            "  - {key: A-2}\n"
        ),
        "imported-date": "imported: 2026-10-14\ntickets: []\n",
        "imported-bad": "imported: yesterday\ntickets: []\n",
        "imported-micro": "imported: 2026-10-14 08:00:00.5\ntickets: []\n",
        "imported-string": "imported: '2026-10-14T08:00:00'\ntickets: []\n",
        "no-key": "tickets: [{title: x}]\n",
        "key-number": "tickets: [{key: 5}]\n",
        "key-zero": "tickets: [{key: 0}]\n",
        "estimate-bad": "tickets: [{key: a, estimate: lots}]\n",
        "source-bad": "tickets: [{key: a, estimate_source: guess}]\n",
        "in-sprint-float": "tickets: [{key: a, in_sprint: 2026.20}]\n",
        "labels-scalar": "tickets: [{key: a, labels: x}]\n",
        "labels-map": "tickets: [{key: a, labels: {a: b}}]\n",
        "labels-number": "tickets: [{key: a, labels: [1, 2.5, true]}]\n",
        "fields-bad": "tickets: [{key: a, fields: [x]}]\n",
        "fields-map-value": "tickets: [{key: a, fields: {t: {a: b}}}]\n",
        "title-number": "tickets: [{key: a, title: 12}]\n",
        "schema-newer": "schema: 9\ntickets: []\n",
        "rank-number": "tickets: [{key: a, rank: 12}]\n",
        "unestimated": "tickets: [{key: a, estimate: , remaining: 0}]\n",
        "estimate-rounding": "tickets: [{key: a, estimate: 2.123456789}]\n",
    },
    "preplan": {
        "empty": "",
        "basic": (
            "schema: 1\nearmarks:\n  - {ticket: A-1, sprint: '2026.5', note: soon}\n  - {ticket: A-2, sprint: x}\n"
            "estimates:\n  - {ticket: A-3, estimate: 5, note: guess}\n  - {ticket: A-4}\n"
        ),
        "earmark-no-ticket": "earmarks: [{sprint: x}]\n",
        "earmark-no-sprint": "earmarks: [{ticket: a}]\n",
        "earmark-sprint-float": "earmarks: [{ticket: a, sprint: 2026.20}]\n",
        "estimate-no-ticket": "estimates: [{estimate: 1}]\n",
        "estimate-bad": "estimates: [{ticket: a, estimate: lots}]\n",
        "entry-not-mapping": "earmarks: [x]\n",
        "earmarks-map": "earmarks: {a: 1}\n",
        "schema-newer": "schema: 3\n",
    },
}


def generate(ctx: Any) -> None:
    cases = []
    for kind, items in CASES.items():
        for name, text in items.items():
            entry: dict[str, Any] = {"kind": kind, "name": name, "yaml": text}
            try:
                entry["ok"] = KINDS[kind](text)
            except storage.DataError as e:
                entry["error"] = str(e)
            except yaml.YAMLError as e:
                entry["yaml_error"] = True
                entry["error"] = type(e).__name__
            cases.append(entry)
    ctx.write("storage/cases.json", ctx.dump_json(cases))
