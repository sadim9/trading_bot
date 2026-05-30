"""
dashboard/ml_tab.py — Machine Learning Analysis Tab for Apex Terminal.

Renders the full ML tab inside app.py's tab layout.

Features:
  - Model training controls (model type, horizon, CV folds)
  - Live training progress bar
  - Out-of-sample metrics dashboard (R², Directional Acc, Sharpe, MAE)
  - Interactive charts:
      • Actual vs Predicted returns scatter
      • Rolling OOS predictions vs actual price
      • Feature importance bar chart
      • CV fold R² breakdown
      • Prediction confidence gauge
      • Multi-horizon price targets
  - Real-time prediction card with BUY/SELL/HOLD signal
  - All charts theme-aware (dark/light) and mobile-friendly
"""

from __future__ import annotations

import time
import warnings
import numpy as np
import pandas as pd
import streamlit as st
from typing import Optional

warnings.filterwarnings("ignore")

try:
    import plotly.graph_objects as go
    from plotly.subplots import make_subplots
    PLOTLY_OK = True
except ImportError:
    PLOTLY_OK = False

from dashboard.charts import THEME


# ── Theme helpers ──────────────────────────────────────────────────────────────
def _th(light_mode: bool) -> dict:
    """Return colour tokens for current theme."""
    if light_mode:
        return dict(
            bg="#F2F6FC", surface="#E8EEF8", card="#FFFFFF",
            border="#BDC9DC", text="#0B1929", text_sec="#365070",
            text_mute="#7090AE", green="#00735C", red="#C0001E",
            amber="#96620A", blue="#1555A2", purple="#6030BE",
            grid="#BDC9DC",
        )
    return dict(
        bg="#080D1A", surface="#0C1322", card="#101827",
        border="#1A2540", text="#DCE4F5", text_sec="#7A8BA8",
        text_mute="#3A4A62", green="#00C9A7", red="#FF4560",
        amber="#FFB800", blue="#4B9FFF", purple="#9B6DFF",
        grid="#1E2433",
    )


def _plotly_layout(t: dict, title: str = "", height: int = 360) -> dict:
    return dict(
        title=dict(text=title, font=dict(size=12, color=t["text_sec"], family="IBM Plex Mono")),
        paper_bgcolor=t["bg"], plot_bgcolor=t["surface"],
        font=dict(family="IBM Plex Mono", size=10, color=t["text"]),
        height=height,
        margin=dict(l=40, r=20, t=40, b=40),
        xaxis=dict(gridcolor=t["grid"], showgrid=True, zeroline=False,
                   tickfont=dict(size=9, color=t["text_mute"])),
        yaxis=dict(gridcolor=t["grid"], showgrid=True, zeroline=True,
                   zerolinecolor=t["border"], tickfont=dict(size=9, color=t["text_mute"])),
        legend=dict(bgcolor=t["card"], bordercolor=t["border"], borderwidth=1,
                    font=dict(size=9, color=t["text_sec"])),
    )


def _signal_css_class(signal: str) -> str:
    return {"BUY": "qt-signal-buy", "SELL": "qt-signal-sell"}.get(signal, "qt-signal-hold")


