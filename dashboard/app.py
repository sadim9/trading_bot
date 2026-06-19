"""
dashboard/app.py — Institutional Trading Terminal
Redesigned: Bloomberg-meets-Binance-Pro aesthetic.

Launch:  python -m streamlit run dashboard/app.py
"""

import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import time, warnings
warnings.filterwarnings("ignore")

import pandas as pd
import numpy as np
import streamlit as st
from datetime import datetime, timezone

# ── Authentication guard — must come BEFORE any other Streamlit content ───────
# Page config is set below (must be first Streamlit call), then auth is checked.
# The require_auth() call will stop rendering and show the login form if the
# user is not authenticated.
from dashboard.auth import require_auth, logout, get_api_client
from dashboard.settings_store import (
    load_settings, apply_settings_to_session, save_settings,
    fmt_local_time, now_local_str, tz_label, get_tz_offset
)

# ── Helpers ────────────────────────────────────────────────────────────────────
def _local_now():
    from datetime import datetime, timezone, timedelta
    import streamlit as st
    offset = float(st.session_state.get("tz_offset_hours", 3.0))
    local_tz = timezone(timedelta(hours=offset))
    return datetime.now(timezone.utc).astimezone(local_tz)

def _fmt_local(dt_str: str) -> str:
    """Format UTC timestamp using user's local timezone offset."""
    return fmt_local_time(dt_str, "%H:%M:%S")

# ── Page config — MUST be first Streamlit call ────────────────────────────────
st.set_page_config(
    page_title="APEX TERMINAL",
    page_icon="▲",
    layout="wide",
    initial_sidebar_state="collapsed",
)

# ── Enforce authentication ─────────────────────────────────────────────────────
require_auth()   # will st.stop() and show login form if not logged in

# ── Load persisted settings from disk ─────────────────────────────────────────
_persisted_settings = load_settings()
apply_settings_to_session(_persisted_settings)

# ── Logout button + theme toggle in top-right corner ──────────────────────────
_user_info = st.session_state.get("_auth_user", {})
with st.container():
    col_spacer, col_user, col_theme, col_logout = st.columns([7.5, 1.5, 0.5, 0.5])
    with col_user:
        st.caption(f"👤 {_user_info.get('username', '')}  [{_user_info.get('role', '')}]")
    with col_theme:
        _cur_theme = st.session_state.get("theme", "light")
        _theme_icon = "☾" if _cur_theme == "light" else "☀"
        _theme_help = "Switch to Dark mode" if _cur_theme == "light" else "Switch to Light mode"
        if st.button(_theme_icon, help=_theme_help, key="_theme_btn"):
            st.session_state["theme"] = "dark" if _cur_theme == "light" else "light"
            st.rerun()
    with col_logout:
        if st.button("⏏", help="Sign out", key="_logout_btn"):
            logout()

