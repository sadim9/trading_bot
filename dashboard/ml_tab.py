"""
dashboard/ml_tab.py — Machine Learning Analysis Tab for Apex Terminal.

Key design principles:
  - Never auto-trains; all training is explicit (button click only)
  - Price-level charts instead of raw return % (intuitive for traders)
  - Clear data quality guidance
  - Capped metric display (no -86000% R² confusing users)
  - Mobile-friendly Plotly charts
"""

from __future__ import annotations

import os
import pickle
import warnings
import numpy as np
import pandas as pd
import streamlit as st
from pathlib import Path
from typing import Optional

warnings.filterwarnings("ignore")

_MODEL_DIR = Path(os.getenv("SETTINGS_DIR", "/app/logs"))


def _model_path(symbol: str, model_type: str, horizon: int) -> Path:
    # Sanitise symbol: keep only alphanumeric, dash, underscore — prevent path traversal
    import re
    safe = re.sub(r"[^A-Za-z0-9_\-]", "_", symbol)[:32]
    safe_type = re.sub(r"[^A-Za-z0-9_]", "_", model_type)[:24]
    return _MODEL_DIR / f"ml_model_{safe}_{safe_type}_h{int(horizon)}.pkl"


def _save_model(result, symbol: str, model_type: str, horizon: int):
    """Persist a trained MLTrainingResult to disk."""
    try:
        _MODEL_DIR.mkdir(parents=True, exist_ok=True)
        p = _model_path(symbol, model_type, horizon)
        with open(p, "wb") as f:
            pickle.dump(result, f)
    except Exception:
        try:
            fb = Path(".cache")
            fb.mkdir(exist_ok=True)
            safe = symbol.replace("/", "_").replace(":", "_")
            p2 = fb / f"ml_model_{safe}_{model_type}_h{horizon}.pkl"
            with open(p2, "wb") as f:
                pickle.dump(result, f)
        except Exception:
            pass


def _load_model(symbol: str, model_type: str, horizon: int):
    """Load a previously saved MLTrainingResult from disk."""
    for p in [
        _model_path(symbol, model_type, horizon),
        Path(".cache") / f"ml_model_{symbol.replace('/', '_').replace(':', '_')}_{model_type}_h{horizon}.pkl",
    ]:
        try:
            if p.exists():
                with open(p, "rb") as f:
                    return pickle.load(f)
        except Exception:
            continue
    return None

try:
    import plotly.graph_objects as go
    from plotly.subplots import make_subplots
    PLOTLY_OK = True
except ImportError:
    PLOTLY_OK = False


# ── Theme helpers ──────────────────────────────────────────────────────────────
def _th(light_mode: bool) -> dict:
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


def _plotly_base(t: dict, title: str = "", height: int = 360) -> dict:
    return dict(
        title=dict(text=title, font=dict(size=11, color=t["text_sec"], family="IBM Plex Mono")),
        paper_bgcolor=t["bg"], plot_bgcolor=t["surface"],
        font=dict(family="IBM Plex Mono", size=10, color=t["text"]),
        height=height,
        margin=dict(l=50, r=20, t=40, b=40),
        xaxis=dict(gridcolor=t["grid"], showgrid=True, zeroline=False,
                   tickfont=dict(size=9, color=t["text_mute"])),
        yaxis=dict(gridcolor=t["grid"], showgrid=True, zeroline=True,
                   zerolinecolor=t["border"], tickfont=dict(size=9, color=t["text_mute"])),
        legend=dict(bgcolor="rgba(0,0,0,0)", bordercolor=t["border"], borderwidth=0,
                    font=dict(size=9, color=t["text_sec"]), orientation="h",
                    yanchor="bottom", y=1.02, xanchor="left", x=0),
        hovermode="x unified",
    )


def _cap_r2(v: float) -> str:
    """Cap displayed R² to ±500% to prevent confusing huge negatives."""
    if v < -5.0:
        return f"< -500%"
    return f"{v*100:.4f}%"


def _quality_badge(quality: str, t: dict) -> str:
    cfg = {
        "good":         ("✓ GOOD DATA",        t["green"],  "≥2000 bars — full model suite active"),
        "fair":         ("~ FAIR DATA",         t["amber"],  "600–2000 bars — NN3 uses smaller architecture"),
        "poor":         ("⚠ LIMITED DATA",      t["red"],    "200–600 bars — ElasticNet + RF only"),
        "insufficient": ("✗ INSUFFICIENT DATA", t["red"],    "<200 bars — increase period or use daily interval"),
    }.get(quality, ("? UNKNOWN", t["text_mute"], ""))
    label, color, tip = cfg
    return (
        f'<span style="background:{color}22;border:1px solid {color}55;'
        f'border-radius:3px;padding:2px 8px;font-size:9px;letter-spacing:.1em;'
        f'color:{color};font-family:IBM Plex Mono">{label}</span> '
        f'<span style="font-size:9px;color:{t["text_mute"]}">{tip}</span>'
    )


