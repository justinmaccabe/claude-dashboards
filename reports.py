"""The three Claude dashboards, each a union of CRM reports off the
"New SLA Enhancement Dashboard", aggregated per "Assigned to" person.

  open-outside      = 2(b)+2(c)+2(d)  Open Support Tickets - Outside SLA
  completed-outside = 2(e)+2(g)+2(i)  Tickets Completed Last 7 Days - Outside SLA
  completed-within  = 2(f)+2(h)+2(j)  Tickets Completed Last 7 Days - Within SLA

Each sub-report contributes a set of ticket ids -> assigned_to owner. We union by
ticket id (so a ticket counted in two sub-reports counts once) and tally per owner.
"""
from __future__ import annotations

from hubspot_client import (HubSpot, P, start_of_today_ms, days_ago_ms,
                            today_bounds_ms, to_ms, to_num)

# Board A restricts to this 10-person support roster (report 2b/c/d filter 5).
SUPPORT_ROSTER = [
    "Hardeepika Ahluwalia", "Batuhan Karabay", "Christian Alvarez", "Ryan Connon",
    "Shivani Shaurya", "Phil Kolanowski", "Andrew Kirkham", "Ali Vahedi",
    "Adam Goldband", "Gabriel Tan",
]
OWNER_EXCLUDE = ["Stephanie Hunter", "Daniel Willett"]

# Common return properties (superset; harmless to over-request).
RETURN_PROPS = [
    P["assigned_to"], P["submitted_by"], P["ttfr"], P["create_date"],
    P["first_agent_response"], P["total_time_in_process"],
    P["total_time_pending_conf"], P["action_item"],
]


def _tally(rows, id_to_name):
    """rows -> {name: count}, attributing by assigned_to owner id, deduped by ticket."""
    counts = {}
    for r in rows:
        oid = r.get(P["assigned_to"])
        if not oid:
            continue
        name = id_to_name.get(str(oid), str(oid))
        counts[name] = counts.get(name, 0) + 1
    return counts


def _union(*subresults):
    """Merge {ticket_id: owner_id} dicts (union by ticket id)."""
    merged = {}
    for sr in subresults:
        merged.update(sr)
    return merged


# ---------------------------------------------------------------------------
# Board A — Open Support Tickets - Outside SLA (2b+2c+2d)
# ---------------------------------------------------------------------------
def build_open_outside(hs: HubSpot):
    """2(b)+2(c)+2(d): union of the 'Outside SLA - <stage> (Support Tickets)'
    segments, minus the report's exclusion filters, tallied by assigned_to. The
    segments carry the outside-SLA logic, so this tracks the report as its criteria
    evolve. No hard-coded roster — the report dropped it."""
    id_to_name, name_to_id = hs.owner_maps()
    _, closed = hs.support_ids()
    exclude_ids = {name_to_id[n.casefold()] for n in OWNER_EXCLUDE if n.casefold() in name_to_id}

    seg = hs.sla_segments()
    ids = set()
    for list_id in seg.values():
        ids.update(hs.list_members(list_id))
    props = hs.batch_read(list(ids), [P["assigned_to"], P["owner"], P["stage"],
                                       P["submitted_by"], P["in_process_reason"]])
    counts = {}
    for p in props.values():
        if p.get(P["stage"]) == closed:                       # status ≠ Closed
            continue
        owner = p.get(P["owner"])
        if owner and str(owner) in exclude_ids:               # owner ∉ {Stephanie, Daniel}, empty OK
            continue
        if "daniel willett" in (p.get(P["submitted_by"]) or "").lower():
            continue
        reason = (p.get(P["in_process_reason"]) or "").lower()
        if "nbin" in reason or "custodian" in reason:         # In Process Reason ∌ NBIN/Custodian
            continue
        a = p.get(P["assigned_to"])
        if not a:
            continue
        name = id_to_name.get(str(a), str(a))
        counts[name] = counts.get(name, 0) + 1
    return counts


# ---------------------------------------------------------------------------
# Board B / C — Completed Last 7 Days (Outside / Within SLA)
# ---------------------------------------------------------------------------
TTFR_MS = 15 * 60 * 1000   # "15 minutes"; time_to_first_agent_reply is stored in ms


def _completed_pending_action(hs, within: bool):
    """2(f) within / 2(e) outside — Pending Action. SLA = time-to-first-reply vs 15m.
    Attributed to assigned_to_processing (the rep who did the processing)."""
    pid, _ = hs.support_ids()
    cutoff = days_ago_ms(8)
    common = [
        {"propertyName": P["pipeline"], "operator": "EQ", "value": pid},
        {"propertyName": P["action_item"], "operator": "NOT_IN", "values": ["Pending Action"]},
        {"propertyName": P["assigned_to_processing"], "operator": "HAS_PROPERTY"},
    ]
    # Window server-side as two OR'd groups to stay under the 10k cap.
    groups = [
        {"filters": common + [{"propertyName": P["create_date"], "operator": "GT", "value": cutoff}]},
        {"filters": common + [{"propertyName": P["first_agent_response"], "operator": "GT", "value": cutoff}]},
    ]
    rows = hs.search_groups(groups, RETURN_PROPS + [P["assigned_to_processing"]])
    out = {}
    for r in rows:
        ttfr = to_num(r.get(P["ttfr"]))
        if within:
            if not (ttfr is not None and ttfr <= TTFR_MS):
                continue
        else:
            if not (ttfr is not None and ttfr > TTFR_MS):
                continue
        out[r["id"]] = r.get(P["assigned_to_processing"])
    return out


