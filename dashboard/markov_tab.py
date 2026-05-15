"""
dashboard/markov_tab.py — Dedicated Markov Chains Analysis Tab

Renders a full-page Markov Chains visualisation including:
  1. Transition Matrix Heatmap (Plotly)
  2. Stationary Distribution Bar Chart
  3. State Probability Path (rolling current state probability)
  4. N-Step Forecast Visualisation
  5. Regime Detection Panel
  6. Signal History Timeline
  7. Raw transition matrix table
"""

from __future__ import annotations

import warnings
from typing import Optional

import numpy as np
import pandas as pd
import streamlit as st

warnings.filterwarnings("ignore")

try:
    import plotly.graph_objects as go
    from plotly.subplots import make_subplots
    PLOTLY_OK = True
except ImportError:
    PLOTLY_OK = False


# ── Color palette (matches main THEME) ────────────────────────────────────────
MKV_PALETTE = {
    "bg":       "#131722",
    "surface":  "#1E222D",
    "card":     "#101827",
    "text":     "#D1D4DC",
    "text_dim": "#787B86",
    "grid":     "#1E2433",
    "purple":   "#9B6DFF",
    "green":    "#00C9A7",
    "red":      "#FF4560",
    "amber":    "#FFB800",
    "blue":     "#4B9FFF",
    "orange":   "#FF8C00",
}


def _get_theme():
    """Return colour palette matching current theme."""
    if st.session_state.get("theme", "light") == "light":
        return {
            "bg":       "#F2F6FC",
            "surface":  "#E8EEF8",
            "card":     "#FFFFFF",
            "text":     "#0B1929",
            "text_dim": "#4A6580",
            "grid":     "#C8D4E8",
            "purple":   "#6A0DAD",
            "green":    "#007A5E",
            "red":      "#C0392B",
            "amber":    "#B7860B",
            "blue":     "#1565C0",
            "orange":   "#D35400",
        }
    return MKV_PALETTE


def _compute_markov(df: pd.DataFrame, n_states: int = 8, lookback: int = 200,
                    n_step: int = 3, tau: float = 0.87, eps: float = 0.05):
    """
    Run the full Markov Chains computation and return a results dict with all
    the data needed for visualisation.
    """
    from strategies.markov_chains import MarkovChainsStrategy, _stationary_distribution, _matrix_power

    if df is None or len(df) < 40:
        return None

    close   = df["Close"].values.astype(float)
    returns = np.diff(close) / np.maximum(close[:-1], 1e-12)
    n = len(returns)
    window  = min(lookback, n)
    r_win   = returns[-window:]

    # Build quantile-based state sequence
    bins    = np.quantile(r_win, np.linspace(0, 1, n_states + 1))
    bins[0]  -= 1e-9
    bins[-1] += 1e-9
    states  = np.digitize(r_win, bins) - 1
    states  = np.clip(states, 0, n_states - 1)

    # Build transition matrix
    P = np.zeros((n_states, n_states))
    for i in range(len(states) - 1):
        P[states[i], states[i + 1]] += 1
    row_sums = P.sum(axis=1, keepdims=True)
    row_sums[row_sums == 0] = 1
    P = P / row_sums

    # Current state + 1-step probabilities
    cur_state = int(states[-1])
    p_hat     = P[cur_state].copy()      # 1-step forward probabilities
    j_star    = int(np.argmax(p_hat))    # most likely next state
    q         = 1.0 / n_states           # uniform baseline

    # N-step probabilities
    P_n       = _matrix_power(P, n_step)
    p_hat_n   = P_n[cur_state]
    j_star_n  = int(np.argmax(p_hat_n))

    # Blend
    w         = 0.35
    p_blend   = (1 - w) * p_hat + w * p_hat_n

    # Stationary distribution
    pi        = _stationary_distribution(P)

    # Arbitrage gap
    delta_j   = float(p_hat[j_star] - q)
    persist   = float(P[j_star, j_star])
    pi_edge   = float(pi[j_star] - q)

    # Signal
    if delta_j >= eps and persist >= tau:
        if j_star >= n_states // 2:
            signal = "BUY"
        else:
            signal = "SELL"
    else:
        signal = "HOLD"

    # Regime
    upper_half = n_states // 2
    bull_mass  = float(pi[upper_half:].sum())
    bear_mass  = float(pi[:upper_half].sum())
    if bull_mass > 0.55:
        regime = "BULL"
    elif bear_mass > 0.55:
        regime = "BEAR"
    else:
        regime = "SIDEWAYS"

    # Rolling current-state probability path (last 60 bars)
    state_path = []
    for i in range(max(0, len(states) - 60), len(states)):
        s = int(states[i])
        p = float(P[s, s]) if i > 0 else 0.5
        state_path.append({"bar": i, "state": s, "persist": p,
                            "return": float(r_win[i]) if i < len(r_win) else 0})

    # N-step forecast bars (show n_step ahead probabilities)
    forecast = [{"step": i + 1, "probs": _matrix_power(P, i + 1)[cur_state].tolist()}
                for i in range(min(n_step, 5))]

    return {
        "P":           P,
        "pi":          pi,
        "p_hat":       p_hat,
        "p_hat_n":     p_hat_n,
        "p_blend":     p_blend,
        "j_star":      j_star,
        "j_star_n":    j_star_n,
        "cur_state":   cur_state,
        "delta_j":     delta_j,
        "persist":     persist,
        "pi_edge":     pi_edge,
        "signal":      signal,
        "regime":      regime,
        "bull_mass":   bull_mass,
        "bear_mass":   bear_mass,
        "n_states":    n_states,
        "tau":         tau,
        "eps":         eps,
        "state_path":  state_path,
        "forecast":    forecast,
        "states":      states,
        "r_win":       r_win,
        "bins":        bins,
    }


