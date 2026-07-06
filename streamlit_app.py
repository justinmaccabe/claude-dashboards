"""Claude ops dashboards — Support-team leaderboards for the office TVs.

One app, three boards selected by ?report= :
  ?report=open-outside        Open Support Tickets Outside SLA        (2b+2c+2d)
  ?report=completed-outside    Tickets Completed Last 7 Days - Outside SLA  (2e+2g+2i)
  ?report=completed-within     Tickets Completed Last 7 Days - Within SLA   (2f+2h+2j)

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

# --- which board? ----------------------------------------------------------
def _report_key():
    try:
        k = st.query_params.get("report")
    except Exception:
        k = None
    return k if k in reports.REPORTS else reports.DEFAULT_REPORT


KEY = _report_key()
CFG = reports.REPORTS[KEY]

st.set_page_config(page_title=f"{CFG['title']} — Optimize", page_icon="◆",
                   layout="wide", initial_sidebar_state="collapsed")

try:
    from streamlit_autorefresh import st_autorefresh
    st_autorefresh(interval=60_000, key="tick")
except Exception:
    pass

NAVY = "#2B3A4E"
NAVY_LINE = "rgba(255,255,255,.07)"
ORANGE = "#C97B30"
TEAL = "#5E8A7E"
INK = "#FFFFFF"
MUTED = "#9CB0C2"


def _token():
    tok = os.environ.get("HUBSPOT_TOKEN")
    if not tok:
        try:
            tok = st.secrets.get("HUBSPOT_TOKEN")
        except Exception:
            tok = None
    return tok


@st.cache_data(ttl=900, show_spinner=False)
def _fetch(report_key: str, _tok_tail: str):
    """Query HubSpot at most once per 15 min per board. Returns (counts, fetched_at)."""
    from hubspot_client import HubSpot
    counts = reports.REPORTS[report_key]["build"](HubSpot(token=_token()))
    return counts, dt.datetime.now(dt.timezone.utc)


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
.rows {{ flex:0 0 auto; column-count:3; column-gap:1.5rem; margin-top:1.3rem; }}
.row {{ break-inside:avoid; display:flex; align-items:center; gap:.6rem; background:rgba(255,255,255,.05);
        border-radius:11px; padding:.6rem .85rem; margin-bottom:.6rem; border-left:3px solid transparent; }}
.row.top {{ border-left-color:{ORANGE}; background:rgba(201,123,48,.12); }}
.row .rank {{ flex:0 0 1.9rem; font-family:'Lora',serif; font-size:1.3rem; color:{MUTED}; text-align:right; }}
.row.top .rank {{ color:{ORANGE}; }}
.row .name {{ flex:1 1 auto; min-width:0; font-size:1.35rem; font-weight:600; white-space:nowrap; overflow:hidden; text-overflow:ellipsis; }}
.row .bar {{ flex:0 0 100px; height:14px; border-radius:7px; background:rgba(255,255,255,.08); overflow:hidden; }}
.row .bar i {{ display:block; height:100%; border-radius:7px; }}
.row .n {{ flex:0 0 2.7rem; text-align:right; font-family:'Lora',serif; font-weight:700; font-size:1.7rem; }}
.foot {{ flex:0 0 auto; margin-top:auto; display:flex; justify-content:space-between; align-items:center;
         padding-top:.8rem; border-top:1px solid rgba(255,255,255,.12); color:{MUTED}; font-size:.84rem; }}
.foot b {{ color:{INK}; }}
.foot .big {{ font-family:'Lora',serif; color:{ORANGE}; font-size:1.5rem; vertical-align:-2px; }}
.empty {{ flex:1 1 auto; display:flex; align-items:center; justify-content:center; color:{MUTED}; font-size:1.1rem; }}
</style>
""", unsafe_allow_html=True)


def bar_color(n, mx):
    frac = (n / mx) if mx else 0
    if frac >= 0.45:
        return "#B85C2A"
    if frac >= 0.15:
        return ORANGE
    return "#D8A65E"


# --- data ------------------------------------------------------------------
now = dt.datetime.now(TZ)
counts, captured, err = {}, None, None
tok = _token()
if not tok:
    err = "No HUBSPOT_TOKEN configured"
else:
    try:
        counts, captured = _fetch(KEY, tok[-8:])
    except Exception as e:
        err = str(e)

df = (pd.DataFrame(sorted(counts.items(), key=lambda kv: (-kv[1], kv[0])),
                   columns=["person", "tickets"])
      if counts else pd.DataFrame(columns=["person", "tickets"]))
total = int(df["tickets"].sum()) if not df.empty else 0
mx = int(df["tickets"].max()) if not df.empty else 0

updated_txt = "—"
if captured is not None:
    updated_txt = captured.astimezone(TZ).strftime("%-I:%M %p")

# --- header ----------------------------------------------------------------
html = ['<div class="board">']
html.append(f"""
<div class="hero">{CURVES}
<div class="hero-row">
{logo_markup()}
<div class="headline"><div class="pip"></div><h1>{CFG['title']}</h1><div class="lbl">{CFG['label']}</div></div>
<div class="clock"><div class="t">{now:%-I:%M %p}</div><div class="d">{now:%A, %B %-d, %Y}</div>
<div class="upd">Synced {updated_txt} · every 15 min</div></div>
</div></div>
""")

if err:
    html.append(f'<div class="empty">Waiting on data — {err}</div>')
elif df.empty:
    html.append('<div class="empty">No tickets in this view right now ✓</div>')
else:
    html.append('<div class="rows">')
    rank, last_n = 0, None
    for i, r in df.iterrows():
        n = int(r["tickets"])
        if n != last_n:
            rank = i + 1
            last_n = n
        width = max((n / mx) * 100, 3) if mx else 0
        cls = "row top" if rank <= 3 else "row"
        html.append(f'<div class="{cls}"><div class="rank">{rank}</div>'
                     f'<div class="name">{r["person"]}</div>'
                     f'<div class="bar"><i style="width:{width:.0f}%;background:{bar_color(n, mx)}"></i></div>'
                     f'<div class="n">{n}</div></div>')
    html.append('</div>')

html.append(f"""
<div class="foot"><div>If broken, contact Justin Maccabe</div>
<div><span class="big">{total}</span> tickets &nbsp;·&nbsp; <b>{len(df)}</b> people</div></div>""")
html.append('</div>')

final_html = "\n".join(line.lstrip() for line in "\n".join(html).splitlines())
st.markdown(final_html, unsafe_allow_html=True)
