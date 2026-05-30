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

    # ── Model configuration ────────────────────────────────────────────────────
    _has_any_result = any(k.startswith(f"ml_result_{symbol}_") for k in sess.keys())
    with st.expander("⚙ MODEL CONFIGURATION", expanded=not _has_any_result):
        c1, c2, c3, c4 = st.columns([2, 1.5, 1.5, 1])
        model_labels = ["Ensemble (Best)", "Random Forest", "Elastic Net", "Neural Net NN3"]
        model_vals   = ["ensemble",        "random_forest", "elastic_net", "neural_net"]
        model_label  = c1.selectbox(
            "Model", model_labels, index=0,
            help="Ensemble combines the best models for your dataset size. "
                 "Neural Net requires 600+ bars and works best with daily data.",
        )
        model_type = model_vals[model_labels.index(model_label)]

        horizon = c2.selectbox(
            "Horizon", [1, 3, 5, 10, 20], index=0,
            format_func=lambda x: f"{x} bar{'s' if x>1 else ''}",
            help="Bars ahead to predict. Shorter horizons = more frequent signals.",
        )
        n_cv = c3.selectbox("CV Folds", [3, 5], index=0)
        train_btn = c4.button("▶ TRAIN", type="primary", use_container_width=True)

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

    # ── Training (only on button click) ───────────────────────────────────────
    _cache_key = f"ml_result_{symbol}_{model_type}_{horizon}"
    result = sess.get(_cache_key)

    if train_btn:
        _MH_HORIZONS = [1, 5, 20]   # always train all three for multi-horizon display
        _total_steps  = len(_MH_HORIZONS)
        _prog = st.progress(0, text="Initialising …")
        _stat = st.empty()

        try:
            from ml.trainer import train as ml_train

            for _hi, _h in enumerate(_MH_HORIZONS):
                _is_primary = (_h == horizon)
                _h_key      = f"ml_result_{symbol}_{model_type}_{_h}" if _is_primary \
                              else f"ml_mh_{symbol}_{model_type}_{_h}"
                _h_cv       = n_cv if _is_primary else 2   # fewer folds for secondary horizons

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

                # Also store primary result under the selected horizon cache key
                if _is_primary:
                    result = _h_result

            _prog.progress(1.0, text="All horizons trained ✓")
            _prog.empty()
            _stat.empty()
            st.toast(
                f"✅ {model_type.replace('_',' ').title()} trained — "
                f"H1/H5/H20 ready · Dir. Acc: {result.directional_acc*100:.1f}%",
                icon="🤖",
            )
        except Exception as e:
            _prog.empty()
            _stat.empty()
            st.error(f"Training failed: {e}")
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

    # ── Row 2: Diagnostic charts — always all three visible ───────────────────
    diag1, diag2, diag3 = st.columns([1, 1, 1], gap="small")
    with diag1:
        st.plotly_chart(
            _chart_actual_vs_predicted(result, t),
            use_container_width=True, config=dict(displayModeBar=False),
        )
    with diag2:
        st.plotly_chart(
            _chart_feature_importance(result, t),
            use_container_width=True, config=dict(displayModeBar=False),
        )
    with diag3:
        st.plotly_chart(
            _chart_cv_folds(result, t),
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
        fig.update_layout(**_plotly_base(t, "Price + ML Signals"))
        return fig

    oos_dates = pd.to_datetime(result.oos_dates)
    oos_pred  = np.array(result.oos_predicted)
    oos_act   = np.array(result.oos_actual)

    # Align df to OOS period
    df_oos = df.reindex(oos_dates, method="nearest").dropna(subset=["Close"])

    fig = make_subplots(rows=2, cols=1, shared_xaxes=True,
                        row_heights=[0.70, 0.30], vertical_spacing=0.04)

    # ── Candlestick / price line ──────────────────────────────────────────────
    if len(df_oos) > 10:
        fig.add_trace(go.Candlestick(
            x=df_oos.index,
            open=df_oos["Open"], high=df_oos["High"],
            low=df_oos["Low"],   close=df_oos["Close"],
            name="Price",
            increasing_line_color=t["green"], decreasing_line_color=t["red"],
            increasing_fillcolor="rgba(0,201,167,0.25)" if not light_mode else "rgba(0,115,92,0.20)",
            decreasing_fillcolor="rgba(255,69,96,0.25)"  if not light_mode else "rgba(192,0,30,0.20)",
            showlegend=False,
        ), row=1, col=1)
    else:
        fig.add_trace(go.Scatter(
            x=df_oos.index, y=df_oos["Close"],
            name="Price", line=dict(color=t["text_sec"], width=1.5),
        ), row=1, col=1)

    # ── BUY / SELL signals from OOS predictions ───────────────────────────────
    # Threshold: top/bottom 30% of predictions → strong signals only
    pred_std = float(np.std(oos_pred)) if len(oos_pred) > 5 else 0.003
    buy_thr  = max(0.002, pred_std * 0.5)
    sell_thr = -buy_thr
    buy_idx  = np.where(oos_pred > buy_thr)[0]
    sell_idx = np.where(oos_pred < sell_thr)[0]

    n_oos = len(df_oos)
    if len(buy_idx) and n_oos:
        buy_valid  = [i for i in buy_idx if i < n_oos]
        buy_dates  = [oos_dates[i] for i in buy_valid]
        buy_prices = [float(df_oos["Low"].iloc[i]) * 0.997 for i in buy_valid]
        if buy_dates:
            fig.add_trace(go.Scatter(
                x=buy_dates, y=buy_prices, mode="markers", name="ML BUY ▲",
                marker=dict(symbol="triangle-up", size=14, color=t["green"],
                            opacity=0.95, line=dict(color=t["bg"], width=1)),
                hovertemplate="<b>ML BUY</b><br>Date: %{x}<br>Price: %{y:,.2f}<extra></extra>",
            ), row=1, col=1)

    if len(sell_idx) and n_oos:
        sell_valid  = [i for i in sell_idx if i < n_oos]
        sell_dates  = [oos_dates[i] for i in sell_valid]
        sell_prices = [float(df_oos["High"].iloc[i]) * 1.003 for i in sell_valid]
        if sell_dates:
            fig.add_trace(go.Scatter(
                x=sell_dates, y=sell_prices, mode="markers", name="ML SELL ▼",
                marker=dict(symbol="triangle-down", size=14, color=t["red"],
                            opacity=0.95, line=dict(color=t["bg"], width=1)),
                hovertemplate="<b>ML SELL</b><br>Date: %{x}<br>Price: %{y:,.2f}<extra></extra>",
            ), row=1, col=1)

    # ── Current price + ML target ─────────────────────────────────────────────
    if pred and len(df_oos):
        last_date = df_oos.index[-1]
        fig.add_hline(
            y=pred.current_price, line_color=t["amber"], line_width=1,
            line_dash="dot", annotation_text=f"Now ${pred.current_price:,.2f}",
            annotation_font_color=t["amber"], annotation_font_size=9,
            row=1, col=1,
        )
        sig_col = {"BUY": t["green"], "SELL": t["red"]}.get(pred.signal, t["text_mute"])
        fig.add_hline(
            y=pred.predicted_price, line_color=sig_col, line_width=1.5,
            line_dash="dash",
            annotation_text=f"ML Target ${pred.predicted_price:,.2f}",
            annotation_font_color=sig_col, annotation_font_size=9,
            row=1, col=1,
        )

    # ── Prediction accuracy bar (bottom subplot) ──────────────────────────────
    correct = (np.sign(oos_act) == np.sign(oos_pred)).astype(float)
    rolling_acc = pd.Series(correct).rolling(20, min_periods=5).mean() * 100
    fig.add_trace(go.Scatter(
        x=oos_dates, y=rolling_acc, name="20-bar Dir. Acc %",
        line=dict(color=t["blue"], width=1.5),
        fill="tozeroy",
        fillcolor="rgba(21,85,162,0.13)" if light_mode else "rgba(75,159,255,0.13)",
    ), row=2, col=1)
    fig.add_hline(y=50, line_color=t["border"], line_width=1,
                  line_dash="dot", row=2, col=1)

    lay = _plotly_base(t, f"ML Signals on Price · {symbol} — Drag to zoom · Scroll to pan", height=600)
    lay["xaxis"]  = {**lay.get("xaxis", {}),
                     "rangeslider": dict(visible=True, thickness=0.06,
                                        bgcolor=t["surface"], bordercolor=t["border"]),
                     "type": "date"}
    lay["xaxis2"] = dict(gridcolor=t["grid"], showgrid=True, zeroline=False,
                         tickfont=dict(size=9, color=t["text_mute"]))
    lay["yaxis"]  = {**lay.get("yaxis", {}),
                     "title": dict(text="Price", font=dict(size=9)), "side": "right",
                     "showgrid": True, "gridcolor": t["grid"]}
    lay["yaxis2"] = dict(gridcolor=t["grid"], showgrid=True, zeroline=False,
                         tickfont=dict(size=9, color=t["text_mute"]),
                         title=dict(text="Dir. Acc %", font=dict(size=9)),
                         range=[0, 100], side="right")
    lay["hovermode"]   = "x unified"
    lay["dragmode"]    = "pan"      # default to pan so user can scroll immediately
    lay["legend"]      = dict(orientation="h", yanchor="top", y=1.12, x=0,
                               bgcolor="rgba(0,0,0,0)", font=dict(size=10))
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
#  CHART 3: Actual vs Predicted scatter
# ─────────────────────────────────────────────────────────────────────────────
def _chart_actual_vs_predicted(result, t: dict) -> go.Figure:
    if not result.oos_actual:
        fig = go.Figure()
        fig.update_layout(**_plotly_base(t, "Actual vs Predicted"))
        return fig

    actual    = np.array(result.oos_actual)   * 100
    predicted = np.array(result.oos_predicted) * 100

    # Clip extreme predictions for display clarity
    p95 = np.percentile(np.abs(predicted), 95)
    predicted_disp = np.clip(predicted, -p95 * 3, p95 * 3)

    correct = (np.sign(actual) == np.sign(predicted))
    colors  = [t["green"] if c else t["red"] for c in correct]

    mx = max(np.abs(actual).max(), np.abs(predicted_disp).max()) * 1.1
    fig = go.Figure()
    fig.add_trace(go.Scatter(
        x=[-mx, mx], y=[-mx, mx], name="Perfect",
        line=dict(color=t["border"], dash="dash", width=1), showlegend=False,
    ))
    fig.add_trace(go.Scatter(
        x=predicted_disp, y=actual, mode="markers",
        name="OOS Samples",
        marker=dict(color=colors, size=4, opacity=0.55),
        hovertemplate="Pred: %{x:.3f}%<br>Act: %{y:.3f}%<extra></extra>",
    ))

    lay = _plotly_base(t, "Actual vs Predicted Return (%)", height=400)
    lay["xaxis"] = {**lay.get("xaxis", {}), "title": dict(text="Predicted %", font=dict(size=9))}
    lay["yaxis"] = {**lay.get("yaxis", {}), "title": dict(text="Actual %",    font=dict(size=9))}
    fig.update_layout(**lay)
    dir_acc = result.directional_acc * 100
    fig.add_annotation(
        text=f"Dir. Acc: {dir_acc:.1f}%",
        xref="paper", yref="paper", x=0.05, y=0.93,
        showarrow=False, font=dict(size=10, color=t["text_sec"]),
        bgcolor=t["card"], bordercolor=t["border"],
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