# ═══════════════════════════════════════════════════════════════════════════════
#  DESIGN SYSTEM — IBM Plex Mono + Institutional Terminal (Dark default)
# ═══════════════════════════════════════════════════════════════════════════════
st.markdown("""
<style>
@import url('https://fonts.googleapis.com/css2?family=IBM+Plex+Mono:wght@300;400;500;600;700&family=IBM+Plex+Sans:wght@300;400;500;600;700&display=swap');

/* ── CSS Variables — Dark Theme (base/fallback) ── */
:root {
  --bg-base:    #080D1A;
  --bg-surface: #0C1322;
  --bg-card:    #101827;
  --bg-hover:   #141E2E;
  --border:     #1A2540;
  --border-lit: #2A3F6F;
  --border-acc: #3A5590;
  --text-pri:   #DCE4F5;
  --text-sec:   #7A8BA8;
  --text-mute:  #3A4A62;
  --green:      #00C9A7;
  --green-dim:  rgba(0,201,167,0.12);
  --red:        #FF4560;
  --red-dim:    rgba(255,69,96,0.12);
  --amber:      #FFB800;
  --amber-dim:  rgba(255,184,0,0.10);
  --blue:       #4B9FFF;
  --blue-dim:   rgba(75,159,255,0.10);
  --purple:     #9B6DFF;
  --mono:       'IBM Plex Mono', monospace;
  --sans:       'IBM Plex Sans', sans-serif;
}

/* ── Global reset ── */
html, body, [class*="css"], .stApp {
  font-family: var(--mono) !important;
  background-color: var(--bg-base) !important;
  color: var(--text-pri) !important;
}
.stApp { background: var(--bg-base); }
.block-container { padding: 0 !important; max-width: 100% !important; }

/* ── Scrollbar ── */
::-webkit-scrollbar { width: 4px; height: 4px; }
::-webkit-scrollbar-track { background: var(--bg-base); }
::-webkit-scrollbar-thumb { background: var(--border-lit); border-radius: 2px; }

/* ── Sidebar ── */
[data-testid="stSidebar"] {
  background: var(--bg-surface) !important;
  border-right: 1px solid var(--border) !important;
}

/* ── Hide Streamlit chrome ── */
#MainMenu, footer, header, [data-testid="stDecoration"],
[data-testid="stToolbar"], .reportview-container .main .block-container > div:first-child { visibility: hidden; height: 0; }

/* ── Prevent chart/content dimming during auto-refresh reruns ── */
.stApp [data-testid="stPlotlyChart"],
.stApp [data-testid="element-container"],
.stApp .element-container,
.stApp iframe {
  opacity: 1 !important;
  pointer-events: auto !important;
  transition: none !important;
}
/* Suppress Streamlit's running-state overlay and spinner */
[data-testid="stStatusWidget"] { display: none !important; }
.stSpinner > div { display: none !important; }

/* ── Metrics ── */
[data-testid="metric-container"] {
  background: var(--bg-card) !important;
  border: 1px solid var(--border) !important;
  border-radius: 4px !important;
  padding: 10px 14px !important;
  transition: border-color 0.2s;
}
[data-testid="metric-container"]:hover { border-color: var(--border-lit) !important; }
[data-testid="metric-container"] label {
  color: var(--text-sec) !important;
  font-size: 9px !important;
  letter-spacing: 0.12em !important;
  text-transform: uppercase !important;
  font-family: var(--mono) !important;
}
[data-testid="metric-container"] [data-testid="metric-value"] {
  color: var(--text-pri) !important;
  font-size: 17px !important;
  font-weight: 600 !important;
  font-family: var(--mono) !important;
}
[data-testid="metric-container"] [data-testid="metric-delta"] {
  font-size: 11px !important;
  font-family: var(--mono) !important;
}

/* ── Tabs ── */
[data-testid="stTabs"] { gap: 0; }
[data-testid="stTabs"] > div:first-child {
  border-bottom: 1px solid var(--border) !important;
  gap: 0;
}
[data-testid="stTabs"] button {
  background: transparent !important;
  color: var(--text-sec) !important;
  border: none !important;
  border-bottom: 2px solid transparent !important;
  border-radius: 0 !important;
  font-family: var(--mono) !important;
  font-size: 11px !important;
  letter-spacing: 0.08em !important;
  padding: 10px 18px !important;
  text-transform: uppercase !important;
  transition: all 0.15s !important;
}
[data-testid="stTabs"] button:hover { color: var(--text-pri) !important; }
[data-testid="stTabs"] button[aria-selected="true"] {
  color: var(--blue) !important;
  border-bottom-color: var(--blue) !important;
}

/* ── Inputs ── */
input, textarea, select, [data-baseweb="select"] > div {
  background: var(--bg-card) !important;
  border-color: var(--border) !important;
  color: var(--text-pri) !important;
  font-family: var(--mono) !important;
  font-size: 12px !important;
}
input:focus, textarea:focus { border-color: var(--border-lit) !important; box-shadow: 0 0 0 1px var(--border-lit) !important; }

/* ── Buttons ── */
[data-testid="baseButton-primary"] {
  background: var(--blue) !important;
  color: #000 !important;
  border: none !important;
  font-family: var(--mono) !important;
  font-size: 11px !important;
  font-weight: 600 !important;
  letter-spacing: 0.06em !important;
  text-transform: uppercase !important;
  border-radius: 3px !important;
  transition: opacity 0.15s !important;
}
[data-testid="baseButton-primary"]:hover { opacity: 0.85 !important; }
[data-testid="baseButton-secondary"] {
  background: #1E2D45 !important;
  border: 1px solid #2A3F6F !important;
  color: #DCE4F5 !important;
  font-family: 'IBM Plex Mono', monospace !important;
  font-size: 11px !important;
  font-weight: 500 !important;
  letter-spacing: 0.06em !important;
  border-radius: 3px !important;
}
[data-testid="baseButton-secondary"]:hover { background: #243450 !important; border-color: #3A5590 !important; color: #fff !important; }

/* ── Selectbox + Popover dropdown (all modes) ── */
[data-baseweb="select"] { font-family: var(--mono) !important; }
[data-baseweb="popover"] {
  background: var(--bg-card) !important;
  border: 1px solid var(--border-lit) !important;
}
[data-baseweb="popover"] * { color: var(--text-pri) !important; background: var(--bg-card) !important; }
[data-baseweb="menu"]     { background: var(--bg-card) !important; }
[data-baseweb="option"]   { background: var(--bg-card) !important; color: var(--text-pri) !important; }
[data-baseweb="option"]:hover { background: var(--bg-hover) !important; color: var(--text-pri) !important; }
li[role="option"]         { background: var(--bg-card) !important; color: var(--text-pri) !important; }
li[role="option"]:hover   { background: var(--bg-hover) !important; }

/* ── Slider ── */
[data-testid="stSlider"] > div > div > div { background: var(--border-lit) !important; }
[data-testid="stSlider"] > div > div > div > div { background: var(--blue) !important; }

/* ── Toggle ── */
[data-testid="stToggle"] > label { font-family: var(--mono) !important; font-size: 11px !important; color: var(--text-sec) !important; }

/* ── Expander ── */
[data-testid="stExpander"] {
  border: 1px solid var(--border) !important;
  border-radius: 4px !important;
  background: var(--bg-card) !important;
}
[data-testid="stExpander"] summary { font-family: var(--mono) !important; font-size: 11px !important; color: var(--text-sec) !important; }

/* ── Dataframe ── */
[data-testid="stDataFrame"] { font-family: var(--mono) !important; font-size: 11px !important; }
[data-testid="stDataFrame"] th { background: var(--bg-surface) !important; color: var(--text-sec) !important; font-size: 9px !important; letter-spacing: 0.1em !important; text-transform: uppercase !important; }
[data-testid="stDataFrame"] td { color: var(--text-pri) !important; }

/* ── Divider ── */
hr { border-color: var(--border) !important; margin: 6px 0 !important; }

/* ── Toast ── */
[data-testid="stToast"] { background: var(--bg-card) !important; border: 1px solid var(--border-lit) !important; font-family: var(--mono) !important; }

/* ── Caption / small text ── */
[data-testid="stCaptionContainer"] { font-family: var(--mono) !important; font-size: 10px !important; color: var(--text-mute) !important; }

/* ── Warning / info / error ── */
[data-testid="stAlert"] { font-family: var(--mono) !important; font-size: 11px !important; border-radius: 4px !important; }

/* ── CUSTOM COMPONENTS ── */

/* Header bar */
.qt-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  background: var(--bg-surface);
  border-bottom: 1px solid var(--border);
  padding: 0 20px;
  height: 52px;
}
.qt-logo {
  font-family: var(--mono);
  font-size: 15px;
  font-weight: 700;
  letter-spacing: 0.2em;
  color: var(--text-pri);
}
.qt-logo span { color: var(--blue); }
.qt-header-right { display: flex; align-items: center; gap: 20px; font-size: 10px; color: var(--text-sec); letter-spacing: 0.08em; font-family: var(--mono); }
.qt-live-dot { width: 6px; height: 6px; border-radius: 50%; background: var(--green); display: inline-block; margin-right: 6px; animation: pulse-dot 2s infinite; }
@keyframes pulse-dot { 0%,100%{opacity:1;transform:scale(1)} 50%{opacity:0.5;transform:scale(0.8)} }

/* Signal card */
.qt-signal {
  border-radius: 6px;
  padding: 18px 20px;
  margin-bottom: 12px;
  position: relative;
  overflow: hidden;
}
.qt-signal::before {
  content: '';
  position: absolute;
  top: 0; left: 0; right: 0;
  height: 2px;
}
.qt-signal-buy   { background: var(--green-dim); border: 1px solid rgba(0,201,167,0.3); }
.qt-signal-sell  { background: var(--red-dim);   border: 1px solid rgba(255,69,96,0.3); }
.qt-signal-hold  { background: var(--amber-dim); border: 1px solid rgba(255,184,0,0.25); }
.qt-signal-buy::before  { background: linear-gradient(90deg, var(--green), transparent); }
.qt-signal-sell::before { background: linear-gradient(90deg, var(--red), transparent); }
.qt-signal-hold::before { background: linear-gradient(90deg, var(--amber), transparent); }
.qt-signal-label {
  font-size: 26px;
  font-weight: 700;
  letter-spacing: 0.12em;
  font-family: var(--mono);
  display: flex;
  align-items: center;
  gap: 10px;
}
.qt-signal-meta { font-size: 10px; color: var(--text-sec); letter-spacing: 0.08em; margin-top: 4px; font-family: var(--mono); }
.qt-pulse {
  width: 10px; height: 10px; border-radius: 50%;
  animation: qt-ping 1.4s cubic-bezier(0,0,0.2,1) infinite;
  flex-shrink: 0;
}
@keyframes qt-ping {
  0%  { transform: scale(1); opacity: 1; }
  75%,100% { transform: scale(1.8); opacity: 0; }
}

/* Score bar */
.qt-score-row { margin: 5px 0; }
.qt-score-label {
  display: flex;
  justify-content: space-between;
  font-size: 10px;
  font-family: var(--mono);
  color: var(--text-sec);
  margin-bottom: 3px;
  letter-spacing: 0.05em;
}
.qt-score-track {
  height: 3px;
  background: var(--border);
  border-radius: 2px;
  overflow: hidden;
  position: relative;
}
.qt-score-fill {
  height: 100%;
  border-radius: 2px;
  transition: width 0.4s ease;
}

/* Alert item */
.qt-alert {
  border-radius: 4px;
  padding: 9px 12px;
  margin: 4px 0;
  border-left: 3px solid;
  font-family: var(--mono);
  font-size: 10px;
  line-height: 1.5;
}
.qt-alert-buy  { background: var(--green-dim); border-left-color: var(--green); }
.qt-alert-sell { background: var(--red-dim);   border-left-color: var(--red); }
.qt-alert-info { background: var(--blue-dim);  border-left-color: var(--blue); }
.qt-alert-title { font-weight: 600; font-size: 11px; }
.qt-alert-time  { color: var(--text-mute); font-size: 9px; float: right; }

/* Section header */
.qt-section {
  font-family: var(--mono);
  font-size: 9px;
  letter-spacing: 0.18em;
  text-transform: uppercase;
  color: var(--text-mute);
  padding: 8px 0 6px;
  border-bottom: 1px solid var(--border);
  margin-bottom: 10px;
}

/* Price level row */
.qt-level-row {
  display: flex;
  justify-content: space-between;
  padding: 6px 10px;
  border-radius: 3px;
  margin: 3px 0;
  font-family: var(--mono);
  font-size: 11px;
}
.qt-level-entry { background: rgba(255,184,0,0.07); border: 1px solid rgba(255,184,0,0.2); }
.qt-level-sl    { background: rgba(255,69,96,0.07);  border: 1px solid rgba(255,69,96,0.2); }
.qt-level-tp    { background: rgba(0,201,167,0.07);  border: 1px solid rgba(0,201,167,0.2); }

/* Ticker strip */
.qt-ticker {
  display: flex;
  gap: 0;
  overflow-x: auto;
  background: var(--bg-surface);
  border-bottom: 1px solid var(--border);
  padding: 0;
  scrollbar-width: none;
}
.qt-ticker::-webkit-scrollbar { display: none; }
.qt-ticker-item {
  padding: 8px 20px;
  border-right: 1px solid var(--border);
  white-space: nowrap;
  font-family: var(--mono);
  font-size: 11px;
  cursor: pointer;
  transition: background 0.15s;
  flex-shrink: 0;
}
.qt-ticker-item:hover { background: var(--bg-hover); }
.qt-ticker-sym  { color: var(--text-sec); font-size: 9px; letter-spacing: 0.1em; display: block; }
.qt-ticker-px   { color: var(--text-pri); font-weight: 600; }
.qt-ticker-chg  { font-size: 10px; }
.qt-ticker-up   { color: var(--green); }
.qt-ticker-dn   { color: var(--red); }

/* KPI strip */
.qt-kpi-strip {
  display: grid;
  grid-template-columns: repeat(6, 1fr);
  gap: 6px;
  padding: 10px 16px;
  background: var(--bg-surface);
  border-bottom: 1px solid var(--border);
}
.qt-kpi-card {
  background: var(--bg-card);
  border: 1px solid var(--border);
  border-radius: 4px;
  padding: 8px 12px;
  transition: border-color 0.2s;
}
.qt-kpi-card:hover { border-color: var(--border-lit); }
.qt-kpi-label { font-size: 8px; letter-spacing: 0.15em; text-transform: uppercase; color: var(--text-mute); margin-bottom: 3px; }
.qt-kpi-value { font-size: 15px; font-weight: 600; color: var(--text-pri); font-family: var(--mono); }
.qt-kpi-delta { font-size: 9px; margin-top: 1px; font-family: var(--mono); }
.qt-kpi-up   { color: var(--green); }
.qt-kpi-dn   { color: var(--red); }
.qt-kpi-neu  { color: var(--text-sec); }

/* Main layout */
.qt-main { display: flex; gap: 0; height: calc(100vh - 165px); overflow: hidden; }
.qt-chart-area { flex: 1; min-width: 0; border-right: 1px solid var(--border); overflow: hidden; display: flex; flex-direction: column; }
.qt-panel { width: 320px; flex-shrink: 0; overflow-y: auto; padding: 12px; background: var(--bg-surface); display: flex; flex-direction: column; gap: 0; }
.qt-chart-header { padding: 8px 14px; border-bottom: 1px solid var(--border); background: var(--bg-surface); display: flex; align-items: center; justify-content: space-between; }
.qt-chart-title { font-size: 13px; font-weight: 600; font-family: var(--mono); letter-spacing: 0.04em; }
.qt-chart-sub { font-size: 10px; color: var(--text-sec); font-family: var(--mono); }

/* Staleness bar */
.qt-status-bar {
  display: flex;
  align-items: center;
  gap: 16px;
  padding: 4px 16px;
  background: var(--bg-base);
  border-bottom: 1px solid var(--border);
  font-family: var(--mono);
  font-size: 9px;
  color: var(--text-mute);
  letter-spacing: 0.08em;
  overflow-x: auto;
  white-space: nowrap;
  scrollbar-width: none;
}
.qt-status-bar::-webkit-scrollbar { display: none; }
.qt-status-live { color: var(--green); }
.qt-status-stale { color: var(--red); }

/* ── Pinned Ticker Tabs ── */
.qt-ticker-tabs {
  display: flex;
  align-items: stretch;
  background: var(--bg-surface);
  border-bottom: 1px solid var(--border);
  overflow-x: auto;
  scrollbar-width: none;
  padding: 0 8px;
  gap: 2px;
}
.qt-ticker-tabs::-webkit-scrollbar { display: none; }
.qt-ticker-tab {
  display: flex;
  flex-direction: column;
  align-items: flex-start;
  justify-content: center;
  padding: 6px 14px 4px;
  border-bottom: 2px solid transparent;
  cursor: pointer;
  white-space: nowrap;
  font-family: var(--mono);
  transition: all 0.15s;
  min-width: 80px;
  position: relative;
}
.qt-ticker-tab:hover { background: var(--bg-hover); }
.qt-ticker-tab.active {
  border-bottom-color: var(--blue);
  background: var(--bg-card);
}
.qt-ticker-tab-sym {
  font-size: 11px;
  font-weight: 600;
  color: var(--text-pri);
  letter-spacing: 0.04em;
}
.qt-ticker-tab-sig {
  font-size: 8px;
  letter-spacing: 0.1em;
  margin-top: 1px;
  font-weight: 600;
}
.qt-ticker-tab-sig.buy  { color: var(--green); }
.qt-ticker-tab-sig.sell { color: var(--red); }
.qt-ticker-tab-sig.hold { color: var(--amber); }
.qt-ticker-tab-sig.none { color: var(--text-mute); }
.qt-ticker-tab-px {
  font-size: 9px;
  color: var(--text-sec);
  margin-top: 1px;
}
.qt-ticker-tab-close {
  position: absolute;
  top: 3px;
  right: 4px;
  font-size: 8px;
  color: var(--text-mute);
  cursor: pointer;
  line-height: 1;
  padding: 1px 3px;
  border-radius: 2px;
}
.qt-ticker-tab-close:hover { color: var(--red); background: var(--red-dim); }
.qt-ticker-tab-add {
  display: flex;
  align-items: center;
  justify-content: center;
  padding: 6px 12px;
  color: var(--text-mute);
  font-size: 16px;
  cursor: pointer;
  border-radius: 3px;
  transition: all 0.15s;
  align-self: center;
}
.qt-ticker-tab-add:hover { color: var(--blue); background: var(--blue-dim); }

/* ── Price Sparkline mini chart ── */
.qt-sparkline-row {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 4px 10px;
  background: var(--bg-card);
  border: 1px solid var(--border);
  border-radius: 4px;
  margin: 6px 0;
}
.qt-sparkline-label { font-size: 9px; color: var(--text-mute); font-family: var(--mono); letter-spacing: 0.1em; }
.qt-sparkline-value { font-size: 12px; font-weight: 600; font-family: var(--mono); color: var(--text-pri); }
.qt-sparkline-delta { font-size: 9px; font-family: var(--mono); }

/* ── Score bar gradient ── */
.qt-score-fill-buy  { background: linear-gradient(90deg, #00C9A7, rgba(0,201,167,0.4)); }
.qt-score-fill-sell { background: linear-gradient(90deg, #FF4560, rgba(255,69,96,0.4)); }
.qt-score-fill-neu  { background: linear-gradient(90deg, #4B9FFF, rgba(75,159,255,0.4)); }

/* ── Mini stats grid (2-col) in panel ── */
.qt-mini-grid {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 4px;
  margin: 6px 0;
}
.qt-mini-stat {
  background: var(--bg-card);
  border: 1px solid var(--border);
  border-radius: 4px;
  padding: 6px 10px;
  font-family: var(--mono);
}
.qt-mini-stat-label { font-size: 8px; color: var(--text-mute); letter-spacing: 0.12em; text-transform: uppercase; }
.qt-mini-stat-value { font-size: 12px; font-weight: 600; color: var(--text-pri); margin-top: 2px; }

/* ── Toolbar responsive ── */
.qt-toolbar-wrap {
  padding: 8px 12px;
  background: var(--bg-surface);
  border-bottom: 1px solid var(--border);
  overflow-x: auto;
  scrollbar-width: none;
}
.qt-toolbar-wrap::-webkit-scrollbar { display: none; }

/* ══════════════════════════════════════════════════════════════
   MOBILE  ≤ 768px  — Professional Terminal Layout
══════════════════════════════════════════════════════════════ */
@media (max-width: 768px) {

  /* ── Global: full-width, no overflow ── */
  html, body, .stApp, section.main, .main {
    overflow-x: hidden !important;
    max-width: 100vw !important;
  }
  .main .block-container {
    padding: 0.25rem 0.5rem !important;
    max-width: 100vw !important;
  }

  /* ── Header ── */
  .qt-header { padding: 0 10px; height: 40px; }
  .qt-logo   { font-size: 12px; letter-spacing: 0.12em; }
  .qt-header-right > span:nth-child(n+2) { display: none; }

  /* ── KPI strip — 2 columns on phone, 3 on small tablet ── */
  .qt-kpi-strip {
    grid-template-columns: repeat(2, 1fr) !important;
    gap: 4px !important;
    padding: 6px 8px !important;
  }
  .qt-kpi-value { font-size: 13px !important; }
  .qt-kpi-label { font-size: 7px !important; letter-spacing: 0.1em !important; }
  .qt-kpi-delta { font-size: 8px !important; }

  /* ── Status bar — horizontal scroll, compact ── */
  .qt-status-bar {
    gap: 10px; padding: 3px 8px; font-size: 8px;
    overflow-x: auto; white-space: nowrap;
  }

  /* ── Pinned ticker tabs — scrollable strip ── */
  .qt-ticker-tabs { padding: 0 2px; gap: 1px; }
  .qt-ticker-tab  { padding: 5px 8px 3px; min-width: 64px; }
  .qt-ticker-tab-sym { font-size: 10px; }
  .qt-ticker-tab-sig { font-size: 7px; }
  .qt-ticker-tab-px  { font-size: 8px; }

  /* ── Streamlit column stacking ── */
  [data-testid="stHorizontalBlock"] {
    flex-direction: column !important;
    gap: 4px !important;
  }
  [data-testid="stHorizontalBlock"] > [data-testid="column"] {
    width: 100% !important; flex: 1 1 100% !important; min-width: 100% !important;
  }

  /* ── Toolbar: allow 2-up pairs instead of full stack ── */
  [data-testid="stHorizontalBlock"].toolbar-row > [data-testid="column"] {
    min-width: 48% !important; flex: 0 0 48% !important;
    width: 48% !important;
  }

  /* ── Tabs bar — horizontal scroll, compact, no wrap ── */
  [data-testid="stTabs"] > div:first-child {
    overflow-x: auto !important;
    -webkit-overflow-scrolling: touch !important;
    flex-wrap: nowrap !important;
    scrollbar-width: none !important;
    border-bottom-width: 1px !important;
  }
  [data-testid="stTabs"] > div:first-child::-webkit-scrollbar { display: none !important; }
  [data-testid="stTabs"] button {
    padding: 8px 10px !important;
    font-size: 9px !important;
    white-space: nowrap !important;
    flex-shrink: 0 !important;
  }

  /* ── Touch-friendly inputs ── */
  input[type="text"], input[type="password"],
  input[type="number"], textarea {
    font-size: 16px !important;   /* prevents iOS Safari auto-zoom */
    min-height: 42px !important;
  }
  [data-baseweb="select"],
  [data-baseweb="select"] > div { min-height: 42px !important; }

  /* ── Buttons — 44px tap target ── */
  [data-testid="baseButton-primary"],
  [data-testid="baseButton-secondary"],
  [data-testid="stFormSubmitButton"] > button {
    min-height: 44px !important;
    font-size: 12px !important;
    width: 100% !important;
  }

  /* ── Charts ── */
  .js-plotly-plot, .plotly, .plot-container {
    width: 100% !important;
    overflow-x: hidden !important;
  }
  /* Remove Plotly modebar on mobile — not useful with touch */
  .modebar-container { display: none !important; }

  /* ── Metrics ── */
  [data-testid="metric-container"] { padding: 7px 10px !important; }
  [data-testid="metric-container"] [data-testid="metric-value"] { font-size: 14px !important; }
  [data-testid="metric-container"] label { font-size: 7px !important; }

  /* ── Dataframe ── */
  [data-testid="stDataFrame"] { overflow-x: auto !important; max-width: 100vw !important; }

  /* ── Expanders ── */
  [data-testid="stExpander"] { width: 100% !important; }
  details > summary { font-size: 11px !important; padding: 10px 0 !important; }

  /* ── Signal cards ── */
  .qt-signal       { padding: 12px 14px !important; }
  .qt-signal-label { font-size: 18px !important; }
  .qt-signal-meta  { font-size: 9px !important; }

  /* ── Level rows ── */
  .qt-level-row { padding: 8px 10px !important; font-size: 11px !important; }

  /* ── Alert cards ── */
  .qt-alert       { padding: 8px 10px !important; }
  .qt-alert-title { font-size: 10px !important; }

  /* ── Mini grid — 1 col on phone ── */
  .qt-mini-grid { grid-template-columns: 1fr !important; }

  /* ── Section headers ── */
  .qt-section { font-size: 8px !important; padding: 6px 0 !important; }

  /* ── Score bars ── */
  .qt-score-label { font-size: 9px !important; }

  /* ── Panel column — full width under chart ── */
  .qt-panel { width: 100% !important; }

  /* ── Sidebar hidden ── */
  [data-testid="stSidebar"] { display: none !important; }

  /* ── Toast ── */
  [data-testid="stToast"] { font-size: 11px !important; max-width: 90vw !important; }
}

/* ══════════════════════════════════════════════════════════════
   SMALL PHONE  ≤ 390px
══════════════════════════════════════════════════════════════ */
@media (max-width: 390px) {
  .qt-kpi-strip {
    grid-template-columns: repeat(2, 1fr) !important;
    padding: 4px !important;
    gap: 3px !important;
  }
  .qt-header-right { display: none !important; }
  .qt-logo         { font-size: 11px; }
  [data-testid="stTabs"] button { padding: 6px 8px !important; font-size: 8px !important; }
  .qt-ticker-tab   { min-width: 56px; padding: 4px 6px 2px; }
  .qt-ticker-tab-sym { font-size: 9px; }
}

/* ══════════════════════════════════════════════════════════════
   SMALL TABLET  769–1024px
══════════════════════════════════════════════════════════════ */
@media (min-width: 769px) and (max-width: 1024px) {
  .main .block-container {
    padding-left: 1rem !important;
    padding-right: 1rem !important;
  }
  .qt-kpi-strip { grid-template-columns: repeat(3, 1fr) !important; }
  [data-testid="stHorizontalBlock"] > [data-testid="column"] {
    min-width: 45% !important;
  }
}

/* ── Desktop — full layouts preserved ── */
@media (min-width: 1025px) {
  .main .block-container {
    padding-left: 1.5rem !important;
    padding-right: 1.5rem !important;
  }
}

/* ── Sticky header on all screen sizes ── */
.qt-header {
  position: sticky !important;
  top: 0 !important;
  z-index: 999 !important;
}

/* ── Prevent horizontal overflow on all screens ── */
html, body {
  overflow-x: hidden !important;
  max-width: 100vw !important;
}
.main, .stApp, section.main {
  overflow-x: hidden !important;
  max-width: 100vw !important;
}
</style>
""", unsafe_allow_html=True)

