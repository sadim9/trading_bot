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
    safe = symbol.replace("/", "_").replace(":", "_")
    return _MODEL_DIR / f"ml_model_{safe}_{model_type}_h{horizon}.pkl"


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
#  5-MINUTE PREDICTION ENGINE
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
    """Render the 5-minute high-frequency prediction section."""
    sess = st.session_state

    st.markdown(
        '<div class="qt-section">⚡ 5-MINUTE HIGH-FREQUENCY PREDICTION ENGINE</div>',
        unsafe_allow_html=True,
    )

    with st.expander("ℹ️ About 5-Minute Prediction", expanded=False):
        st.markdown("""
**Important context for 5-minute ML trading:**

| | Monthly (Paper) | 5-Minute (This section) |
|---|---|---|
| Signal-to-noise | Low but manageable | Extremely low |
| Best model | Feed-forward NN | Short-term momentum + reversal |
| Key signals | Fundamentals + momentum | Price position in range, volume surge |
| Annual cost drag | ~1.2% | **~720%** at 10 trades/day |
| Realistic Sharpe | 0.8–1.2 | 0.3–0.8 (if done well) |

⚠️ **Transaction costs dominate at 5-minute frequency.** Each round-trip trade costs ~0.04%.
At 10 trades/day × 252 days = ~$720 cost per $1,000 traded. Your strategy must generate
extraordinary gross returns just to break even.

💡 **Recommended:** Use this section to identify intraday momentum and range signals,
but only trade when the predicted return **clearly exceeds the cost hurdle** shown below.
""")

    # ── Only useful for intraday data ─────────────────────────────────────────
    _is_intraday = interval in ("1m", "5m", "15m", "30m")
    if not _is_intraday:
        st.info(
            "ℹ️ **5-min section requires intraday data.** "
            "Switch interval to **5m** or **15m** and reload data to use this section. "
            "Daily data is better suited for the main ML engine above.",
            icon="📊",
        )
        return

    if df is None or len(df) < 100:
        st.warning("⚠️ Need at least 100 intraday bars. Load more data (30d period on 5m interval).")
        return

    n_bars = len(df)

    # ── Cost model ───────────────────────────────────────────────────────────
    _spread_bps     = 2.0
    _commission_bps = 0.5
    _impact_bps     = 1.0
    _slippage_bps   = 0.5
    _total_cost_pct = (_spread_bps + _commission_bps + _impact_bps + _slippage_bps) / 10000
    _hurdle_pct     = _total_cost_pct * 2 * 100  # 2× safety buffer

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Cost per Trade",   f"{_total_cost_pct*100:.3f}%",   "round-trip")
    c2.metric("Profit Hurdle",    f"{_hurdle_pct:.3f}%",           "2× cost buffer")
    c3.metric("Bars Loaded",      f"{n_bars}")
    _trades_day = 390 // int(interval.replace("m", "")) if interval.endswith("m") else 1
    _annual_drag = _total_cost_pct * _trades_day * 252 * 100
    c4.metric("Annual Cost Drag", f"{_annual_drag:.0f}%",          f"if {_trades_day} trades/day")

    # ── 5-min model config + train ────────────────────────────────────────────
    _5m_cache_key = f"ml5m_result_{symbol}"
    _5m_result    = sess.get(_5m_cache_key)

    # Try loading from disk
    if _5m_result is None:
        _5m_result = _load_model(symbol, "hf_rf", 1)
        if _5m_result is not None:
            sess[_5m_cache_key] = _5m_result

    with st.form("ml5m_config_form", clear_on_submit=False):
        _fc1, _fc2, _fc3 = st.columns([2, 2, 1])
        _5m_n_cv  = _fc1.selectbox("CV Folds", [3, 5], index=0, key="ml5m_cv")
        _5m_h     = _fc2.selectbox(
            "Predict ahead", [1, 3, 6, 12], index=0,
            format_func=lambda x: f"{x} bar{'s' if x>1 else ''} ({x * int(interval.replace('m','')) if interval.endswith('m') else x} min)",
            key="ml5m_horizon",
        )
        _train5m_btn = _fc3.form_submit_button("⚡ TRAIN HF", type="primary", use_container_width=True)

    if _train5m_btn:
        _prog5 = st.progress(0, text="Building HF features …")
        try:
            from sklearn.ensemble import RandomForestRegressor
            from sklearn.preprocessing import StandardScaler

            _feat = _build_hf_features(df)
            if len(_feat) < 60:
                st.error("Not enough clean HF features — need more data.")
                _prog5.empty()
                return

            _closes = (df["close"] if "close" in df.columns else df["Close"]).reindex(_feat.index)
            _y_arr  = _closes.pct_change(_5m_h).shift(-_5m_h).reindex(_feat.index).dropna()
            _X_feat = _feat.reindex(_y_arr.index)

            _prog5.progress(0.25, text="Fitting Random Forest …")
            _n = len(_y_arr)
            _split = int(_n * 0.75)
            _X_tr, _y_tr = _X_feat.iloc[:_split].values, _y_arr.values[:_split]
            _X_te, _y_te = _X_feat.iloc[_split:].values, _y_arr.values[_split:]

            _scaler = StandardScaler()
            _X_tr_s = _scaler.fit_transform(_X_tr)
            _X_te_s = _scaler.transform(_X_te)

            _rf = RandomForestRegressor(
                n_estimators=80, max_depth=6, min_samples_leaf=5,
                n_jobs=-1, random_state=42,
            )
            _rf.fit(_X_tr_s, _y_tr)

            _prog5.progress(0.75, text="Evaluating OOS …")
            _y_pred_te = _rf.predict(_X_te_s)
            _dir_acc   = float((np.sign(_y_te) == np.sign(_y_pred_te)).mean())

            # Sharpe estimate
            _pnl = np.where(_y_pred_te > 0, _y_te, -_y_te) - _total_cost_pct
            _sharpe = float(_pnl.mean() / (_pnl.std() + 1e-9) * np.sqrt(_trades_day * 252))

            _5m_result = {
                "model":     _rf,
                "scaler":    _scaler,
                "features":  _feat.columns.tolist(),
                "horizon":   _5m_h,
                "interval":  interval,
                "dir_acc":   _dir_acc,
                "sharpe":    _sharpe,
                "oos_pred":  _y_pred_te.tolist(),
                "oos_act":   _y_te.tolist(),
                "oos_dates": _y_arr.index[_split:].tolist(),
                "feat_imp":  dict(zip(_feat.columns, _rf.feature_importances_)),
                "symbol":    symbol,
                "n_bars":    _n,
            }
            sess[_5m_cache_key] = _5m_result
            _save_model(_5m_result, symbol, "hf_rf", _5m_h)

            _prog5.progress(1.0, text="HF model trained ✓")
            _prog5.empty()
            st.toast(
                f"⚡ HF model trained — Dir. Acc: {_dir_acc*100:.1f}% · Est. Sharpe: {_sharpe:.2f}",
                icon="⚡",
            )
        except Exception as _e5m:
            _prog5.empty()
            st.error(f"HF training failed: {_e5m}")
            return

    if _5m_result is None:
        st.info(
            f"No 5-min HF model for **{symbol}** yet. "
            "Load intraday data (5m/15m interval, 30d period), then click **⚡ TRAIN HF**."
        )
        return

    # ── HF Metrics ───────────────────────────────────────────────────────────
    _dir_acc   = _5m_result.get("dir_acc", 0)
    _sharpe_hf = _5m_result.get("sharpe", 0)
    _oos_pred  = np.array(_5m_result.get("oos_pred", []))
    _oos_act   = np.array(_5m_result.get("oos_act",  []))
    _oos_dates = _5m_result.get("oos_dates", [])

    _m1, _m2, _m3, _m4 = st.columns(4)
    _dir_col = t["green"] if _dir_acc > 0.52 else (t["amber"] if _dir_acc > 0.48 else t["red"])
    _sh_col  = t["green"] if _sharpe_hf > 0 else t["red"]
    _m1.metric("Dir. Accuracy", f"{_dir_acc*100:.1f}%", "above 52% = edge")
    _m2.metric("Est. Sharpe",   f"{_sharpe_hf:.2f}",    "after costs")
    _m3.metric("HF Bars Trained", f"{_5m_result.get('n_bars', 0)}")
    # Current prediction
    try:
        _feat_now = _build_hf_features(df)
        if len(_feat_now) > 0:
            _X_now = _5m_result["scaler"].transform(_feat_now.iloc[[-1]][_5m_result["features"]].values)
            _ret_now = float(_5m_result["model"].predict(_X_now)[0])
            _close_now = float((df["close"] if "close" in df.columns else df["Close"]).iloc[-1])
            _price_tgt = _close_now * (1 + _ret_now)
            _sig_now = "BUY" if _ret_now > _total_cost_pct * 2 else ("SELL" if _ret_now < -_total_cost_pct * 2 else "HOLD")
            _m4.metric("HF Signal",     _sig_now, f"{_ret_now*100:+.3f}%")
            _sig_col5 = {"BUY": t["green"], "SELL": t["red"]}.get(_sig_now, t["amber"])
            st.markdown(f"""
<div style="background:{_sig_col5}18;border:1px solid {_sig_col5}44;border-radius:5px;
  padding:10px 14px;font-family:IBM Plex Mono;font-size:11px;margin:8px 0">
  <b style="color:{_sig_col5}">{_sig_now}</b> &nbsp;·&nbsp;
  Predicted {_ret_now*100:+.3f}% over next {_5m_h} bar(s) &nbsp;·&nbsp;
  Target: ${_price_tgt:,.4f} &nbsp;·&nbsp;
  Cost hurdle: {_hurdle_pct:.3f}%
  {"&nbsp;·&nbsp;<b style='color:"+t['green']+"'>✓ Clears cost hurdle</b>" if abs(_ret_now)*100 > _hurdle_pct else "&nbsp;·&nbsp;<b style='color:"+t['red']+"'>✗ Below cost hurdle — no trade</b>"}
</div>""", unsafe_allow_html=True)
    except Exception:
        _m4.metric("HF Signal", "?")

    # ── OOS Performance Chart ─────────────────────────────────────────────────
    if len(_oos_pred) > 5 and len(_oos_act) > 5 and PLOTLY_OK:
        try:
            _oos_dt = pd.to_datetime(_oos_dates)
            _pnl_arr = np.where(_oos_pred > _total_cost_pct, _oos_act,
                        np.where(_oos_pred < -_total_cost_pct, -_oos_act, 0)) - _total_cost_pct
            _cum_pnl = np.cumsum(_pnl_arr) * 100

            _fig5 = go.Figure()
            _fig5.add_trace(go.Scatter(
                x=_oos_dt, y=_cum_pnl, name="Cumulative P&L (after costs)",
                line=dict(color=t["blue"], width=2),
                fill="tozeroy",
                fillcolor=f"rgba(75,159,255,0.08)" if not light_mode else "rgba(21,85,162,0.06)",
            ))
            _fig5.add_hline(y=0, line_color=t["border"], line_width=1)
            _lay5 = _plotly_base(t, "HF Model OOS Cumulative P&L (after costs, after hurdle)", height=280)
            _lay5["yaxis"] = {**_lay5.get("yaxis", {}), "title": dict(text="Cum. P&L %", font=dict(size=9)), "side": "right"}
            _fig5.update_layout(**_lay5)
            st.plotly_chart(_fig5, use_container_width=True, config=dict(displayModeBar=False))

            # Feature importance
            _feat_imp5 = _5m_result.get("feat_imp", {})
            if _feat_imp5:
                _sorted5 = sorted(_feat_imp5.items(), key=lambda x: x[1], reverse=True)[:12]
                _f_labels = [k.replace("_", " ").title() for k, _ in _sorted5]
                _f_vals   = [v for _, v in _sorted5]
                _fig5fi = go.Figure(go.Bar(
                    x=_f_vals, y=_f_labels, orientation="h",
                    marker_color=t["amber"], opacity=0.85,
                ))
                _lay5fi = _plotly_base(t, "HF Feature Importance (Top 12)", height=320)
                _lay5fi["yaxis"] = {**_lay5fi.get("yaxis", {}), "autorange": "reversed"}
                _fig5fi.update_layout(**_lay5fi)
                st.plotly_chart(_fig5fi, use_container_width=True, config=dict(displayModeBar=False))
        except Exception:
            pass

    st.markdown(f"""
<div style="font-family:IBM Plex Mono;font-size:9px;color:{t['text_mute']};
  padding:8px 12px;background:{t['surface']};border-radius:4px;border-left:3px solid {t['amber']};
  margin-top:10px;line-height:1.7">
⚠️ <b style="color:{t['amber']}">5-MIN TRADING REALITY CHECK:</b>
Annual cost drag at {_trades_day} trades/day = <b>{_annual_drag:.0f}%</b>.
Only trade when signal exceeds <b>{_hurdle_pct:.3f}%</b> (2× cost hurdle).
Best results: liquid instruments (BTC, ETH, major FX) with tight spreads.
Paper trade for 3–6 months before committing real capital.
</div>""", unsafe_allow_html=True)