# ── Main render function ───────────────────────────────────────────────────────
def render_ml_tab(
    df: pd.DataFrame,
    symbol: str,
    interval: str = "1d",
    light_mode: bool = True,
):
    """
    Render the full ML tab content.

    Called from app.py inside the ML tab context.
    """
    t = _th(light_mode)
    sess = st.session_state

    st.markdown(
        '<div class="qt-section">🤖 MACHINE LEARNING — RETURN PREDICTION ENGINE</div>',
        unsafe_allow_html=True,
    )

    if not PLOTLY_OK:
        st.error("plotly not installed — run `pip install plotly`")
        return

    if df is None or len(df) < 60:
        st.warning(
            "⚠️ Need at least **60 bars** to train the ML models. "
            "Load a longer period (e.g. 1y daily) and try again."
        )
        return

    # ── Sidebar controls ───────────────────────────────────────────────────────
    with st.expander("⚙ MODEL CONFIGURATION", expanded=False):
        c1, c2, c3, c4 = st.columns([2, 1.5, 1.5, 1])

        model_labels = ["Ensemble (Best)", "Neural Net NN3", "Random Forest", "Elastic Net"]
        model_vals   = ["ensemble", "neural_net", "random_forest", "elastic_net"]
        model_label  = c1.selectbox(
            "Model", model_labels,
            index=0,
            help="Ensemble combines all 3 models (best OOS performance)",
        )
        model_type = model_vals[model_labels.index(model_label)]

        horizon = c2.selectbox(
            "Horizon", [1, 3, 5, 10, 20],
            index=0,
            format_func=lambda x: f"{x} bar{'s' if x>1 else ''}",
            help="Bars ahead to predict",
        )

        n_cv = c3.selectbox("CV Folds", [3, 5, 7], index=0)

        train_btn = c4.button("▶ TRAIN", type="primary", use_container_width=True)

    # ── Training ───────────────────────────────────────────────────────────────
    _cache_key = f"ml_result_{symbol}_{model_type}_{horizon}"
    result = sess.get(_cache_key)

    if train_btn or result is None:
        _train_progress = st.progress(0, text="Initialising …")
        _train_status   = st.empty()

        def _cb(pct: int, msg: str):
            _train_progress.progress(pct / 100, text=msg)
            _train_status.caption(msg)

        try:
            from ml.trainer import train as ml_train
            result = ml_train(
                df=df,
                symbol=symbol,
                model_type=model_type,
                horizon=horizon,
                n_cv_folds=n_cv,
                progress_callback=_cb,
            )
            sess[_cache_key] = result
            _train_progress.progress(1.0, text="Training complete ✓")
            time.sleep(0.4)
            _train_progress.empty()
            _train_status.empty()
            st.toast(f"ML model trained for {symbol} — R²(OOS): {result.r2_oos*100:.3f}%", icon="🤖")
        except Exception as e:
            _train_progress.empty()
            _train_status.empty()
            st.error(f"Training failed: {e}")
            return

    if result is None:
        st.info("Click **▶ TRAIN** to train the ML model on the loaded data.")
        return

    # ── Generate prediction ────────────────────────────────────────────────────
    from ml.predictor import predict as ml_predict
    pred = ml_predict(result, df, interval)

    # ═══════════════════════════════════════════════════════════════════════════
    #  PREDICTION CARD  (top section)
    # ═══════════════════════════════════════════════════════════════════════════
    _render_prediction_card(pred, result, t, interval)

    st.markdown("<hr style='margin:12px 0'>", unsafe_allow_html=True)

    # ═══════════════════════════════════════════════════════════════════════════
    #  METRICS STRIP
    # ═══════════════════════════════════════════════════════════════════════════
    _render_metrics_strip(result, t)

    st.markdown("<hr style='margin:12px 0'>", unsafe_allow_html=True)

    # ═══════════════════════════════════════════════════════════════════════════
    #  CHARTS — 2-column layout
    # ═══════════════════════════════════════════════════════════════════════════
    ch_left, ch_right = st.columns([1, 1], gap="small")

    with ch_left:
        st.plotly_chart(
            _chart_oos_overlay(result, df, t, symbol),
            use_container_width=True,
            config=dict(displayModeBar=False),
        )

    with ch_right:
        st.plotly_chart(
            _chart_feature_importance(result, t),
            use_container_width=True,
            config=dict(displayModeBar=False),
        )

    ch2_left, ch2_right = st.columns([1, 1], gap="small")

    with ch2_left:
        st.plotly_chart(
            _chart_actual_vs_predicted(result, t),
            use_container_width=True,
            config=dict(displayModeBar=False),
        )

    with ch2_right:
        st.plotly_chart(
            _chart_cv_folds(result, t),
            use_container_width=True,
            config=dict(displayModeBar=False),
        )

    # ═══════════════════════════════════════════════════════════════════════════
    #  MULTI-HORIZON TARGETS
    # ═══════════════════════════════════════════════════════════════════════════
    if pred:
        st.markdown('<div class="qt-section">MULTI-HORIZON PRICE TARGETS</div>', unsafe_allow_html=True)
        _render_multi_horizon(result, df, interval, t)

    # ═══════════════════════════════════════════════════════════════════════════
    #  REASONING / EXPLANATION
    # ═══════════════════════════════════════════════════════════════════════════
    if pred and pred.reasoning:
        with st.expander("💡 MODEL REASONING", expanded=True):
            for r in pred.reasoning:
                st.markdown(f"• {r}")

    # Training metadata
    with st.expander("ℹ MODEL DETAILS", expanded=False):
        col_a, col_b, col_c, col_d = st.columns(4)
        col_a.metric("Bars Used",     f"{result.n_bars}")
        col_b.metric("Features",      f"{result.n_features}")
        col_c.metric("Train Time",    f"{result.train_time_s:.1f}s")
        col_d.metric("Horizon",       f"{result.horizon} bar(s)")
        st.caption(
            f"Model: **{result.model_type}** · Symbol: {result.symbol} · "
            f"CV Folds: {len(result.cv_folds)}"
        )