# ── Theme override — injected dynamically so the last :root wins in the DOM ───
# Light mode is the default. When theme == "light" we override the dark-base
# :root above with high-contrast light values; dark uses the base as-is.
if st.session_state.get("theme", "light") == "light":
    st.markdown("""
<style>
:root {
  --bg-base:    #F2F6FC;
  --bg-surface: #E8EEF8;
  --bg-card:    #FFFFFF;
  --bg-hover:   #DBE4F5;
  --border:     #BDC9DC;
  --border-lit: #879EC2;
  --border-acc: #5278B0;
  --text-pri:   #0B1929;
  --text-sec:   #365070;
  --text-mute:  #7090AE;
  --green:      #00735C;
  --green-dim:  rgba(0,115,92,0.11);
  --red:        #C0001E;
  --red-dim:    rgba(192,0,30,0.09);
  --amber:      #96620A;
  --amber-dim:  rgba(150,98,10,0.10);
  --blue:       #1555A2;
  --blue-dim:   rgba(21,85,162,0.10);
  --purple:     #6030BE;
}

/* ── Light mode: force Streamlit app background ── */
html, body, .stApp, [class*="css"] {
  background-color: #F2F6FC !important;
  color: #0B1929 !important;
}
section.main > div { background: #F2F6FC !important; }

/* ── Light mode: all labels, captions, text visible ── */
label, p, span, div,
[data-testid="stWidgetLabel"],
[data-testid="stCaptionContainer"],
[data-testid="stMarkdownContainer"] p,
[data-testid="stMarkdownContainer"] span,
[data-testid="stText"] {
  color: #0B1929 !important;
}

/* ── Light mode: input / select boxes ── */
input, textarea,
[data-baseweb="select"] > div,
[data-baseweb="input"] > div {
  background: #FFFFFF !important;
  color: #0B1929 !important;
  border-color: #BDC9DC !important;
}
input::placeholder, textarea::placeholder { color: #7090AE !important; }

/* ── Light mode: selectbox dropdown popover + options ── */
[data-baseweb="popover"],
[data-baseweb="popover"] * {
  background: #FFFFFF !important;
  color: #0B1929 !important;
}
[data-baseweb="option"] {
  background: #FFFFFF !important;
  color: #0B1929 !important;
}
[data-baseweb="option"]:hover,
[data-baseweb="option"][aria-selected="true"] {
  background: #DBE4F5 !important;
  color: #0B1929 !important;
}

/* ── Light mode: metric cards ── */
[data-testid="metric-container"] {
  background: #FFFFFF !important;
  border-color: #BDC9DC !important;
}
[data-testid="metric-container"] label { color: #365070 !important; }
[data-testid="metric-container"] [data-testid="metric-value"] { color: #0B1929 !important; }

/* ── Light mode: tabs ── */
[data-testid="stTabs"] button { color: #365070 !important; }
[data-testid="stTabs"] button[aria-selected="true"] { color: #1555A2 !important; border-bottom-color: #1555A2 !important; }
[data-testid="stTabs"] > div:first-child { border-bottom-color: #BDC9DC !important; }

/* ── Light mode: expander ── */
[data-testid="stExpander"] { background: #FFFFFF !important; border-color: #BDC9DC !important; }
[data-testid="stExpander"] summary { color: #365070 !important; }
[data-testid="stExpander"] summary p { color: #365070 !important; }

/* ── Light mode: sidebar ── */
[data-testid="stSidebar"] { background: #E8EEF8 !important; border-right-color: #BDC9DC !important; }

/* ── Light mode: toggle label ── */
[data-testid="stToggle"] > label { color: #365070 !important; }

/* ── Light mode: dataframe ── */
[data-testid="stDataFrame"] th { background: #E8EEF8 !important; color: #365070 !important; }
[data-testid="stDataFrame"] td { color: #0B1929 !important; }

/* ── Light mode: alerts / toasts ── */
[data-testid="stAlert"] { background: #FFFFFF !important; color: #0B1929 !important; }
[data-testid="stToast"] { background: #FFFFFF !important; color: #0B1929 !important; }

/* ── Light mode: scrollbar ── */
::-webkit-scrollbar-track { background: #F2F6FC; }
::-webkit-scrollbar-thumb { background: #879EC2; }

/* ── Light mode: acct-section / account panel cards ── */
.acct-section { background: #FFFFFF !important; border-color: #BDC9DC !important; }
.acct-title   { color: #0B1929 !important; }
.acct-sub     { color: #7090AE !important; }
.acct-how     { background: #E8EEF8 !important; color: #365070 !important; border-left-color: #1555A2 !important; }
.acct-ok      { color: #00735C !important; }
.acct-fail    { color: #C0001E !important; }
.acct-info    { color: #1555A2 !important; }

/* ── Light mode: qt-section headers ── */
.qt-section   { color: #7090AE !important; border-bottom-color: #BDC9DC !important; }
.qt-kpi-label { color: #7090AE !important; }
.qt-kpi-value { color: #0B1929 !important; }
.qt-mini-stat-label { color: #7090AE !important; }
.qt-mini-stat-value { color: #0B1929 !important; }
.qt-score-label     { color: #365070 !important; }
.qt-status-bar      { background: #F2F6FC !important; color: #7090AE !important; border-bottom-color: #BDC9DC !important; }
.qt-status-live     { color: #00735C !important; }
.qt-status-stale    { color: #C0001E !important; }
.qt-ticker-tabs     { background: #E8EEF8 !important; border-bottom-color: #BDC9DC !important; }
.qt-ticker-tab      { color: #0B1929 !important; }
.qt-ticker-tab.active { background: #FFFFFF !important; border-bottom-color: #1555A2 !important; }
.qt-ticker-tab-sym  { color: #365070 !important; }
.qt-ticker-tab-px   { color: #365070 !important; }
.qt-alert-time      { color: #7090AE !important; }
</style>
""", unsafe_allow_html=True)

# ── Imports ────────────────────────────────────────────────────────────────────
from config import CONFIG
from data.ingestion import load_data, generate_sample_data, add_technical_indicators, _period_to_candles
from signals.aggregator import SignalAggregator
from backtest.engine import BacktestEngine
from dashboard.charts import build_chart, PLOTLY_OK, THEME
from dashboard.alerts import AlertEngine, EmailConfig, DiscordConfig, WhatsAppConfig, TelegramConfig
from strategies.ma_cross import MACrossStrategy
from dashboard.broker_panel import render_broker_panel
from dashboard.account_panel import render_account_panel
from dashboard.watchlist import render_watchlist
from dashboard.markov_tab import render_markov_tab
from dashboard.ml_tab import render_ml_tab
from dashboard.crypto_panel import render_crypto_selector, render_24h_ticker, render_quick_switch
from dashboard.commodity_panel import render_commodity_quickpick
from dashboard.trade_journal import render_trade_journal
from data.crypto_feeds import POPULAR_CRYPTO, clear_cache
from data.ingestion import clear_ingestion_cache
from data.commodity_feeds import COMMODITY_SYMBOLS, COMMODITY_YFINANCE_MAP, clear_commodity_cache

try:
    import plotly.graph_objects as go
except ImportError:
    go = None

try:
    import requests as _requests_mod
    REQUESTS_OK = True
except ImportError:
    REQUESTS_OK = False

# ── Session state ──────────────────────────────────────────────────────────────
# Saved defaults override config defaults so the user's last saved ticker is
# restored on every page refresh (fix: previously _def_symbol was ignored here).
_cfg_sym = st.session_state.get("_def_symbol") or CONFIG.data.ui_default_symbol
_cfg_src = st.session_state.get("_def_source") or CONFIG.data.ui_default_source
_cfg_ivl = st.session_state.get("_def_interval") or CONFIG.data.ui_default_interval
_cfg_per = st.session_state.get("_def_period") or CONFIG.data.ui_default_period

_defaults = dict(
    last_refresh=time.time(), prev_signal=None,
    alert_engine=AlertEngine(), df=None, rec=None,  # rebuilt below from persisted settings
    # Use config UI defaults so Settings → Save Defaults takes effect on restart
    symbol=_cfg_sym,   interval=_cfg_ivl, period=_cfg_per, source=_cfg_src,
    # Display theme: "light" is the default
    theme="light",
    bitoasis_connected=False,
    backtest_run=False, backtest_equity=None, backtest_trades=None,
    backtest_metrics=None, historical_signals=[],
    refresh_interval=30, auto_refresh=True, n_candles=200, crypto_limit=1000,
    ma_cross_result=None, show_ma_cross_overlay=True,
    # Strategy mode: "multi" | "markov" | "markov_multi"
    strategy_mode="multi",
    # Markov signal history for chart overlay
    markov_signals=[],
    # ── Multi-ticker pinned tabs ─────────────────────────────────────
    # List of pinned symbols (shown as tabs above the toolbar)
    pinned_tickers=[_cfg_sym],
    # Per-ticker full settings saved at pin time:
    # { symbol: {source, interval, period, strategy_mode, tz_offset_hours} }
    pinned_ticker_settings={},
    # Per-ticker independent state cache:
    # { symbol: {df, rec, signal, entry_price, close_price, last_load, interval, period, source} }
    _tabs_cache={},
)
for k, v in _defaults.items():
    if k not in st.session_state:
        st.session_state[k] = v

# ── Restore alert engine from persisted settings (runs once per session) ────────
if not st.session_state.get("_alert_engine_restored"):
    _dc_url  = st.session_state.get("_discord_webhook_url", "")
    _em_s    = st.session_state.get("_email_sender", "")
    _em_r    = st.session_state.get("_email_recipient", "")
    _wa_ph   = st.session_state.get("_whatsapp_phone", "")
    _wa_key  = st.session_state.get("_whatsapp_api_key", "")
    _tg_t    = st.session_state.get("_telegram_bot_token", "")
    _tg_c    = st.session_state.get("_telegram_chat_id", "")
    if any([_dc_url, _em_s, _wa_ph, _tg_t]):
        from dashboard.alerts import AlertEngine as _AE, EmailConfig, DiscordConfig, WhatsAppConfig, TelegramConfig
        st.session_state["alert_engine"] = _AE(
            email_cfg    = EmailConfig(_em_s, "", _em_r),
            discord_cfg  = DiscordConfig(_dc_url),
            whatsapp_cfg = WhatsAppConfig(_wa_ph, _wa_key),
            telegram_cfg = TelegramConfig(_tg_t, _tg_c),
        )
    st.session_state["_alert_engine_restored"] = True

_DATA_CACHE: dict = {}

def _rebuild_engine(em_s="", em_p="", em_r="", dc_url="", wa_phone="", wa_key="", tg_t="", tg_c=""):
    old = st.session_state.alert_engine
    def _g(nv, *path):
        if nv: return nv
        obj = old
        for p in path:
            obj = getattr(obj, p, "")
        return obj or ""
    st.session_state.alert_engine = AlertEngine(
        email_cfg    = EmailConfig(_g(em_s,"email_cfg","sender_email"), _g(em_p,"email_cfg","sender_password"), _g(em_r,"email_cfg","recipient_email")),
        discord_cfg  = DiscordConfig(_g(dc_url,"discord_cfg","webhook_url")),
        whatsapp_cfg = WhatsAppConfig(_g(wa_phone,"whatsapp_cfg","phone"), _g(wa_key,"whatsapp_cfg","api_key")),
        telegram_cfg = TelegramConfig(_g(tg_t,"telegram_cfg","bot_token"), _g(tg_c,"telegram_cfg","chat_id")),
    )

def _load(symbol, interval, period, source, force=False, crypto_limit=500):
    """
    Fetch market data with a 3-tier fallback chain:
      1. Requested source (binance / yfinance / coingecko / sample)
      2. yfinance with crypto-style symbol (BTC-USD) if primary fails
      3. Synthetic sample data — always succeeds offline

    The critical bug this fixes: load_data() can return an empty DataFrame
    (0 rows) without raising an exception when indicator warmup drops all
    rows.  We detect that here and route to the next fallback.
    """
    key = f"{symbol}_{interval}_{period}_{source}_{crypto_limit}"
    # TTL: short intervals need fresher data. Force re-fetch after TTL.
    interval_ttl = {"1m":30,"5m":30,"15m":45,"1h":60,"4h":120,"1d":300,"1wk":600}
    ttl = interval_ttl.get(interval, 60)
    now = time.time()

    if not force and key in _DATA_CACHE:
        df_c, w_c, ts = _DATA_CACHE[key]
        if now - ts < ttl:
            return df_c, w_c

    last_err = ""

    # Resolve Twelve Data API key from session state / CONFIG
    _td_key = st.session_state.get("_twelvedata_api_key", "") or CONFIG.data.twelvedata_api_key or ""

    # ── Tier 1: requested source ──────────────────────────────────
    # Pass TradingView exchange override if the user has specified one
    _tv_exch = st.session_state.get("_tv_exchange_override") if source == "tradingview" else None
    try:
        df = load_data(symbol, interval=interval, period=period,
                       source=source, crypto_limit=crypto_limit,
                       twelvedata_api_key=_td_key, exchange=_tv_exch)
        if df is not None and len(df) >= 2:
            _DATA_CACHE[key] = (df, None, now)
            return df, None
        last_err = f"TradingView returned no data for {symbol}" + (f" on {_tv_exch}" if _tv_exch else "")
    except Exception as e:
        last_err = str(e)

    # ── Tier 1b: TradingView auto-detect fallback (if user-specified exchange failed) ─
    if source == "tradingview" and _tv_exch is not None:
        try:
            df = load_data(symbol, interval=interval, period=period,
                           source=source, crypto_limit=crypto_limit,
                           twelvedata_api_key=_td_key, exchange=None)
            if df is not None and len(df) >= 2:
                warn = (
                    f"Exchange '{_tv_exch}' returned no data for {symbol} — "
                    f"loaded with auto-detected exchange instead. "
                    f"Check: symbol format (Binance: BTCUSDT), internet "
                    f"or try source = yfinance / sample."
                )
                _DATA_CACHE[key] = (df, warn, now)
                return df, warn
        except Exception as e2:
            last_err += f" | auto-detect also failed: {e2}"

    # ── Tier 2: fallbacks ─────────────────────────────────────────
    _sym_up = symbol.upper()
    _is_commodity = _sym_up in COMMODITY_SYMBOLS or _sym_up in COMMODITY_YFINANCE_MAP

    if source == "twelvedata" and _is_commodity:
        # Twelve Data failed — fall back to yfinance futures (GC=F etc.)
        try:
            df = load_data(_sym_up, interval=interval, period=period, source="yfinance")
            if df is not None and len(df) >= 2:
                warn = "Twelve Data unavailable — showing Yahoo Finance futures data (GC=F proxy)"
                _DATA_CACHE[key] = (df, warn, now)
                return df, warn
        except Exception as e2:
            last_err += f" | yfinance commodity fallback failed: {e2}"

    elif source in ("binance", "coingecko", "bitoasis", "kraken", "kucoin"):
        yf_sym = _sym_up
        for suffix in ("USDT", "BUSD", "BTC", "ETH"):
            if yf_sym.endswith(suffix) and len(yf_sym) > len(suffix):
                yf_sym = yf_sym[:-len(suffix)] + "-USD"
                break
        if not yf_sym.endswith("-USD"):
            yf_sym = yf_sym.rstrip("-") + "-USD"
        try:
            df = load_data(yf_sym, interval=interval, period="2y", source="yfinance")
            if df is not None and len(df) >= 2:
                warn = f"Binance unavailable — showing Yahoo Finance data for {yf_sym}"
                _DATA_CACHE[key] = (df, warn, now)
                return df, warn
        except Exception as e2:
            last_err += f" | yfinance fallback also failed: {e2}"

    # ── Tier 3: synthetic sample data (always works offline) ──────
    try:
        df = add_technical_indicators(generate_sample_data(symbol, n_days=800))
        warn = (
            f"Could not load live data — using synthetic sample data.\n"
            f"Cause: {last_err[:120]}\n"
            f"Check: symbol format (Binance: BTCUSDT), internet connection, "
            f"or try source = yfinance / sample."
        )
        _DATA_CACHE[key] = (df, warn, now)
        return df, warn
    except Exception as e3:
        return None, f"All data sources failed: {last_err} | {e3}"

