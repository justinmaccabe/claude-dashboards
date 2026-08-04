"""Claude ops dashboards — Support-team leaderboards for the office TVs.

Boards selected by ?report= :
  open-outside        Open Support Tickets Outside SLA             (2b+2c+2d)
  completed-outside    Tickets Completed Last 7 Days - Outside SLA  (2e+2g+2i)
  completed-within     Tickets Completed Last 7 Days - Within SLA   (2f+2h+2j)
  completed-both       Split screen: Outside | Within, side by side

Queries HubSpot live (cached 15 min) via reports.py, most-on-top, only people with
counts. Same Optimize Advisor Portal styling as the SLA board.
"""
import base64
import datetime as dt
import os
from zoneinfo import ZoneInfo

import sys

import pandas as pd
import streamlit as st

try:                      # self-heal if the module cache is left corrupt by a rerun
    import reports
except KeyError:
    sys.modules.pop("reports", None)
    import reports

TZ = ZoneInfo("America/Toronto")
HERE = os.path.dirname(os.path.abspath(__file__))

NAVY = "#2B3A4E"
NAVY_LINE = "rgba(255,255,255,.07)"
ORANGE = "#C97B30"
TEAL = "#5E8A7E"
INK = "#FFFFFF"
MUTED = "#9CB0C2"

# Bump on each deploy so the live build is verifiable on-screen (footer/clock).
BUILD = "04Aug-transfers"

# Combined (split-screen) views compose two single boards side by side.
COMBINED = {
    "completed-both": {
        "title": "Tickets Completed This Week",
        "label": "Advisor Support · Service Delivery",
        "panels": [("completed-outside", "Outside SLA", "warn"),
                   ("completed-within", "Within SLA", "good")],
    },
    "today-both": {
        "title": "Tickets Completed Today",
        "label": "Advisor Support · Service Delivery",
        "panels": [("today-outside", "Outside SLA", "warn"),
                   ("today-within", "Within SLA", "good")],
    },
}

# Stacked per-stage view: two columns (Outside | Within), each with 3 stage tables
# (Pending Action, In Process, Pending Confirmation) — NOT summed.
STAGE_VIEW = {
    "completed-stages": {
        "title": "Tickets Completed This Week — by Stage",
        "label": "Advisor Support · Service Delivery",
    },
}


def _report_key():
    try:
        k = st.query_params.get("report")
    except Exception:
        k = None
    if k in reports.REPORTS or k in COMBINED or k in STAGE_VIEW:
        return k
    return reports.DEFAULT_REPORT


KEY = _report_key()
IS_COMBINED = KEY in COMBINED
IS_STAGES = KEY in STAGE_VIEW
CFG = (STAGE_VIEW[KEY] if IS_STAGES
       else COMBINED[KEY] if IS_COMBINED
       else reports.REPORTS[KEY])

st.set_page_config(page_title=f"{CFG['title']} — Optimize", page_icon="◆",
                   layout="wide", initial_sidebar_state="collapsed")

try:
    from streamlit_autorefresh import st_autorefresh
    st_autorefresh(interval=60_000, key="tick")
except Exception:
    pass

# Belt-and-suspenders: a plain-JS full-page reload every 15 min, independent of the
# autorefresh component. Guarantees the board (and its data) refreshes on the TV even
# if the component fails to load, and wakes a lightly-idle app.
import streamlit.components.v1 as components  # noqa: E402
components.html(
    "<script>setTimeout(function(){try{window.parent.location.reload();}"
    "catch(e){window.location.reload();}}, 900000);</script>",
    height=0,
)


def _token():
    tok = os.environ.get("HUBSPOT_TOKEN")
    if not tok:
        try:
            tok = st.secrets.get("HUBSPOT_TOKEN")
        except Exception:
            tok = None
    return tok


@st.cache_data(ttl=300, show_spinner=False)
def _fetch(report_key: str, _tok_tail: str):
    """Query HubSpot at most once per 5 min per board. Returns (counts, fetched_at)."""
    from hubspot_client import HubSpot
    counts = reports.REPORTS[report_key]["build"](HubSpot(token=_token()))
    return counts, dt.datetime.now(dt.timezone.utc)


@st.cache_data(ttl=300, show_spinner=False)
def _fetch_stages(within: bool, _tok_tail: str):
    """Completed-Last-7-Days per stage for one SLA side. Returns
    ([(stage_label, [(name, count), ...]), ...], fetched_at)."""
    from hubspot_client import HubSpot
    stages = reports.build_completed_stage(HubSpot(token=_token()), within)
    out = [(label, sorted(counts.items(), key=lambda kv: (-kv[1], kv[0])))
           for label, counts in stages]
    return out, dt.datetime.now(dt.timezone.utc)


def _debug_requested():
    try:
        return str(st.query_params.get("debug") or "") in ("1", "true", "yes")
    except Exception:
        return False


def _render_reconciliation():
    """?debug=1 — per-person, per-leg composition of the today boards so numbers
    can be reconciled against the source reports. Never part of the TV render."""
    import html as _html

    from hubspot_client import HubSpot

    sides = []
    if KEY in ("today-both", "today-within"):
        sides.append(("Within SLA (2f today-row + 2l + 2n)", True))
    if KEY in ("today-both", "today-outside"):
        sides.append(("Outside SLA (2e today-row + 2k + 2m)", False))
    if not sides:
        sides = [("Within SLA", True), ("Outside SLA", False)]

    st.title("Reconciliation — today boards")
    st.caption("summed = what the TV shows (a ticket counts once per leg). "
               "distinct = unique tickets credited to that person. "
               "summed > distinct ⇒ that person handled multiple stages of the "
               "same ticket today and is being multi-counted.")
    hs = HubSpot(token=_token())
    for label, within in sides:
        st.header(label)
        bd = reports.today_breakdown(hs, within)
        if not bd:
            st.write("_No rows in this view right now._")
            continue
        leg_names = [n for n, _ in reports._TODAY_LEGS["within" if within else "outside"]]
        rows = []
        for person in sorted(bd, key=lambda p: (-bd[p]["summed"], p)):
            rec = bd[person]
            cells = {"person": person}
            for ln in leg_names:
                ids = rec["legs"].get(ln, [])
                cells[ln] = f"{len(ids)}  " + (", ".join(ids) if ids else "")
            cells["SUMMED (TV)"] = rec["summed"]
            cells["DISTINCT"] = rec["distinct"]
            cells["flag"] = "⚠︎ multi-counted" if rec["summed"] != rec["distinct"] else ""
            rows.append(cells)
        st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)
        st.write(f"**Board total (summed):** {sum(r['SUMMED (TV)'] for r in rows)}  ·  "
                 f"**distinct-ticket total:** {sum(r['DISTINCT'] for r in rows)}")
        _ = _html  # keep import referenced


