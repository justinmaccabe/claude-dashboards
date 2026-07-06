"""The three Claude dashboards, each a union of CRM reports off the
"New SLA Enhancement Dashboard", aggregated per "Assigned to" person.

  open-outside      = 2(b)+2(c)+2(d)  Open Support Tickets - Outside SLA
  completed-outside = 2(e)+2(g)+2(i)  Tickets Completed Last 7 Days - Outside SLA
  completed-within  = 2(f)+2(h)+2(j)  Tickets Completed Last 7 Days - Within SLA

Each sub-report contributes a set of ticket ids -> assigned_to owner. We union by
ticket id (so a ticket counted in two sub-reports counts once) and tally per owner.
"""
from __future__ import annotations

from hubspot_client import HubSpot, P, start_of_today_ms, days_ago_ms, to_ms, to_num

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
    id_to_name, name_to_id = hs.owner_maps()
    pid, closed = hs.support_ids()
    roster_ids = [name_to_id[n.casefold()] for n in SUPPORT_ROSTER if n.casefold() in name_to_id]
    exclude_ids = {name_to_id[n.casefold()] for n in OWNER_EXCLUDE if n.casefold() in name_to_id}

    filters = [
        {"propertyName": P["pipeline"], "operator": "EQ", "value": pid},
        {"propertyName": P["stage"], "operator": "NOT_IN", "values": [closed]},
        {"propertyName": P["action_item"], "operator": "IN",
         "values": ["Pending Action", "In Process", "Pending Confirmation"]},
        # "Action Item not updated in the last 0 days" == last changed before today
        {"propertyName": P["action_item_updated"], "operator": "LT", "value": start_of_today_ms()},
        {"propertyName": P["assigned_to"], "operator": "IN", "values": roster_ids},
    ]
    rows = hs.search(filters, RETURN_PROPS)
    result = {}
    for r in rows:
        owner = r.get(P["owner"])
        if owner and str(owner) in exclude_ids:          # owner none of {Stephanie, Daniel}, empty OK
            continue
        sub = (r.get(P["submitted_by"]) or "").lower()
        if "daniel willett" in sub:                       # submitted by doesn't contain Daniel Willett
            continue
        result[r["id"]] = r.get(P["assigned_to"])
    return _tally([{P["assigned_to"]: v, "id": k} for k, v in result.items()], id_to_name)


# ---------------------------------------------------------------------------
# Board B / C — Completed Last 7 Days (Outside / Within SLA)
# ---------------------------------------------------------------------------
def _completed_pending_action(hs, within: bool):
    """2(f) within / 2(e) outside — Pending Action, SLA on time-to-first-reply (15m)."""
    pid, _ = hs.support_ids()
    filters = [
        {"propertyName": P["pipeline"], "operator": "EQ", "value": pid},
        {"propertyName": P["action_item"], "operator": "NOT_IN", "values": ["Pending Action"]},
        {"propertyName": P["assigned_to_processing"], "operator": "HAS_PROPERTY"},
    ]
    rows = hs.search(filters, RETURN_PROPS)
    cutoff = days_ago_ms(8)
    out = {}
    for r in rows:
        # window: first agent response < 8 days ago OR create date < 8 days ago
        far = to_ms(r.get(P["first_agent_response"]))
        cre = to_ms(r.get(P["create_date"]))
        if not ((far and far > cutoff) or (cre and cre > cutoff)):
            continue
        ttfr = to_num(r.get(P["ttfr"]))
        within_sla = ttfr is not None and ttfr <= 15
        if within and not within_sla:
            continue
        if not within and within_sla:      # outside = not within (reply >15 or no reply)
            continue
        out[r["id"]] = r.get(P["assigned_to"])
    return out


def _completed_in_process(hs, within: bool):
    """2(h) within / 2(g) outside — In Process, SLA on Total Time In Process (240)."""
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
    rows = hs.search(filters, RETURN_PROPS)
    out = {}
    for r in rows:
        ttp = to_num(r.get(P["total_time_in_process"]))
        if ttp is None:
            continue
        within_sla = ttp <= 240
        if within and not within_sla:
            continue
        if not within and within_sla:
            continue
        out[r["id"]] = r.get(P["assigned_to"])
    return out


def _completed_pending_conf(hs, within: bool):
    """2(j) within / 2(i) outside — Pending Confirmation, SLA on Total Time in
    Pending Confirmation (15)."""
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
    rows = hs.search(filters, RETURN_PROPS)
    out = {}
    for r in rows:
        ttc = to_num(r.get(P["total_time_pending_conf"]))
        if ttc is None:
            continue
        within_sla = ttc <= 15
        if within and not within_sla:
            continue
        if not within and within_sla:
            continue
        out[r["id"]] = r.get(P["assigned_to"])
    return out


def build_completed(hs: HubSpot, within: bool):
    id_to_name, _ = hs.owner_maps()
    merged = _union(
        _completed_pending_action(hs, within),
        _completed_in_process(hs, within),
        _completed_pending_conf(hs, within),
    )
    return _tally([{P["assigned_to"]: v, "id": k} for k, v in merged.items()], id_to_name)


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
}
DEFAULT_REPORT = "open-outside"