# ─────────────────────────────────────────────────────────────────────────────
#  MAIN RENDER
# ─────────────────────────────────────────────────────────────────────────────
def render_ml_tab(
    df: pd.DataFrame,
    symbol: str,
    interval: str = "1d",
    light_mode: bool = True,
):
    t   = _th(light_mode)
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
            "⚠️ Need at least **60 bars** to train. "
            "For best results: switch interval to **1d** and period to **2y**."
        )
        return

    # ── Data quality pre-check ─────────────────────────────────────────────────
    n_bars = len(df)
    if n_bars < 500:
        quality_hint = "fair" if n_bars >= 200 else "poor"
    elif n_bars < 2000:
        quality_hint = "fair"
    else:
        quality_hint = "good"

    # ── Symbol guard — purge stale cached results on ticker change ─────────────
    _last_sym = sess.get("_ml_active_symbol")
    if _last_sym and _last_sym != symbol:
        for _k in [k for k in list(sess.keys())
                   if k.startswith("ml_result_") or k.startswith("ml_mh_")]:
            del sess[_k]
    sess["_ml_active_symbol"] = symbol

    # ── Model configuration — wrapped in a form to prevent per-widget reruns ─────
    _has_any_result = any(k.startswith(f"ml_result_{symbol}_") for k in sess.keys())
    # Restore persisted config defaults
    _saved_model_type = sess.get("_ml_model_type", "ensemble")
    _saved_horizon    = sess.get("_ml_horizon", 1)
    _saved_cv         = sess.get("_ml_cv_folds", 3)

    model_labels = ["Ensemble (Best)", "Random Forest", "Elastic Net", "Neural Net NN3"]
    model_vals   = ["ensemble",        "random_forest", "elastic_net", "neural_net"]
    _model_default_idx = model_vals.index(_saved_model_type) if _saved_model_type in model_vals else 0
    _horizon_opts  = [1, 3, 5, 10, 20]
    _horizon_default_idx = _horizon_opts.index(_saved_horizon) if _saved_horizon in _horizon_opts else 0
    _cv_opts = [3, 5]
    _cv_default_idx = _cv_opts.index(_saved_cv) if _saved_cv in _cv_opts else 0

    with st.expander("⚙ MODEL CONFIGURATION", expanded=not _has_any_result):
        with st.form("ml_config_form", clear_on_submit=False):
            c1, c2, c3, c4 = st.columns([2, 1.5, 1.5, 1])
            model_label = c1.selectbox(
                "Model", model_labels, index=_model_default_idx,
                help="Ensemble combines the best models for your dataset size. "
                     "Neural Net requires 600+ bars and works best with daily data.",
            )
            model_type = model_vals[model_labels.index(model_label)]

            horizon = c2.selectbox(
                "Horizon", _horizon_opts, index=_horizon_default_idx,
                format_func=lambda x: f"{x} bar{'s' if x>1 else ''}",
                help="Bars ahead to predict. Shorter horizons = more frequent signals.",
            )
            n_cv = c3.selectbox("CV Folds", _cv_opts, index=_cv_default_idx)
            train_btn = c4.form_submit_button("▶ TRAIN", type="primary", use_container_width=True)

            # Data quality inline guidance
            st.markdown(
                f'<div style="margin-top:8px">{_quality_badge(quality_hint, t)}</div>',
                unsafe_allow_html=True,
            )
            if n_bars < 2000:
                st.caption(
                    f"💡 **Tip:** You have {n_bars} bars of {interval} data. "
                    "For the best ML results, switch to **1d** interval with **2y** period "
                    "(≈500 bars) — daily data has cleaner signal-to-noise than intraday."
                )

    # Persist config whenever it changes (form submit)
    if train_btn:
        from dashboard.settings_store import save_settings
        sess["_ml_model_type"] = model_type
        sess["_ml_horizon"]    = horizon
        sess["_ml_cv_folds"]   = n_cv
        save_settings()
    else:
        # Keep in sync even without training
        model_type = sess.get("_ml_model_type", model_type)
        horizon    = sess.get("_ml_horizon",    horizon)
        n_cv       = sess.get("_ml_cv_folds",   n_cv)

    # ── Training (only on button click) ───────────────────────────────────────
    _cache_key = f"ml_result_{symbol}_{model_type}_{horizon}"
    result = sess.get(_cache_key)

    # Try loading from disk if not in session
    if result is None:
        result = _load_model(symbol, model_type, horizon)
        if result is not None:
            sess[_cache_key] = result

    if train_btn:
        # Always include the selected horizon; also train H1, H5, H20 for multi-horizon display
        _MH_HORIZONS = list(dict.fromkeys([horizon, 1, 5, 20]))
        _total_steps  = len(_MH_HORIZONS)
        _prog = st.progress(0, text="Initialising …")
        _stat = st.empty()
        result = None  # reset so we get the fresh result

        try:
            from ml.trainer import train as ml_train

            for _hi, _h in enumerate(_MH_HORIZONS):
                _is_primary = (_h == horizon)
                _h_key      = f"ml_result_{symbol}_{model_type}_{_h}" if _is_primary \
                              else f"ml_mh_{symbol}_{model_type}_{_h}"
                _h_cv       = n_cv if _is_primary else 2

                _base_pct = int(_hi / _total_steps * 100)

                def _cb(pct: int, msg: str, base=_base_pct, span=int(100/_total_steps)):
                    total = min(base + int(pct * span / 100), 99)
                    _prog.progress(total / 100, text=f"H={_h}: {msg}")
                    _stat.caption(f"Horizon {_h} bars — {msg}")

                _h_result = ml_train(
                    df=df, symbol=symbol, model_type=model_type,
                    horizon=_h, n_cv_folds=_h_cv,
                    progress_callback=_cb,
                )
                sess[_h_key] = _h_result
                # Save to disk
                _save_model(_h_result, symbol, model_type, _h)

                if _is_primary:
                    result = _h_result
                    sess[_cache_key] = _h_result

            # Safety: if selected horizon wasn't in list somehow, use first trained
            if result is None:
                result = sess.get(_cache_key)

            _prog.progress(1.0, text="All horizons trained ✓")
            _prog.empty()
            _stat.empty()
            if result is not None:
                st.toast(
                    f"✅ {model_type.replace('_',' ').title()} trained — "
                    f"H1/H5/H20 ready · Dir. Acc: {result.directional_acc*100:.1f}%",
                    icon="🤖",
                )
        except Exception as e:
            _prog.empty()
            _stat.empty()
            st.error(f"Training failed: {e}")
            import traceback
            st.code(traceback.format_exc(), language="python")
            return

    if result is None:
        st.info(
            f"No trained model for **{symbol}** yet. "
            "Select your model above and click **▶ TRAIN** to start."
        )
        return

    # ── Generate current prediction ────────────────────────────────────────────
    from ml.predictor import predict as ml_predict
    pred = ml_predict(result, df, interval)

    # ═══════════════════════════════════════════════════════════════════════════
    #  PREDICTION SIGNAL CARD
    # ═══════════════════════════════════════════════════════════════════════════
    _render_prediction_card(pred, result, t, interval)

    st.markdown(
        f'<div style="margin:6px 0 10px">{_quality_badge(result.data_quality, t)}</div>',
        unsafe_allow_html=True,
    )

    # ═══════════════════════════════════════════════════════════════════════════
    #  METRICS STRIP
    # ═══════════════════════════════════════════════════════════════════════════
    _render_metrics_strip(result, t)

    st.markdown("<hr style='margin:10px 0 14px'>", unsafe_allow_html=True)

    # ═══════════════════════════════════════════════════════════════════════════
    #  CHARTS
    #  Row 1 (full-width): Price chart with ML signals — scrollable / zoomable
    #  Row 2 (3-col):      Actual vs Predicted | Feature Importance | CV Folds
    # ═══════════════════════════════════════════════════════════════════════════

    # ── Row 1: Price chart — full width, tall, interactive ───────────────────
    st.plotly_chart(
        _chart_price_with_signals(result, df, t, symbol, pred, light_mode=light_mode),
        use_container_width=True,
        config=dict(
            scrollZoom=True,
            displayModeBar=True,
            modeBarButtonsToRemove=["lasso2d", "select2d", "autoScale2d",
                                    "toggleSpikelines", "hoverClosestCartesian"],
            modeBarButtonsToAdd=["drawline"],
            toImageButtonOptions=dict(format="png", filename=f"{symbol}_ml_chart"),
            responsive=True,
        ),
    )

    # ── Row 2: Actual vs Predicted PRICE line chart ──────────────────────────
    st.plotly_chart(
        _chart_price_prediction_line(result, df, t),
        use_container_width=True,
        config=dict(
            scrollZoom=True,
            displayModeBar=True,
            modeBarButtonsToRemove=["lasso2d", "select2d", "autoScale2d",
                                    "toggleSpikelines", "hoverClosestCartesian"],
            toImageButtonOptions=dict(format="png", filename=f"{symbol}_predicted_price"),
            responsive=True,
        ),
    )

    # ── Row 3: Scatter + CV Folds (side by side) ─────────────────────────────
    sc_col, cv_col = st.columns([1, 1], gap="small")
    with sc_col:
        st.plotly_chart(
            _chart_actual_vs_predicted(result, t),
            use_container_width=True, config=dict(displayModeBar=False),
        )

    with cv_col:
        st.plotly_chart(
            _chart_cv_folds(result, t),
            use_container_width=True, config=dict(displayModeBar=False),
        )

    # ── Row 5: Feature Importance (full width) ────────────────────────────────
    st.plotly_chart(
        _chart_feature_importance(result, t),
        use_container_width=True, config=dict(displayModeBar=False),
    )

    # ═══════════════════════════════════════════════════════════════════════════
    #  MULTI-HORIZON TARGETS (cached only — no extra training)
    # ═══════════════════════════════════════════════════════════════════════════
    st.markdown('<div class="qt-section">MULTI-HORIZON PRICE TARGETS</div>',
                unsafe_allow_html=True)
    _render_multi_horizon(result, df, interval, t)

    # ═══════════════════════════════════════════════════════════════════════════
    #  MODEL REASONING
    # ═══════════════════════════════════════════════════════════════════════════
    if pred and pred.reasoning:
        with st.expander("💡 MODEL REASONING", expanded=True):
            for r in pred.reasoning:
                st.markdown(f"• {r}")

    with st.expander("ℹ MODEL DETAILS", expanded=False):
        d1, d2, d3, d4 = st.columns(4)
        d1.metric("Bars Used",   f"{result.n_bars}")
        d2.metric("Features",    f"{result.n_features}")
        d3.metric("Train Time",  f"{result.train_time_s:.1f}s")
        d4.metric("Horizon",     f"{result.horizon} bar(s)")
        if result.active_models:
            st.caption(f"Active models: **{', '.join(result.active_models)}**")
        st.caption(
            f"Model: **{result.model_type}** · Symbol: {result.symbol} · "
            f"CV Folds: {len(result.cv_folds)} · Data quality: **{result.data_quality}**"
        )

    # ═══════════════════════════════════════════════════════════════════════════
    #  5-MINUTE PREDICTION ENGINE (separate section)
    # ═══════════════════════════════════════════════════════════════════════════
    st.markdown("<hr style='margin:18px 0'>", unsafe_allow_html=True)
    _render_5min_section(df, symbol, interval, t, light_mode)


# ─────────────────────────────────────────────────────────────────────────────
#  PREDICTION CARD
# ─────────────────────────────────────────────────────────────────────────────
def _render_prediction_card(pred, result, t: dict, interval: str):
    if pred is None:
        st.info("Generating prediction …")
        return

    sig_class = {"BUY": "qt-signal-buy", "SELL": "qt-signal-sell"}.get(pred.signal, "qt-signal-hold")
    sig_color = {"BUY": t["green"], "SELL": t["red"]}.get(pred.signal, t["amber"])
    sig_icon  = {"BUY": "▲", "SELL": "▼", "HOLD": "◼"}.get(pred.signal, "◼")
    ret_str   = f"{pred.predicted_return*100:+.3f}%"
    conf_col  = t["green"] if pred.confidence >= 60 else (t["amber"] if pred.confidence >= 45 else t["red"])

    # Individual model predictions
    indiv_html = ""
    if pred.individual_preds:
        m_labels = {"enet": "ElasticNet", "rf": "Random Forest", "nn3": "Neural Net"}
        m_colors = {"enet": t["blue"], "rf": t["green"], "nn3": t["purple"]}
        for mk, mv in pred.individual_preds.items():
            col = m_colors.get(mk, t["text_sec"])
            lbl = m_labels.get(mk, mk)
            indiv_html += (
                f'<span style="color:{col};font-size:10px;margin-right:14px">'
                f'{lbl}: {mv*100:+.3f}%</span>'
            )

    st.markdown(f"""
<div class="qt-signal {sig_class}">
  <div class="qt-signal-label">
    <span class="qt-pulse" style="background:{sig_color}"></span>
    {pred.signal_strength}&nbsp;{pred.signal}&nbsp;
    <span style="font-size:22px;color:{sig_color}">{sig_icon}&nbsp;{ret_str}</span>
    <span style="font-size:12px;color:{t['text_sec']};font-weight:400">
      &nbsp;· next {pred.horizon_label}
    </span>
  </div>
  <div style="margin-top:8px;display:flex;gap:20px;flex-wrap:wrap;font-family:IBM Plex Mono;font-size:10px;color:{t['text_sec']}">
    <span>NOW <b style="color:{t['text']}">${pred.current_price:,.4f}</b></span>
    <span>TARGET <b style="color:{sig_color}">${pred.predicted_price:,.4f}</b></span>
    <span>CONFIDENCE <b style="color:{conf_col}">{pred.confidence:.0f}%</b></span>
    <span>SL <b style="color:{t['red']}">${pred.stop_loss:,.4f}</b></span>
    <span>TP <b style="color:{t['green']}">${pred.take_profit:,.4f}</b></span>
    <span>R/R <b style="color:{t['text']}">{pred.risk_reward:.1f}×</b></span>
  </div>
  {f'<div style="margin-top:6px">{indiv_html}</div>' if indiv_html else ''}
</div>
""", unsafe_allow_html=True)