# ── Sub-renderers ──────────────────────────────────────────────────────────────

def _render_prediction_card(pred, result, t: dict, interval: str):
    """Big signal card at the top of the ML tab."""
    if pred is None:
        st.info("Generating prediction …")
        return

    sig_class = _signal_css_class(pred.signal)
    ret_str   = f"{pred.predicted_return*100:+.3f}%"
    px_str    = f"${pred.predicted_price:,.4f}"
    cur_str   = f"${pred.current_price:,.4f}"
    conf_str  = f"{pred.confidence:.0f}%"
    sig_icon  = {"BUY": "▲", "SELL": "▼", "HOLD": "◼"}.get(pred.signal, "◼")
    sig_color = {"BUY": t["green"], "SELL": t["red"], "HOLD": t["amber"]}.get(pred.signal, t["amber"])

    # Individual model preds
    indiv_html = ""
    if pred.individual_preds:
        model_colors = {"enet": t["blue"], "rf": t["green"], "nn3": t["purple"]}
        model_labels = {"enet": "ElasticNet", "rf": "Random Forest", "nn3": "Neural Net"}
        for mk, mv in pred.individual_preds.items():
            col = model_colors.get(mk, t["text_sec"])
            lbl = model_labels.get(mk, mk)
            indiv_html += (
                f'<span style="color:{col};font-size:10px;margin-right:14px">'
                f'{lbl}: {mv*100:+.3f}%</span>'
            )

    st.markdown(f"""
<div class="qt-signal {sig_class}">
  <div class="qt-signal-label">
    <span class="qt-pulse" style="background:{sig_color}"></span>
    {pred.signal_strength} {pred.signal} &nbsp;
    <span style="font-size:20px;color:{sig_color}">{sig_icon} {ret_str}</span>
    <span style="font-size:13px;color:{t['text_sec']};font-weight:400">
      &nbsp;next {pred.horizon_label}
    </span>
  </div>
  <div class="qt-signal-meta" style="margin-top:8px;display:flex;gap:24px;flex-wrap:wrap">
    <span>NOW <b style="color:{t['text']}">{cur_str}</b></span>
    <span>TARGET <b style="color:{sig_color}">{px_str}</b></span>
    <span>CONFIDENCE <b style="color:{t['text']}">{conf_str}</b></span>
    <span>SL <b style="color:{t['red']}">${pred.stop_loss:,.4f}</b></span>
    <span>TP <b style="color:{t['green']}">${pred.take_profit:,.4f}</b></span>
    <span>R/R <b style="color:{t['text']}">{pred.risk_reward:.1f}×</b></span>
  </div>
  <div style="margin-top:6px">{indiv_html}</div>
</div>
""", unsafe_allow_html=True)