if _debug_requested():
    try:
        _render_reconciliation()
    except Exception as e:
        st.error(f"debug view error: {e}")
    st.stop()


# ---------------------------------------------------------------------------
# Daily Report view  ( ?report=daily-report )  and  Inventory view ( ?report=inventory )
# A document-style render of the daily SLA email, pulled LIVE from HubSpot. Only the
# tables that are genuinely live are shown (Advisor Support). Inventory lists every
# HubSpot list + pipeline so the remaining dashboards can be mapped and added.
# ---------------------------------------------------------------------------
def _view_key():
    try:
        return str(st.query_params.get("report") or "")
    except Exception:
        return ""


@st.cache_data(ttl=300, show_spinner=False)
def _daily_data(_tok_tail: str):
    from hubspot_client import HubSpot
    hs = HubSpot(token=_token())

    def _tbl(title, w, o, oo):
        names = sorted(set(w) | set(o) | set(oo))
        rows = [[n, w.get(n, 0), o.get(n, 0), oo.get(n, 0)] for n in names]
        return {"title": title, "rows": rows,
                "total": [sum(w.values()), sum(o.values()), sum(oo.values())]}

    # Advisor Support (Pending Action) — today's completed PA + currently-open PA outside
    w_pa = reports._sum_per_person(hs, [reports._today_pending_action(hs, True)])
    o_pa = reports._sum_per_person(hs, [reports._today_pending_action(hs, False)])
    open_pa = {}
    seg = hs.sla_segments().get("Pending Action")
    if seg:
        id_to_name, _ = hs.owner_maps()
        for p in hs.batch_read(hs.list_members(seg), [reports.P["assigned_to_processing"]]).values():
            oid = p.get(reports.P["assigned_to_processing"])
            if oid:
                nm = id_to_name.get(str(oid), str(oid))
                open_pa[nm] = open_pa.get(nm, 0) + 1

    # Advisor Support Dashboard — all three stages completed today + open outside (2b+2c+2d)
    tables = [
        _tbl("Advisor Support (Pending Action) — Daily Stats", w_pa, o_pa, open_pa),
        _tbl("Advisor Support Dashboard",
             reports.build_today(hs, True), reports.build_today(hs, False),
             reports.build_open_outside(hs)),
        _advisor_support_nbin(hs),
        _account_admin_nbin(hs),
    ]
    try:
        tables.append(_account_services(hs))
    except Exception as e:
        tables.append({"title": "Account Services Dashboard",
                       "columns": ["Name", "Completed Within SLA", "Completed Outside SLA", "Tickets Outside SLA"],
                       "rows": [], "total": ["Total", 0, 0, 0], "note": f"(temporarily unavailable: {e})"})
    try:
        tables.append(_transfers(hs))
    except Exception as e:
        tables.append({"title": "Transfers (Pending Review)",
                       "columns": ["Name", "Tickets Outside SLA", "Pending Review — Due Today"],
                       "rows": [], "total": ["Total", 0, 0], "note": f"(temporarily unavailable: {e})"})
    return tables, dt.datetime.now(dt.timezone.utc)


def _transfers(hs):
    """Transfers (Pending Review). Attributed to Assigned to Processing.
    'Pending Review — Due Today' = report 3a: request_type 'Initiate a transfer',
    Follow Up Date (Fixed Date) is Today (date-only field -> UTC-midnight window),
    action_item != Cancelled. Verified vs HubSpot 2026-08-04 = 7.
    'Tickets Outside SLA' = report 3d: request_type 'Initiate a transfer', action_item
    == 'Pending Final Review' (label 'Pending Review'), Follow Up Date more than 0 days
    ago (before today). Verified = 1."""
    import datetime as _dt
    from hubspot_client import TZ
    today = _dt.datetime.now(TZ).date()
    start = _dt.datetime(today.year, today.month, today.day, tzinfo=_dt.timezone.utc)
    t0 = int(start.timestamp() * 1000)
    t1 = int((start + _dt.timedelta(days=1)).timestamp() * 1000)
    id_to_name, _ = hs.owner_maps()

    def _tally(filters):
        out = {}
        for r in hs.search(filters, ["assigned_to_processing"]):
            oid = r.get("assigned_to_processing")
            if oid:
                nm = id_to_name.get(str(oid), str(oid))
                out[nm] = out.get(nm, 0) + 1
        return out

    due = _tally([  # 3a
        {"propertyName": "request_type", "operator": "EQ", "value": "Initiate a transfer"},
        {"propertyName": "follow_up_date_fixed_date", "operator": "GTE", "value": t0},
        {"propertyName": "follow_up_date_fixed_date", "operator": "LT", "value": t1},
        {"propertyName": "action_item", "operator": "NEQ", "value": "Cancelled"},
    ])
    outside = _tally([  # 3d
        {"propertyName": "request_type", "operator": "EQ", "value": "Initiate a transfer"},
        {"propertyName": "action_item", "operator": "EQ", "value": "Pending Final Review"},
        {"propertyName": "follow_up_date", "operator": "LT", "value": t0},
        {"propertyName": "follow_up_date", "operator": "HAS_PROPERTY"},
    ])
    names = sorted(set(due) | set(outside))
    rows = [[n, outside.get(n, 0), due.get(n, 0)] for n in names]
    total = ["Total", sum(outside.values()), sum(due.values())]
    return {"title": "Transfers (Pending Review)",
            "columns": ["Name", "Tickets Outside SLA", "Pending Review — Due Today"],
            "rows": rows, "total": total}