# ─────────────────────────────────────────────────────────────────────────────
#  METRICS STRIP
# ─────────────────────────────────────────────────────────────────────────────
def _render_metrics_strip(result, t: dict):
    c1, c2, c3, c4, c5 = st.columns(5)

    r2_str   = _cap_r2(result.r2_oos)
    r2cv_str = _cap_r2(result.r2_oos_cv)
    dir_pct  = result.directional_acc * 100
    dir_ok   = dir_pct > 52
    sharpe   = result.sharpe_est

    c1.metric("OOS R²",         r2_str,  "✓" if result.r2_oos > 0 else "✗ negative")
    c2.metric("CV Avg R²",      r2cv_str)
    c3.metric("Directional Acc", f"{dir_pct:.1f}%",
              "above chance" if dir_ok else "≤ random")
    c4.metric("Est. Sharpe",    f"{sharpe:.2f}",
              "positive" if sharpe > 0 else "negative")
    c5.metric("Train Bars",     f"{result.n_bars}")

    # Interpretation guide
    if result.r2_oos < -5.0 or dir_pct < 45:
        st.warning(
            "⚠️ **Low model quality** — negative R² and sub-random directional accuracy "
            "indicate the model is fitting noise, not signal. "
            "**Recommended fix:** Switch to **1d interval + 2y period** (click ⟳ LOAD first, then ▶ TRAIN). "
            "Daily data has 10× better signal-to-noise than 5-minute intraday data.",
            icon="📊",
        )
    elif dir_pct < 52:
        st.info(
            "ℹ Model is at/near random (directional accuracy ≈ 50%). "
            "Consider using a longer history or daily data for stronger signal."
        )

    # Individual model R² breakdown (ensemble)
    if result.individual_r2:
        labels = {"enet": "ElasticNet R²", "rf": "Random Forest R²", "nn3": "Neural Net R²"}
        cols = st.columns(len(result.individual_r2))
        for ci, (mk, mv) in zip(cols, result.individual_r2.items()):
            cols[ci].metric(labels.get(mk, mk), _cap_r2(mv))