def _completed_in_process(hs, within: bool):
    """2(h) within / 2(g) outside — In Process. SLA = Total Time In Process vs 240.
    Attributed to assigned_to_support_ticket."""
    pid, _ = hs.support_ids()
    cutoff = days_ago_ms(8)
    filters = [
        {"propertyName": P["pipeline"], "operator": "EQ", "value": pid},
        {"propertyName": P["action_item"], "operator": "NOT_IN", "values": ["In Process"]},
        {"propertyName": P["assigned_to_support_ticket"], "operator": "HAS_PROPERTY"},
        {"propertyName": P["date_entered_in_process"], "operator": "HAS_PROPERTY"},
        {"propertyName": P["date_entered_in_process"], "operator": "GT", "value": cutoff},
    ]
    if not within:  # 2(g) also requires assigned_to_processing known
        filters.append({"propertyName": P["assigned_to_processing"], "operator": "HAS_PROPERTY"})
    rows = hs.search(filters, RETURN_PROPS + [P["assigned_to_support_ticket"]])
    out = {}
    for r in rows:
        ttp = to_num(r.get(P["total_time_in_process"]))
        if ttp is None:
            continue
        within_sla = ttp <= 240
        if within != within_sla:
            continue
        out[r["id"]] = r.get(P["assigned_to_support_ticket"])
    return out


def _completed_pending_conf(hs, within: bool):
    """2(j) within / 2(i) outside — Pending Confirmation. SLA = Total Time in Pending
    Confirmation vs 15. Attributed to assigned_to_final_review."""
    pid, _ = hs.support_ids()
    cutoff = days_ago_ms(8)
    filters = [
        {"propertyName": P["pipeline"], "operator": "EQ", "value": pid},
        {"propertyName": P["action_item"], "operator": "IN", "values": ["Completed"]},
        {"propertyName": P["date_exited_pending_conf"], "operator": "HAS_PROPERTY"},
        {"propertyName": P["date_exited_pending_conf"], "operator": "GT", "value": cutoff},
    ]
    if within:  # 2(j) requires assigned_to_final_review known
        filters.append({"propertyName": P["assigned_to_final_review"], "operator": "HAS_PROPERTY"})
    rows = hs.search(filters, RETURN_PROPS + [P["assigned_to_final_review"], P["assigned_to_support_ticket"]])
    out = {}
    for r in rows:
        ttc = to_num(r.get(P["total_time_pending_conf"]))
        if ttc is None:
            continue
        within_sla = ttc <= 15
        if within != within_sla:
            continue
        out[r["id"]] = (r.get(P["assigned_to_final_review"])
                        or r.get(P["assigned_to_support_ticket"]) or r.get(P["assigned_to"]))
    return out


def build_completed(hs: HubSpot, within: bool):
    id_to_name, _ = hs.owner_maps()
    merged = _union(
        _completed_pending_action(hs, within),
        _completed_in_process(hs, within),
        _completed_pending_conf(hs, within),
    )
    counts = {}
    for oid in merged.values():
        if not oid:
            continue
        name = id_to_name.get(str(oid), str(oid))
        counts[name] = counts.get(name, 0) + 1
    return counts


# ---------------------------------------------------------------------------
# Completed TODAY (2k/2l In Process, 2m/2n Pending Confirmation, 2e/2f Pending
# Action's today row). Same shape as the 7-day boards but keyed off
# "Date <Entered/Exited> <stage> is Today"; In-Process SLA splits at 15 (not 240).
# ---------------------------------------------------------------------------
def _today_pending_action(hs, within: bool):
    """2(e)/2(f) 'today' row — Pending Action entered today. Attributed to
    assigned_to_processing; SLA on time-to-first-reply vs 15m."""
    pid, _ = hs.support_ids()
    t0, t1 = today_bounds_ms()
    filters = [
        {"propertyName": P["pipeline"], "operator": "EQ", "value": pid},
        {"propertyName": P["action_item"], "operator": "NOT_IN", "values": ["Pending Action"]},
        {"propertyName": P["assigned_to_processing"], "operator": "HAS_PROPERTY"},
        # "completed pending action today" == entered the next stage (In Process) today
        {"propertyName": P["date_entered_in_process"], "operator": "GTE", "value": t0},
        {"propertyName": P["date_entered_in_process"], "operator": "LT", "value": t1},
    ]
    rows = hs.search(filters, RETURN_PROPS + [P["assigned_to_processing"]])
    out = {}
    for r in rows:
        ttfr = to_num(r.get(P["ttfr"]))
        within_sla = ttfr is not None and ttfr <= TTFR_MS
        if within != within_sla:
            continue
        out[r["id"]] = r.get(P["assigned_to_processing"])
    return out