# --- Account Services Dashboard (reports 5c / 5e / 5f) -----------------------
_AA_STAGES = [
    ("date_entered_enhanced_review", "enhanced_review_sla_account_administration"),
    ("date_entered_transmitted", "transmitted_sla_account_administration"),
    ("date_entered_preparing_paperwork", "preparing_paperwork_sla_account_administration"),
    ("date_entered_in_review_pending_action", "pending_action_sla_account_administration"),
]
_AA_READ = ["hubspot_owner_id", "portfolio_manager", "supervising_portfolio_manager",
            "assigned_to_outside_sla", "assigned_to_within_sla", "assigned_to",
            "total_time_with_nbin", "request_type",
            "date_entered_in_process_support_ticket", "sent_to_nbin__date__time"]


def _aa_report(hs, *, sla_value, date_mode, owner_checks, exclude_admin, total_time_clause,
               segment_keywords, nbin_branch, attribution_field):
    """One account-administration SLA report (5c/5e/5f), returned as {name: count}.
    All clauses are stored ticket fields; see the report filter screenshots."""
    from hubspot_client import today_bounds_ms, days_ago_ms, to_ms, to_num
    ids = set()
    for date_prop, sla_prop in _AA_STAGES:
        f = [{"propertyName": "request_type", "operator": "IN", "values": _ACCT_ADMIN_REQ_TYPES},
             {"propertyName": sla_prop, "operator": "EQ", "value": sla_value}]
        if date_mode == "today":
            t0, t1 = today_bounds_ms()
            f += [{"propertyName": date_prop, "operator": "GTE", "value": t0},
                  {"propertyName": date_prop, "operator": "LT", "value": t1}]
        else:  # "8days"
            f += [{"propertyName": date_prop, "operator": "GTE", "value": days_ago_ms(8)}]
        for r in hs.search(f, [date_prop]):
            ids.add(str(r["id"]))
    if segment_keywords:
        lid = _find_list_id(hs, segment_keywords)
        if lid:
            ids.update(str(x) for x in hs.list_members(lid))
    if nbin_branch:  # 5c clause 8: Time to Send to NBIN > 15 AND Pending Confirmation SLA = Outside
        f = [{"propertyName": "request_type", "operator": "IN", "values": _ACCT_ADMIN_REQ_TYPES},
             {"propertyName": "pending_confirmation_sla_account_administration", "operator": "EQ", "value": "Outside SLA"},
             {"propertyName": "sent_to_nbin__date__time", "operator": "HAS_PROPERTY"}]
        for r in hs.search(f, ["date_entered_in_process_support_ticket", "sent_to_nbin__date__time"]):
            a = to_ms(r.get("date_entered_in_process_support_ticket"))
            b = to_ms(r.get("sent_to_nbin__date__time"))
            if a is not None and b is not None and int((b - a) / 60000) > 15:
                ids.add(str(r["id"]))
    if not ids:
        return {}
    props = hs.batch_read(list(ids), _AA_READ)
    id_to_name, _ = hs.owner_maps()
    counts = {}
    for p in props.values():
        if p.get("request_type") not in _ACCT_ADMIN_REQ_TYPES:
            continue
        if exclude_admin and str(p.get("assigned_to")) == "104417029":
            continue
        if total_time_clause:
            t = to_num(p.get("total_time_with_nbin"))
            if t is not None and t > 2:      # keep only <= 2 days or empty
                continue
        aos = p.get("assigned_to_outside_sla")
        if aos and any(str(p.get(of)) == str(aos) for of in owner_checks):
            continue                          # Ticket Owner / PM / Supervising-PM check is True -> excluded
        attr = p.get(attribution_field)
        if not attr:
            continue
        nm = id_to_name.get(str(attr), str(attr))
        counts[nm] = counts.get(nm, 0) + 1
    return counts


def _account_services(hs):
    OWNER = "hubspot_owner_id"
    PM = "portfolio_manager"
    SPM = "supervising_portfolio_manager"
    within = _aa_report(hs, sla_value="Within SLA", date_mode="today", owner_checks=[OWNER],
                        exclude_admin=False, total_time_clause=False,
                        segment_keywords=["account opening completed today", "within"],
                        nbin_branch=False, attribution_field="assigned_to_within_sla")            # 5f
    outside = _aa_report(hs, sla_value="Outside SLA", date_mode="today", owner_checks=[OWNER, PM, SPM],
                         exclude_admin=True, total_time_clause=True,
                         segment_keywords=["account opening completed today", "outside"],
                         nbin_branch=False, attribution_field="assigned_to_outside_sla")           # 5e
    open_outside = _aa_report(hs, sla_value="Outside SLA", date_mode="8days", owner_checks=[OWNER, PM, SPM],
                              exclude_admin=True, total_time_clause=True,
                              segment_keywords=None, nbin_branch=True,
                              attribution_field="assigned_to_outside_sla")                          # 5c
    names = sorted(set(within) | set(outside) | set(open_outside))
    rows = [[n, within.get(n, 0), outside.get(n, 0), open_outside.get(n, 0)] for n in names]
    total = ["Total", sum(within.values()), sum(outside.values()), sum(open_outside.values())]
    return {"title": "Account Services Dashboard",
            "columns": ["Name", "Completed Within SLA", "Completed Outside SLA", "Tickets Outside SLA"],
            "rows": rows, "total": total}


def _find_list_id(hs, keywords):
    """Find a ticket list whose name contains all `keywords` (case-insensitive)."""
    data = hs._req("POST", "/crm/v3/lists/search", json={"query": keywords[0], "count": 100})
    for l in data.get("lists", []):
        name = (l.get("name") or "").lower()
        if l.get("objectTypeId") == "0-5" and all(k in name for k in keywords):
            return l.get("listId")
    return None


