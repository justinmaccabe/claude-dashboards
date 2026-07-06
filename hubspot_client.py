"""HubSpot client for the Claude ops dashboards.

Each board is a union of several CRM reports off the "New SLA Enhancement
Dashboard". We reproduce each underlying report's filters against the CRM Search
API, union the resulting tickets by id, attribute each to its "Assigned to" owner,
and count per person. Filters HubSpot Search can't express (calculated properties,
report formula fields) are applied client-side over the returned rows.

Property internal names were resolved from the ticket schema on 2026-07-06.
"""
from __future__ import annotations

import datetime as dt
import os
import time
from zoneinfo import ZoneInfo

import requests

BASE = "https://api.hubapi.com"
TZ = ZoneInfo("America/Toronto")

# --- ticket property internal names (resolved from the schema) --------------
P = {
    "pipeline": "hs_pipeline",
    "stage": "hs_pipeline_stage",
    "action_item": "action_item",
    "action_item_updated": "action_item_updated",     # date, calc=False
    "owner": "hubspot_owner_id",
    "assigned_to": "assigned_to",                      # owner-ref enum (dimension)
    "submitted_by": "request_submitted_by",            # string
    "assigned_to_processing": "assigned_to_processing",
    "assigned_to_support_ticket": "assigned_to_support_ticket",
    "assigned_to_final_review": "assigned_to_final_review",
    "date_entered_in_process": "date_entered_in_process_support_ticket",           # calc=False
    "date_exited_pending_conf": "date_exited_pending_confirmation_support_ticket",  # calc=False
    "ttfr": "time_to_first_agent_reply",               # number, calc=False (minutes)
    "create_date": "createdate",
    # calculated (calc=True) — must be read + filtered client-side:
    "first_agent_response": "hs_first_agent_message_sent_at",
    "total_time_in_process": "total_time_in_process_support_ticket",
    "total_time_pending_conf": "total_time_in_pending_confirmation_support_ticket",
}

SUPPORT_PIPELINE_LABEL = "Support Ticket"
CLOSED_STAGE_LABEL = "Closed"   # the stage label in the Support pipeline is just "Closed"


class HubSpot:
    def __init__(self, token: str | None = None):
        self.token = token or os.environ.get("HUBSPOT_TOKEN")
        if not self.token:
            raise RuntimeError("No HUBSPOT_TOKEN set.")
        self.s = requests.Session()
        self.s.headers.update({"Authorization": f"Bearer {self.token}",
                               "Content-Type": "application/json"})
        self._owner_cache = None
        self._pipeline_cache = None

    def _req(self, method, path, **kw):
        for attempt in range(5):
            r = self.s.request(method, f"{BASE}{path}", timeout=30, **kw)
            if r.status_code == 429:
                time.sleep(2 ** attempt)
                continue
            r.raise_for_status()
            return r.json()
        r.raise_for_status()

    # -- metadata -----------------------------------------------------------
    def owner_maps(self):
        """(id_to_name, name_to_id) from the owners endpoint. assigned_to and
        hubspot_owner_id both store owner ids."""
        if self._owner_cache:
            return self._owner_cache
        id_to_name, name_to_id, after = {}, {}, None
        while True:
            params = {"limit": 100}
            if after:
                params["after"] = after
            data = self._req("GET", "/crm/v3/owners", params=params)
            for o in data.get("results", []):
                oid = str(o.get("id"))
                name = (f"{o.get('firstName') or ''} {o.get('lastName') or ''}".strip()
                        or o.get("email") or oid)
                id_to_name[oid] = name
                name_to_id[name.casefold()] = oid
            after = data.get("paging", {}).get("next", {}).get("after")
            if not after:
                break
        self._owner_cache = (id_to_name, name_to_id)
        return self._owner_cache

    def support_ids(self):
        """(support_pipeline_id, closed_stage_id)."""
        if self._pipeline_cache:
            return self._pipeline_cache
        data = self._req("GET", "/crm/v3/pipelines/tickets")
        pid, closed = None, None
        for pl in data.get("results", []):
            if pl["label"] == SUPPORT_PIPELINE_LABEL:
                pid = pl["id"]
                for st in pl.get("stages", []):
                    if st["label"] == CLOSED_STAGE_LABEL:
                        closed = st["id"]
        self._pipeline_cache = (pid, closed)
        return self._pipeline_cache

    # -- generic search -----------------------------------------------------
    def search(self, filters: list, props: list) -> list:
        """Tickets matching the AND of `filters` (one filter group)."""
        return self.search_groups([{"filters": filters}], props)

    def search_groups(self, filter_groups: list, props: list) -> list:
        """Tickets matching ANY filter group (groups are OR'd), each group's filters
        AND'd. Always includes assigned_to + id. Paginates fully; deduped by HubSpot."""
        out, after = [], None
        want = list({*props, P["assigned_to"], "hs_object_id"})
        while True:
            body = {"filterGroups": filter_groups, "properties": want, "limit": 100}
            if after:
                body["after"] = after
            data = self._req("POST", "/crm/v3/objects/tickets/search", json=body)
            for t in data.get("results", []):
                row = dict(t.get("properties", {}))
                row["id"] = t.get("id")
                out.append(row)
            after = data.get("paging", {}).get("next", {}).get("after")
            if not after:
                break
        return out

    def action_item_last_changed(self, ids: list) -> dict:
        """{ticket_id: epoch_ms of the most recent action_item change} via the
        batch-read-with-history API (100 ids/call). Reproduces HubSpot's
        'Action Item (not) updated in the last N days' property-history filter."""
        out = {}
        for i in range(0, len(ids), 100):
            chunk = ids[i:i + 100]
            body = {"propertiesWithHistory": ["action_item"],
                    "inputs": [{"id": x} for x in chunk]}
            data = self._req("POST", "/crm/v3/objects/tickets/batch/read", json=body)
            for r in data.get("results", []):
                hist = r.get("propertiesWithHistory", {}).get("action_item", [])
                if hist:  # history is newest-first
                    out[r.get("id")] = to_ms(hist[0].get("timestamp"))
        return out


# --- date helpers -----------------------------------------------------------
def start_of_today_ms() -> int:
    d = dt.datetime.now(TZ).replace(hour=0, minute=0, second=0, microsecond=0)
    return int(d.astimezone(dt.timezone.utc).timestamp() * 1000)


def days_ago_ms(days: int) -> int:
    d = dt.datetime.now(TZ) - dt.timedelta(days=days)
    return int(d.astimezone(dt.timezone.utc).timestamp() * 1000)


def to_ms(v):
    """Normalise a HubSpot datetime value (epoch-ms string or ISO) to epoch ms."""
    if v in (None, ""):
        return None
    try:
        return int(v)
    except (ValueError, TypeError):
        try:
            return int(dt.datetime.fromisoformat(str(v).replace("Z", "+00:00")).timestamp() * 1000)
        except Exception:
            return None


def to_num(v):
    if v in (None, ""):
        return None
    try:
        return float(v)
    except (ValueError, TypeError):
        return None
