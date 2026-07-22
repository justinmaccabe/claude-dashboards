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

import pandas as pd
import streamlit as st

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
BUILD = "22Jul-ip+pc"

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


def _report_key():
    try:
        k = st.query_params.get("report")
    except Exception:
        k = None
    if k in reports.REPORTS or k in COMBINED:
        return k
    return reports.DEFAULT_REPORT


KEY = _report_key()
IS_COMBINED = KEY in COMBINED
CFG = COMBINED[KEY] if IS_COMBINED else reports.REPORTS[KEY]

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
if not err:
    try:
        if IS_COMBINED:
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
html = ['<div class="board">']
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