# Account-administration Request Types feeding report 6d.
_ACCT_ADMIN_REQ_TYPES = [
    "Update Account Documentation", "Modify banking", "Amend previous year tax returns",
    "RESP Breakdown", "Tax Slip Corrections", "Update Phone Number", "Add banking",
    "Delete banking", "Designation and change of beneficiary", "Client Consent Form",
    "Add/Update POA", "Close Account", "Clerical Error Update", "Tax Slip Duplicates",
    "Update SIN", "Update Entity", "Signature for Locked-In Agreements", "Update Address",
    "Update Marital Status", "Update Email", "Estate Processing", "Book Value Adjustment",
    "Change delivery method", "Update Name", "Third Party Contribution Authorization",
    "RESP beneficiary information update", "Update DOB", "Recalculate LIF Maximum",
    "Third party online access", "Update Account Legislation", "Password reset",
]


def _account_admin_nbin(hs):
    """Account Administration Tickets with NBIN.
    'Tickets With NBIN' = report 6d ("1 AND 2"): account-admin request types, Assigned to
    != Optimize Administrator, Action Item Closed/Completed, Close date < 8 days ago,
    Notification Sent to Assignee known. Verified vs HubSpot 2026-08-04 = 13.
    'Completed Outside SLA' = report 6g, the list
    'Outside SLA - Pending Confirmation (Account Administration)'."""
    from hubspot_client import days_ago_ms
    filters = [
        {"propertyName": "request_type", "operator": "IN", "values": _ACCT_ADMIN_REQ_TYPES},
        {"propertyName": "assigned_to", "operator": "NOT_IN", "values": ["104417029"]},  # not Optimize Administrator
        {"propertyName": "action_item", "operator": "IN", "values": ["Closed", "Completed"]},
        {"propertyName": "closed_date", "operator": "GTE", "value": days_ago_ms(8)},
        {"propertyName": "notification_sent_to_assignee", "operator": "HAS_PROPERTY"},
    ]
    with_nbin = len(hs.search(filters, ["request_type"]))
    outside = 0
    lid = _find_list_id(hs, ["outside sla", "pending confirmation", "account administration"])
    if lid:
        outside = len(hs.list_members(lid))
    return {"title": "Account Administration Tickets with NBIN",
            "columns": ["Tickets With NBIN", "Completed Outside SLA"],
            "flat_row": [with_nbin, outside]}


def _advisor_support_nbin(hs):
    """Advisor Support Tickets With NBIN (reports 6a/6b). Support tickets currently
    sent to NBIN, awaiting NBIN, not Closed. Split by Time to Send to NBIN =
    DATEDIFF(MINUTE, date_entered_in_process, sent_to_nbin) <= 15 (within) / > 15 (outside).
    Verified against HubSpot 2026-07-31: 13 within / 34 outside / 47 total."""
    from hubspot_client import to_ms
    CLOSED = "208647293"  # Support pipeline "Closed" stage
    filters = [
        {"propertyName": reports.P["pipeline"], "operator": "EQ", "value": "117451896"},
        {"propertyName": "sent_to_nbin__date__time", "operator": "HAS_PROPERTY"},
        {"propertyName": "received_response_from_nbin", "operator": "NOT_HAS_PROPERTY"},
        {"propertyName": "hs_pipeline_stage", "operator": "NEQ", "value": CLOSED},
    ]
    rows = hs.search(filters, ["date_entered_in_process_support_ticket", "sent_to_nbin__date__time"])
    within = outside = 0
    for r in rows:
        a = to_ms(r.get("date_entered_in_process_support_ticket"))
        b = to_ms(r.get("sent_to_nbin__date__time"))
        if a is None or b is None:
            continue  # DATEDIFF null -> in neither 6a nor 6b
        mins = int((b - a) / 60000)  # DATEDIFF("MINUTE") truncates toward zero
        if mins <= 15:
            within += 1
        else:
            outside += 1
    return {"title": "Advisor Support Tickets With NBIN",
            "columns": ["Actioned Within SLA", "Actioned Outside SLA",
                        "Total Advisor Support Tickets with NBIN"],
            "flat_row": [within, outside, within + outside]}


@st.cache_data(ttl=300, show_spinner=False)
def _inventory_data(_tok_tail: str):
    from hubspot_client import HubSpot
    hs = HubSpot(token=_token())
    pipes = hs._req("GET", "/crm/v3/pipelines/tickets").get("results", [])
    lists, offset = [], 0
    while True:
        data = hs._req("POST", "/crm/v3/lists/search", json={"query": "", "count": 250, "offset": offset})
        batch = data.get("lists", [])
        lists.extend(batch)
        if not data.get("hasMore") or not batch:
            break
        offset = data.get("offset", offset + len(batch))
    return pipes, lists, dt.datetime.now(dt.timezone.utc)