@st.cache_resource(show_spinner=False)
def _aggregator(cfg_id, strategy_mode: str = "multi"):
    """
    Cache the SignalAggregator by (config-id, strategy-mode).
    The cache is invalidated whenever the strategy mode changes.
    """
    return SignalAggregator(CONFIG, strategy_mode=strategy_mode)

# ═══════════════════════════════════════════════════════════════════════════════
#  HEADER BAR
# ═══════════════════════════════════════════════════════════════════════════════
now_str   = _local_now().strftime("%Y-%m-%d  %H:%M:%S")
_tz_offset_for_clock = float(st.session_state.get("tz_offset_hours", 3.0))
_tz_offset_ms_for_clock = int(_tz_offset_for_clock * 3600 * 1000)
src_label = {
    "kraken":     "KRAKEN — REAL-TIME",
    "kucoin":     "KUCOIN — REAL-TIME",
    "binance":    "BINANCE",
    "yfinance":   "YAHOO FINANCE",
    "twelvedata": "TWELVE DATA — COMMODITIES",
    "bitoasis":   "BITOASIS (AED)",
    "coingecko":  "COINGECKO",
    "sample":     "SAMPLE",
}.get(st.session_state.source, st.session_state.source.upper())

st.markdown(f"""
<div class="qt-header">
  <div class="qt-logo">▲ APEX<span>TERMINAL</span></div>
  <div class="qt-header-right">
    <span><span class="qt-live-dot"></span>LIVE</span>
    <span>SOURCE: {src_label}</span>
    <span>⏱ {now_str}</span>
    <span>⚠️ ANALYSIS ONLY</span>
  </div>
</div>
""", unsafe_allow_html=True)

# ═══════════════════════════════════════════════════════════════════════════════
#  PINNED TICKER TABS
# ═══════════════════════════════════════════════════════════════════════════════
_pinned   = st.session_state.pinned_tickers
_tc       = st.session_state._tabs_cache
_active   = st.session_state.symbol

# Build the HTML tab bar (decorative only — buttons below handle interaction)
_tabs_html = '<div class="qt-ticker-tabs">'
for _t in _pinned:
    _td   = _tc.get(_t, {})
    _sig  = _td.get("signal", "")
    # For the active ticker, always use live session df for price accuracy
    if _t == _active and st.session_state.df is not None and len(st.session_state.df) > 1:
        _df_tab = st.session_state.df
        _px     = float(_df_tab["Close"].iloc[-1])
        _chg    = float((_df_tab["Close"].iloc[-1] / _df_tab["Close"].iloc[-2] - 1) * 100)
        _sig    = st.session_state.rec.signal if st.session_state.rec else _sig
    else:
        _px   = _td.get("close_price", 0)
        _chg  = _td.get("chg_pct", 0)
    _sig_cls  = {"BUY":"buy","SELL":"sell","HOLD":"hold"}.get(_sig, "none")
    _sig_txt  = _sig if _sig else "···"
    _active_cls = " active" if _t == _active else ""
    _px_str   = f"${_px:,.4f}" if _px else ""
    _chg_col  = "var(--green)" if _chg >= 0 else "var(--red)"
    _chg_str  = f'<span style="color:{_chg_col};font-size:8px">{_chg:+.2f}%</span>' if _px else ""
    _tabs_html += (
        f'<div class="qt-ticker-tab{_active_cls}">'
        f'  <span class="qt-ticker-tab-sym">{_t}</span>'
        f'  <span class="qt-ticker-tab-sig {_sig_cls}">{_sig_txt}</span>'
        f'  <span class="qt-ticker-tab-px">{_px_str} {_chg_str}</span>'
        f'</div>'
    )
_tabs_html += '</div>'
st.markdown(_tabs_html, unsafe_allow_html=True)

# Interactive tab row — one button per pinned ticker + an unpin button
_n_pinned = len(_pinned)
if _n_pinned > 0:
    _tab_btns = st.columns(_n_pinned + 1, gap="small")
    for _i, _t in enumerate(_pinned):
        _btn_label = f"{'▶ ' if _t == _active else ''}{_t}"
        _btn_type  = "primary" if _t == _active else "secondary"
        if _tab_btns[_i].button(_btn_label, key=f"_pin_tab_{_t}", type=_btn_type,
                                 use_container_width=True):
            # Save current ticker state before switching
            _tc[st.session_state.symbol] = {
                "df":          st.session_state.df,
                "rec":         st.session_state.rec,
                "signal":      st.session_state.rec.signal if st.session_state.rec else "",
                "close_price": float(st.session_state.df["Close"].iloc[-1]) if st.session_state.df is not None and len(st.session_state.df) > 0 else 0,
                "chg_pct":     float((st.session_state.df["Close"].iloc[-1] / st.session_state.df["Close"].iloc[-2] - 1) * 100) if st.session_state.df is not None and len(st.session_state.df) > 1 else 0,
                "last_load":   time.time(),
                "interval":    st.session_state.interval,
                "period":      st.session_state.period,
                "source":      st.session_state.source,
            }
            st.session_state._tabs_cache = _tc
            # Restore cached state for the clicked ticker (if available)
            if _t != _active:
                _cached      = _tc.get(_t, {})
                _pin_settings = st.session_state.get("pinned_ticker_settings", {})
                _saved        = _pin_settings.get(_t, {})
                st.session_state.symbol = _t
                # ── CRITICAL: sync the toolbar text-input widget key so the
                # next rerun reads the correct symbol, not the previous ticker.
                # Without this, sym_toolbar still holds the old symbol, which
                # causes need_load to revert st.session_state.symbol back.
                st.session_state["sym_toolbar"] = _t
                # Restore saved toolbar settings for this pin
                if _saved.get("source"):
                    st.session_state.source        = _saved["source"]
                    st.session_state.interval      = _saved.get("interval", st.session_state.interval)
                    st.session_state.period        = _saved.get("period",   st.session_state.period)
                    st.session_state.strategy_mode = _saved.get("strategy_mode", st.session_state.strategy_mode)
                    st.session_state.tz_offset_hours = float(_saved.get("tz_offset_hours", st.session_state.get("tz_offset_hours", 3.0)))
                    # Restore TV exchange — set BOTH the logical key AND the
                    # widget's own session-state key so the selectbox renders
                    # the saved exchange without needing a second rerun.
                    _saved_tv = _saved.get("_tv_exchange", "Auto-detect")
                    st.session_state["_tv_exchange"]     = _saved_tv
                    st.session_state["_tv_exchange_sel"] = _saved_tv   # widget key
                    if "_tv_exchange_custom" in _saved:
                        st.session_state["_tv_exchange_custom"] = _saved["_tv_exchange_custom"]
                    if "_tv_exchange_override" in _saved:
                        st.session_state["_tv_exchange_override"] = _saved["_tv_exchange_override"]
                elif _cached.get("df") is not None:
                    # Fall back to runtime cache if no saved settings
                    st.session_state.df       = _cached["df"]
                    st.session_state.rec      = _cached.get("rec")
                    st.session_state.interval = _cached.get("interval", st.session_state.interval)
                    st.session_state.period   = _cached.get("period",   st.session_state.period)
                    st.session_state.source   = _cached.get("source",   st.session_state.source)
                # Always force fresh data load on tab switch
                st.session_state.df = None
                st.rerun()

    # ─ Unpin active ticker button (only show if >1 pinned)
    if _n_pinned > 1:
        if _tab_btns[_n_pinned].button("✕ UNPIN", key="_unpin_btn", use_container_width=True):
            st.session_state.pinned_tickers = [t for t in _pinned if t != _active]
            st.rerun()
    else:
        _tab_btns[_n_pinned].markdown("")   # spacer

# ═══════════════════════════════════════════════════════════════════════════════
#  TOOLBAR ROW
# ═══════════════════════════════════════════════════════════════════════════════
with st.container():
    st.markdown('<div style="padding:8px 12px;background:var(--bg-surface);border-bottom:1px solid var(--border)">', unsafe_allow_html=True)
    t1,t2,t3,t4,t5,t6,t7,t8,t9,t10 = st.columns([2.2,1,1,1.1,1.3,0.7,0.7,0.7,0.7,0.7])

    sym  = t1.text_input("", value=st.session_state.symbol, placeholder="Symbol", label_visibility="collapsed", key="sym_toolbar")
    if st.session_state.source in ("kraken","kucoin","binance","bitoasis"):
        ivl_opts = ["1m","5m","15m","30m","1h","4h","1d","1wk"]
    elif st.session_state.source == "yfinance":
        ivl_opts = ["1m","5m","15m","1h","1d","1wk"]
    elif st.session_state.source == "tradingview":
        ivl_opts = ["1m","3m","5m","15m","30m","1h","2h","4h","1d","1wk"]
    else:
        ivl_opts = ["1h","1d"]
    ivl  = t2.selectbox("", ivl_opts, index=ivl_opts.index(st.session_state.interval) if st.session_state.interval in ivl_opts else 0, label_visibility="collapsed")
    _src_opts = ["kraken","kucoin","yfinance","twelvedata","bitoasis","binance","coingecko","tradingview","sample"]
    src  = t3.selectbox("", _src_opts, index=_src_opts.index(st.session_state.source) if st.session_state.source in _src_opts else 0, label_visibility="collapsed")
    per_opts = ["7d","30d","60d"] if ivl in ("1m","5m","15m") else ["6mo","1y","2y","5y"]
    # Remember the last period per interval group so it survives tab switches
    _per_key = f"_last_per_{ivl}"
    _saved_per = st.session_state.get(_per_key, st.session_state.period)
    _per_idx = per_opts.index(_saved_per) if _saved_per in per_opts else min(1, len(per_opts)-1)
    per  = t4.selectbox("", per_opts, index=_per_idx, label_visibility="collapsed")

    # ── Strategy mode selector ─────────────────────────────────────────────
    _mode_opts  = ["Multi-Strategy", "Markov Chains", "Markov + Multi", "Markov Plus"]
    _mode_vals  = ["multi", "markov", "markov_multi", "markov_plus"]
    _cur_mode   = st.session_state.get("strategy_mode", "multi")
    _mode_idx   = _mode_vals.index(_cur_mode) if _cur_mode in _mode_vals else 0
    _mode_label = t5.selectbox("", _mode_opts, index=_mode_idx, label_visibility="collapsed",
                                help="Select the signal generation strategy")
    strategy_mode = _mode_vals[_mode_opts.index(_mode_label)]

    load_btn  = t6.button("⟳ LOAD",  type="primary",    use_container_width=True)
    auto      = t7.toggle("AUTO",    value=st.session_state.auto_refresh)
    rsec      = t8.selectbox("", [10,30,60,300], index=1, label_visibility="collapsed", format_func=lambda x:f"{x}s")
    clear_btn = t9.button("✕ CACHE", type="secondary", use_container_width=True)

    # ── Auto-save pinned settings for active ticker when toolbar changes ────
    # This ensures switching away and back restores the latest settings, not
    # only the settings that were active at pin time.
    _active_sym = st.session_state.symbol
    if _active_sym in st.session_state.pinned_tickers:
        _pts = st.session_state.get("pinned_ticker_settings", {})
        _saved_pts = _pts.get(_active_sym, {})
        # Effective exchange = custom text > dropdown if not Auto-detect > None
        _pts_tv_sel = st.session_state.get("_tv_exchange_sel",
                        st.session_state.get("_tv_exchange", "Auto-detect"))
        _pts_tv_cust = st.session_state.get("_tv_exchange_custom", "")
        _pts_tv_ov   = (_pts_tv_cust.strip().upper() if _pts_tv_cust.strip()
                        else (None if _pts_tv_sel == "Auto-detect" else _pts_tv_sel))
        _new_pts = {
            "source":              src,
            "interval":            ivl,
            "period":              per,
            "strategy_mode":       strategy_mode,
            "tz_offset_hours":     float(st.session_state.get("tz_offset_hours", 3.0)),
            "_tv_exchange":        _pts_tv_sel,
            "_tv_exchange_custom": _pts_tv_cust,
            "_tv_exchange_override": _pts_tv_ov,
        }
        if _saved_pts != _new_pts:
            _pts[_active_sym] = _new_pts
            st.session_state["pinned_ticker_settings"] = _pts
            save_settings()

    # ── PIN button — add current symbol to pinned tabs ─────────────────────
    _already_pinned = sym.strip().upper() in [p.upper() for p in st.session_state.pinned_tickers]
    _pin_label = "✓ PINNED" if _already_pinned else "📌 PIN"
    _pin_clicked = t10.button(_pin_label, type="secondary", use_container_width=True,
                               help="Pin this symbol as a quick-access tab")
    if _pin_clicked and not _already_pinned:
        _new_sym = sym.strip().upper() or sym.strip()
        if _new_sym and _new_sym not in st.session_state.pinned_tickers:
            st.session_state.pinned_tickers = st.session_state.pinned_tickers + [_new_sym]
            # Save full toolbar settings for this pin so they restore on click
            _pin_settings = st.session_state.get("pinned_ticker_settings", {})
            _pin_tv_sel  = st.session_state.get("_tv_exchange_sel",
                             st.session_state.get("_tv_exchange", "Auto-detect"))
            _pin_tv_cust = st.session_state.get("_tv_exchange_custom", "")
            _pin_tv_ov   = (_pin_tv_cust.strip().upper() if _pin_tv_cust.strip()
                            else (None if _pin_tv_sel == "Auto-detect" else _pin_tv_sel))
            _pin_settings[_new_sym] = {
                "source":              src,
                "interval":            ivl,
                "period":              per,
                "strategy_mode":       strategy_mode,
                "tz_offset_hours":     float(st.session_state.get("tz_offset_hours", 3.0)),
                "_tv_exchange":        _pin_tv_sel,
                "_tv_exchange_custom": _pin_tv_cust,
                "_tv_exchange_override": _pin_tv_ov,
            }
            st.session_state["pinned_ticker_settings"] = _pin_settings
            save_settings()
            st.toast(f"Pinned {_new_sym} with {src}/{ivl}/{per}/{strategy_mode}")
            st.rerun()

    st.markdown('</div>', unsafe_allow_html=True)