def _render_metrics_strip(result, t: dict):
    """Row of model performance metrics."""
    c1, c2, c3, c4, c5, c6 = st.columns(6)

    r2_pct     = result.r2_oos * 100
    r2_cv_pct  = result.r2_oos_cv * 100
    dir_pct    = result.directional_acc * 100
    sharpe     = result.sharpe_est
    mae_bps    = result.mae * 10000

    # R² colour coding (positive = good in this context even if small)
    r2_delta = "✓" if r2_pct > 0 else "✗"

    c1.metric("OOS R² (vs zero)", f"{r2_pct:.4f}%", r2_delta)
    c2.metric("CV Avg R²",        f"{r2_cv_pct:.4f}%")
    c3.metric("Directional Acc",  f"{dir_pct:.1f}%",
              "above chance" if dir_pct > 52 else "at/below chance")
    c4.metric("Est. Sharpe",      f"{sharpe:.2f}",
              "positive" if sharpe > 0 else "negative")
    c5.metric("MAE",              f"{mae_bps:.1f} bps")
    n_folds = len(result.cv_folds)
    c6.metric("CV Folds",         f"{n_folds}")

    # Individual model R² breakdown (ensemble only)
    if result.individual_r2:
        cols = st.columns(len(result.individual_r2))
        labels = {"enet": "ElasticNet R²", "rf": "Random Forest R²", "nn3": "Neural Net R²"}
        for ci, (mk, mv) in zip(cols, result.individual_r2.items()):
            ci.metric(labels.get(mk, mk), f"{mv*100:.4f}%")


def _hex_to_rgba(hex_color: str, alpha: float = 0.12) -> str:
    """Convert hex colour string to rgba(r,g,b,alpha)."""
    h = hex_color.lstrip("#")
    if len(h) == 6:
        r, g, b = int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)
        return f"rgba({r},{g},{b},{alpha})"
    return f"rgba(0,201,167,{alpha})"


def _chart_oos_overlay(result, df: pd.DataFrame, t: dict, symbol: str) -> go.Figure:
    """Actual price + ML predicted return overlay (rolling OOS test period)."""
    if not result.oos_dates:
        fig = go.Figure()
        fig.update_layout(**_plotly_layout(t, "OOS Predictions vs Actual"))
        return fig

    dates = pd.to_datetime(result.oos_dates)
    actual   = np.array(result.oos_actual)   * 100
    predicted = np.array(result.oos_predicted) * 100

    # Cumulative return of long/short strategy
    ls_pnl = np.where(predicted > 0, actual, -actual)
    cum_ls = np.cumprod(1 + ls_pnl / 100) - 1

    fig = make_subplots(rows=2, cols=1, shared_xaxes=True,
                        row_heights=[0.55, 0.45], vertical_spacing=0.05)

    # Top: Actual vs predicted bar returns
    fig.add_trace(go.Scatter(
        x=dates, y=actual, name="Actual Return",
        line=dict(color=t["text_sec"], width=1), opacity=0.6,
    ), row=1, col=1)
    fig.add_trace(go.Scatter(
        x=dates, y=predicted, name="ML Predicted",
        line=dict(color=t["blue"], width=1.5),
    ), row=1, col=1)

    # Bottom: Cumulative L/S strategy
    fig.add_trace(go.Scatter(
        x=dates, y=cum_ls * 100,
        name="Long/Short Cumulative %",
        fill="tozeroy",
        line=dict(color=t["green"], width=1.5),
        fillcolor=_hex_to_rgba(t["green"], 0.12),
    ), row=2, col=1)

    lay = _plotly_layout(t, f"OOS: Predicted vs Actual · {symbol}", height=380)
    lay["yaxis"]  = dict(**lay.get("yaxis", {}), title=dict(text="Return %", font=dict(size=9)))
    lay["yaxis2"] = dict(gridcolor=t["grid"], showgrid=True, zeroline=True,
                         zerolinecolor=t["border"], tickfont=dict(size=9, color=t["text_mute"]),
                         title=dict(text="L/S Cumulative %", font=dict(size=9)))
    fig.update_layout(**lay)
    return fig