def _fig_transition_matrix(m: dict, th: dict) -> go.Figure:
    """Render the N×N transition matrix as a heatmap with annotations."""
    P = m["P"]
    n = m["n_states"]
    j_star = m["j_star"]
    cur = m["cur_state"]

    # Custom colorscale: low = surface, high = purple
    colorscale = [
        [0.0, th["surface"]],
        [0.3, "rgba(75,159,255,0.4)"],
        [0.7, "rgba(155,109,255,0.7)"],
        [1.0, th["purple"]],
    ]

    text_vals = [[f"{P[i, j]:.2f}" for j in range(n)] for i in range(n)]
    # Highlight current row and j* column
    font_colors = []
    for i in range(n):
        row_colors = []
        for j in range(n):
            if i == cur and j == j_star:
                row_colors.append(th["amber"])
            elif i == cur or j == j_star:
                row_colors.append(th["text"])
            else:
                row_colors.append(th["text_dim"])
        font_colors.append(row_colors)

    fig = go.Figure(go.Heatmap(
        z=P,
        text=text_vals,
        texttemplate="%{text}",
        textfont=dict(size=9, family="IBM Plex Mono, monospace"),
        colorscale=colorscale,
        showscale=True,
        colorbar=dict(
            title="P(i→j)",
            titlefont=dict(color=th["text_dim"], size=10),
            tickfont=dict(color=th["text_dim"], size=9),
            thickness=10,
        ),
        hovertemplate="From state %{y} → To state %{x}<br>P = %{z:.4f}<extra></extra>",
    ))

    # Mark current state row
    fig.add_shape(type="rect",
        x0=cur - 0.5, x1=cur + 0.5, y0=-0.5, y1=n - 0.5,
        line=dict(color=th["amber"], width=2), fillcolor="rgba(0,0,0,0)")
    # Mark j* column
    fig.add_shape(type="rect",
        x0=j_star - 0.5, x1=j_star + 0.5, y0=-0.5, y1=n - 0.5,
        line=dict(color=th["green"], width=2, dash="dot"), fillcolor="rgba(0,0,0,0)")

    state_labels = [f"S{i}" for i in range(n)]
    fig.update_layout(
        paper_bgcolor=th["bg"],
        plot_bgcolor=th["surface"],
        font=dict(color=th["text"], family="IBM Plex Mono, monospace", size=10),
        title=dict(text="TRANSITION MATRIX P(i→j)",
                   font=dict(size=12, color=th["text"]), x=0.0, xanchor="left"),
        xaxis=dict(tickvals=list(range(n)), ticktext=state_labels,
                   title="Next State", tickfont=dict(size=9),
                   gridcolor=th["grid"]),
        yaxis=dict(tickvals=list(range(n)), ticktext=state_labels,
                   title="Current State", tickfont=dict(size=9),
                   gridcolor=th["grid"], autorange="reversed"),
        margin=dict(l=50, r=60, t=40, b=40),
        height=340,
        annotations=[
            dict(text=f"■ Current state S{cur}", x=1.18, y=1.0,
                 xref="paper", yref="paper", showarrow=False,
                 font=dict(color=th["amber"], size=9)),
            dict(text=f"┊ j*=S{j_star} (next)", x=1.18, y=0.92,
                 xref="paper", yref="paper", showarrow=False,
                 font=dict(color=th["green"], size=9)),
        ]
    )
    return fig