_REPORT_CSS = f"""
<style>
#MainMenu, header, footer {{ visibility: hidden; }}
html, body, .stApp {{ background:#EEF1F4 !important; overflow:auto !important; }}
.block-container {{ padding:1.2rem 1rem 3rem; max-width:1000px; }}
.doc {{ font-family:'Montserrat',sans-serif; background:#fff; border-radius:14px;
        box-shadow:0 8px 30px rgba(20,30,45,.12); overflow:hidden; }}
.dhdr {{ background:#FBF8F0; border-bottom:3px solid {ORANGE}; padding:22px 30px;
         display:flex; justify-content:space-between; align-items:center; }}
.dhdr .b {{ font-family:'Lora',serif; font-weight:700; font-size:22px; letter-spacing:2px; color:{NAVY}; }}
.dhdr .b span {{ display:block; font-size:9px; letter-spacing:4px; margin-top:3px; }}
.dhdr .r {{ text-align:right; }}
.dhdr .r .t {{ font-family:'Lora',serif; font-size:19px; color:{NAVY}; font-weight:700; }}
.dhdr .r .s {{ font-size:10px; letter-spacing:2px; text-transform:uppercase; color:{ORANGE}; font-weight:700; margin-top:3px; }}
.dhdr .r .d {{ font-size:11px; color:#8A94A0; margin-top:4px; }}
.dbody {{ padding:20px 30px 26px; }}
.dintro {{ font-size:12.5px; color:#3A4B60; margin-bottom:18px; }}
.dcap {{ font-family:'Lora',serif; font-size:15px; font-weight:700; color:{NAVY};
         border-bottom:2px solid {ORANGE}; padding-bottom:6px; margin:22px 0 0; }}
table.d {{ width:100%; border-collapse:collapse; font-size:12.5px; margin-top:0; }}
table.d th {{ background:{NAVY}; color:#fff; font-size:9px; letter-spacing:.5px; text-transform:uppercase;
              font-weight:700; padding:8px 10px; text-align:right; }}
table.d th.l {{ text-align:left; }}
table.d td {{ padding:7px 10px; border-bottom:1px solid #E7E0D2; }}
table.d td.l {{ text-align:left; color:{NAVY}; font-weight:600; }}
table.d td.n {{ text-align:right; font-variant-numeric:tabular-nums; color:#3A4B60; }}
table.d tr:nth-child(even) td {{ background:#FAF7EF; }}
table.d tr.tot td {{ border-top:2px solid {NAVY}; background:#FBF8F0; color:{NAVY}; font-weight:700; }}
.dnote {{ font-size:11px; color:#8A94A0; margin-top:14px; text-align:center; }}
.badge {{ display:inline-block; font-size:10px; font-weight:700; letter-spacing:.5px; color:{TEAL};
          border:1px solid {TEAL}; border-radius:20px; padding:2px 10px; margin-left:8px; vertical-align:middle; }}
</style>
"""


def _num_cell(v, kind):
    v = int(v)
    style = ""
    if kind == "out" and v > 0:
        style = f"color:{ORANGE};font-weight:700"
    elif kind == "in" and v > 0:
        style = f"color:{TEAL};font-weight:600"
    return f'<td class="n" style="{style}">{v}</td>'


def _render_daily_report():
    tok = _token()
    if not tok:
        st.error("No HUBSPOT_TOKEN configured on the app.")
        return
    tables, captured = _daily_data(tok[-8:])
    updated = captured.astimezone(TZ).strftime("%-I:%M %p")
    now_l = dt.datetime.now(TZ)
    st.markdown(_REPORT_CSS, unsafe_allow_html=True)
    people_cols = ["Name", "Completed Within SLA", "Completed Outside SLA", "Tickets Outside SLA"]

    def _tone_for(colname):
        c = colname.lower()
        if "within" in c:
            return "in"
        if "outside" in c:
            return "out"
        return None

    parts = ['<div class="doc">',
             f'<div class="dhdr"><div class="b">OPTIMIZE<span>FINANCIAL GROUP</span></div>'
             f'<div class="r"><div class="t">Daily SLA Report</div><div class="s">Tickets Outside SLA</div>'
             f'<div class="d">{now_l:%A, %B %-d, %Y} · synced {updated} · live</div></div></div>',
             '<div class="dbody">',
             '<div class="dintro">Please see the update below for tickets outside SLA. '
             'These figures are pulled live from HubSpot.</div>']
    for t in tables:
        cols = t["columns"]
        if "flat_row" in t:
            # aggregate table (e.g. NBIN): custom columns, one row of numbers, no Name column
            thead = "".join(f"<th>{c}</th>" for c in cols)
            tds = "".join(_num_cell(v, _tone_for(cols[i]) or "plain") for i, v in enumerate(t["flat_row"]))
            body = f"<tr>{tds}</tr>"
        else:
            # people table: first column is Name (label), the rest are numbers coloured by header
            has_name = bool(cols) and cols[0].lower() == "name"
            thead = "".join(
                f'<th class="{"l" if (i == 0 and has_name) else "r"}">{c}</th>' for i, c in enumerate(cols))
            rows_html = []
            for r in t.get("rows", []):
                cells = []
                for i, v in enumerate(r):
                    if i == 0 and has_name:
                        cells.append(f'<td class="l">{v}</td>')
                    else:
                        cells.append(_num_cell(v, _tone_for(cols[i]) or "plain"))
                rows_html.append("<tr>" + "".join(cells) + "</tr>")
            tot = t.get("total")
            if tot:
                cells = []
                for i, v in enumerate(tot):
                    cells.append(f'<td class="l">{v}</td>' if i == 0 else f'<td class="n">{v}</td>')
                rows_html.append('<tr class="tot">' + "".join(cells) + "</tr>")
            body = "".join(rows_html)
        note = f'<div class="dnote">{t["note"]}</div>' if t.get("note") else ""
        parts.append(f'<div class="dcap">{t["title"]}<span class="badge">LIVE</span></div>'
                     f'<table class="d"><thead><tr>{thead}</tr></thead><tbody>{body}</tbody></table>{note}')
    parts.append('<div class="dnote">Live from HubSpot. Client Service Dashboard and the Client '
                 'Service NBIN "outside" column are report-only fields and are shown separately.</div>')
    parts.append('</div></div>')
    st.markdown("\n".join(parts), unsafe_allow_html=True)

    # Setup helper: show the SLA-related lists in this portal so the remaining four
    # dashboards can be wired to their exact source. Screenshot this and send to Claude.
    try:
        _, lists, _ = _inventory_data(tok[-8:])
        sla = [l for l in lists
               if any(k in (l.get("name") or "").lower() for k in ("sla", "outside", "nbin", "custodian", "review"))]
        st.markdown("---")
        st.markdown("#### ⚙︎ Setup — send this to Claude to finish the remaining tables")
        st.caption("You don't need to read or understand this. Just screenshot the table below "
                   "(or the whole page) and send it over. It lists the HubSpot lists that define "
                   "the SLA counts for Client Service, Account Services, Transfers and NBIN.")
        st.dataframe(
            pd.DataFrame([{"listId": l.get("listId"), "list name": l.get("name"),
                           "size": l.get("size", "")} for l in
                          sorted(sla, key=lambda x: (x.get("name") or "").lower())],
                        columns=["listId", "list name", "size"]),
            use_container_width=True, hide_index=True, height=min(430, 60 + 35 * max(len(sla), 1)))
        st.caption(f"{len(sla)} SLA-related lists found. Full inventory: add ?report=inventory to the URL.")
    except Exception as e:
        st.caption(f"(Setup helper unavailable: {e})")