# ── TradingView exchange selector ─────────────────────────────────────────────
# Shows a compact row below the toolbar when TradingView is the selected source.
# Auto-detect covers most common symbols; exotic ones may need an explicit exchange.
if src == "tradingview":
    _tv_exch_presets = [
        "Auto-detect", "NASDAQ", "NYSE", "AMEX", "BINANCE", "KRAKEN",
        "OANDA", "TVC", "DJ", "SP500", "NSE", "BSE", "LSE",
    ]
    _saved_tv_exch = st.session_state.get("_tv_exchange", "Auto-detect")
    _tv_exch_idx = _tv_exch_presets.index(_saved_tv_exch) if _saved_tv_exch in _tv_exch_presets else 0
    _tvc1, _tvc2, _tvc3 = st.columns([1.2, 2, 5.8])
    _tvc1.markdown(
        '<div style="font-family:monospace;font-size:10px;color:#4a5a7a;padding-top:8px">TV EXCHANGE</div>',
        unsafe_allow_html=True,
    )
    _tv_exch_sel = _tvc2.selectbox(
        "", _tv_exch_presets, index=_tv_exch_idx,
        label_visibility="collapsed", key="_tv_exchange_sel",
        help="TradingView exchange/market. Auto-detect works for most symbols. "
             "Override if you get 'no data' errors — e.g. NASDAQ for US stocks, TVC for gold/oil.",
    )
    # _tv_exchange_custom is in _PERSIST_KEYS — apply_settings_to_session sets it
    # before this widget renders, so Streamlit reads session_state automatically.
    # Do NOT provide value= here or Streamlit ≥1.35 raises StreamlitAPIException.
    st.session_state.setdefault("_tv_exchange_custom", "")
    _tv_custom_exch = _tvc3.text_input(
        "", placeholder="Or type a custom exchange: EURONEXT, SGX, TSX, MOEX ...",
        label_visibility="collapsed", key="_tv_exchange_custom",
    )
    # Custom text field takes priority; dropdown value used if not Auto-detect
    _tv_exchange_override = (
        _tv_custom_exch.strip().upper() if _tv_custom_exch.strip()
        else (None if _tv_exch_sel == "Auto-detect" else _tv_exch_sel)
    )
    # Persist whenever the selection changes.
    # NOTE: widget key "_tv_exchange_custom" means Streamlit sets
    # st.session_state["_tv_exchange_custom"] = current_value BEFORE user code
    # runs, so comparing session_state vs _tv_custom_exch is always equal.
    # Use a separate "_tv_exchange_custom_saved" key to track what was last
    # written to disk and compare against that instead.
    _tv_exch_changed = (
        st.session_state.get("_tv_exchange") != _tv_exch_sel
        or st.session_state.get("_tv_exchange_custom_saved", "__unset__") != _tv_custom_exch
        or st.session_state.get("_tv_exchange_override") != _tv_exchange_override
    )
    st.session_state["_tv_exchange"]          = _tv_exch_sel
    st.session_state["_tv_exchange_override"] = _tv_exchange_override
    if _tv_exch_changed:
        st.session_state["_tv_exchange_custom_saved"] = _tv_custom_exch
        save_settings()

# Hint about BitOasis credentials
if src == "bitoasis" and not st.session_state.get("bitoasis_connected"):
    st.warning("⚠️ BitOasis selected — enter your API credentials in the **⚙ ACCOUNTS** tab, then click **Connect & Test**.", icon="🔑")

# Hint about Twelve Data key
if src == "twelvedata":
    _td_key_check = st.session_state.get("_twelvedata_api_key", "") or CONFIG.data.twelvedata_api_key or ""
    if not _td_key_check:
        st.warning(
            "⚠️ **Twelve Data** selected — enter your free API key in the **⚙ ACCOUNTS** tab "
            "under *Free API Keys*. Get one at **twelvedata.com** (800 credits/day, no credit card).",
            icon="🔑"
        )

# ── Commodity quick-picker (shown when source is yfinance or twelvedata) ──────
_show_commodity_bar = src in ("yfinance", "twelvedata")
if _show_commodity_bar:
    _td_key_for_panel = st.session_state.get("_twelvedata_api_key", "") or CONFIG.data.twelvedata_api_key or ""
    _cqp_clicked = render_commodity_quickpick(
        current_symbol=sym,
        source=src,
        api_key=_td_key_for_panel,
    )
    if _cqp_clicked:
        st.session_state["symbol"]      = _cqp_clicked
        st.session_state["sym_toolbar"] = _cqp_clicked  # sync toolbar widget
        st.session_state["source"] = src
        st.session_state["df"]     = None
        st.rerun()

st.session_state.auto_refresh      = auto
st.session_state.refresh_interval  = rsec
st.session_state.strategy_mode     = strategy_mode
st.session_state[f"_last_per_{ivl}"] = per   # remember period per interval

if clear_btn:
    _DATA_CACHE.clear()
    clear_cache()
    clear_commodity_cache()
    st.toast("Cache cleared")

# ── Load trigger ───────────────────────────────────────────────────────────────
_mode_changed = strategy_mode != st.session_state.get("_last_strategy_mode")
need_load = (
    load_btn or st.session_state.df is None
    or sym != st.session_state.symbol
    or ivl != st.session_state.interval
    or src != st.session_state.source
    or per != st.session_state.period
    or _mode_changed
    or (auto and time.time() - st.session_state.last_refresh > rsec)
)

if need_load:
    st.session_state.symbol = sym; st.session_state.interval = ivl
    st.session_state.period = per; st.session_state.source   = src
    st.session_state["_last_strategy_mode"] = strategy_mode
    # Detect parameter changes (symbol / source / interval / period)
    _params_changed = (
        sym != st.session_state.get("_last_sym")
        or src != st.session_state.get("_last_src")
        or ivl != st.session_state.get("_last_ivl")
        or per != st.session_state.get("_last_per")
    )
    is_manual = load_btn or _params_changed
    # Only purge caches on explicit LOAD button, CLEAR CACHE button, or genuine
    # parameter change.  Auto-refresh and tab-switch (df=None) use the TTL cache
    # so repeated refreshes don't hammer the network on every rerun.
    if load_btn or clear_btn or _params_changed:
        _DATA_CACHE.clear()
        clear_cache()
        clear_ingestion_cache()
        clear_commodity_cache()
    # Always request at least 1000 bars for Binance so indicator warmup
    # never drops all rows (EMA/RSI/BB each need ≥20 bars to initialise)
    # Derive candle count from the selected period + interval so the chart
    # always shows the full requested time range (fixes "data capped at <1 day")
    # twelvedata uses outputsize internally via _period_to_candles in commodity_feeds
    _period_lim = _period_to_candles(per, ivl)
    if src == "kraken":
        lim = max(_period_lim, 200)   # min 200 bars for indicator warmup
    elif src == "kucoin":
        lim = max(_period_lim, 200)
    elif src == "binance":
        lim = max(_period_lim, 1000)
    elif src == "twelvedata":
        lim = 500   # outputsize handled inside fetch_twelvedata via period
    else:
        lim = max(_period_lim, 500)
    with st.spinner(""):
        df, warn = _load(sym, ivl, per, src, force=is_manual, crypto_limit=lim)
    st.session_state["_last_sym"] = sym
    st.session_state["_last_ivl"] = ivl
    st.session_state["_last_src"] = src
    st.session_state["_last_per"] = per
    if warn: st.warning(warn)
    # Issue helpful guidance for intraday US stocks with no data
    if df is None or (df is not None and len(df) < 5):
        _is_intraday = ivl in ("1m", "5m", "15m", "30m")
        _is_yf = src == "yfinance"
        _is_stock = not any(x in sym.upper() for x in (
            "USD","BTC","ETH","SOL","BNB","XRP","ADA","DOGE","AVAX","LINK","ATOM","USDT"
        ))
        if _is_intraday and _is_yf and _is_stock:
            st.info(
                f"⚠️ **No {ivl} data returned for {sym} via Yahoo Finance.**\n\n"
                "Possible reasons:\n"
                "- **Outside market hours** — US markets trade Mon–Fri 09:30–16:00 ET. "
                "Yahoo returns empty data for intraday intervals outside trading hours.\n"
                "- **Symbol not found** — try the exact Yahoo ticker (e.g. `AAPL`, `SPY`, `MSFT`).\n"
                "- **Yahoo rate limit** — try switching source to `twelvedata` for reliable intraday US stock data.\n\n"
                "💡 *Tip: Switch source to `twelvedata` (free API key at twelvedata.com) for 5m US stock data that works anytime.*",
                icon="📊"
            )
    if df is not None:
        st.session_state.df           = df
        st.session_state.last_refresh = time.time()
        try:
            agg = _aggregator(id(CONFIG), strategy_mode)
            rec_new = agg.analyse(df, sym)
            st.session_state.rec = rec_new
            # Record Markov signal for chart overlay when in a Markov mode
            if strategy_mode in ("markov", "markov_multi", "markov_plus") and rec_new and rec_new.signal in ("BUY", "SELL"):
                mkv_entry = {
                    "date":   df.index[-1],
                    "signal": rec_new.signal,
                    "price":  rec_new.entry_price,
                    "score":  rec_new.composite_score,
                }
                mkv_hist = st.session_state.get("markov_signals", [])
                # Avoid duplicate on same date
                if not mkv_hist or mkv_hist[-1].get("date") != mkv_entry["date"]:
                    mkv_hist = (mkv_hist + [mkv_entry])[-50:]  # keep last 50
                st.session_state["markov_signals"] = mkv_hist
        except Exception as e:
            st.session_state.rec = None
        try:
            _ms = int(st.session_state.get("ma_short",9))
            _ml = int(st.session_state.get("ma_long",21))
            mac = MACrossStrategy(_ms, _ml)
            st.session_state.ma_cross_result = mac.score(df)
        except Exception:
            st.session_state.ma_cross_result = None

        # ── Update tabs cache with fresh data ──────────────────────────────
        if st.session_state.df is not None and len(st.session_state.df) > 1:
            _df_fresh = st.session_state.df
            _close_now  = float(_df_fresh["Close"].iloc[-1])
            _close_prev = float(_df_fresh["Close"].iloc[-2])
            _chg_now    = (_close_now / _close_prev - 1) * 100 if _close_prev else 0
            st.session_state._tabs_cache[sym] = {
                "df":          _df_fresh,
                "rec":         st.session_state.rec,
                "signal":      st.session_state.rec.signal if st.session_state.rec else "",
                "close_price": _close_now,
                "chg_pct":     _chg_now,
                "last_load":   time.time(),
                "interval":    ivl,
                "period":      per,
                "source":      src,
            }
            # Ensure this symbol is pinned
            if sym not in st.session_state.pinned_tickers:
                st.session_state.pinned_tickers = st.session_state.pinned_tickers + [sym]

df  = st.session_state.df
rec = st.session_state.rec

# Guard: df must exist AND have at least 2 rows (need iloc[-1] and iloc[-2])
# Empty df happens when indicator warmup drops all rows (e.g. EMA200 needs
# 200+ bars; requesting only 30 bars leaves 0 rows after dropna)
if df is None or len(df) < 2:
    st.error(
        "**All data sources failed.** "
        "Check your internet connection and symbol format, then click **⟳ LOAD** to retry. "
        "Switch source to `sample` to use offline synthetic data."
    )
    st.stop()

# ── Alert firing ───────────────────────────────────────────────────────────────
# prev_signals is per-symbol so switching tickers never spuriously re-fires
# an alert that was already seen on the target ticker.
engine = st.session_state.alert_engine
if rec:
    # Per-symbol previous-signal tracking (keyed by symbol string)
    _prev_signals = st.session_state.setdefault("prev_signals", {})
    _prev_sig_for_sym = _prev_signals.get(sym)

    _fired_alerts = engine.check_conditions(sym, df, rec, _prev_sig_for_sym)
    for a in _fired_alerts:
        st.toast(f"{a.emoji} {a.title} — {a.symbol} @ {a.price:.4f}", icon="⚡")
    # Log BUY/SELL signal alerts to the persistent alert log
    if rec.signal in ("BUY", "SELL") and rec.signal != _prev_sig_for_sym:
        try:
            from dashboard.alert_log import log_alert
            log_alert(
                symbol        = sym,
                signal        = rec.signal,
                price         = rec.entry_price,
                strategy_mode = strategy_mode,
                score         = rec.composite_score,
                confidence    = rec.confidence_pct,
                planned_amount= float(st.session_state.get("planned_trade_amount", 0.0)),
                entry_price   = rec.entry_price,
                stop_loss     = rec.stop_loss,
                take_profit   = rec.take_profit,
            )
        except Exception:
            pass
    # Always update prev_signal for THIS symbol (HOLD resets BUY memory per ticker)
    _prev_signals[sym] = rec.signal
    st.session_state.prev_signals = _prev_signals
    # Keep legacy key in sync so any other code referencing it sees current symbol's state
    st.session_state.prev_signal = rec.signal

# ═══════════════════════════════════════════════════════════════════════════════
#  TICKER STRIP — 24h stats for Binance
# ═══════════════════════════════════════════════════════════════════════════════
_is_crypto = src in ("kraken","kucoin","binance","coingecko","bitoasis","yfinance") and any(c in sym.upper() for c in ("BTC","XBT","ETH","SOL","BNB","XRP","ADA","DOGE","AED","USDT"))
if _is_crypto and src == "binance":
    try:
        from data.crypto_feeds import get_binance_24h, _validate_symbol
        _ts_syms = ["BTCUSDT","ETHUSDT","SOLUSDT","BNBUSDT","XRPUSDT","ADAUSDT"]
        _ts_html = '<div class="qt-ticker">'
        for _s in _ts_syms:
            try:
                _st = get_binance_24h(_s)
                _px  = _st.get("price",0)
                _ch  = _st.get("change_pct",0)
                _cls = "qt-ticker-up" if _ch >= 0 else "qt-ticker-dn"
                _arr = "▲" if _ch >= 0 else "▼"
                _ts_html += f'<div class="qt-ticker-item"><span class="qt-ticker-sym">{_s.replace("USDT","")}/USDT</span><span class="qt-ticker-px">${_px:,.2f}</span> <span class="qt-ticker-chg {_cls}">{_arr}{abs(_ch):.2f}%</span></div>'
            except Exception:
                pass
        _ts_html += '</div>'
        st.markdown(_ts_html, unsafe_allow_html=True)
    except Exception:
        pass

# ═══════════════════════════════════════════════════════════════════════════════
#  KPI STRIP
# ═══════════════════════════════════════════════════════════════════════════════
# Safe accessors — never throw IndexError even if df has exactly 1 row
def _last(col, default=0.0):
    """Return df[col].iloc[-1] safely, or default if missing/empty."""
    try:
        return float(df[col].iloc[-1]) if col in df.columns and len(df) > 0 else default
    except (IndexError, KeyError, TypeError, ValueError):
        return default

def _prev(col, default=0.0):
    """Return df[col].iloc[-2] safely, or default if fewer than 2 rows."""
    try:
        return float(df[col].iloc[-2]) if col in df.columns and len(df) > 1 else _last(col, default)
    except (IndexError, KeyError, TypeError, ValueError):
        return default

close_c = _last("Close", 0.0)
close_p = _prev("Close", close_c)
chg   = (close_c / close_p - 1) * 100 if close_p != 0 else 0.0
rsi_v = _last("rsi",      50.0)
ema_f = _last("ema_fast", close_c)
ema_s = _last("ema_slow", close_c)
vol_r = _last("vol_ratio", 1.0)
atr_v = _last("atr",       0.0)
trend   = "UPTREND" if ema_f > ema_s else "DOWNTREND"
chg_cls = "qt-kpi-up" if chg >= 0 else "qt-kpi-dn"
rsi_cls = "qt-kpi-dn" if rsi_v > 70 else ("qt-kpi-up" if rsi_v < 30 else "qt-kpi-neu")
tr_cls  = "qt-kpi-up" if ema_f > ema_s else "qt-kpi-dn"
vol_cls = "qt-kpi-up" if vol_r > 2 else "qt-kpi-neu"

def _kpi(label, val, delta="", cls="qt-kpi-neu"):
    delta_html = f'<div class="qt-kpi-delta {cls}">{delta}</div>' if delta else ""
    return f'<div class="qt-kpi-card"><div class="qt-kpi-label">{label}</div><div class="qt-kpi-value">{val}</div>{delta_html}</div>'