def _fig_stationary_dist(m: dict, th: dict) -> go.Figure:
    """Stationary distribution π bar chart."""
    pi = m["pi"]
    n  = m["n_states"]
    j_star = m["j_star"]
    q = 1.0 / n

    colors = []
    for i in range(n):
        if i == j_star:
            colors.append(th["amber"])
        elif i >= n // 2:
            colors.append(th["green"])
        else:
            colors.append(th["red"])

    fig = go.Figure()
    fig.add_trace(go.Bar(
        x=[f"S{i}" for i in range(n)],
        y=pi,
        marker_color=colors,
        text=[f"{v:.3f}" for v in pi],
        textposition="outside",
        textfont=dict(size=9, color=th["text"]),
        name="π",
        hovertemplate="State %{x}<br>π = %{y:.4f}<extra></extra>",
    ))
    # Uniform baseline
    fig.add_hline(y=q, line=dict(color=th["purple"], width=1.5, dash="dash"),
                  annotation_text=f"Uniform 1/N={q:.3f}",
                  annotation_font=dict(color=th["purple"], size=9))

    fig.update_layout(
        paper_bgcolor=th["bg"],
        plot_bgcolor=th["surface"],
        font=dict(color=th["text"], family="IBM Plex Mono, monospace", size=10),
        title=dict(text="STATIONARY DISTRIBUTION π  (long-run state probabilities)",
                   font=dict(size=12, color=th["text"]), x=0.0, xanchor="left"),
        xaxis=dict(gridcolor=th["grid"], tickfont=dict(size=9)),
        yaxis=dict(gridcolor=th["grid"], tickfont=dict(size=9), title="Probability"),
        showlegend=False,
        margin=dict(l=50, r=20, t=40, b=30),
        height=260,
    )
    return fig