def _render_inventory():
    tok = _token()
    if not tok:
        st.error("No HUBSPOT_TOKEN configured on the app.")
        return
    pipes, lists, captured = _inventory_data(tok[-8:])
    st.markdown("<style>#MainMenu,header,footer{visibility:hidden;} "
                ".stApp{background:#EEF1F4;}</style>", unsafe_allow_html=True)
    st.title("HubSpot list & pipeline inventory")
    st.caption("Screenshot or copy the four dashboards' lists (Client Service, Account "
               "Services, Transfers, NBIN) and send them to Claude to wire them live.")
    OBJ = {"0-5": "Ticket", "0-1": "Contact", "0-2": "Company", "0-3": "Deal"}
    st.subheader(f"Lists ({len(lists)})")
    st.dataframe(pd.DataFrame(
        [{"listId": l.get("listId"), "name": l.get("name"),
          "object": OBJ.get(l.get("objectTypeId"), l.get("objectTypeId")),
          "size": l.get("size", "")} for l in
         sorted(lists, key=lambda x: (x.get("objectTypeId", ""), (x.get("name") or "").lower()))],
        columns=["listId", "name", "object", "size"]),
        use_container_width=True, hide_index=True, height=520)
    st.subheader(f"Ticket pipelines ({len(pipes)})")
    st.dataframe(pd.DataFrame([{"id": p.get("id"), "label": p.get("label")} for p in pipes],
                              columns=["id", "label"]),
                 use_container_width=True, hide_index=True)


_VIEW = _view_key()
if _VIEW == "daily-report":
    try:
        _render_daily_report()
    except Exception as e:
        st.error(f"Daily report error: {e}")
    st.stop()
if _VIEW == "inventory":
    try:
        _render_inventory()
    except Exception as e:
        st.error(f"Inventory error: {e}")
    st.stop()


def logo_markup() -> str:
    mimes = {"svg": "image/svg+xml", "png": "image/png", "jpg": "image/jpeg",
             "jpeg": "image/jpeg", "webp": "image/webp"}
    d = os.path.join(HERE, "assets")
    chosen = None
    if os.path.isdir(d):
        imgs = [f for f in sorted(os.listdir(d)) if f.rsplit(".", 1)[-1].lower() in mimes]
        imgs.sort(key=lambda f: (not f.lower().startswith("logo."), f))
        chosen = imgs[0] if imgs else None
    if chosen:
        with open(os.path.join(d, chosen), "rb") as f:
            b64 = base64.b64encode(f.read()).decode()
        mime = mimes[chosen.rsplit(".", 1)[-1].lower()]
        return (f'<div class="brand"><span class="logo-badge">'
                f'<img class="logo-img" src="data:{mime};base64,{b64}" alt="Optimize"/>'
                f'</span><div class="wm"><b>OPTIMIZE</b></div></div>')
    return '<div class="brand"><div class="wm"><b>OPTIMIZE</b></div></div>'


CURVES = f"""
<svg class="curves" viewBox="0 0 1600 200" preserveAspectRatio="none" xmlns="http://www.w3.org/2000/svg">
<path d="M820 200 Q1060 40 1600 10" fill="none" stroke="{NAVY_LINE}" stroke-width="1.5"/>
<path d="M1020 200 Q1220 60 1600 70" fill="none" stroke="{NAVY_LINE}" stroke-width="1.5"/>
<path d="M1220 200 Q1360 90 1600 130" fill="none" stroke="{NAVY_LINE}" stroke-width="1.5"/>
</svg>"""