# ─────────────────────────────────────────────────────────────────────────────
#  CHART 1: Price chart with ML signal overlay
# ─────────────────────────────────────────────────────────────────────────────
def _chart_price_with_signals(result, df: pd.DataFrame, t: dict, symbol: str, pred, light_mode: bool = False) -> go.Figure:
    """
    Show actual price (candlestick) for the recent OOS period,
    overlaid with ML BUY/SELL signals based on OOS predictions.
    Also marks the current price and ML target.
    """
    if not result.oos_dates or len(result.oos_dates) < 5:
        fig = go.Figure()
        fig.update_layout(**_plotly_base(t, "Price + ML Signals — train a model to see signals"))
        return fig

    oos_dates = pd.to_datetime(result.oos_dates)
    oos_pred  = np.array(result.oos_predicted)
    oos_act   = np.array(result.oos_actual)

    # Bug 4 fix: use the FULL df for price display (not just OOS period).
    # The OOS period ends `horizon` bars before the last bar because forward
    # returns are NaN for the last N rows. Show the full loaded data so the
    # chart reaches today, then overlay signals on the OOS sub-period.
    df_full = df.dropna(subset=["Close", "Open", "High", "Low"])
    df_oos  = df_full.reindex(oos_dates, method="nearest", tolerance="1D").dropna(subset=["Close"])

    fig = make_subplots(
        rows=2, cols=1, shared_xaxes=True,
        row_heights=[0.72, 0.28], vertical_spacing=0.02,
        subplot_titles=["", "Rolling 20-bar Directional Accuracy"],
    )
    fig.layout.annotations[0].update(text="")   # clear auto subplot title

    # ── Full price history (candlestick) ──────────────────────────────────────
    fig.add_trace(go.Candlestick(
        x=df_full.index,
        open=df_full["Open"], high=df_full["High"],
        low=df_full["Low"],   close=df_full["Close"],
        name="Price",
        increasing_line_color=t["green"],
        decreasing_line_color=t["red"],
        increasing_fillcolor="rgba(0,201,167,0.22)" if not light_mode else "rgba(0,115,92,0.18)",
        decreasing_fillcolor="rgba(255,69,96,0.22)"  if not light_mode else "rgba(192,0,30,0.18)",
        showlegend=True,
        whiskerwidth=0,
    ), row=1, col=1)

    # ── Shade the OOS test period ─────────────────────────────────────────────
    if len(oos_dates) > 1:
        oos_start = oos_dates[0]
        oos_end   = oos_dates[-1]
        fill_col  = "rgba(75,159,255,0.06)" if not light_mode else "rgba(21,85,162,0.05)"
        fig.add_vrect(
            x0=oos_start, x1=oos_end,
            fillcolor=fill_col, line_width=0,
            annotation_text="← OOS test period →",
            annotation_position="top left",
            annotation_font=dict(size=9, color=t["text_mute"]),
            row=1, col=1,
        )

    # ── BUY / SELL signals on OOS period ─────────────────────────────────────
    pred_std = max(float(np.std(oos_pred)), 1e-6) if len(oos_pred) > 5 else 0.003
    buy_thr  = pred_std * 0.4    # top ~35% of predictions → BUY
    sell_thr = -pred_std * 0.4   # bottom ~35%             → SELL

    n_oos = len(df_oos)
    if n_oos > 0:
        buy_idx  = [i for i in np.where(oos_pred > buy_thr)[0]  if i < n_oos]
        sell_idx = [i for i in np.where(oos_pred < sell_thr)[0] if i < n_oos]

        if buy_idx:
            fig.add_trace(go.Scatter(
                x=[oos_dates[i] for i in buy_idx],
                y=[float(df_oos["Low"].iloc[i])  * 0.9965 for i in buy_idx],
                mode="markers", name="ML BUY",
                marker=dict(symbol="triangle-up", size=13, color=t["green"],
                            opacity=1.0, line=dict(color=t["bg"], width=1.5)),
                hovertemplate="<b>ML BUY Signal</b><br>%{x|%b %d %H:%M}<br>Price: $%{y:,.2f}<extra></extra>",
            ), row=1, col=1)

        if sell_idx:
            fig.add_trace(go.Scatter(
                x=[oos_dates[i] for i in sell_idx],
                y=[float(df_oos["High"].iloc[i]) * 1.0035 for i in sell_idx],
                mode="markers", name="ML SELL",
                marker=dict(symbol="triangle-down", size=13, color=t["red"],
                            opacity=1.0, line=dict(color=t["bg"], width=1.5)),
                hovertemplate="<b>ML SELL Signal</b><br>%{x|%b %d %H:%M}<br>Price: $%{y:,.2f}<extra></extra>",
            ), row=1, col=1)

    # ── Current price + ML target lines (at current date) ────────────────────
    if pred:
        sig_col = {"BUY": t["green"], "SELL": t["red"]}.get(pred.signal, t["text_mute"])
        fig.add_hline(
            y=pred.current_price, line_color=t["amber"], line_width=1.5,
            line_dash="dot",
            annotation_text=f"  Now  ${pred.current_price:,.2f}",
            annotation_font=dict(size=9, color=t["amber"]),
            annotation_position="right", row=1, col=1,
        )
        if pred.signal != "HOLD":
            fig.add_hline(
                y=pred.predicted_price, line_color=sig_col, line_width=1.5,
                line_dash="dash",
                annotation_text=f"  ML Target  ${pred.predicted_price:,.2f}",
                annotation_font=dict(size=9, color=sig_col),
                annotation_position="right", row=1, col=1,
            )

    # ── Rolling directional accuracy (bottom panel) ───────────────────────────
    correct     = (np.sign(oos_act) == np.sign(oos_pred)).astype(float)
    window      = min(20, max(5, len(correct) // 10))
    rolling_acc = pd.Series(correct).rolling(window, min_periods=3).mean() * 100
    fig.add_trace(go.Scatter(
        x=oos_dates, y=rolling_acc,
        name=f"{window}-bar Dir. Acc",
        line=dict(color=t["blue"], width=2),
        fill="tozeroy",
        fillcolor="rgba(21,85,162,0.12)" if light_mode else "rgba(75,159,255,0.12)",
        hovertemplate="%{y:.1f}% accuracy<extra></extra>",
    ), row=2, col=1)
    fig.add_hline(y=50, line_color=t["red"], line_width=1,
                  line_dash="dot", annotation_text="50% (random)",
                  annotation_font=dict(size=8, color=t["red"]),
                  annotation_position="right", row=2, col=1)

    lay = _plotly_base(t, f"{symbol} · ML Price Signals  ·  OOS test period shaded in blue", height=600)
    lay["xaxis"] = {**lay.get("xaxis", {}),
                    "rangeslider": dict(visible=True, thickness=0.05,
                                       bgcolor=t["surface"], bordercolor=t["border"]),
                    "type": "date",
                    "tickfont": dict(size=9, color=t["text_mute"])}
    lay["xaxis2"] = dict(gridcolor=t["grid"], zeroline=False,
                         tickfont=dict(size=9, color=t["text_mute"]))
    lay["yaxis"]  = {**lay.get("yaxis", {}),
                     "title": dict(text="Price ($)", font=dict(size=9)),
                     "side": "right", "gridcolor": t["grid"], "showgrid": True}
    lay["yaxis2"] = dict(gridcolor=t["grid"], showgrid=True, zeroline=False,
                         tickfont=dict(size=9, color=t["text_mute"]),
                         title=dict(text="Dir. Acc %", font=dict(size=9)),
                         range=[0, 100], side="right")
    lay["margin"]    = dict(l=10, r=120, t=44, b=60)
    lay["hovermode"] = "x unified"
    lay["dragmode"]  = "pan"
    lay["legend"] = dict(
        orientation="h", x=0.5, y=-0.08,
        xanchor="center", yanchor="top",
        bgcolor="rgba(0,0,0,0)", borderwidth=0,
        font=dict(size=9, color=t["text_sec"]),
    )
    fig.update_layout(**lay)
    return fig


# ─────────────────────────────────────────────────────────────────────────────
#  CHART 2: Feature importance
# ─────────────────────────────────────────────────────────────────────────────
def _chart_feature_importance(result, t: dict) -> go.Figure:
    imp = result.feature_importance
    if not imp:
        fig = go.Figure()
        fig.update_layout(**_plotly_base(t, "Feature Importance"))
        return fig

    sorted_imp = sorted(imp.items(), key=lambda x: x[1], reverse=True)[:15]
    labels = [_fmt_feat(k) for k, _ in sorted_imp]
    values = [v for _, v in sorted_imp]

    # Colour by category
    cat_colors = {
        "momentum": t["amber"], "reversal": t["amber"],
        "oscillator": t["purple"], "reversion": t["purple"],
        "volatility": t["red"],
        "trend": t["blue"],
        "volume": t["green"],
        "breakout": t["text_sec"],
    }
    colors = []
    for k, _ in sorted_imp:
        if any(x in k for x in ("ret_", "accel")):
            colors.append(t["amber"])
        elif any(x in k for x in ("rsi", "bb", "stoch")):
            colors.append(t["purple"])
        elif any(x in k for x in ("atr", "vol", "realvol")):
            colors.append(t["red"])
        elif any(x in k for x in ("ema", "macd")):
            colors.append(t["blue"])
        else:
            colors.append(t["green"])

    fig = go.Figure(go.Bar(
        x=values, y=labels, orientation="h",
        marker=dict(color=colors, opacity=0.85),
        hovertemplate="%{y}: %{x:.4f}<extra></extra>",
    ))
    lay = _plotly_base(t, "Feature Importance (Top 15)", height=400)
    lay["yaxis"] = {**lay.get("yaxis", {}), "autorange": "reversed"}
    lay["xaxis"] = {**lay.get("xaxis", {}), "title": dict(text="Importance", font=dict(size=9))}
    fig.update_layout(**lay)
    return fig


# ─────────────────────────────────────────────────────────────────────────────
#  CHART 2b: Actual vs ML-Predicted PRICE (line chart)
# ─────────────────────────────────────────────────────────────────────────────
def _chart_price_prediction_line(result, df: pd.DataFrame, t: dict) -> go.Figure:
    """
    Line chart comparing actual closing prices vs ML-predicted prices over the
    OOS period. For each bar, the predicted price = close[i-h] * (1 + pred[i-h]),
    i.e. what the model forecast the price would be h bars later.
    """
    if not result.oos_dates or len(result.oos_dates) < 5:
        fig = go.Figure()
        fig.update_layout(**_plotly_base(t, "Actual vs ML-Predicted Price"))
        return fig

    oos_dates = pd.to_datetime(result.oos_dates)
    oos_pred  = np.array(result.oos_predicted)
    horizon   = result.horizon

    df_full = df.dropna(subset=["Close"])
    df_oos  = df_full.reindex(oos_dates, method="nearest", tolerance="1D").dropna(subset=["Close"])

    if len(df_oos) < 5:
        fig = go.Figure()
        fig.update_layout(**_plotly_base(t, "Actual vs ML-Predicted Price"))
        return fig

    closes    = df_oos["Close"].values
    dates_use = df_oos.index

    # Reconstruct predicted price: at each bar i the prediction was made at
    # bar (i - horizon), so predicted_price[i] = close[i-h] * (1 + pred[i-h])
    predicted_prices = np.full(len(closes), np.nan)
    n_pred = len(oos_pred)
    for i in range(horizon, len(closes)):
        ref = i - horizon
        if ref < n_pred:
            predicted_prices[i] = closes[ref] * (1 + oos_pred[ref])

    # Error band (predicted - actual)
    error = predicted_prices - closes

    fig = make_subplots(
        rows=2, cols=1, shared_xaxes=True,
        row_heights=[0.70, 0.30], vertical_spacing=0.04,
    )

    # Actual price
    fig.add_trace(go.Scatter(
        x=dates_use, y=closes,
        name="Actual Price", mode="lines",
        line=dict(color=t["blue"], width=2),
        hovertemplate="Actual: $%{y:,.4f}<extra></extra>",
    ), row=1, col=1)

    # ML predicted price
    fig.add_trace(go.Scatter(
        x=dates_use, y=predicted_prices,
        name=f"ML Predicted (H={horizon})", mode="lines",
        line=dict(color=t["amber"], width=1.5, dash="dot"),
        hovertemplate="ML Pred: $%{y:,.4f}<extra></extra>",
    ), row=1, col=1)

    # Prediction error bar chart (bottom panel)
    pos_err = np.where(error >= 0, error, 0)
    neg_err = np.where(error <  0, error, 0)
    fig.add_trace(go.Bar(
        x=dates_use, y=pos_err,
        name="Pred > Actual", marker_color=t["green"], opacity=0.7, showlegend=False,
        hovertemplate="Error: +$%{y:,.4f}<extra></extra>",
    ), row=2, col=1)
    fig.add_trace(go.Bar(
        x=dates_use, y=neg_err,
        name="Pred < Actual", marker_color=t["red"], opacity=0.7, showlegend=False,
        hovertemplate="Error: -$%{customdata:,.4f}<extra></extra>",
        customdata=np.abs(neg_err),
    ), row=2, col=1)
    fig.add_hline(y=0, line_color=t["border"], line_width=0.8, row=2, col=1)

    # ── Future predictions (next 20 bars) ────────────────────────────────────
    _n_future = 20
    try:
        from ml.features import build_features, rank_standardise
        _feat_full = build_features(df_full)
        if len(_feat_full) >= 2:
            _last_close = float(df_full["Close"].iloc[-1])
            _last_date  = df_full.index[-1]
            # Infer bar frequency for future timestamps
            try:
                _freq = pd.infer_freq(df_full.index[-20:]) or "B"
            except Exception:
                _freq = "B"
            _future_dates  = pd.date_range(start=_last_date, periods=_n_future + 1, freq=_freq)[1:]
            _future_prices = []
            _current_proj  = _last_close
            for _fi in range(_n_future):
                try:
                    _X = _feat_full.iloc[[-1]].copy()
                    for _col in _X.columns:
                        _X[_col] = rank_standardise(_feat_full[_col]).iloc[-1]
                    _X_arr = _X.values.astype(np.float32)
                    _raw = float(result.model.predict(_X_arr)[0])
                    if result.model_type == "ensemble" and result.oos_actual:
                        _oos_std = float(np.std(result.oos_actual)) or 0.01
                        _ret = _raw * _oos_std * 2
                    else:
                        _ret = _raw
                    _current_proj = _current_proj * (1 + _ret)
                    _future_prices.append(_current_proj)
                except Exception:
                    _future_prices.append(np.nan)

            _valid_fut = [(d, p) for d, p in zip(_future_dates, _future_prices) if not np.isnan(p)]
            if _valid_fut:
                _fd, _fp = zip(*_valid_fut)
                # Connector from last actual to first forecast
                fig.add_trace(go.Scatter(
                    x=[dates_use[-1], _fd[0]], y=[closes[-1], _fp[0]],
                    mode="lines", line=dict(color=t["amber"], width=1, dash="dot"),
                    showlegend=False, hoverinfo="skip",
                ), row=1, col=1)
                fig.add_trace(go.Scatter(
                    x=list(_fd), y=list(_fp),
                    name=f"Forecast +{_n_future} bars", mode="lines+markers",
                    line=dict(color=t["amber"], width=2, dash="dash"),
                    marker=dict(size=5, color=t["amber"]),
                    hovertemplate="Forecast: $%{y:,.4f}<extra></extra>",
                ), row=1, col=1)
                # Shaded uncertainty band (±1% of forecast)
                _fp_arr = np.array(_fp)
                fig.add_trace(go.Scatter(
                    x=list(_fd) + list(reversed(list(_fd))),
                    y=list(_fp_arr * 1.01) + list(reversed(list(_fp_arr * 0.99))),
                    fill="toself",
                    fillcolor="rgba(255,184,0,0.08)" if not False else "rgba(150,98,10,0.08)",
                    line_color="rgba(0,0,0,0)",
                    showlegend=False, hoverinfo="skip",
                ), row=1, col=1)
    except Exception:
        pass

    lay = _plotly_base(t, f"Actual vs ML-Predicted Price  ·  OOS period  ·  +{_n_future}-bar forecast", height=500)
    lay["xaxis"] = {**lay.get("xaxis", {}),
                    "rangeslider": dict(visible=True, thickness=0.05,
                                       bgcolor=t["surface"], bordercolor=t["border"]),
                    "type": "date",
                    "tickfont": dict(size=9, color=t["text_mute"])}
    lay["xaxis2"] = dict(gridcolor=t["grid"], zeroline=False,
                         tickfont=dict(size=9, color=t["text_mute"]))
    lay["yaxis"]  = {**lay.get("yaxis", {}),
                     "title": dict(text="Price ($)", font=dict(size=9)),
                     "side": "right", "gridcolor": t["grid"]}
    lay["yaxis2"] = dict(gridcolor=t["grid"], showgrid=True, zeroline=True,
                         zerolinecolor=t["border"],
                         tickfont=dict(size=9, color=t["text_mute"]),
                         title=dict(text="Error ($)", font=dict(size=9)),
                         side="right")
    lay["legend"]  = dict(
        orientation="h", x=0.5, y=-0.08,
        xanchor="center", yanchor="top",
        bgcolor="rgba(0,0,0,0)", borderwidth=0,
        font=dict(size=9, color=t["text_sec"]),
    )
    lay["margin"]   = dict(l=10, r=120, t=44, b=60)
    lay["barmode"]  = "overlay"
    lay["hovermode"] = "x unified"
    lay["dragmode"]  = "pan"
    fig.update_layout(**lay)
    return fig


# ─────────────────────────────────────────────────────────────────────────────
#  CHART 3: Actual vs Predicted scatter
# ─────────────────────────────────────────────────────────────────────────────
def _chart_actual_vs_predicted(result, t: dict) -> go.Figure:
    """
    Scatter: predicted return (x) vs actual return (y).
    Green = model predicted correct direction. Red = wrong direction.
    The tighter the cloud around the diagonal, the better the model.
    """
    if not result.oos_actual:
        fig = go.Figure()
        fig.update_layout(**_plotly_base(t, "Predicted vs Actual Return"))
        return fig

    actual    = np.array(result.oos_actual)    * 100
    predicted = np.array(result.oos_predicted) * 100

    # Winsorise to 98th percentile for clean display (outliers distort the chart)
    p98_act  = np.percentile(np.abs(actual),    98)
    p98_pred = np.percentile(np.abs(predicted), 98)
    act_disp  = np.clip(actual,    -p98_act  * 1.5, p98_act  * 1.5)
    pred_disp = np.clip(predicted, -p98_pred * 1.5, p98_pred * 1.5)

    correct = (np.sign(actual) == np.sign(predicted))
    n_correct = int(correct.sum())
    n_total   = len(correct)
    dir_acc   = result.directional_acc * 100

    # Build two separate traces for legend clarity
    mask_ok  = correct
    mask_err = ~correct

    mx = max(np.abs(act_disp).max(), np.abs(pred_disp).max(), 0.01) * 1.15

    fig = go.Figure()

    # Perfect prediction diagonal
    fig.add_trace(go.Scatter(
        x=[-mx, mx], y=[-mx, mx],
        mode="lines", name="Perfect prediction",
        line=dict(color=t["border"], dash="dash", width=1.5),
        showlegend=False,
    ))
    # Zero-axes
    fig.add_hline(y=0, line_color=t["border"], line_width=0.8, line_dash="dot")
    fig.add_vline(x=0, line_color=t["border"], line_width=0.8, line_dash="dot")

    # Correct direction (green)
    if mask_ok.any():
        fig.add_trace(go.Scatter(
            x=pred_disp[mask_ok], y=act_disp[mask_ok],
            mode="markers", name=f"Correct dir. ({n_correct})",
            marker=dict(color=t["green"], size=5, opacity=0.55,
                        line=dict(color=t["bg"], width=0.5)),
            hovertemplate="Pred: %{x:.3f}%<br>Act: %{y:.3f}%<extra>✓ Correct</extra>",
        ))

    # Wrong direction (red)
    if mask_err.any():
        n_err = int(mask_err.sum())
        fig.add_trace(go.Scatter(
            x=pred_disp[mask_err], y=act_disp[mask_err],
            mode="markers", name=f"Wrong dir. ({n_err})",
            marker=dict(color=t["red"], size=5, opacity=0.45,
                        line=dict(color=t["bg"], width=0.5)),
            hovertemplate="Pred: %{x:.3f}%<br>Act: %{y:.3f}%<extra>✗ Wrong</extra>",
        ))

    lay = _plotly_base(t, "Predicted vs Actual Return  (OOS test period)", height=380)
    lay["xaxis"] = {**lay.get("xaxis", {}),
                    "title": dict(text="Predicted Return %", font=dict(size=9)),
                    "range": [-mx, mx], "zeroline": True, "zerolinecolor": t["border"]}
    lay["yaxis"] = {**lay.get("yaxis", {}),
                    "title": dict(text="Actual Return %", font=dict(size=9)),
                    "range": [-mx, mx], "zeroline": True, "zerolinecolor": t["border"]}
    lay["legend"] = dict(orientation="h", yanchor="bottom", y=1.02, x=0,
                         bgcolor="rgba(0,0,0,0)", font=dict(size=9, color=t["text_sec"]))
    lay["hovermode"] = "closest"
    lay["margin"] = dict(l=60, r=20, t=50, b=50)
    fig.update_layout(**lay)

    # Directional accuracy badge
    badge_col = t["green"] if dir_acc > 52 else (t["amber"] if dir_acc > 48 else t["red"])
    fig.add_annotation(
        text=f"Dir. Acc: {dir_acc:.1f}%  ({n_correct}/{n_total})",
        xref="paper", yref="paper", x=0.98, y=0.02,
        xanchor="right", yanchor="bottom",
        showarrow=False, font=dict(size=11, color=badge_col, family="IBM Plex Mono"),
        bgcolor=t["card"], bordercolor=badge_col, borderpad=4,
    )
    return fig


# ─────────────────────────────────────────────────────────────────────────────
#  CHART 4: CV fold R² breakdown
# ─────────────────────────────────────────────────────────────────────────────
def _chart_cv_folds(result, t: dict) -> go.Figure:
    folds = result.cv_folds
    if not folds:
        fig = go.Figure()
        fig.update_layout(**_plotly_base(t, "CV Results"))
        return fig

    fold_labels = [f"Fold {f.fold}" for f in folds]
    r2_vals     = [max(f.r2_oos * 100, -200.0) for f in folds]  # cap at -200%
    colors      = [t["green"] if r > 0 else t["red"] for r in r2_vals]
    train_n     = [f.train_size for f in folds]

    fig = make_subplots(rows=1, cols=2,
                        subplot_titles=["OOS R² per Fold (capped -200%)", "Training Size"],
                        column_widths=[0.55, 0.45])

    fig.add_trace(go.Bar(
        x=fold_labels, y=r2_vals,
        marker_color=colors, opacity=0.85, name="R²",
        hovertemplate="%{x}: %{y:.2f}%<extra></extra>",
    ), row=1, col=1)

    fig.add_trace(go.Bar(
        x=fold_labels, y=train_n,
        marker_color=t["blue"], opacity=0.7, name="Bars",
        hovertemplate="%{x}: %{y} bars<extra></extra>",
    ), row=1, col=2)

    lay = _plotly_base(t, "Expanding-Window CV Results", height=400)
    lay["yaxis"]  = {**lay.get("yaxis", {}),
                     "title": dict(text="R² %", font=dict(size=9)),
                     "zeroline": True, "zerolinecolor": t["border"]}
    lay["yaxis2"] = dict(gridcolor=t["grid"], showgrid=True, zeroline=False,
                         tickfont=dict(size=9, color=t["text_mute"]),
                         title=dict(text="# bars", font=dict(size=9)))
    lay["showlegend"] = False
    fig.update_layout(**lay)
    return fig


# ─────────────────────────────────────────────────────────────────────────────
#  MULTI-HORIZON (cached only)
# ─────────────────────────────────────────────────────────────────────────────
def _render_multi_horizon(result, df: pd.DataFrame, interval: str, t: dict):
    from ml.predictor import predict as ml_predict, _horizon_label

    horizons = [1, 5, 20]
    cols = st.columns(len(horizons))

    for ci, h in enumerate(horizons):
        try:
            # Primary cache key (used when this horizon was the selected one)
            primary_key = f"ml_result_{result.symbol}_{result.model_type}_{h}"
            # Secondary key (used when trained alongside another primary horizon)
            secondary_key = f"ml_mh_{result.symbol}_{result.model_type}_{h}"

            r_h = (
                st.session_state.get(primary_key)
                or st.session_state.get(secondary_key)
                or (result if h == result.horizon else None)
            )

            if r_h is None:
                cols[ci].markdown(
                    f'<div style="background:{t["card"]};border:1px solid {t["border"]};'
                    f'border-radius:6px;padding:12px;text-align:center">'
                    f'<div style="font-size:9px;color:{t["text_mute"]};letter-spacing:.15em">'
                    f'{h} BAR{"S" if h>1 else ""}</div>'
                    f'<div style="font-size:12px;color:{t["text_mute"]};margin-top:8px">'
                    f'Click ▶ TRAIN to unlock</div>'
                    f'</div>',
                    unsafe_allow_html=True,
                )
                continue

            p_h = ml_predict(r_h, df, interval)
            if p_h is None:
                continue

            ret_pct = p_h.predicted_return * 100
            sig     = p_h.signal
            sig_col = {"BUY": t["green"], "SELL": t["red"]}.get(sig, t["amber"])
            hl      = _horizon_label(h, interval)

            cols[ci].markdown(f"""
<div style="background:{t['card']};
     border:1px solid {sig_col if sig != 'HOLD' else t['border']};
     border-radius:6px;padding:12px 14px;text-align:center">
  <div style="font-size:9px;color:{t['text_mute']};letter-spacing:.15em;text-transform:uppercase;margin-bottom:4px">
    {hl}
  </div>
  <div style="font-size:22px;font-weight:700;color:{sig_col}">{sig}</div>
  <div style="font-size:13px;font-weight:600;color:{t['text']};margin-top:2px">{ret_pct:+.3f}%</div>
  <div style="font-size:11px;color:{t['text_sec']};margin-top:4px">Target: ${p_h.predicted_price:,.4f}</div>
  <div style="font-size:10px;color:{t['text_mute']};margin-top:2px">Conf: {p_h.confidence:.0f}%</div>
</div>""", unsafe_allow_html=True)

        except Exception:
            cols[ci].caption(f"H={h}: error")


# ── Helpers ────────────────────────────────────────────────────────────────────
def _fmt_feat(key: str) -> str:
    return {
        "f_ret_1": "Return 1-bar", "f_ret_5": "Return 5-bar",
        "f_ret_20": "Momentum 1mo", "f_ret_60": "Momentum 3mo",
        "f_ret_120": "Momentum 6mo", "f_ema_cross": "EMA Cross",
        "f_vs_ema_f": "Price vs EMA Fast", "f_vs_ema_s": "Price vs EMA Slow",
        "f_macd_norm": "MACD (norm)", "f_macd_hist": "MACD Histogram",
        "f_rsi_norm": "RSI (norm)", "f_bb_pct": "Bollinger %B",
        "f_stoch": "Stochastic %K", "f_close_vs_high": "Close vs High20",
        "f_close_vs_low": "Close vs Low20", "f_atr_norm": "ATR / Price",
        "f_realvol": "Realised Vol", "f_vol_accel": "Vol Acceleration",
        "f_vol_ratio": "Volume Ratio", "f_obv_mom": "OBV Momentum",
        "f_breakout_u": "Breakout Up", "f_breakout_d": "Breakout Down",
        "f_range_pos": "Range Position", "f_price_accel": "Price Acceleration",
    }.get(key, key.replace("f_", "").replace("_", " ").title())


# ─────────────────────────────────────────────────────────────────────────────
#  INTRADAY (5-MIN) PREDICTION ENGINE  — complete rewrite
# ─────────────────────────────────────────────────────────────────────────────

def _build_hf_features(df: pd.DataFrame) -> pd.DataFrame:
    """Build high-frequency (5-min optimised) predictive features from OHLCV bars."""
    features = pd.DataFrame(index=df.index)
    closes = df["close"] if "close" in df.columns else df["Close"]
    opens  = df["open"]  if "open"  in df.columns else df["Open"]
    highs  = df["high"]  if "high"  in df.columns else df["High"]
    lows   = df["low"]   if "low"   in df.columns else df["Low"]
    volumes = df["volume"] if "volume" in df.columns else df.get("Volume", pd.Series(1, index=df.index))

    for n in [1, 3, 6, 12, 24, 48]:
        features[f"ret_{n}"] = closes.pct_change(n)

    features["reversal_1"] = -features["ret_1"]
    returns = closes.pct_change()
    for n in [6, 12, 36, 78]:
        features[f"realvol_{n}"] = returns.rolling(n).std() * np.sqrt(n)

    avg_vol = volumes.rolling(78).mean().replace(0, np.nan)
    features["vol_ratio"]  = volumes / avg_vol
    features["vol_trend"]  = volumes.rolling(6).mean() / volumes.rolling(24).mean().replace(0, np.nan)
    features["bar_range"]  = (highs - lows) / closes.replace(0, np.nan)
    features["close_pos"]  = (closes - lows) / (highs - lows + 1e-8)

    for n in [12, 36, 78]:
        rh = highs.rolling(n).max()
        rl = lows.rolling(n).min()
        features[f"range_pos_{n}"] = (closes - rl) / (rh - rl + 1e-8)

    for n in [6, 12, 24, 78]:
        ma = closes.rolling(n).mean()
        features[f"vs_ma_{n}"] = (closes - ma) / ma.replace(0, np.nan)

    features["near_bottom"] = 1 - features.get("range_pos_78", 0)

    # Time-of-day (cycle encoding so model treats 09:30 and 09:35 as close)
    hours   = df.index.hour + df.index.minute / 60
    features["time_sin"] = np.sin(2 * np.pi * hours / 24)
    features["time_cos"] = np.cos(2 * np.pi * hours / 24)

    return features.replace([np.inf, -np.inf], np.nan).dropna()


def _render_5min_section(df: pd.DataFrame, symbol: str, interval: str, t: dict, light_mode: bool):
    """
    Intraday (5-min / 15-min / 30-min) ML Prediction Engine.

    Works with any intraday-loaded DataFrame.  Trains a Random Forest on HF
    features, then shows:
      1. Training / OOS quality metrics
      2. Live trade recommendation card with entry / SL / TP
      3. Predicted-price chart: last 100 bars actual + next N bars forecast
      4. OOS backtest equity curve (after transaction costs)
      5. Feature importance bar chart
    """
    sess = st.session_state

    st.markdown(
        '<div class="qt-section">⚡ INTRADAY PREDICTION ENGINE — 5/15/30-MIN</div>',
        unsafe_allow_html=True,
    )

    # ── Guard: only useful with intraday data ─────────────────────────────────
    _is_intraday = interval in ("1m", "5m", "15m", "30m", "1h")
    if not _is_intraday:
        st.info(
            "ℹ️ **Intraday Prediction requires intraday data.** "
            "Switch interval to **5m**, **15m**, or **30m** and click **⟳ LOAD** first, "
            "then return here to train the intraday model.",
            icon="📊",
        )
        return

    if df is None or len(df) < 80:
        st.warning(
            "⚠️ Need at least **80 intraday bars**. "
            "Set period to **30d** on a **5m** or **15m** interval and reload."
        )
        return

    n_bars = len(df)

    # ── Cost model ────────────────────────────────────────────────────────────
    # Separate costs for crypto vs equities/FX
    _sym_upper = symbol.upper()
    _is_crypto = any(x in _sym_upper for x in ("BTC","ETH","SOL","XRP","BNB","USDT","ADA","XAU"))
    _spread_bps     = 1.5 if _is_crypto else 2.5
    _commission_bps = 0.5 if _is_crypto else 1.0
    _total_cost_pct = (_spread_bps + _commission_bps) / 10000
    _hurdle_pct     = _total_cost_pct * 2.5 * 100   # 2.5× safety buffer

    # Bars per trading day for this interval
    _min_per_bar   = int(interval.replace("m", "").replace("h", "60")) if interval[-1] in "mh" else 60
    _bars_per_day  = max(1, int(390 / _min_per_bar))   # ~390 min US session

    # ── Session cache ─────────────────────────────────────────────────────────
    _5m_cache_key = f"ml5m_{symbol}_{interval}"
    _5m_result    = sess.get(_5m_cache_key)
    if _5m_result is None:
        _5m_result = _load_model(symbol, f"hf_{interval}", 1)
        if _5m_result is not None:
            sess[_5m_cache_key] = _5m_result

    # ── Config form (no per-widget rerun) ─────────────────────────────────────
    _h_opts    = [1, 2, 3, 6, 12]
    _h_default = sess.get(f"_ml5m_h_{symbol}", 1)
    _h_default = _h_default if _h_default in _h_opts else 1

    with st.form(f"ml5m_form_{symbol}", clear_on_submit=False):
        _fa, _fb, _fc = st.columns([2.5, 2.5, 1])
        _h5 = _fa.selectbox(
            "Predict ahead (bars)",
            _h_opts,
            index=_h_opts.index(_h_default),
            format_func=lambda x: f"{x} bar{'s' if x>1 else ''} ≈ {x * _min_per_bar} min",
        )
        _n_fut = _fb.selectbox(
            "Forecast bars (chart)",
            [10, 20, 30],
            index=1,
            format_func=lambda x: f"Next {x} bars",
        )
        _train5 = _fc.form_submit_button("⚡ TRAIN", type="primary", use_container_width=True)

    if _train5:
        sess[f"_ml5m_h_{symbol}"] = _h5
        _prog5 = st.progress(0, "Building features …")
        try:
            from sklearn.ensemble import GradientBoostingRegressor
            from sklearn.preprocessing import RobustScaler

            _feat5 = _build_hf_features(df)
            if len(_feat5) < 60:
                st.error("Not enough clean feature rows — load more intraday data.")
                _prog5.empty(); return

            _closes5 = (df["Close"] if "Close" in df.columns else df["close"]).reindex(_feat5.index)
            _y5 = _closes5.pct_change(_h5).shift(-_h5).reindex(_feat5.index).dropna()
            _X5 = _feat5.reindex(_y5.index)

            _n5    = len(_y5)
            _split = int(_n5 * 0.75)
            if _split < 30:
                st.error("Need more bars — split produces < 30 training samples."); _prog5.empty(); return

            _X_tr5 = _X5.iloc[:_split].values.astype(np.float32)
            _y_tr5 = _y5.values[:_split].astype(np.float32)
            _X_te5 = _X5.iloc[_split:].values.astype(np.float32)
            _y_te5 = _y5.values[_split:].astype(np.float32)

            _prog5.progress(0.20, "Scaling features …")
            _sc5 = RobustScaler()
            _X_tr5s = _sc5.fit_transform(_X_tr5)
            _X_te5s = _sc5.transform(_X_te5)

            _prog5.progress(0.40, "Training GradientBoosting …")
            # Gradient Boosting: better calibrated probabilities than RF for small datasets
            _mdl5 = GradientBoostingRegressor(
                n_estimators=120, max_depth=3, learning_rate=0.05,
                subsample=0.8, random_state=42,
            )
            _mdl5.fit(_X_tr5s, _y_tr5)

            _prog5.progress(0.75, "Evaluating OOS …")
            _yp5     = _mdl5.predict(_X_te5s).astype(np.float32)
            _dir_acc = float((np.sign(_y_te5) == np.sign(_yp5)).mean())

            # Net P&L per trade (long when pred>0, short when pred<0), minus costs
            _pnl5    = np.where(_yp5 > _total_cost_pct, _y_te5,
                       np.where(_yp5 < -_total_cost_pct, -_y_te5, 0.0)) - _total_cost_pct
            _sharpe5 = float(_pnl5.mean() / (_pnl5.std() + 1e-9) * np.sqrt(_bars_per_day * 252))

            # OOS actual close prices (for the price chart)
            _oos_close_prices = _closes5.iloc[_split:].reindex(_y5.index[_split:]).values.tolist()

            _5m_result = {
                "model":       _mdl5,
                "scaler":      _sc5,
                "features":    _feat5.columns.tolist(),
                "horizon":     _h5,
                "interval":    interval,
                "dir_acc":     _dir_acc,
                "sharpe":      _sharpe5,
                "oos_pred":    _yp5.tolist(),
                "oos_act":     _y_te5.tolist(),
                "oos_dates":   _y5.index[_split:].tolist(),
                "oos_closes":  _oos_close_prices,
                "train_dates": _y5.index[:_split].tolist(),
                "feat_imp":    dict(zip(_feat5.columns, _mdl5.feature_importances_)),
                "symbol":      symbol,
                "n_bars":      _n5,
                "cost_pct":    _total_cost_pct,
                "hurdle_pct":  _hurdle_pct / 100,
            }
            sess[_5m_cache_key] = _5m_result
            _save_model(_5m_result, symbol, f"hf_{interval}", _h5)

            _prog5.progress(1.0, "Done ✓"); _prog5.empty()
            st.toast(
                f"⚡ Intraday model trained — "
                f"Dir Acc: {_dir_acc*100:.1f}% · Sharpe: {_sharpe5:.2f}",
                icon="⚡",
            )
        except Exception as _e5:
            _prog5.empty()
            st.error(f"Training failed: {_e5}")
            import traceback; st.code(traceback.format_exc(), language="python")
            return

    if _5m_result is None:
        st.info(
            f"No intraday model for **{symbol} ({interval})** yet. "
            "Click **⚡ TRAIN** above to build one."
        )
        return

    # ─────────────────────────────────────────────────────────────────────────
    #  LIVE PREDICTION + RECOMMENDATION CARD
    # ─────────────────────────────────────────────────────────────────────────
    _close_last = float((df["Close"] if "Close" in df.columns else df["close"]).iloc[-1])
    _atr_last   = float(df["atr"].iloc[-1]) if "atr" in df.columns else _close_last * 0.005

    _pred_ret    = None
    _feat_live   = None
    try:
        _feat_live = _build_hf_features(df)
        if len(_feat_live) > 0:
            _feats_needed = _5m_result["features"]
            _feat_row = _feat_live.iloc[[-1]][_feats_needed].values.astype(np.float32)
            _feat_row = _5m_result["scaler"].transform(_feat_row)
            _pred_ret = float(_5m_result["model"].predict(_feat_row)[0])
    except Exception:
        pass

    if _pred_ret is not None:
        _horizon   = _5m_result.get("horizon", 1)
        _cost_pct  = _5m_result.get("cost_pct", _total_cost_pct)
        _hurdle    = _5m_result.get("hurdle_pct", _hurdle_pct / 100)
        _pred_px   = _close_last * (1 + _pred_ret)
        _clears    = abs(_pred_ret) > _hurdle

        if _pred_ret > _hurdle:
            _sig5, _sig_icon5 = "BUY",  "▲"
            _sl5 = _close_last - _atr_last * 1.5
            _tp5 = _close_last + _atr_last * 2.5
        elif _pred_ret < -_hurdle:
            _sig5, _sig_icon5 = "SELL", "▼"
            _sl5 = _close_last + _atr_last * 1.5
            _tp5 = _close_last - _atr_last * 2.5
        else:
            _sig5, _sig_icon5 = "HOLD", "◼"
            _sl5 = _close_last - _atr_last * 1.5
            _tp5 = _close_last + _atr_last * 1.5

        _rr5      = abs(_tp5 - _close_last) / max(abs(_sl5 - _close_last), 1e-9)
        _sig_col5 = {"BUY": t["green"], "SELL": t["red"]}.get(_sig5, t["amber"])
        _bg_cls5  = {"BUY": "qt-signal-buy", "SELL": "qt-signal-sell"}.get(_sig5, "qt-signal-hold")
        _dir_acc5 = _5m_result.get("dir_acc", 0.5)
        _conf5    = min(95, max(30, _dir_acc5 * 100 + (20 if _clears else -10)))
        _conf_col = t["green"] if _conf5 >= 60 else (t["amber"] if _conf5 >= 45 else t["red"])
        _h_lbl    = f"{_horizon} bar{'s' if _horizon>1 else ''} ≈ {_horizon * _min_per_bar} min"

        st.markdown(f"""
<div class="qt-signal {_bg_cls5}" style="margin-bottom:12px">
  <div class="qt-signal-label" style="color:{_sig_col5}">
    <span class="qt-pulse" style="background:{_sig_col5}"></span>
    {_sig_icon5} {_sig5} &nbsp;
    <span style="font-size:20px;color:{_sig_col5}">{_pred_ret*100:+.3f}%</span>
    <span style="font-size:11px;color:{t['text_sec']};font-weight:400">
      &nbsp;· next {_h_lbl}
    </span>
  </div>
  <div style="margin-top:10px;display:flex;gap:16px;flex-wrap:wrap;
       font-family:IBM Plex Mono;font-size:11px;color:{t['text_sec']}">
    <span>NOW <b style="color:{t['text']}">${_close_last:,.4f}</b></span>
    <span>TARGET <b style="color:{_sig_col5}">${_pred_px:,.4f}</b></span>
    <span>SL <b style="color:{t['red']}">${_sl5:,.4f}</b></span>
    <span>TP <b style="color:{t['green']}">${_tp5:,.4f}</b></span>
    <span>R/R <b style="color:{t['blue']}">{_rr5:.1f}×</b></span>
    <span>CONF <b style="color:{_conf_col}">{_conf5:.0f}%</b></span>
    <span>DIR ACC <b style="color:{t['text']}">{_dir_acc5*100:.1f}%</b></span>
  </div>
  <div style="margin-top:8px;font-family:IBM Plex Mono;font-size:10px;
       color:{_sig_col5 if _clears else t['text_mute']}">
    {"✓ Signal clears cost hurdle (" + f"{abs(_pred_ret)*100:.3f}% > {_hurdle*100:.3f}%)" if _clears
      else "⚠ Signal below cost hurdle — HOLD / no trade recommended"}
  </div>
</div>
""", unsafe_allow_html=True)

        # Quick metrics strip
        _qa, _qb, _qc, _qd = st.columns(4)
        _qa.metric("Signal",        _sig5,               f"{_pred_ret*100:+.3f}%")
        _qb.metric("Dir. Accuracy", f"{_dir_acc5*100:.1f}%", "OOS backtest")
        _qc.metric("Est. Sharpe",   f"{_5m_result.get('sharpe',0):.2f}", "after costs")
        _qd.metric("Bars Trained",  f"{_5m_result.get('n_bars',0)}")

    # ─────────────────────────────────────────────────────────────────────────
    #  PREDICTED PRICE CHART — last N actual bars + forecast
    # ─────────────────────────────────────────────────────────────────────────
    if PLOTLY_OK:
        try:
            from plotly.subplots import make_subplots as _msp

            _closes_col = "Close" if "Close" in df.columns else "close"
            _cl_series  = df[_closes_col]
            _n_hist     = min(120, len(_cl_series))
            _hist_df    = df.iloc[-_n_hist:]
            _hist_dates = _hist_df.index
            _hist_cl    = _hist_df[_closes_col].values

            # ── Generate step-ahead predictions for the historical window ──
            _step_preds = np.full(len(_hist_cl), np.nan)
            if _feat_live is not None:
                _feat_hist = _feat_live.reindex(_hist_dates, method="nearest").dropna()
                if len(_feat_hist) > 0:
                    try:
                        _fh_rows = _feat_hist[_5m_result["features"]].values.astype(np.float32)
                        _fh_rows = _5m_result["scaler"].transform(_fh_rows)
                        _fh_preds = _5m_result["model"].predict(_fh_rows)
                        _horizon5 = _5m_result.get("horizon", 1)
                        for _ii, _idx in enumerate(_hist_dates):
                            _pos = list(_hist_dates).index(_idx) if _idx in _hist_dates else -1
                            if _pos >= _horizon5:
                                _ref = _pos - _horizon5
                                if _ref < len(_fh_preds) and _ref < len(_hist_cl):
                                    _step_preds[_pos] = _hist_cl[_ref] * (1 + _fh_preds[_ref])
                    except Exception:
                        pass

            # ── Forecast: next _n_fut bars ──────────────────────────────────
            try:
                _freq5 = pd.infer_freq(_hist_dates[-20:]) or "5min"
            except Exception:
                _freq5 = "5min"
            _fut_dates = pd.date_range(start=_hist_dates[-1], periods=_n_fut + 1, freq=_freq5)[1:]
            _fut_prices = []
            _proj = float(_hist_cl[-1])
            for _fi in range(_n_fut):
                try:
                    _feat_last = _feat_live.iloc[[-1]][_5m_result["features"]].values.astype(np.float32)
                    _feat_last = _5m_result["scaler"].transform(_feat_last)
                    _fr = float(_5m_result["model"].predict(_feat_last)[0])
                    _proj = _proj * (1 + _fr)
                    _fut_prices.append(_proj)
                except Exception:
                    _fut_prices.append(_proj)  # flat if prediction fails

            # ── Build figure ──────────────────────────────────────────────
            _fig5c = _msp(rows=2, cols=1, shared_xaxes=True,
                          row_heights=[0.72, 0.28], vertical_spacing=0.03)

            # Actual candlestick
            _fig5c.add_trace(go.Candlestick(
                x=_hist_dates,
                open=_hist_df["Open"].values if "Open" in _hist_df.columns else _hist_cl,
                high=_hist_df["High"].values if "High" in _hist_df.columns else _hist_cl,
                low=_hist_df["Low"].values  if "Low"  in _hist_df.columns else _hist_cl,
                close=_hist_cl,
                name="Price",
                increasing_line_color=t["green"], decreasing_line_color=t["red"],
                increasing_fillcolor=f"rgba(0,201,167,0.2)",
                decreasing_fillcolor=f"rgba(255,69,96,0.2)",
                showlegend=True,
            ), row=1, col=1)

            # ML in-sample predicted prices (dotted amber)
            _valid_step = [(d, p) for d, p in zip(_hist_dates, _step_preds) if not np.isnan(p)]
            if _valid_step:
                _vsd, _vsp = zip(*_valid_step)
                _fig5c.add_trace(go.Scatter(
                    x=list(_vsd), y=list(_vsp),
                    name="ML Predicted Price", mode="lines",
                    line=dict(color=t["amber"], width=1.5, dash="dot"),
                    hovertemplate="Predicted: $%{y:,.4f}<extra></extra>",
                ), row=1, col=1)

            # Forecast zone
            if _fut_prices:
                _fp_arr = np.array(_fut_prices)
                # Connector from last actual to first forecast
                _fig5c.add_trace(go.Scatter(
                    x=[_hist_dates[-1], _fut_dates[0]],
                    y=[float(_hist_cl[-1]), _fut_prices[0]],
                    mode="lines",
                    line=dict(color=_sig_col5 if _pred_ret else t["amber"], width=1, dash="dot"),
                    showlegend=False, hoverinfo="skip",
                ), row=1, col=1)
                _fig5c.add_trace(go.Scatter(
                    x=list(_fut_dates), y=list(_fp_arr),
                    name=f"Forecast +{_n_fut} bars",
                    mode="lines+markers",
                    line=dict(color=_sig_col5 if _pred_ret else t["amber"], width=2.5, dash="dash"),
                    marker=dict(size=6, color=_sig_col5 if _pred_ret else t["amber"],
                                symbol="circle-open"),
                    hovertemplate="Forecast: $%{y:,.4f}<extra></extra>",
                ), row=1, col=1)
                # Uncertainty band ±ATR
                _band = _atr_last * 1.5
                _fig5c.add_trace(go.Scatter(
                    x=list(_fut_dates) + list(reversed(list(_fut_dates))),
                    y=list(_fp_arr + _band) + list(reversed(list(_fp_arr - _band))),
                    fill="toself",
                    fillcolor="rgba(255,184,0,0.08)" if not light_mode else "rgba(150,98,10,0.07)",
                    line_color="rgba(0,0,0,0)",
                    name="Uncertainty ±ATR",
                    hoverinfo="skip",
                ), row=1, col=1)
                # Entry / SL / TP lines if active signal
                if _pred_ret is not None and _sig5 != "HOLD":
                    for _px_line, _lc, _lbl in [
                        (_close_last, t["amber"],  f"Entry ${_close_last:,.4f}"),
                        (_sl5,        t["red"],    f"SL ${_sl5:,.4f}"),
                        (_tp5,        t["green"],  f"TP ${_tp5:,.4f}"),
                    ]:
                        _fig5c.add_hline(
                            y=_px_line, line_color=_lc, line_width=1.2,
                            line_dash="dot",
                            annotation_text=f"  {_lbl}",
                            annotation_font=dict(size=9, color=_lc),
                            annotation_position="right",
                            row=1, col=1,
                        )

            # OOS accuracy rolling panel (bottom)
            _oos_pred5 = np.array(_5m_result.get("oos_pred", []))
            _oos_act5  = np.array(_5m_result.get("oos_act",  []))
            _oos_dt5   = pd.to_datetime(_5m_result.get("oos_dates", []))
            if len(_oos_pred5) > 10 and len(_oos_dt5) == len(_oos_pred5):
                _correct5 = (np.sign(_oos_act5) == np.sign(_oos_pred5)).astype(float)
                _win5 = min(20, max(5, len(_correct5) // 8))
                _roll5 = pd.Series(_correct5).rolling(_win5, min_periods=3).mean() * 100
                _fig5c.add_trace(go.Scatter(
                    x=_oos_dt5, y=_roll5,
                    name=f"{_win5}-bar rolling acc",
                    line=dict(color=t["blue"], width=1.5),
                    fill="tozeroy",
                    fillcolor="rgba(75,159,255,0.10)",
                    hovertemplate="%{y:.1f}%<extra></extra>",
                ), row=2, col=1)
                _fig5c.add_hline(y=50, line_color=t["red"], line_width=0.8,
                                 line_dash="dot", row=2, col=1)

            # Layout
            _lay5c = _plotly_base(
                t,
                f"{symbol} · {interval} · Last {_n_hist} bars + {_n_fut}-bar forecast",
                height=560,
            )
            _lay5c["xaxis"]  = {**_lay5c.get("xaxis", {}),
                                 "rangeslider": dict(visible=False),
                                 "type": "date",
                                 "tickfont": dict(size=9, color=t["text_mute"])}
            _lay5c["xaxis2"] = dict(gridcolor=t["grid"], tickfont=dict(size=9, color=t["text_mute"]))
            _lay5c["yaxis"]  = {**_lay5c.get("yaxis", {}),
                                 "title": dict(text="Price ($)", font=dict(size=9)),
                                 "side": "right", "gridcolor": t["grid"]}
            _lay5c["yaxis2"] = dict(
                gridcolor=t["grid"], showgrid=True, zeroline=False,
                tickfont=dict(size=9, color=t["text_mute"]),
                title=dict(text="Dir. Acc %", font=dict(size=9)),
                range=[0, 100], side="right",
            )
            _lay5c["margin"]    = dict(l=10, r=130, t=44, b=50)
            _lay5c["dragmode"]  = "pan"
            _lay5c["hovermode"] = "x unified"
            _lay5c["legend"]    = dict(
                orientation="h", x=0.5, y=-0.06,
                xanchor="center", yanchor="top",
                bgcolor="rgba(0,0,0,0)",
                font=dict(size=9, color=t["text_sec"]),
            )
            _fig5c.update_layout(**_lay5c)

            st.plotly_chart(
                _fig5c, use_container_width=True,
                config=dict(
                    scrollZoom=True, displayModeBar=True,
                    modeBarButtonsToRemove=["lasso2d", "select2d", "autoScale2d",
                                            "toggleSpikelines"],
                    responsive=True,
                ),
            )
        except Exception as _ce:
            st.warning(f"Could not render forecast chart: {_ce}")

    # ─────────────────────────────────────────────────────────────────────────
    #  OOS EQUITY CURVE + FEATURE IMPORTANCE
    # ─────────────────────────────────────────────────────────────────────────
    if PLOTLY_OK:
        _oos_pred5 = np.array(_5m_result.get("oos_pred", []))
        _oos_act5  = np.array(_5m_result.get("oos_act",  []))
        _oos_dt5   = pd.to_datetime(_5m_result.get("oos_dates", []))
        _cost5     = _5m_result.get("cost_pct", _total_cost_pct)
        _hurdle5   = _5m_result.get("hurdle_pct", _hurdle_pct / 100)

        _eq_col, _fi_col = st.columns([1, 1], gap="small")

        # Equity curve
        if len(_oos_pred5) > 5:
            try:
                _pnl5e  = np.where(_oos_pred5 >  _hurdle5, _oos_act5,
                           np.where(_oos_pred5 < -_hurdle5, -_oos_act5, 0.0)) - _cost5
                _cum5   = np.cumprod(1 + _pnl5e) - 1
                _equity = (1 + _cum5) * 100  # start at 100

                _fe = go.Figure()
                _fe.add_trace(go.Scatter(
                    x=_oos_dt5, y=_equity,
                    name="Equity (OOS)", mode="lines",
                    line=dict(color=t["green"] if _equity[-1] >= 100 else t["red"], width=2),
                    fill="tozeroy",
                    fillcolor=f"rgba(0,201,167,0.07)" if _equity[-1] >= 100 else "rgba(255,69,96,0.07)",
                ))
                _fe.add_hline(y=100, line_color=t["border"], line_width=1)
                _le = _plotly_base(t, "OOS Equity (after costs & hurdle)", height=320)
                _le["yaxis"] = {**_le.get("yaxis", {}),
                                "title": dict(text="% of capital", font=dict(size=9)), "side": "right"}
                _fe.update_layout(**_le)
                with _eq_col:
                    st.plotly_chart(_fe, use_container_width=True, config=dict(displayModeBar=False))
            except Exception:
                pass

        # Feature importance
        _fimp = _5m_result.get("feat_imp", {})
        if _fimp:
            try:
                _fi_top = sorted(_fimp.items(), key=lambda x: x[1], reverse=True)[:12]
                _fi_lbl = [k.replace("_", " ").title() for k, _ in _fi_top]
                _fi_val = [v for _, v in _fi_top]
                _fif = go.Figure(go.Bar(
                    x=_fi_val, y=_fi_lbl, orientation="h",
                    marker_color=t["amber"], opacity=0.85,
                    hovertemplate="%{y}: %{x:.4f}<extra></extra>",
                ))
                _lif = _plotly_base(t, "Feature Importance (Top 12)", height=320)
                _lif["yaxis"] = {**_lif.get("yaxis", {}), "autorange": "reversed"}
                _fif.update_layout(**_lif)
                with _fi_col:
                    st.plotly_chart(_fif, use_container_width=True, config=dict(displayModeBar=False))
            except Exception:
                pass

    # ── Reality check footer ──────────────────────────────────────────────────
    _annual_drag5 = _total_cost_pct * _bars_per_day * 252 * 100
    st.markdown(f"""
<div style="font-family:IBM Plex Mono;font-size:9px;color:{t['text_mute']};
  padding:8px 12px;background:{t['surface']};border-radius:4px;
  border-left:3px solid {t['amber']};margin-top:8px;line-height:1.8">
⚠️ <b style="color:{t['amber']}">INTRADAY TRADING COST REALITY:</b> &nbsp;
Cost per round-trip ≈ <b>{_total_cost_pct*100:.3f}%</b> &nbsp;·&nbsp;
Profit hurdle ≈ <b>{_hurdle_pct:.3f}%</b> &nbsp;·&nbsp;
At {_bars_per_day} bars/day the annual cost drag ≈ <b>{_annual_drag5:.0f}%</b> if trading every bar.
Only trade when signal clearly exceeds the cost hurdle.
Best results: liquid instruments (BTC, major FX) with tight spreads.
</div>""", unsafe_allow_html=True)