def _fig_state_path(m: dict, df: pd.DataFrame, th: dict) -> go.Figure:
    """Price + current state over time with colour coding."""
    states = m["states"]
    r_win  = m["r_win"]
    n      = m["n_states"]
    n_bars = min(len(states), 80)

    close = df["Close"].values[-n_bars:] if df is not None else np.arange(n_bars)
    s_win = states[-n_bars:]
    idx   = list(range(n_bars))

    # Normalise state to [-1, 1] for overlay
    s_norm = (s_win / (n - 1)) * 2 - 1

    fig = make_subplots(rows=2, cols=1, shared_xaxes=True,
                        row_heights=[0.65, 0.35],
                        vertical_spacing=0.06)

    # Price
    fig.add_trace(go.Scatter(
        x=idx, y=close,
        line=dict(color=th["blue"], width=1.5),
        name="Price", showlegend=True,
    ), row=1, col=1)

    # State bar (coloured green=bull, red=bear)
    bar_colors = [th["green"] if s >= n // 2 else th["red"] for s in s_win]
    fig.add_trace(go.Bar(
        x=idx, y=s_win,
        marker_color=bar_colors,
        name="State", opacity=0.7, showlegend=True,
        hovertemplate="Bar %{x}<br>State %{y}<extra></extra>",
    ), row=2, col=1)

    # Mark current state
    fig.add_vline(x=n_bars - 1, line=dict(color=th["amber"], width=1.5, dash="dash"),
                  row="all", col=1)

    fig.update_layout(
        paper_bgcolor=th["bg"],
        plot_bgcolor=th["surface"],
        font=dict(color=th["text"], family="IBM Plex Mono, monospace", size=10),
        title=dict(text="PRICE vs STATE SEQUENCE  (last 80 bars)",
                   font=dict(size=12, color=th["text"]), x=0.0, xanchor="left"),
        xaxis=dict(gridcolor=th["grid"], tickfont=dict(size=9), showticklabels=False),
        xaxis2=dict(gridcolor=th["grid"], tickfont=dict(size=9), title="Bar"),
        yaxis=dict(gridcolor=th["grid"], tickfont=dict(size=9), title="Price"),
        yaxis2=dict(gridcolor=th["grid"], tickfont=dict(size=9), title="State",
                    tickvals=list(range(n)), ticktext=[f"S{i}" for i in range(n)]),
        legend=dict(bgcolor="rgba(0,0,0,0)", font=dict(size=9)),
        margin=dict(l=60, r=20, t=40, b=30),
        height=340,
        hovermode="x unified",
    )
    return fig


def _fig_forecast(m: dict, th: dict) -> go.Figure:
    """N-step ahead forecast: probability of each state at each step."""
    forecast = m["forecast"]
    n        = m["n_states"]
    j_star   = m["j_star"]

    fig = go.Figure()
    steps = [f["step"] for f in forecast]

    for state_idx in range(n):
        probs = [f["probs"][state_idx] for f in forecast]
        color = th["amber"] if state_idx == j_star else (
                th["green"] if state_idx >= n // 2 else th["red"])
        width = 2.5 if state_idx == j_star else 1.0
        dash  = "solid" if state_idx == j_star else "dot"
        opacity = 1.0 if state_idx == j_star else 0.45
        fig.add_trace(go.Scatter(
            x=steps, y=probs,
            mode="lines+markers",
            name=f"S{state_idx}{'★' if state_idx == j_star else ''}",
            line=dict(color=color, width=width, dash=dash),
            marker=dict(size=6 if state_idx == j_star else 4),
            opacity=opacity,
            hovertemplate=f"S{state_idx}<br>Step %{{x}}<br>P=%{{y:.4f}}<extra></extra>",
        ))

    # Uniform baseline
    fig.add_hline(y=1 / n, line=dict(color=th["purple"], width=1, dash="dash"),
                  annotation_text=f"Uniform 1/N",
                  annotation_font=dict(color=th["purple"], size=9))

    fig.update_layout(
        paper_bgcolor=th["bg"],
        plot_bgcolor=th["surface"],
        font=dict(color=th["text"], family="IBM Plex Mono, monospace", size=10),
        title=dict(text=f"N-STEP FORECAST  (P^n from current state S{m['cur_state']})",
                   font=dict(size=12, color=th["text"]), x=0.0, xanchor="left"),
        xaxis=dict(gridcolor=th["grid"], tickfont=dict(size=9), title="Step Ahead",
                   tickvals=steps, ticktext=[f"t+{s}" for s in steps]),
        yaxis=dict(gridcolor=th["grid"], tickfont=dict(size=9), title="P(next state)"),
        legend=dict(bgcolor="rgba(0,0,0,0)", font=dict(size=9),
                    orientation="h", yanchor="bottom", y=1.02),
        margin=dict(l=50, r=20, t=60, b=40),
        height=280,
        hovermode="x unified",
    )
    return fig


def _fig_return_distribution(m: dict, th: dict) -> go.Figure:
    """Return distribution per state (violin/box)."""
    states = m["states"]
    r_win  = m["r_win"]
    n      = m["n_states"]
    n_bars = min(len(states), len(r_win))

    fig = go.Figure()
    for s in range(n):
        mask   = (states[:n_bars] == s)
        rets_s = r_win[:n_bars][mask] * 100  # pct
        if len(rets_s) == 0:
            continue
        color = th["green"] if s >= n // 2 else th["red"]
        fig.add_trace(go.Violin(
            y=rets_s,
            name=f"S{s}",
            box_visible=True,
            meanline_visible=True,
            line_color=color,
            fillcolor=color.replace(")", ",0.15)").replace("rgb", "rgba") if "rgb" in color else color,
            opacity=0.7,
        ))

    fig.update_layout(
        paper_bgcolor=th["bg"],
        plot_bgcolor=th["surface"],
        font=dict(color=th["text"], family="IBM Plex Mono, monospace", size=10),
        title=dict(text="RETURN DISTRIBUTION BY STATE  (%)",
                   font=dict(size=12, color=th["text"]), x=0.0, xanchor="left"),
        xaxis=dict(gridcolor=th["grid"], tickfont=dict(size=9)),
        yaxis=dict(gridcolor=th["grid"], tickfont=dict(size=9), title="Return (%)"),
        showlegend=False,
        margin=dict(l=50, r=20, t=40, b=30),
        height=260,
        violinmode="overlay",
    )
    return fig


def render_markov_tab(df: Optional[pd.DataFrame], symbol: str):
    """
    Render the full Markov Chains analysis tab.
    Call this inside a st.tab("⛓ MARKOV") block.
    """
    th = _get_theme()

    st.markdown(f"""
    <div style="font-family:'IBM Plex Mono',monospace;padding:12px 0 8px">
      <span style="font-size:16px;font-weight:700;color:{th['text']};letter-spacing:.1em">
        ⛓ MARKOV CHAINS ANALYSIS
      </span>
      <span style="margin-left:12px;font-size:10px;color:{th['text_dim']}">
        {symbol} · Statistical market-state model
      </span>
    </div>
    """, unsafe_allow_html=True)

    if df is None or len(df) < 40:
        st.warning("Load at least 40 bars of chart data first, then switch to this tab.")
        return

    # ── Controls ──────────────────────────────────────────────────────────────
    with st.expander("⚙ Model Parameters", expanded=False):
        c1, c2, c3, c4, c5 = st.columns(5)
        n_states = c1.number_input("States (N)", 4, 16, 8, 2, key="mkv_n_states",
                                    help="Number of quantile-based return states")
        lookback = c2.number_input("Lookback", 50, 500, 200, 25, key="mkv_lookback",
                                    help="Bars used to build transition matrix")
        n_step   = c3.number_input("N-Step", 1, 10, 3, 1, key="mkv_n_step",
                                    help="Steps ahead for forecast")
        tau_v    = c4.slider("τ Persistence", 0.5, 0.99, 0.87, 0.01, key="mkv_tau",
                              help="Min diagonal persistence for signal")
        eps_v    = c5.slider("ε Gap", 0.01, 0.30, 0.05, 0.01, key="mkv_eps",
                              help="Min arbitrage gap p̂(j*) − 1/N")

    n_states = int(n_states)
    lookback = int(lookback)
    n_step   = int(n_step)

    # ── Compute ───────────────────────────────────────────────────────────────
    with st.spinner("Computing Markov Chains model..."):
        try:
            m = _compute_markov(df, n_states=n_states, lookback=lookback,
                                 n_step=n_step, tau=tau_v, eps=eps_v)
        except Exception as e:
            st.error(f"Markov computation failed: {e}")
            return

    if m is None:
        st.warning("Insufficient data for Markov model. Load more bars.")
        return

    # ── Signal banner ─────────────────────────────────────────────────────────
    sig = m["signal"]
    sig_color = th["green"] if sig == "BUY" else (th["red"] if sig == "SELL" else th["amber"])
    regime = m["regime"]
    regime_icon = "🐂" if regime == "BULL" else ("🐻" if regime == "BEAR" else "↔")

    st.markdown(f"""
    <div style="display:flex;gap:12px;align-items:stretch;margin-bottom:12px;flex-wrap:wrap">
      <div style="flex:1;min-width:140px;background:{th['surface']};border:2px solid {sig_color};
           border-radius:8px;padding:14px 18px;text-align:center">
        <div style="font-size:9px;color:{th['text_dim']};letter-spacing:.15em;margin-bottom:4px">SIGNAL</div>
        <div style="font-size:28px;font-weight:700;color:{sig_color};font-family:'IBM Plex Mono',monospace;
             letter-spacing:.1em">{sig}</div>
      </div>
      <div style="flex:1;min-width:130px;background:{th['surface']};border:1px solid {th['grid']};
           border-radius:8px;padding:14px 18px;text-align:center">
        <div style="font-size:9px;color:{th['text_dim']};letter-spacing:.15em;margin-bottom:4px">REGIME</div>
        <div style="font-size:20px;font-weight:700;color:{th['text']};font-family:'IBM Plex Mono',monospace">
          {regime_icon} {regime}</div>
      </div>
      <div style="flex:1;min-width:120px;background:{th['surface']};border:1px solid {th['grid']};
           border-radius:8px;padding:14px 18px;text-align:center">
        <div style="font-size:9px;color:{th['text_dim']};letter-spacing:.15em;margin-bottom:4px">CUR STATE</div>
        <div style="font-size:20px;font-weight:700;color:{th['amber']};font-family:'IBM Plex Mono',monospace">
          S{m['cur_state']}</div>
      </div>
      <div style="flex:1;min-width:120px;background:{th['surface']};border:1px solid {th['grid']};
           border-radius:8px;padding:14px 18px;text-align:center">
        <div style="font-size:9px;color:{th['text_dim']};letter-spacing:.15em;margin-bottom:4px">NEXT j*</div>
        <div style="font-size:20px;font-weight:700;color:{th['green']};font-family:'IBM Plex Mono',monospace">
          S{m['j_star']}</div>
      </div>
      <div style="flex:1;min-width:120px;background:{th['surface']};border:1px solid {th['grid']};
           border-radius:8px;padding:14px 18px;text-align:center">
        <div style="font-size:9px;color:{th['text_dim']};letter-spacing:.15em;margin-bottom:4px">δ(j*)</div>
        <div style="font-size:20px;font-weight:700;color:{th['blue']};font-family:'IBM Plex Mono',monospace">
          {m['delta_j']:+.4f}</div>
      </div>
      <div style="flex:1;min-width:120px;background:{th['surface']};border:1px solid {th['grid']};
           border-radius:8px;padding:14px 18px;text-align:center">
        <div style="font-size:9px;color:{th['text_dim']};letter-spacing:.15em;margin-bottom:4px">P(j*,j*) τ</div>
        <div style="font-size:20px;font-weight:700;color:{'var(--green)' if m['persist']>=tau_v else 'var(--red)'};
             font-family:'IBM Plex Mono',monospace">{m['persist']:.3f}</div>
      </div>
      <div style="flex:1;min-width:120px;background:{th['surface']};border:1px solid {th['grid']};
           border-radius:8px;padding:14px 18px;text-align:center">
        <div style="font-size:9px;color:{th['text_dim']};letter-spacing:.15em;margin-bottom:4px">π-EDGE</div>
        <div style="font-size:20px;font-weight:700;color:{th['purple']};font-family:'IBM Plex Mono',monospace">
          {m['pi_edge']:+.4f}</div>
      </div>
    </div>
    """, unsafe_allow_html=True)

    # ── Charts ────────────────────────────────────────────────────────────────
    if not PLOTLY_OK:
        st.warning("Install plotly for charts: pip install plotly")
        return

    # Row 1: Transition matrix + Stationary dist
    c1, c2 = st.columns([1, 1])
    with c1:
        st.plotly_chart(_fig_transition_matrix(m, th), use_container_width=True,
                        config=dict(displayModeBar=False))
    with c2:
        st.plotly_chart(_fig_stationary_dist(m, th), use_container_width=True,
                        config=dict(displayModeBar=False))

    # Row 2: Price + State path (full width)
    st.plotly_chart(_fig_state_path(m, df, th), use_container_width=True,
                    config=dict(displayModeBar=True,
                                modeBarButtonsToRemove=["toImage"],
                                displaylogo=False))

    # Row 3: N-step forecast + Return distribution
    c1, c2 = st.columns([1, 1])
    with c1:
        st.plotly_chart(_fig_forecast(m, th), use_container_width=True,
                        config=dict(displayModeBar=False))
    with c2:
        st.plotly_chart(_fig_return_distribution(m, th), use_container_width=True,
                        config=dict(displayModeBar=False))

    # ── Conditions check ─────────────────────────────────────────────────────
    st.markdown(f"""
    <div style="background:{th['surface']};border:1px solid {th['grid']};border-radius:6px;
         padding:14px 18px;margin-top:8px;font-family:'IBM Plex Mono',monospace">
      <div style="font-size:10px;font-weight:700;color:{th['text']};letter-spacing:.12em;margin-bottom:10px">
        ENTRY CONDITIONS CHECK
      </div>
      <div style="display:grid;grid-template-columns:repeat(auto-fill,minmax(200px,1fr));gap:8px">
        <div style="padding:8px 12px;border-radius:4px;
             background:{'rgba(0,201,167,0.1)' if m['delta_j']>=eps_v else 'rgba(255,69,96,0.1)'};
             border:1px solid {'rgba(0,201,167,0.3)' if m['delta_j']>=eps_v else 'rgba(255,69,96,0.3)'}">
          <div style="font-size:8px;color:{th['text_dim']};letter-spacing:.1em">ARBITRAGE GAP δ ≥ ε</div>
          <div style="font-size:13px;font-weight:600;color:{'th[green]' if m['delta_j']>=eps_v else th['red']}">
            {m['delta_j']:+.4f} {'✓' if m['delta_j']>=eps_v else '✗'} (ε={eps_v})</div>
        </div>
        <div style="padding:8px 12px;border-radius:4px;
             background:{'rgba(0,201,167,0.1)' if m['persist']>=tau_v else 'rgba(255,69,96,0.1)'};
             border:1px solid {'rgba(0,201,167,0.3)' if m['persist']>=tau_v else 'rgba(255,69,96,0.3)'}">
          <div style="font-size:8px;color:{th['text_dim']};letter-spacing:.1em">PERSISTENCE P(j*,j*) ≥ τ</div>
          <div style="font-size:13px;font-weight:600;color:{'#00C9A7' if m['persist']>=tau_v else '#FF4560'}">
            {m['persist']:.4f} {'✓' if m['persist']>=tau_v else '✗'} (τ={tau_v})</div>
        </div>
        <div style="padding:8px 12px;border-radius:4px;background:rgba(75,159,255,0.1);
             border:1px solid rgba(75,159,255,0.3)">
          <div style="font-size:8px;color:{th['text_dim']};letter-spacing:.1em">BULL MARKET MASS</div>
          <div style="font-size:13px;font-weight:600;color:{th['blue']}">{m['bull_mass']:.3f}</div>
        </div>
        <div style="padding:8px 12px;border-radius:4px;background:rgba(75,159,255,0.1);
             border:1px solid rgba(75,159,255,0.3)">
          <div style="font-size:8px;color:{th['text_dim']};letter-spacing:.1em">BEAR MARKET MASS</div>
          <div style="font-size:13px;font-weight:600;color:{th['blue']}">{m['bear_mass']:.3f}</div>
        </div>
        <div style="padding:8px 12px;border-radius:4px;background:rgba(155,109,255,0.1);
             border:1px solid rgba(155,109,255,0.3)">
          <div style="font-size:8px;color:{th['text_dim']};letter-spacing:.1em">π-EDGE (j* over-rep)</div>
          <div style="font-size:13px;font-weight:600;color:{th['purple']}">{m['pi_edge']:+.4f}</div>
        </div>
        <div style="padding:8px 12px;border-radius:4px;background:rgba(255,184,0,0.1);
             border:1px solid rgba(255,184,0,0.3)">
          <div style="font-size:8px;color:{th['text_dim']};letter-spacing:.1em">CURRENT STATE</div>
          <div style="font-size:13px;font-weight:600;color:{th['amber']}">S{m['cur_state']} of {m['n_states']}</div>
        </div>
      </div>
    </div>
    """, unsafe_allow_html=True)

    # ── Raw matrix table ──────────────────────────────────────────────────────
    with st.expander("📊 Raw Transition Matrix Table", expanded=False):
        P = m["P"]
        n = m["n_states"]
        df_P = pd.DataFrame(
            P,
            index=[f"S{i} →" for i in range(n)],
            columns=[f"S{j}" for j in range(n)],
        ).round(4)
        st.dataframe(df_P, use_container_width=True)

    with st.expander("📐 Stationary Distribution Table", expanded=False):
        pi = m["pi"]
        df_pi = pd.DataFrame({
            "State": [f"S{i}" for i in range(n_states)],
            "π(i)": pi.round(4),
            "π(i) - 1/N": (pi - 1/n_states).round(4),
            "Bull/Bear": ["BULL" if i >= n_states//2 else "BEAR" for i in range(n_states)],
        })
        st.dataframe(df_pi, use_container_width=True, hide_index=True)