st.markdown(f"""
<style>
@import url('https://fonts.googleapis.com/css2?family=Lora:wght@500;600;700&family=Montserrat:wght@500;600;700;800&display=swap');
#MainMenu, header, footer {{ visibility: hidden; }}
html, body, .stApp {{ background: {NAVY}; overflow: hidden; }}
.block-container {{ padding: 0; max-width: 100%; }}
.board {{ font-family:'Montserrat',sans-serif; color:{INK}; height:100vh; box-sizing:border-box;
          padding:1.4rem 2.2rem 1.1rem; display:flex; flex-direction:column; }}
.hero {{ position:relative; overflow:hidden; flex:0 0 auto; border-bottom:1px solid rgba(255,255,255,.12); padding-bottom:.9rem; }}
.curves {{ position:absolute; inset:0; width:100%; height:100%; z-index:0; pointer-events:none; }}
.hero-row {{ position:relative; z-index:1; display:flex; align-items:center; justify-content:space-between; gap:1.6rem; }}
.brand {{ display:flex; align-items:center; gap:.75rem; }}
.brand .logo-badge {{ background:#fff; border-radius:13px; width:56px; height:56px; display:inline-flex; align-items:center; justify-content:center; overflow:hidden; }}
.brand .logo-img {{ width:100%; height:100%; object-fit:contain; transform:scale(1.25); }}
.brand .wm b {{ font-family:'Lora',serif; font-size:1.5rem; letter-spacing:.05em; display:block; line-height:1; }}
.headline {{ text-align:center; }}
.headline .pip {{ width:34px; height:4px; background:{ORANGE}; border-radius:2px; margin:0 auto .4rem; }}
.headline h1 {{ font-family:'Lora',serif; font-weight:600; font-size:2.1rem; margin:0; line-height:1.05; }}
.headline .lbl {{ font-size:.62rem; letter-spacing:.3em; text-transform:uppercase; color:{MUTED}; margin-top:.35rem; font-weight:700; }}
.clock {{ text-align:right; min-width:180px; }}
.clock .t {{ font-family:'Lora',serif; font-size:1.6rem; line-height:1; }}
.clock .d {{ color:{MUTED}; font-size:.74rem; margin-top:.18rem; }}
.clock .upd {{ color:{ORANGE}; font-size:.68rem; margin-top:.35rem; }}

/* single-board: one full-width row per person */
.rows {{ flex:0 0 auto; column-count:1; margin-top:1.3rem; }}
.rows .row {{ padding:.8rem 1.1rem; }}
.rows .row .name {{ flex:0 0 auto; max-width:42%; }}
.rows .row .bar {{ flex:1 1 auto; }}

/* split-screen: two panels */
.split {{ flex:1 1 auto; display:flex; gap:1.8rem; margin-top:1.2rem; align-items:flex-start; }}
.panel {{ flex:1 1 0; min-width:0; }}
.ptitle {{ font-family:'Lora',serif; font-size:1.2rem; font-weight:600; color:{INK};
           display:flex; justify-content:space-between; align-items:baseline;
           border-bottom:2px solid rgba(255,255,255,.15); padding-bottom:.45rem; margin-bottom:.75rem; }}
.ptitle .pc {{ font-size:1.5rem; }}
.ptitle.warn {{ border-bottom-color:{ORANGE}; }} .ptitle.warn .pc {{ color:{ORANGE}; }}
.ptitle.good {{ border-bottom-color:{TEAL}; }} .ptitle.good .pc {{ color:{TEAL}; }}
.rows2 {{ column-count:1; }}

.row {{ break-inside:avoid; display:flex; align-items:center; gap:.6rem; background:rgba(255,255,255,.05);
        border-radius:11px; padding:.6rem .85rem; margin-bottom:.6rem; border-left:3px solid transparent; }}
.row.top {{ border-left-color:{ORANGE}; background:rgba(201,123,48,.12); }}
.good .row.top {{ border-left-color:{TEAL}; background:rgba(94,138,126,.14); }}
.row .rank {{ flex:0 0 1.9rem; font-family:'Lora',serif; font-size:1.3rem; color:{MUTED}; text-align:right; }}
.row.top .rank {{ color:{ORANGE}; }} .good .row.top .rank {{ color:{TEAL}; }}
.row .name {{ flex:1 1 auto; min-width:0; font-size:1.35rem; font-weight:600; white-space:nowrap; overflow:hidden; text-overflow:ellipsis; }}
.row .bar {{ flex:0 0 90px; height:14px; border-radius:7px; background:rgba(255,255,255,.08); overflow:hidden; }}
.row .bar i {{ display:block; height:100%; border-radius:7px; }}
.row .n {{ flex:0 0 2.7rem; text-align:right; font-family:'Lora',serif; font-weight:700; font-size:1.7rem; }}
.foot {{ flex:0 0 auto; margin-top:auto; display:flex; justify-content:space-between; align-items:center;
         padding-top:.8rem; border-top:1px solid rgba(255,255,255,.12); color:{MUTED}; font-size:.84rem; }}
.foot b {{ color:{INK}; }}
.foot .big {{ font-family:'Lora',serif; color:{ORANGE}; font-size:1.5rem; vertical-align:-2px; }}
.foot .gbig {{ font-family:'Lora',serif; color:{TEAL}; font-size:1.5rem; vertical-align:-2px; }}
.empty {{ flex:1 1 auto; display:flex; align-items:center; justify-content:center; color:{MUTED}; font-size:1.1rem; }}
.pempty {{ color:{MUTED}; padding:.6rem .2rem; }}

/* stacked per-stage view: 2-col grid so each stage lines up across columns — every
   name shown (no cap), and Pending Confirmation shifts down to start at the same
   level on both Outside and Within. */
/* this view is data-dense, so shrink the hero to give the tables more vertical room */
.board.stages {{ padding-top:.8rem; }}
.board.stages .hero {{ padding-bottom:.35rem; }}
.board.stages .headline h1 {{ font-size:1.5rem; }}
.board.stages .headline .lbl {{ margin-top:.2rem; }}
.board.stages .brand .logo-badge {{ width:42px; height:42px; }}
.board.stages .clock .t {{ font-size:1.25rem; }}
.stagewrap {{ flex:1 1 auto; min-height:0; display:flex; gap:2rem;
              align-items:flex-start; margin-top:.5rem; padding-bottom:1.2rem; }}
.stagecol {{ flex:1 1 0; min-width:0; }}
.stagecol .stage {{ margin-bottom:.55rem; }}
.stage {{ min-width:0; }}
.stage .sh {{ display:flex; justify-content:space-between; align-items:baseline;
              border-bottom:1px solid rgba(255,255,255,.15); padding-bottom:.2rem; margin-bottom:.35rem; }}
.stage .sh .sl {{ font-family:'Lora',serif; font-size:1.15rem; font-weight:600; color:{INK}; letter-spacing:.02em; }}
.stage .sh .sc {{ font-family:'Lora',serif; font-size:1.35rem; font-weight:700; }}
.stage.warn .sh .sc {{ color:{ORANGE}; }} .stage.good .sh .sc {{ color:{TEAL}; }}
.srow {{ display:flex; align-items:center; gap:.6rem; padding:.16rem .55rem; margin-bottom:.16rem;
         border-radius:10px; }}
.srow.top {{ background:rgba(201,123,48,.11); }} .stage.good .srow.top {{ background:rgba(94,138,126,.13); }}
.srow .sr {{ flex:0 0 1.7rem; text-align:right; font-family:'Lora',serif; color:{MUTED}; font-size:1.05rem; }}
.srow.top .sr {{ color:{ORANGE}; }} .stage.good .srow.top .sr {{ color:{TEAL}; }}
.srow .sn {{ flex:1 1 auto; min-width:0; font-size:1.18rem; font-weight:600; white-space:nowrap; overflow:hidden; text-overflow:ellipsis; }}
.srow .sv {{ flex:0 0 2.4rem; text-align:right; font-family:'Lora',serif; font-weight:700; font-size:1.4rem; }}
</style>
""", unsafe_allow_html=True)


def bar_color(n, mx, tone):
    frac = (n / mx) if mx else 0
    if tone == "good":
        return "#4E7A6E" if frac >= 0.45 else (TEAL if frac >= 0.15 else "#8FB3A8")
    return "#B85C2A" if frac >= 0.45 else (ORANGE if frac >= 0.15 else "#D8A65E")