def _chart_feature_importance(result, t: dict) -> go.Figure:
    """Horizontal bar chart of feature importance."""
    imp = result.feature_importance
    if not imp:
        fig = go.Figure()
        fig.update_layout(**_plotly_layout(t, "Feature Importance"))
        return fig

    sorted_imp = sorted(imp.items(), key=lambda x: x[1], reverse=True)[:15]
    labels = [_fmt_feat_name(k) for k, _ in sorted_imp]
    values = [v for _, v in sorted_imp]

    # Colour by category
    colors = []
    for k, _ in sorted_imp:
        if "ret" in k or "accel" in k:
            colors.append(t["amber"])
        elif "rsi" in k or "bb" in k or "stoch" in k:
            colors.append(t["purple"])
        elif "vol" in k or "atr" in k:
            colors.append(t["red"])
        elif "ema" in k or "macd" in k:
            colors.append(t["blue"])
        else:
            colors.append(t["green"])

    fig = go.Figure(go.Bar(
        x=values, y=labels, orientation="h",
        marker=dict(color=colors, opacity=0.85),
        hovertemplate="%{y}: %{x:.4f}<extra></extra>",
    ))
    lay = _plotly_layout(t, "Feature Importance (Top 15)", height=380)
    lay["yaxis"] = dict(**lay.get("yaxis", {}), autorange="reversed",
                        tickfont=dict(size=9, color=t["text_mute"]))
    lay["xaxis"] = dict(**lay.get("xaxis", {}), title=dict(text="Importance", font=dict(size=9)))
    fig.update_layout(**lay)
    return fig


def _chart_actual_vs_predicted(result, t: dict) -> go.Figure:
    """Scatter: actual vs predicted return (OOS test period)."""
    if not result.oos_actual:
        fig = go.Figure()
        fig.update_layout(**_plotly_layout(t, "Actual vs Predicted"))
        return fig

    actual    = np.array(result.oos_actual)   * 100
    predicted = np.array(result.oos_predicted) * 100

    # Colour by correct direction
    correct = (np.sign(actual) == np.sign(predicted))
    colors  = [t["green"] if c else t["red"] for c in correct]

    # Perfect prediction line
    mx = max(np.abs(actual).max(), np.abs(predicted).max()) * 1.1
    line_x = [-mx, mx]

    fig = go.Figure()
    fig.add_trace(go.Scatter(
        x=line_x, y=line_x, name="Perfect",
        line=dict(color=t["border"], dash="dash", width=1),
        showlegend=False,
    ))
    fig.add_trace(go.Scatter(
        x=predicted, y=actual,
        mode="markers",
        name="OOS Samples",
        marker=dict(color=colors, size=4, opacity=0.6),
        hovertemplate="Pred: %{x:.3f}%<br>Act: %{y:.3f}%<extra></extra>",
    ))

    lay = _plotly_layout(t, "Actual vs Predicted Return (%)", height=350)
    lay["xaxis"] = dict(**lay.get("xaxis", {}), title=dict(text="Predicted %", font=dict(size=9)))
    lay["yaxis"] = dict(**lay.get("yaxis", {}), title=dict(text="Actual %", font=dict(size=9)))
    fig.update_layout(**lay)

    # Annotation: directional accuracy
    fig.add_annotation(
        text=f"Dir. Acc: {result.directional_acc*100:.1f}%",
        xref="paper", yref="paper", x=0.05, y=0.95,
        showarrow=False, font=dict(size=10, color=t["text_sec"]),
        bgcolor=t["card"], bordercolor=t["border"],
    )
    return fig


def _chart_cv_folds(result, t: dict) -> go.Figure:
    """Bar chart of R² across expanding-window CV folds."""
    folds = result.cv_folds
    if not folds:
        fig = go.Figure()
        fig.update_layout(**_plotly_layout(t, "CV Fold Performance"))
        return fig

    fold_nums = [f"Fold {f.fold}" for f in folds]
    r2_vals   = [f.r2_oos * 100 for f in folds]
    train_n   = [f.train_size for f in folds]
    colors    = [t["green"] if r > 0 else t["red"] for r in r2_vals]

    fig = make_subplots(rows=1, cols=2, subplot_titles=["OOS R² per Fold", "Train Size per Fold"],
                        column_widths=[0.6, 0.4])

    fig.add_trace(go.Bar(
        x=fold_nums, y=r2_vals,
        marker_color=colors, opacity=0.85, name="R²",
        hovertemplate="%{x}: %{y:.4f}%<extra></extra>",
    ), row=1, col=1)

    fig.add_trace(go.Bar(
        x=fold_nums, y=train_n,
        marker_color=t["blue"], opacity=0.7, name="Train bars",
        hovertemplate="%{x}: %{y} bars<extra></extra>",
    ), row=1, col=2)

    lay = _plotly_layout(t, "Expanding-Window CV Results", height=310)
    lay["yaxis"]  = dict(**lay.get("yaxis", {}),
                         title=dict(text="R² %", font=dict(size=9)),
                         zeroline=True, zerolinecolor=t["border"])
    lay["yaxis2"] = dict(gridcolor=t["grid"], showgrid=True, zeroline=False,
                         tickfont=dict(size=9, color=t["text_mute"]),
                         title=dict(text="# bars", font=dict(size=9)))
    lay["showlegend"] = False
    fig.update_layout(**lay)
    return fig