kpi_html = f"""
<div class="qt-kpi-strip">
  {_kpi("LAST PRICE", f"${close_c:,.4f}", f"{'▲' if chg>=0 else '▼'} {abs(chg):.2f}%", chg_cls)}
  {_kpi("RSI 14", f"{rsi_v:.1f}", "OVERBOUGHT" if rsi_v>70 else ("OVERSOLD" if rsi_v<30 else "NEUTRAL"), rsi_cls)}
  {_kpi("EMA FAST", f"${ema_f:,.4f}")}
  {_kpi("EMA SLOW", f"${ema_s:,.4f}")}
  {_kpi("VOL RATIO", f"{vol_r:.1f}×", "SPIKE" if vol_r>2 else "", vol_cls)}
  {_kpi("TREND", trend, "", tr_cls)}
</div>
"""
st.markdown(kpi_html, unsafe_allow_html=True)

# ── Staleness bar ──────────────────────────────────────────────────────────────
_age   = time.time() - st.session_state.last_refresh
_stale = _age > max(rsec*2, 120)
_age_s = f"{int(_age)}s ago" if _age < 120 else f"{int(_age/60)}m ago"
_fetch_t = datetime.fromtimestamp(st.session_state.last_refresh).strftime("%H:%M:%S")
# Check data age: last bar timestamp vs now
_last_bar_ts   = df.index[-1] if len(df) > 0 else None
_data_age_hrs  = (datetime.now() - _last_bar_ts.to_pydatetime().replace(tzinfo=None)).total_seconds() / 3600 if _last_bar_ts is not None else 999
# Stale threshold depends on interval: daily bars are always 24h+ old, that's normal
_stale_hrs_map = {
    "1m": 0.1, "5m": 0.2, "15m": 0.4, "30m": 0.75,
    "1h": 4, "2h": 8, "4h": 14, "1d": 36, "1wk": 220,
}
_data_stale    = _data_age_hrs > _stale_hrs_map.get(ivl, 4)
_status_cls    = "qt-status-stale" if _stale or _data_stale else "qt-status-live"
# Shift last bar timestamp to user's local timezone for display
_tz_offset_h = float(st.session_state.get("tz_offset_hours", 3.0))
if _last_bar_ts is not None:
    from datetime import timedelta as _td
    _last_bar_local = _last_bar_ts.to_pydatetime().replace(tzinfo=None) + _td(hours=_tz_offset_h)
    _last_bar_str = _last_bar_local.strftime("%b %d %H:%M")
else:
    _last_bar_str = "?"
_status_label = "STALE" if (_stale or _data_stale) else "LIVE"
# Use user's saved timezone offset for display (not server TZ)
_tz_str = tz_label()
st.markdown(f"""
<div class="qt-status-bar">
  <span class="{_status_cls}">● {_status_label}</span>
  <span>LAST BAR {_last_bar_str} ({_tz_str})</span>
  <span>FETCHED {_fetch_t} ({_age_s})</span>
  <span>LOCAL {_local_now().strftime("%H:%M:%S")} {_tz_str}</span>
  <span>{len(df)} BARS · {ivl}</span>
  <span>{sym} · {src.upper()}{f" · {(st.session_state.get('_tv_exchange_override') or st.session_state.get('_tv_exchange') or 'AUTO').upper()}" if src == "tradingview" else ""}</span>
  {f'<span style="color:var(--red)">DATA {_data_age_hrs:.0f}h OLD — click ⟳ LOAD</span>' if _data_stale else ""}
</div>
""", unsafe_allow_html=True)

# ═══════════════════════════════════════════════════════════════════════════════
#  MAIN LAYOUT — chart left, panel right
# ═══════════════════════════════════════════════════════════════════════════════
chart_col, panel_col = st.columns([7.5, 2.5], gap="small")

