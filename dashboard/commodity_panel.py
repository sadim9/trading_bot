"""
dashboard/commodity_panel.py — Commodity quick-picker panel.

Renders a compact strip of Gold / Silver / WTI / Brent buttons with live
prices and daily change. Clicking a button switches the main chart to that
commodity symbol.

Usage:
    from dashboard.commodity_panel import render_commodity_quickpick

    clicked = render_commodity_quickpick(current_symbol, source, api_key)
    if clicked:
        st.session_state["symbol"] = clicked
        st.session_state["df"] = None
        st.rerun()
"""

from __future__ import annotations

import streamlit as st
from typing import Optional

from data.commodity_feeds import (
    COMMODITY_SYMBOLS,
    get_commodity_last_price,
)

# Default commodities shown in the strip (in display order)
_DEFAULT_STRIP = ["XAUUSD", "XAGUSD", "USOIL", "UKOIL"]

# Extended list shown in the "More commodities" expander
_EXTENDED_STRIP = ["XPTUSD", "NGAS"]


def render_commodity_quickpick(
    current_symbol: str = "",
    source: str = "yfinance",
    api_key: str = "",
) -> Optional[str]:
    """
    Render the commodity quick-picker bar.

    Returns the symbol string if the user clicked a button to switch to it,
    otherwise returns None.
    """
    clicked: Optional[str] = None

    st.markdown(
        """
        <div style="font-family:'IBM Plex Mono',monospace;font-size:8px;
          letter-spacing:.18em;text-transform:uppercase;color:var(--text-mute);
          padding:6px 0 4px 0">
          ◈ COMMODITIES
        </div>
        """,
        unsafe_allow_html=True,
    )

    # ── Price strip ──────────────────────────────────────────────────────────
    strip_syms = _DEFAULT_STRIP + _EXTENDED_STRIP
    cols = st.columns(len(strip_syms))

    for idx, sym in enumerate(strip_syms):
        meta = COMMODITY_SYMBOLS.get(sym, {})
        label = meta.get("label", sym)
        icon  = meta.get("icon",  "◆")

        # Try fetching live price (cached — won't hammer the API)
        info = get_commodity_last_price(sym, source=source, api_key=api_key)

        is_active = current_symbol.upper() == sym.upper()
        border_col = "var(--amber)" if is_active else "var(--border)"

        if info:
            price  = info["price"]
            chg    = info["change_pct"]
            chg_col = "#00C9A7" if chg >= 0 else "#FF4560"
            chg_arr = "▲" if chg >= 0 else "▼"
            price_str = f"${price:,.2f}" if price > 10 else f"${price:,.4f}"

            cols[idx].markdown(
                f"""
                <div style="background:var(--bg-card);border:1px solid {border_col};
                  border-radius:4px;padding:6px 8px;text-align:center;
                  font-family:'IBM Plex Mono',monospace;cursor:pointer;
                  transition:border-color .2s">
                  <div style="font-size:9px;color:var(--text-mute);letter-spacing:.1em">{icon} {label}</div>
                  <div style="font-size:12px;font-weight:600;color:var(--text-pri);margin:2px 0">{price_str}</div>
                  <div style="font-size:9px;color:{chg_col}">{chg_arr}{abs(chg):.2f}%</div>
                </div>
                """,
                unsafe_allow_html=True,
            )
        else:
            cols[idx].markdown(
                f"""
                <div style="background:var(--bg-card);border:1px solid {border_col};
                  border-radius:4px;padding:6px 8px;text-align:center;
                  font-family:'IBM Plex Mono',monospace">
                  <div style="font-size:9px;color:var(--text-mute);letter-spacing:.1em">{icon} {label}</div>
                  <div style="font-size:10px;color:var(--text-mute);margin:2px 0">—</div>
                  <div style="font-size:9px;color:var(--text-mute)">—</div>
                </div>
                """,
                unsafe_allow_html=True,
            )

        # Button to switch to this symbol
        btn_key = f"cmdty_btn_{sym}_{idx}"
        btn_label = f"{'▶ ' if is_active else ''}{sym}"
        if cols[idx].button(btn_label, key=btn_key, use_container_width=True,
                            type="primary" if is_active else "secondary"):
            clicked = sym

    return clicked