def _render_multi_horizon(result, df: pd.DataFrame, interval: str, t: dict):
    """Quick multi-horizon predictions using the already-trained features."""
    from ml.features import build_features, rank_standardise, FEATURE_COLS
    from ml.models import make_model

    horizons = [1, 5, 20]
    current_price = float(df["Close"].iloc[-1])

    cols = st.columns(len(horizons))
    for ci, h in enumerate(horizons):
        try:
            from ml.features import build_dataset
            from ml.trainer import train as ml_train, _r2_oos_vs_zero
            from ml.predictor import predict as ml_predict, _horizon_label

            cache_key = f"ml_mh_{result.symbol}_{result.model_type}_{h}"
            r_h = st.session_state.get(cache_key)
            if r_h is None:
                r_h = ml_train(df, result.symbol, model_type=result.model_type,
                               horizon=h, n_cv_folds=2)
                st.session_state[cache_key] = r_h

            p_h = ml_predict(r_h, df, interval)
            if p_h is None:
                cols[ci].caption(f"H={h}: no prediction")
                continue

            ret_pct = p_h.predicted_return * 100
            sig = p_h.signal
            sig_col = {"BUY": t["green"], "SELL": t["red"]}.get(sig, t["amber"])
            hl = _horizon_label(h, interval)

            cols[ci].markdown(f"""
<div style="background:{t['card']};border:1px solid {sig_col if sig!='HOLD' else t['border']};
     border-radius:6px;padding:12px 14px;text-align:center">
  <div style="font-size:9px;color:{t['text_mute']};letter-spacing:.15em;text-transform:uppercase;margin-bottom:4px">
    {hl}
  </div>
  <div style="font-size:20px;font-weight:700;color:{sig_col}">{sig}</div>
  <div style="font-size:14px;font-weight:600;color:{t['text']};margin-top:2px">
    {ret_pct:+.3f}%
  </div>
  <div style="font-size:11px;color:{t['text_sec']};margin-top:4px">
    Target: ${p_h.predicted_price:,.4f}
  </div>
  <div style="font-size:10px;color:{t['text_mute']};margin-top:2px">
    Conf: {p_h.confidence:.0f}%
  </div>
</div>
""", unsafe_allow_html=True)
        except Exception:
            cols[ci].caption(f"H={h}: computing …")


def _fmt_feat_name(key: str) -> str:
    """Human-readable feature labels."""
    label_map = {
        "f_ret_1":      "Return 1-bar",
        "f_ret_5":      "Return 5-bar",
        "f_ret_20":     "Momentum 1mo",
        "f_ret_60":     "Momentum 3mo",
        "f_ret_120":    "Momentum 6mo",
        "f_ema_cross":  "EMA Cross",
        "f_vs_ema_f":   "Price vs EMA Fast",
        "f_vs_ema_s":   "Price vs EMA Slow",
        "f_macd_norm":  "MACD (norm)",
        "f_macd_hist":  "MACD Histogram",
        "f_rsi_norm":   "RSI (norm)",
        "f_bb_pct":     "Bollinger %B",
        "f_stoch":      "Stochastic %K",
        "f_close_vs_high": "Close vs High20",
        "f_close_vs_low":  "Close vs Low20",
        "f_atr_norm":   "ATR / Price",
        "f_realvol":    "Realised Vol",
        "f_vol_accel":  "Vol Acceleration",
        "f_vol_ratio":  "Volume Ratio",
        "f_obv_mom":    "OBV Momentum",
        "f_breakout_u": "Breakout Up",
        "f_breakout_d": "Breakout Down",
        "f_range_pos":  "Range Position",
        "f_price_accel":"Price Acceleration",
    }
    return label_map.get(key, key.replace("f_", "").replace("_", " ").title())