# ──────────────── LEFT: CHART AREA ────────────────────────────────────────────
with chart_col:
    tab_chart, tab_bt, tab_mkv, tab_ml, tab_log, tab_acct, tab_wl = st.tabs(["CHART", "BACKTEST", "⛓ MARKOV", "🤖 ML", "LOG", "⚙ ACCOUNTS", "📊 WATCHLIST"])

    with tab_chart:
        # Chart controls — 2-row layout to prevent label overlap
        _ms = int(st.session_state.get("ma_short", 9))
        _ml = int(st.session_state.get("ma_long", 21))
        try:
            _tz_disp = f"UTC{int(datetime.now().astimezone().utcoffset().total_seconds()/3600):+d}"
        except Exception:
            _tz_disp = "UTC"

        _ctrl_left, _ctrl_mid, _ctrl_right = st.columns([4, 4, 2])
        with _ctrl_left:
            n_can = st.slider(
                f"Candles (of {len(df)} loaded)",
                30, min(500, len(df)), st.session_state.n_candles, 10,
            )
            st.session_state.n_candles = n_can
        with _ctrl_mid:
            _tog1, _tog2, _tog3 = st.columns(3)
            show_sig = _tog1.toggle("Signals",   value=True,  key="_chart_signals")
            show_mac = _tog2.toggle("MA Cross",  value=True,  key="_chart_macross")
            show_bb  = _tog3.toggle("Bol Bands", value=True,  key="_chart_bb")
            st.session_state["show_ma_cross_overlay"] = show_mac
        with _ctrl_right:
            st.markdown(
                f'<div style="font-size:9px;color:var(--text-mute);padding-top:6px;'
                f'font-family:var(--mono);line-height:1.6">'
                f'SMA {_ms}/{_ml}<br>{_tz_disp}</div>',
                unsafe_allow_html=True,
            )

        if not PLOTLY_OK:
            st.error("pip install plotly")
        else:
            sigs     = st.session_state.historical_signals if show_sig else []
            mkv_sigs = st.session_state.get("markov_signals", [])
            _is_markov_mode = st.session_state.get("strategy_mode", "multi") in ("markov", "markov_multi", "markov_plus")
            fig  = build_chart(
                df=df, symbol=sym, signals=sigs,
                entry_price=rec.entry_price  if rec else None,
                stop_loss  =rec.stop_loss    if rec else None,
                take_profit=rec.take_profit  if rec else None,
                signal_type=rec.signal       if rec else None,
                n_candles=n_can,
                ma_short_period=_ms,
                ma_long_period =_ml,
                show_ma_cross  =show_mac,
                markov_signals =mkv_sigs,
                show_markov    =_is_markov_mode,
                light_mode     =st.session_state.get("theme", "light") == "light",
                tz_offset_hours=float(st.session_state.get("tz_offset_hours", 3.0)),
                interval       =ivl,
            )
            # Patch BB visibility
            if not show_bb:
                for trace in fig.data:
                    if "BB" in (trace.name or ""):
                        trace.visible = False
            st.plotly_chart(fig, width="stretch",
                key="main_chart",
                config=dict(
                    scrollZoom=True,
                    displayModeBar=True,
                    # Keep only useful tools — remove clutter
                    modeBarButtonsToRemove=[
                        "autoScale2d","lasso2d","select2d",
                        "toggleSpikelines","hoverClosestCartesian",
                        "hoverCompareCartesian",
                    ],
                    modeBarButtonsToAdd=["drawline","drawopenpath","eraseshape"],
                    toImageButtonOptions=dict(
                        format="png", width=1920, height=1080,
                        filename=f"{sym}_chart_{datetime.now().strftime('%Y%m%d_%H%M')}",
                    ),
                    doubleClick="reset+autosize",
                    showTips=False,
                    responsive=True,
                ))

    with tab_bt:
        # ── Backtest controls ────────────────────────────────────────────
        bl, br = st.columns([3, 1])
        with br:
            bt_cap     = st.number_input("Capital ($)", 10000, 10_000_000, 100_000, 10000, key="bt_cap")
            bt_sl      = st.slider("SL %",  0.5, 10.0, 2.0, 0.5, key="bt_sl")
            bt_tp      = st.slider("TP %",  1.0, 20.0, 4.0, 0.5, key="bt_tp")
            # Warmup: auto-scale to dataset size — max 20% of available bars, min 30
            _max_warm  = max(30, min(100, len(df) // 5))
            bt_warmup  = st.slider("Warmup bars", 20, _max_warm, min(50, _max_warm), 5,
                                   key="bt_warmup",
                                   help="Bars consumed for indicator initialisation before trading starts. "
                                        "Lower = more trades; higher = cleaner signal warmup.")
            run_bt     = st.button("▶ RUN BACKTEST", type="primary", use_container_width=True, key="bt_run")

        with bl:
            if run_bt:
                CONFIG.backtest.initial_capital = float(bt_cap)
                CONFIG.risk.stop_loss_pct       = bt_sl / 100
                CONFIG.risk.take_profit_pct     = bt_tp / 100
                _n_bars = len(df)
                if _n_bars < bt_warmup + 5:
                    st.error(
                        f"Not enough data: {_n_bars} bars loaded but warmup={bt_warmup}. "
                        "Load more data (increase period or use 1d interval) then retry."
                    )
                else:
                    with st.spinner(f"Backtesting {sym} over {_n_bars} bars…"):
                        try:
                            bt_eng = BacktestEngine(CONFIG)
                            eq, tdf, mets = bt_eng.run(df, sym, warmup_bars=bt_warmup, verbose=False)
                            st.session_state.update(dict(
                                backtest_run=True,
                                backtest_equity=eq,
                                backtest_trades=tdf,
                                backtest_metrics=mets,
                                backtest_symbol=sym,
                                backtest_capital=float(bt_cap),
                            ))
                            if tdf is not None and not tdf.empty:
                                st.session_state.historical_signals = [
                                    dict(date=r.entry_date,
                                         signal="BUY" if r.direction == "long" else "SELL",
                                         price=r.entry_price)
                                    for _, r in tdf.iterrows()
                                ]
                        except Exception as _bt_err:
                            st.error(f"Backtest error: {_bt_err}")

            if st.session_state.backtest_run and st.session_state.backtest_equity is not None:
                eq    = st.session_state.backtest_equity
                mets  = st.session_state.backtest_metrics
                tdf   = st.session_state.backtest_trades
                _bcap = st.session_state.get("backtest_capital", bt_cap)

                # ── Equity curve vs Buy-and-Hold ──────────────────────
                _bh = _bcap * (df["Close"] / df["Close"].iloc[0]).reindex(eq.index)
                if go:
                    fig_eq = go.Figure()
                    fig_eq.add_trace(go.Scatter(
                        x=eq.index, y=eq.values, name="Strategy",
                        line=dict(color="#4B9FFF", width=2),
                        fill="tozeroy", fillcolor="rgba(75,159,255,0.05)",
                    ))
                    fig_eq.add_trace(go.Scatter(
                        x=_bh.index, y=_bh.values, name="Buy & Hold",
                        line=dict(color="#3A4A62", width=1.5, dash="dot"),
                    ))
                    fig_eq.update_layout(
                        paper_bgcolor="#0C1322", plot_bgcolor="#0C1322",
                        font=dict(color="#DCE4F5", family="IBM Plex Mono"),
                        margin=dict(l=40, r=20, t=20, b=20),
                        height=260,
                        legend=dict(orientation="h"),
                        hovermode="x unified",
                        xaxis=dict(gridcolor="#1A2540"),
                        yaxis=dict(gridcolor="#1A2540", side="right"),
                    )
                    st.plotly_chart(fig_eq, width="stretch",
                                    config={"displayModeBar": False})

                # ── KPI metrics ───────────────────────────────────────
                m = mets or {}
                mc1, mc2, mc3, mc4 = st.columns(4)
                mc1.metric("TOTAL RETURN",  f"{m.get('total_return_pct', 0):.2f}%")
                mc2.metric("SHARPE",         f"{m.get('sharpe_ratio', 0):.3f}")
                mc3.metric("MAX DRAWDOWN",   f"{m.get('max_drawdown_pct', 0):.2f}%")
                mc4.metric("WIN RATE",       f"{m.get('win_rate_pct', 0):.1f}%")
                mc5, mc6, mc7, mc8 = st.columns(4)
                mc5.metric("CAGR",           f"{m.get('cagr_pct', 0):.2f}%")
                mc6.metric("PROFIT FACTOR",  f"{m.get('profit_factor', 0):.3f}")
                mc7.metric("TOTAL TRADES",   f"{m.get('total_trades', 0)}")
                mc8.metric("SORTINO",        f"{m.get('sortino_ratio', 0):.3f}")

                # ── Per-trade P&L bar chart + table ──────────────────
                if tdf is not None and not tdf.empty:
                    if go:
                        pnl = (tdf["pnl_pct"] * 100).tolist()
                        fc  = ["#00C9A7" if v >= 0 else "#FF4560" for v in pnl]
                        fp  = go.Figure(go.Bar(
                            x=list(range(1, len(pnl) + 1)), y=pnl,
                            marker_color=fc,
                            hovertemplate="Trade %{x}<br>P&L: %{y:+.2f}%<extra></extra>",
                        ))
                        fp.update_layout(
                            paper_bgcolor="#0C1322", plot_bgcolor="#0C1322",
                            font=dict(color="#DCE4F5", family="IBM Plex Mono"),
                            margin=dict(l=40, r=20, t=10, b=20),
                            height=160,
                            xaxis=dict(gridcolor="#1A2540"),
                            yaxis=dict(gridcolor="#1A2540", side="right"),
                        )
                        fp.add_hline(y=0, line=dict(color="#3A4A62", width=1))
                        st.plotly_chart(fp, width="stretch",
                                        config={"displayModeBar": False})

                    disp = tdf.copy()
                    disp["pnl_pct"] = (disp["pnl_pct"] * 100).round(2)
                    show_c = [c for c in [
                        "direction", "entry_date", "entry_price",
                        "exit_date", "exit_price", "exit_reason",
                        "pnl_pct", "pnl_dollar",
                    ] if c in disp.columns]
                    try:
                        st.dataframe(disp[show_c], width="stretch", hide_index=True)
                    except Exception:
                        st.table(disp[show_c].head(50))
                else:
                    st.info(
                        "No trades generated. Try reducing the Warmup bars, "
                        "increasing the data period, or lowering the signal threshold."
                    )
            else:
                st.markdown(
                    '<div style="color:var(--text-mute);font-size:11px;padding:20px;'
                    'font-family:var(--mono);text-align:center">'
                    'Set parameters and click <b>▶ RUN BACKTEST</b></div>',
                    unsafe_allow_html=True,
                )

    with tab_mkv:
        try:
            _mkv_df = st.session_state.get("df")
            if _mkv_df is None or len(_mkv_df) < 40:
                st.info("⏳ Loading chart data for Markov analysis...", icon="📊")
                _DATA_CACHE.clear(); clear_cache(); clear_ingestion_cache(); clear_commodity_cache()
                _mkv_lim = max(_period_to_candles(per, ivl), 200)
                _mkv_df, _mkv_warn = _load(sym, ivl, per, src, force=True, crypto_limit=_mkv_lim)
                if _mkv_warn: st.warning(_mkv_warn)
                if _mkv_df is not None:
                    st.session_state.df = _mkv_df
                    st.session_state.last_refresh = time.time()
            render_markov_tab(st.session_state.get("df"), st.session_state.get("symbol", ""))
        except Exception as _mkv_err:
            st.error(f"Markov tab error: {_mkv_err}", icon="⚠️")

    with tab_ml:
        try:
            render_ml_tab(
                df         = st.session_state.get("df"),
                symbol     = st.session_state.get("symbol", sym),
                interval   = st.session_state.get("interval", ivl),
                light_mode = st.session_state.get("theme", "light") == "light",
            )
        except Exception as _ml_err:
            st.error(f"ML tab error: {_ml_err}", icon="⚠️")
            import traceback
            st.code(traceback.format_exc(), language="python")

    with tab_log:
        try:
            # ── Signal Alert Log (BUY/SELL tracking with planned trade amount)
            from dashboard.alert_log import render_alert_log
            render_alert_log()

            st.divider()

            # ── Trade Journal (full P&L tracking) ───────────────────────────
            render_trade_journal()

            # ── Market data snapshot (collapsible) ──────────────────────────
            with st.expander("Current Market Data / Indicator Snapshot", expanded=False):
                ind_cols = ["Close", "ema_fast", "ema_slow", "rsi", "macd",
                            "macd_hist", "bb_pct", "vol_ratio", "atr"]
                try:
                    st.dataframe(
                        df[[c for c in ind_cols if c in df.columns]].tail(30).round(4).iloc[::-1],
                        width="stretch",
                    )
                except Exception:
                    st.table(
                        df[[c for c in ind_cols if c in df.columns]].tail(15).round(4).iloc[::-1]
                    )
        except Exception as _log_err:
            st.error(f"Log tab error: {_log_err}", icon="⚠️")

    with tab_acct:
        try:
            render_account_panel()
        except Exception as _acct_err:
            import traceback as _tb
            st.error(f"Accounts tab error: {_acct_err}", icon="⚠️")
            st.code(_tb.format_exc(), language="python")

    with tab_wl:
        try:
            st.markdown(
                '''<div style="font-family:var(--mono);font-size:11px;color:var(--text-sec);
                margin-bottom:12px;padding:8px 12px;background:var(--bg-surface);
                border-radius:4px;border-left:3px solid var(--amber)">
                <b style="color:var(--text-pri)">Multi-Ticker Scanner</b> — runs signals across all symbols simultaneously.
                Click <b>⟳ SCAN ALL</b> to analyse. Click <b>Switch →</b> on any row to load that ticker in the main chart.
                Signals fire alerts to Discord/WhatsApp automatically.
                </div>''',
                unsafe_allow_html=True,
            )
            _clicked = render_watchlist(
                main_symbol   = st.session_state.get("symbol", "BTC-USD"),
                main_source   = st.session_state.get("source",   "yfinance"),
                main_interval = st.session_state.get("interval", "1h"),
            )
            if _clicked:
                st.session_state["symbol"]      = _clicked
                st.session_state["sym_toolbar"] = _clicked  # sync toolbar widget
                st.session_state["df"]          = None   # force reload
                st.rerun()
        except Exception as _wl_err:
            import traceback as _tb
            st.error(f"Watchlist tab error: {_wl_err}", icon="⚠️")
            st.code(_tb.format_exc(), language="python")

# ──────────────── RIGHT: SIGNAL PANEL ─────────────────────────────────────────
with panel_col:

    # ── Signal card ───────────────────────────────────────────────────────────
    if rec:
        sig   = rec.signal
        score = rec.composite_score
        conf  = rec.confidence_pct

        css_class = {"BUY":"qt-signal-buy","SELL":"qt-signal-sell","HOLD":"qt-signal-hold"}.get(sig,"qt-signal-hold")
        col_map   = {"BUY":"var(--green)","SELL":"var(--red)","HOLD":"var(--amber)"}
        pulse_col = {"BUY":"#00C9A7","SELL":"#FF4560","HOLD":"#FFB800"}
        arrow     = {"BUY":"▲","SELL":"▼","HOLD":"◆"}.get(sig,"◆")

        _cur_strat = st.session_state.get("strategy_mode", "multi")
        _mode_badge_map = {
            "multi":        ("MULTI-STRATEGY",   "var(--blue)",   "rgba(75,159,255,0.12)",  "rgba(75,159,255,0.3)"),
            "markov":       ("◈ MARKOV CHAINS",  "var(--purple)", "rgba(155,109,255,0.12)", "rgba(155,109,255,0.3)"),
            "markov_multi": ("◈ MARKOV + MULTI", "var(--purple)", "rgba(155,109,255,0.12)", "rgba(155,109,255,0.3)"),
            "markov_plus":  ("◈ MARKOV PLUS",    "var(--purple)", "rgba(155,109,255,0.15)", "rgba(155,109,255,0.4)"),
        }
        _badge_text, _badge_col, _badge_bg, _badge_bdr = _mode_badge_map.get(
            _cur_strat, ("MULTI-STRATEGY", "var(--blue)", "rgba(75,159,255,0.12)", "rgba(75,159,255,0.3)"))

        st.markdown(f"""
        <div class="qt-signal {css_class}">
          <div class="qt-signal-label" style="color:{col_map.get(sig,'var(--text-pri)')}">
            <div class="qt-pulse" style="background:{pulse_col.get(sig,'#fff')}"></div>
            {arrow} {sig}
          </div>
          <div class="qt-signal-meta">
            SCORE {score:+.3f} &nbsp;·&nbsp; CONF {conf:.0f}% &nbsp;·&nbsp; {sym}
          </div>
          <div style="margin-top:6px">
            <span style="background:{_badge_bg};border:1px solid {_badge_bdr};
              border-radius:3px;padding:2px 8px;font-size:8px;letter-spacing:.12em;
              color:{_badge_col};font-family:var(--mono);text-transform:uppercase">{_badge_text}</span>
          </div>
        </div>
        """, unsafe_allow_html=True)

        # Price levels
        rr = abs(rec.take_profit - rec.entry_price) / max(abs(rec.stop_loss - rec.entry_price), 1e-9)
        ep = rec.entry_price
        sl = rec.stop_loss
        tp = rec.take_profit
        sl_pct = (sl/ep-1)*100
        tp_pct = (tp/ep-1)*100

        st.markdown(f"""
        <div class="qt-level-row qt-level-entry">
          <span style="color:var(--text-sec);font-size:9px;letter-spacing:.1em">ENTRY</span>
          <span style="color:var(--amber);font-weight:600">${ep:.4f}</span>
        </div>
        <div class="qt-level-row qt-level-sl">
          <span style="color:var(--text-sec);font-size:9px;letter-spacing:.1em">STOP LOSS</span>
          <span style="color:var(--red);font-weight:600">${sl:.4f} <span style="font-size:9px">{sl_pct:+.2f}%</span></span>
        </div>
        <div class="qt-level-row qt-level-tp">
          <span style="color:var(--text-sec);font-size:9px;letter-spacing:.1em">TAKE PROFIT</span>
          <span style="color:var(--green);font-weight:600">${tp:.4f} <span style="font-size:9px">{tp_pct:+.2f}%</span></span>
        </div>
        <div style="display:flex;justify-content:space-between;padding:5px 10px;font-family:var(--mono);font-size:10px;color:var(--text-sec)">
          <span>R:R RATIO</span>
          <span style="color:var(--blue)">{rr:.2f} : 1</span>
        </div>
        <div style="display:flex;justify-content:space-between;padding:5px 10px;font-family:var(--mono);font-size:10px;color:var(--text-sec)">
          <span>POSITION SIZE</span>
          <span style="color:var(--text-pri)">{rec.position_size_pct:.1f}%</span>
        </div>
        """, unsafe_allow_html=True)

        # Strategy breakdown
        st.markdown('<div class="qt-section" style="margin-top:10px">AGENT SCORES</div>', unsafe_allow_html=True)
        # Weights differ per mode: classic 4-strategy vs markov vs hybrid
        wmap_classic = {"trend":0.30,"momentum":0.25,"mean_reversion":0.25,"ai_model":0.20}
        wmap_markov_multi = {"markov_chains":0.40,"trend":0.18,"momentum":0.15,"mean_reversion":0.15,"ai_model":0.12}
        _strat_wmap = (
            {"markov_chains": 1.0}       if _cur_strat == "markov"       else
            wmap_markov_multi             if _cur_strat == "markov_multi" else
            wmap_classic
        )
        for name, data in rec.strategy_breakdown.items():
            sc    = data.get("score", 0)
            pct   = int((sc+1)/2*100)
            _is_mkv_strat = name == "markov_chains"
            fill  = (
                "var(--purple)" if _is_mkv_strat and sc > 0.1 else
                "var(--amber)"  if _is_mkv_strat and sc < -0.1 else
                "var(--green)"  if sc > 0.1 else
                ("var(--red)"   if sc < -0.1 else "var(--border-lit)")
            )
            label = ("◈ Markov Chains" if _is_mkv_strat else name.replace("_"," ").title())
            w     = _strat_wmap.get(name, 0.25)
            sig_s = data.get("signal","?")
            st.markdown(f"""
            <div class="qt-score-row">
              <div class="qt-score-label">
                <span>{label} <span style="color:var(--text-mute)">·{w:.0%}</span></span>
                <span style="color:{fill}">{sc:+.3f} {sig_s}</span>
              </div>
              <div class="qt-score-track">
                <div class="qt-score-fill" style="width:{pct}%;background:{fill}"></div>
              </div>
            </div>
            """, unsafe_allow_html=True)

        # ── Markov diagnostics panel (Markov, Markov+Multi, Markov Plus modes) ─
        _is_markov_panel = _cur_strat in ("markov", "markov_multi", "markov_plus")
        if _is_markov_panel:
            _mkv_data = rec.strategy_breakdown.get("markov_chains", {})
            _mkv_sub  = _mkv_data.get("sub_scores", {})
            if _mkv_sub:
                _diag          = float(_mkv_sub.get("diag_mean",   0))
                _state         = _mkv_sub.get("current_state", "?")
                _j_star        = _mkv_sub.get("j_star", "?")
                _j_star_1      = _mkv_sub.get("j_star_1step", "?")
                _j_star_n      = _mkv_sub.get("j_star_nstep", "?")
                _p_hat         = float(_mkv_sub.get("p_hat",       0))
                _p_hat_1       = float(_mkv_sub.get("p_hat_1step", 0))
                _p_hat_n       = float(_mkv_sub.get("p_hat_nstep", 0))
                _market_q      = float(_mkv_sub.get("market_q",    0))
                _gap           = float(_mkv_sub.get("gap",         0))
                _persist       = float(_mkv_sub.get("persist",     0))
                _entry_ok      = bool(_mkv_sub.get("entry_ok",     False))
                _is_bull       = bool(_mkv_sub.get("is_bullish",   False))
                _regime        = _mkv_sub.get("regime", "SIDEWAYS")
                _pi_bull       = float(_mkv_sub.get("pi_bull",     0))
                _pi_bear       = float(_mkv_sub.get("pi_bear",     0))
                _pi_edge       = float(_mkv_sub.get("pi_edge",     0))
                _regime_align  = bool(_mkv_sub.get("regime_aligned", False))
                _pi_dist       = _mkv_sub.get("stationary_distribution", [])
                _n_states      = int(_mkv_sub.get("n_states", 8))

                _gap_col   = "var(--green)" if _gap  > 0 else "var(--red)"
                _bull_col  = "var(--green)" if _is_bull else "var(--red)"
                _bull_str  = "BULLISH ▲"   if _is_bull else "BEARISH ▼"
                _entry_col = "var(--green)" if _entry_ok else "var(--text-mute)"
                _entry_str = "● ENTRY VALID" if _entry_ok else "○ NO ENTRY"
                _regime_col = (
                    "var(--green)"  if _regime == "BULL" else
                    "var(--red)"    if _regime == "BEAR" else
                    "var(--amber)"
                )
                _align_str = "✓ ALIGNED" if _regime_align else ("✗ CONTRA" if _regime != "SIDEWAYS" else "~ SIDEWAYS")
                _align_col = "var(--green)" if _regime_align else ("var(--red)" if _regime != "SIDEWAYS" else "var(--amber)")
                _diag_pct  = int(_diag * 100)
                _diag_col  = "var(--purple)" if _diag >= 0.87 else ("var(--amber)" if _diag >= 0.70 else "var(--red)")
                _pi_bull_pct = int(_pi_bull * 100)
                _pi_bear_pct = int(_pi_bear * 100)
                _pi_edge_col = "var(--green)" if _pi_edge > 0 else "var(--red)"
                _nstep_agree = "✓" if _j_star_n == _j_star_1 else "~"
                _nstep_col   = "var(--green)" if _j_star_n == _j_star_1 else "var(--amber)"

                # Build mini stationary distribution bar chart HTML
                _pi_bars_html = ""
                if _pi_dist and len(_pi_dist) > 0:
                    _max_pi = max(_pi_dist) if max(_pi_dist) > 0 else 1.0
                    _mid_idx = len(_pi_dist) // 2
                    for _bi, _bv in enumerate(_pi_dist):
                        _bar_h  = int((_bv / _max_pi) * 28)
                        _bar_c  = "var(--green)" if _bi >= _mid_idx else "var(--red)"
                        _active = "opacity:1" if _bi == _j_star else "opacity:0.5"
                        _border = "border:1px solid var(--purple);" if _bi == _j_star else ""
                        _pi_bars_html += (
                            f'<div title="State {_bi}: π={_bv:.3f}" '
                            f'style="display:inline-flex;flex-direction:column;align-items:center;'
                            f'margin-right:2px;{_active}">'
                            f'<div style="width:10px;height:{_bar_h}px;background:{_bar_c};'
                            f'border-radius:2px 2px 0 0;{_border}"></div>'
                            f'<div style="font-size:6px;color:var(--text-mute);margin-top:1px">{_bi}</div>'
                            f'</div>'
                        )

                st.markdown(f"""
                <div class="qt-section" style="margin-top:10px">MARKOV DIAGNOSTICS</div>
                <div style="background:rgba(155,109,255,0.06);border:1px solid rgba(155,109,255,0.2);
                  border-radius:5px;padding:10px 12px;font-family:var(--mono);font-size:10px">

                  <!-- Row 1: Regime + Entry -->
                  <div style="display:grid;grid-template-columns:1fr 1fr;gap:6px 12px;margin-bottom:8px">
                    <div>
                      <div style="color:var(--text-mute);font-size:8px;letter-spacing:.12em;margin-bottom:2px">MARKET REGIME (π)</div>
                      <div style="color:{_regime_col};font-weight:700;font-size:13px">{_regime}</div>
                      <div style="display:flex;gap:6px;margin-top:3px">
                        <div style="height:3px;width:{_pi_bull_pct}%;background:var(--green);border-radius:2px"></div>
                        <div style="height:3px;width:{_pi_bear_pct}%;background:var(--red);border-radius:2px"></div>
                      </div>
                      <div style="color:var(--text-mute);font-size:8px;margin-top:2px">
                        bull={_pi_bull:.3f} bear={_pi_bear:.3f}
                      </div>
                    </div>
                    <div>
                      <div style="color:var(--text-mute);font-size:8px;letter-spacing:.12em;margin-bottom:2px">REGIME ALIGNMENT</div>
                      <div style="color:{_align_col};font-weight:700;font-size:13px">{_align_str}</div>
                      <div style="color:var(--text-mute);font-size:8px;margin-top:2px">{_bull_str}</div>
                    </div>
                  </div>

                  <!-- Row 2: Core conditions -->
                  <div style="display:grid;grid-template-columns:1fr 1fr;gap:6px 12px;margin-bottom:8px">
                    <div>
                      <div style="color:var(--text-mute);font-size:8px;letter-spacing:.12em;margin-bottom:2px">GAP Δ(w) = P̂−Q</div>
                      <div style="color:{_gap_col};font-weight:600">{_gap:+.4f}</div>
                      <div style="color:var(--text-mute);font-size:8px">P̂={_p_hat_1:.4f} Q={_market_q:.4f}</div>
                    </div>
                    <div>
                      <div style="color:var(--text-mute);font-size:8px;letter-spacing:.12em;margin-bottom:2px">PERSIST P[j*,j*]</div>
                      <div style="color:var(--amber);font-weight:600">{_persist:.4f}</div>
                      <div style="color:var(--text-mute);font-size:8px">τ=0.87  j={_state}→j*={_j_star_1}</div>
                    </div>
                  </div>

                  <!-- Row 3: N-step + π-edge -->
                  <div style="display:grid;grid-template-columns:1fr 1fr;gap:6px 12px;margin-bottom:8px">
                    <div>
                      <div style="color:var(--text-mute);font-size:8px;letter-spacing:.12em;margin-bottom:2px">3-STEP FORECAST</div>
                      <div style="color:{_nstep_col};font-weight:600">{_nstep_agree} j*={_j_star_n}</div>
                      <div style="color:var(--text-mute);font-size:8px">P̂(n)={_p_hat_n:.4f}  blend j*={_j_star}</div>
                    </div>
                    <div>
                      <div style="color:var(--text-mute);font-size:8px;letter-spacing:.12em;margin-bottom:2px">π-EDGE STRUCT.</div>
                      <div style="color:{_pi_edge_col};font-weight:600">{_pi_edge:+.4f}</div>
                      <div style="color:var(--text-mute);font-size:8px">diag_mean={_diag:.3f}</div>
                    </div>
                  </div>

                  <!-- Stationary distribution mini bar chart -->
                  <div style="border-top:1px solid rgba(155,109,255,0.15);padding-top:7px;margin-bottom:7px">
                    <div style="color:var(--text-mute);font-size:8px;letter-spacing:.12em;margin-bottom:4px">
                      STATIONARY DISTRIBUTION π  (purple outline = predicted next state j*)
                    </div>
                    <div style="display:flex;align-items:flex-end;height:36px">
                      {_pi_bars_html}
                    </div>
                  </div>

                  <!-- Footer -->
                  <div style="border-top:1px solid rgba(155,109,255,0.15);padding-top:7px;
                    display:flex;justify-content:space-between;align-items:center">
                    <span style="color:{_entry_col};font-size:9px;letter-spacing:.08em;font-weight:600">{_entry_str}</span>
                    <span style="color:var(--text-mute);font-size:9px">τ=0.87 · ε=0.05 · {_n_states} states</span>
                  </div>
                </div>
                """, unsafe_allow_html=True)

        # MA Cross status
        mac_res = st.session_state.ma_cross_result
        if mac_res:
            sub = mac_res.sub_scores or {}
            cup = bool(sub.get("cross_up",0))
            cdn = bool(sub.get("cross_down",0))
            cross_str = "GOLDEN CROSS ▲" if cup else ("DEATH CROSS ▼" if cdn else ("BULL ZONE" if sub.get("short_ma",0) > sub.get("long_ma",0) else "BEAR ZONE"))
            cross_col = "var(--green)" if cup or sub.get("short_ma",0)>sub.get("long_ma",0) else "var(--red)"
            st.markdown(f"""
            <div style="background:var(--bg-card);border:1px solid var(--border);border-radius:4px;padding:8px 10px;margin:6px 0;font-family:var(--mono);font-size:10px">
              <div style="color:var(--text-mute);font-size:9px;letter-spacing:.1em;margin-bottom:4px">MA CROSS SMA{_ms}/{_ml}</div>
              <div style="color:{cross_col};font-weight:600">{cross_str}</div>
              <div style="color:var(--text-sec);margin-top:3px">{sub.get("short_ma",0):.4f} / {sub.get("long_ma",0):.4f}</div>
            </div>
            """, unsafe_allow_html=True)

        # Reasoning
        with st.expander("SIGNAL REASONING", expanded=False):
            for r in rec.reasoning[1:]:
                if r.startswith("[") and "|" in r: continue
                clean = r.encode("ascii","replace").decode("ascii").strip()
                if clean:
                    st.markdown(f'<div style="font-size:10px;color:var(--text-sec);padding:2px 0;font-family:var(--mono)">{clean}</div>', unsafe_allow_html=True)

        # ── Execute Trade panel ───────────────────────────────────────────
        _trade_border = "var(--green)" if rec.signal == "BUY" else ("var(--red)" if rec.signal == "SELL" else "var(--border)")
        with st.expander(f"⚡ EXECUTE TRADE  ({rec.signal})", expanded=rec.signal in ("BUY","SELL")):
            if rec.signal == "HOLD":
                st.markdown('<div style="font-size:10px;color:var(--text-mute);font-family:var(--mono);padding:6px 0">Signal is HOLD — no trade recommended.</div>', unsafe_allow_html=True)
            else:
                _signal_color = "var(--green)" if rec.signal == "BUY" else "var(--red)"
                st.markdown(
                    f'<div style="font-size:9px;letter-spacing:.1em;color:{_signal_color};font-family:var(--mono);font-weight:700;margin-bottom:8px">'
                    f'● {rec.signal} SIGNAL  ·  CONFIDENCE {rec.confidence_pct:.0f}%  ·  {sym}</div>',
                    unsafe_allow_html=True,
                )
                st.markdown(
                    f'<div style="font-family:var(--mono);font-size:10px;color:var(--text-sec);padding:8px 12px;background:var(--bg-surface);border-radius:4px;border-left:3px solid {_signal_color};margin-bottom:8px">'
                    f'Entry: <b style="color:var(--amber)">${rec.entry_price:.4f}</b>'
                    f' · SL: <b style="color:var(--red)">${rec.stop_loss:.4f}</b>'
                    f' · TP: <b style="color:var(--green)">${rec.take_profit:.4f}</b>'
                    f' · Size: <b style="color:var(--text-pri)">{rec.position_size_pct:.1f}%</b></div>',
                    unsafe_allow_html=True,
                )
                with st.form("exec_trade_form", clear_on_submit=False):
                    _qty = st.number_input("Order size %", min_value=0.01,
                                           value=float(rec.position_size_pct), step=0.5,
                                           format="%.2f", key="exec_qty")
                    _order_type = st.selectbox("Order type", ["Market", "Limit"], key="exec_type")
                    _limit_px = None
                    if _order_type == "Limit":
                        _limit_px = st.number_input("Limit price", value=float(rec.entry_price),
                                                    format="%.4f", key="exec_limit")
                    _submitted = st.form_submit_button(
                        f"► SEND {rec.signal} ORDER",
                        type="primary", use_container_width=True,
                    )
                    if _submitted:
                        _broker = st.session_state.get("active_broker", "paper")
                        st.info(f"Order queued: {rec.signal} {_qty:.2f}% via {_broker}. Configure broker in ⚙ ACCOUNTS tab.", icon="⚡")
                        # Send Discord trade confirmation notification
                        _dc_url = st.session_state.get("_discord_webhook_url", "")
                        if _dc_url and _dc_url.startswith("https://discord.com/api/webhooks/") and REQUESTS_OK:
                            try:
                                import requests as _req
                                _sig_emoji = "🟢" if rec.signal == "BUY" else "🔴"
                                _lim_txt = f"\n💵 Limit Price: **${_limit_px:.4f}**" if _order_type == "Limit" and _limit_px else ""
                                _discord_payload = {
                                    "embeds": [{
                                        "title": f"{_sig_emoji} TRADE ORDER — {rec.signal} {sym}",
                                        "description": (
                                            f"**{rec.signal}** signal submitted via {_broker.upper()}\n\n"
                                            f"📊 Entry: **${rec.entry_price:.4f}**\n"
                                            f"🛑 Stop Loss: **${rec.stop_loss:.4f}**\n"
                                            f"🎯 Take Profit: **${rec.take_profit:.4f}**\n"
                                            f"📦 Size: **{_qty:.2f}%** of capital\n"
                                            f"📋 Order Type: **{_order_type}**{_lim_txt}\n"
                                            f"💡 Confidence: **{rec.confidence_pct:.0f}%**\n"
                                            f"⚖️ R:R Ratio: **{rr:.2f}:1**\n\n"
                                            f"⚠️ *Analysis only — verify before executing real trades.*"
                                        ),
                                        "color": 0x00E676 if rec.signal == "BUY" else 0xFF5252,
                                        "footer": {"text": "Apex Terminal — Trade Confirmation"},
                                    }]
                                }
                                _req.post(_dc_url, json=_discord_payload, timeout=5)
                                st.success("✅ Trade details sent to Discord!", icon="💬")
                            except Exception as _dc_err:
                                st.warning(f"Discord notification failed: {_dc_err}")

        # Log signal
        from utils.logger import TradeLogger
        TradeLogger().log_signal(rec.to_dict())

    # ── Alert feed ───────────────────────────────────────────
    st.markdown('<div class="qt-section" style="margin-top:10px">ALERT FEED</div>', unsafe_allow_html=True)
    a_col1, a_col2 = st.columns([3,1])
    a_col1.markdown(f'<div style="font-size:9px;color:var(--text-mute);font-family:var(--mono)">{len(engine.queue)} EVENTS</div>', unsafe_allow_html=True)
    if a_col2.button("CLR", use_container_width=True, key="clr_alerts"):
        engine.clear()

    for a in engine.queue[:8]:
        css = "qt-alert-buy" if a.signal in ("BUY","RSI_OS") else ("qt-alert-sell" if a.signal in ("SELL","RSI_OB") else "qt-alert-info")
        tc  = "#00C9A7" if "buy" in css else ("#FF4560" if "sell" in css else "#4B9FFF")
        st.markdown(f"""
        <div class="qt-alert {css}">
          <div class="qt-alert-title" style="color:{tc}">{a.emoji} {a.title}
            <span class="qt-alert-time">{_fmt_local(a.timestamp)}</span>
          </div>
          <div style="color:var(--text-sec)">{a.symbol} @ {a.price:.4f}</div>
          <div style="color:var(--text-mute)">{a.reason[:60]}</div>
        </div>
        """, unsafe_allow_html=True)

    if not engine.queue:
        st.markdown('<div style="color:var(--text-mute);font-size:10px;padding:8px;font-family:var(--mono)">No alerts yet</div>', unsafe_allow_html=True)

    # ── Alert channels ───────────────────────────────────────────
    with st.expander("SIGNAL ALERT CHANNELS", expanded=False):
        st.markdown(
            '''<div style="font-family:var(--mono);font-size:10px;color:var(--text-sec);
            margin-bottom:10px;line-height:1.7;padding:8px 10px;
            background:var(--bg-surface);border-radius:4px;border-left:3px solid var(--blue)">
            <b style="color:var(--text-pri)">Signal alerts</b> fire automatically when the bot detects a
            BUY/SELL signal, RSI extreme, or MA crossover on the chart.<br>
            <b>Discord here</b> = one-way push via Webhook URL (no bot needed, instant setup).<br>
            For interactive ✅/❌ trade confirmation → configure the Discord Bot in the ⚙ ACCOUNTS tab.
            </div>''',
            unsafe_allow_html=True
        )
        at1, at2, at3, at4 = st.tabs(["📧 EMAIL","💬 DISCORD WEBHOOK","📱 WHATSAPP","✈ TELEGRAM"])
        with at1:
            st.caption("Gmail app password: myaccount.google.com → Security → App Passwords")
            em_s = st.text_input("From email", placeholder="you@gmail.com",      key="em_s")
            em_p = st.text_input("App password", placeholder="xxxx xxxx xxxx xxxx", key="em_p", type="password")
            em_r = st.text_input("To email",   placeholder="recipient@mail.com", key="em_r")
            c1,c2 = st.columns(2)
            if c1.button("Save Email",key="save_em",use_container_width=True):
                _rebuild_engine(em_s=em_s,em_p=em_p,em_r=em_r); st.success("Email saved")
            if c2.button("Test Email",key="test_em",use_container_width=True):
                ok,msg = engine.test_channel("email"); (st.success if ok else st.error)(msg)
        with at2:
            st.caption("Server Settings → Integrations → Webhooks → New Webhook → Copy URL")
            _saved_dc_url = st.session_state.get("_discord_webhook_url", "")
            dc_url = st.text_input("Webhook URL", key="dc_url",
                value=_saved_dc_url,
                placeholder="https://discord.com/api/webhooks/1234567890/xxxxxxxxxxxx")
            if dc_url and dc_url.startswith("https://discord.com/api/webhooks/"):
                st.success("✅ Webhook URL looks valid")
            elif dc_url and dc_url != "https://discord.com/api/webhooks/...":
                st.error("❌ URL must start with https://discord.com/api/webhooks/")
            c1,c2 = st.columns(2)
            if c1.button("Save & Enable",key="save_dc",use_container_width=True,type="primary"):
                if dc_url.startswith("https://discord.com/api/webhooks/"):
                    st.session_state["_discord_webhook_url"] = dc_url
                    _rebuild_engine(dc_url=dc_url)
                    save_settings()  # persist webhook URL
                    st.success("✅ Discord webhook saved! Signal alerts will now be sent.")
                else:
                    st.error("Enter a valid Discord webhook URL first")
            if c2.button("Send Test",key="test_dc",use_container_width=True):
                if dc_url.startswith("https://discord.com/api/webhooks/"):
                    _rebuild_engine(dc_url=dc_url)
                    ok,msg = engine.test_channel("discord")
                    (st.success if ok else st.error)(msg)
                else:
                    st.error("Save a valid webhook URL first")
        with at3:
            st.caption("Setup: save +34 644 69 87 99 as 'CallMeBot', send 'I allow callmebot to send me messages', get your API key")
            wa_ph = st.text_input("Phone (no + or spaces)", placeholder="9715XXXXXXXX", key="wa_ph")
            wa_key_v = st.text_input("CallMeBot API Key", placeholder="1234567", key="wa_key")
            c1,c2 = st.columns(2)
            if c1.button("Save WhatsApp",key="save_wa",use_container_width=True):
                _rebuild_engine(wa_phone=wa_ph,wa_key=wa_key_v); st.success("WhatsApp saved")
            if c2.button("Test WhatsApp",key="test_wa",use_container_width=True):
                _rebuild_engine(wa_phone=wa_ph,wa_key=wa_key_v)
                ok,msg = engine.test_channel("whatsapp"); (st.success if ok else st.error)(msg)
        with at4:
            st.caption("@BotFather on Telegram: /newbot, copy token. @userinfobot: copy Chat ID.")
            tg_t = st.text_input("Bot Token", placeholder="1234567:AABBcc...", key="tg_t")
            tg_c = st.text_input("Chat ID",   placeholder="-100123456",        key="tg_c")
            c1,c2 = st.columns(2)
            if c1.button("Save Telegram",key="save_tg",use_container_width=True):
                _rebuild_engine(tg_t=tg_t,tg_c=tg_c); st.success("Telegram saved")
            if c2.button("Test Telegram",key="test_tg",use_container_width=True):
                _rebuild_engine(tg_t=tg_t,tg_c=tg_c)
                ok,msg = engine.test_channel("telegram"); (st.success if ok else st.error)(msg)

# Broker panel
render_broker_panel(df=df, rec=rec, ma_cross_result=st.session_state.ma_cross_result)

# Auto-refresh: use streamlit-autorefresh for autonomous, seamless reruns.
# Falls back to the legacy manual-trigger approach if the package is not installed.
_rsec_safe = max(rsec, 10) if rsec else 30
if st.session_state.auto_refresh and st.session_state.last_refresh > 0:
    try:
        from streamlit_autorefresh import st_autorefresh
        st_autorefresh(interval=_rsec_safe * 1000, limit=None, key="apex_autorefresh")
    except ImportError:
        # Fallback: trigger rerun when interval has elapsed.
        # Does NOT clear df or caches so charts don't flash blank.
        elapsed = time.time() - st.session_state.last_refresh
        if elapsed >= _rsec_safe:
            st.rerun()