def _today_in_process(hs, within: bool):
    """2(k)/2(l) — In Process exited today. Attributed to assigned_to_support_ticket;
    SLA on Total Time In Process vs 15."""
    pid, _ = hs.support_ids()
    t0, t1 = today_bounds_ms()
    _, name_to_id = hs.owner_maps()
    daniel = name_to_id.get("daniel willett")
    filters = [
        {"propertyName": P["pipeline"], "operator": "EQ", "value": pid},
        {"propertyName": P["action_item"], "operator": "NOT_IN", "values": ["In Process"]},
        {"propertyName": P["assigned_to_support_ticket"], "operator": "HAS_PROPERTY"},
        {"propertyName": P["date_exited_in_process"], "operator": "GTE", "value": t0},
        {"propertyName": P["date_exited_in_process"], "operator": "LT", "value": t1},
    ]
    if not within:  # 2(k) also requires assigned_to_processing known
        filters.append({"propertyName": P["assigned_to_processing"], "operator": "HAS_PROPERTY"})
    rows = hs.search(filters, RETURN_PROPS + [P["assigned_to_support_ticket"], P["owner"],
                                              P["in_process_reason"]])
    out = {}
    for r in rows:
        ttp = to_num(r.get(P["total_time_in_process"]))
        if ttp is None or (ttp <= 15) != within:
            continue
        if daniel and str(r.get(P["owner"])) == daniel:          # owner ≠ Daniel Willett
            continue
        if not within:                                            # 2(k): reason ∌ nbin/custodian
            rz = (r.get(P["in_process_reason"]) or "").lower()
            if "nbin" in rz or "custodian" in rz:
                continue
        out[r["id"]] = r.get(P["assigned_to_support_ticket"])
    return out


def _today_pending_conf(hs, within: bool):
    """2(m)/2(n) — Pending Confirmation exited today. Attributed to
    assigned_to_final_review; SLA on Total Time in Pending Confirmation vs 15."""
    pid, _ = hs.support_ids()
    t0, t1 = today_bounds_ms()
    filters = [
        {"propertyName": P["pipeline"], "operator": "EQ", "value": pid},
        {"propertyName": P["action_item"], "operator": "IN", "values": ["Completed"]},
        {"propertyName": P["date_exited_pending_conf"], "operator": "GTE", "value": t0},
        {"propertyName": P["date_exited_pending_conf"], "operator": "LT", "value": t1},
    ]
    if within:  # 2(n) requires assigned_to_final_review known
        filters.append({"propertyName": P["assigned_to_final_review"], "operator": "HAS_PROPERTY"})
    rows = hs.search(filters, RETURN_PROPS + [P["assigned_to_final_review"], P["assigned_to_support_ticket"]])
    out = {}
    for r in rows:
        ttc = to_num(r.get(P["total_time_pending_conf"]))
        if ttc is None or (ttc <= 15) != within:
            continue
        out[r["id"]] = (r.get(P["assigned_to_final_review"])
                        or r.get(P["assigned_to_support_ticket"]) or r.get(P["assigned_to"]))
    return out


def build_today(hs: HubSpot, within: bool):
    id_to_name, _ = hs.owner_maps()
    merged = _union(
        _today_pending_action(hs, within),
        _today_in_process(hs, within),
        _today_pending_conf(hs, within),
    )
    counts = {}
    for oid in merged.values():
        if not oid:
            continue
        name = id_to_name.get(str(oid), str(oid))
        counts[name] = counts.get(name, 0) + 1
    return counts


# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------
REPORTS = {
    "open-outside": {
        "title": "Open Support Tickets Outside SLA",
        "label": "Advisor Support · Service Delivery",
        "build": lambda hs: build_open_outside(hs),
    },
    "completed-outside": {
        "title": "Tickets Completed Last 7 Days — Outside SLA",
        "label": "Advisor Support · Service Delivery",
        "build": lambda hs: build_completed(hs, within=False),
    },
    "completed-within": {
        "title": "Tickets Completed Last 7 Days — Within SLA",
        "label": "Advisor Support · Service Delivery",
        "build": lambda hs: build_completed(hs, within=True),
    },
    "today-outside": {
        "title": "Tickets Completed Today — Outside SLA",
        "label": "Advisor Support · Service Delivery",
        "build": lambda hs: build_today(hs, within=False),
    },
    "today-within": {
        "title": "Tickets Completed Today — Within SLA",
        "label": "Advisor Support · Service Delivery",
        "build": lambda hs: build_today(hs, within=True),
    },
}
DEFAULT_REPORT = "open-outside"