def rows_html(df, tone):
    if df.empty:
        return '<div class="pempty">No tickets in this view right now ✓</div>'
    mx = int(df["tickets"].max())
    out, rank, last_n = [], 0, None
    for i, r in df.iterrows():
        n = int(r["tickets"])
        if n != last_n:
            rank = i + 1
            last_n = n
        width = max((n / mx) * 100, 3)
        cls = "row top" if rank <= 3 else "row"
        out.append(f'<div class="{cls}"><div class="rank">{rank}</div>'
                   f'<div class="name">{r["person"]}</div>'
                   f'<div class="bar"><i style="width:{width:.0f}%;background:{bar_color(n, mx, tone)}"></i></div>'
                   f'<div class="n">{n}</div></div>')
    return "".join(out)


def stage_rows_html(rows):
    """rows = [(name, count), ...] sorted desc — compact per-stage leaderboard."""
    if not rows:
        return '<div class="pempty">None in this stage ✓</div>'
    out, rank, last = [], 0, None
    for i, (name, c) in enumerate(rows):
        if c != last:
            rank = i + 1
            last = c
        cls = "srow top" if rank <= 3 else "srow"
        out.append(f'<div class="{cls}"><span class="sr">{rank}</span>'
                   f'<span class="sn">{name}</span><span class="sv">{int(c)}</span></div>')
    return "".join(out)


def fetch_df(key, tok):
    counts, captured = _fetch(key, tok[-8:])
    df = (pd.DataFrame(sorted(counts.items(), key=lambda kv: (-kv[1], kv[0])),
                       columns=["person", "tickets"])
          if counts else pd.DataFrame(columns=["person", "tickets"]))
    return df, captured


# --- data ------------------------------------------------------------------
now = dt.datetime.now(TZ)
tok = _token()
err = None if tok else "No HUBSPOT_TOKEN configured"
captured = None
panels = []   # list of (subtitle, tone, df) ; single board uses one entry with subtitle None
stage_sides = []  # [(side_label, tone, [(stage_label, [(name, count), ...]), ...])]
if not err:
    try:
        if IS_STAGES:
            for within, side_label, tone in [(False, "Outside SLA", "warn"),
                                             (True, "Within SLA", "good")]:
                data, c = _fetch_stages(within, tok[-8:])
                stage_sides.append((side_label, tone, data))
                captured = captured or c
        elif IS_COMBINED:
            for pkey, sub, tone in CFG["panels"]:
                df, c = fetch_df(pkey, tok)
                panels.append((sub, tone, df))
                captured = captured or c
        else:
            tone = "good" if "within" in KEY else "warn"
            df, captured = fetch_df(KEY, tok)
            panels = [(None, tone, df)]
    except Exception as e:
        err = str(e)

updated_txt = captured.astimezone(TZ).strftime("%-I:%M %p") if captured is not None else "—"

# --- header ----------------------------------------------------------------
html = [f'<div class="board{" stages" if IS_STAGES else ""}">']
html.append(f"""
<div class="hero">{CURVES}
<div class="hero-row">
{logo_markup()}
<div class="headline"><div class="pip"></div><h1>{CFG['title']}</h1><div class="lbl">{CFG['label']}</div></div>
<div class="clock"><div class="t">{now:%-I:%M %p}</div><div class="d">{now:%A, %B %-d, %Y}</div>
<div class="upd">Synced {updated_txt} · every 15 min · {BUILD}</div></div>
</div></div>
""")

# --- body ------------------------------------------------------------------
if err:
    html.append(f'<div class="empty">Waiting on data — {err}</div>')
elif IS_STAGES:
    # Two independent columns (Outside | Within). Each column stacks its own 3
    # stages one under another, so Pending Confirmation sits directly beneath that
    # column's In Process with no cross-column padding/blank space. Every name is
    # shown (no cap). No footer on this view.
    html.append('<div class="stagewrap">')
    for side_label, tone, data in stage_sides:
        side_total = sum(int(c) for _, rws in data for _, c in rws)
        col = [f'<div class="stagecol {tone}">',
               f'<div class="ptitle {tone}">{side_label}<span class="pc">{side_total}</span></div>']
        for stage_label, rws in data:
            stage_total = sum(int(c) for _, c in rws)
            col.append(f'<div class="stage {tone}"><div class="sh">'
                       f'<span class="sl">{stage_label}</span><span class="sc">{stage_total}</span></div>'
                       f'{stage_rows_html(rws)}</div>')
        col.append('</div>')
        html.append("".join(col))
    html.append('</div>')
elif IS_COMBINED:
    html.append('<div class="split">')
    for sub, tone, df in panels:
        total = int(df["tickets"].sum()) if not df.empty else 0
        html.append(f'<div class="panel"><div class="ptitle {tone}">{sub}'
                     f'<span class="pc">{total}</span></div>'
                     f'<div class="rows2 {tone}">{rows_html(df, tone)}</div></div>')
    html.append('</div>')
    foot_right = " &nbsp;·&nbsp; ".join(
        f'<span class="{"gbig" if tone == "good" else "big"}">{int(df["tickets"].sum()) if not df.empty else 0}</span> {sub.lower()}'
        for sub, tone, df in panels)
    html.append(f'<div class="foot"><div>If broken, contact Justin Maccabe</div><div>{foot_right}</div></div>')
else:
    sub, tone, df = panels[0]
    total = int(df["tickets"].sum()) if not df.empty else 0
    if df.empty:
        html.append('<div class="empty">No tickets in this view right now ✓</div>')
    else:
        html.append(f'<div class="rows">{rows_html(df, tone)}</div>')
    html.append(f"""
<div class="foot"><div>If broken, contact Justin Maccabe</div>
<div><span class="big">{total}</span> tickets &nbsp;·&nbsp; <b>{len(df)}</b> people</div></div>""")

html.append('</div>')
final_html = "\n".join(line.lstrip() for line in "\n".join(html).splitlines())
st.markdown(final_html, unsafe_allow_html=True)
