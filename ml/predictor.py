"""
ml/predictor.py — Generate predictions and trading recommendations.

Given a trained MLTrainingResult and fresh OHLCV data, produces:
  - Predicted return for the next bar/period
  - Implied price target
  - Confidence score (ensemble spread or model certainty)
  - BUY / SELL / HOLD recommendation with thresholds
  - Multi-horizon predictions (1, 5, 20 bars ahead)
"""

from __future__ import annotations

import numpy as np
import pandas as pd
from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple

from ml.features import build_features, rank_standardise, FEATURE_COLS
from ml.trainer import MLTrainingResult


@dataclass
class MLPrediction:
    symbol:          str
    current_price:   float
    predicted_return: float         # fractional (e.g. 0.012 = +1.2%)
    predicted_price:  float         # current_price * (1 + predicted_return)
    confidence:      float          # 0-100 confidence score
    signal:          str            # "BUY" | "SELL" | "HOLD"
    signal_strength: str            # "STRONG" | "MODERATE" | "WEAK"
    horizon:         int            # bars ahead
    horizon_label:   str            # e.g. "1 bar", "1 day", "1 week"
    individual_preds: Dict[str, float]  # per-model raw predictions
    feature_contributions: Dict[str, float]  # top features driving the prediction
    stop_loss:       float
    take_profit:     float
    risk_reward:     float
    reasoning:       List[str]      # bullet-point reasons for the recommendation


# ── Thresholds ─────────────────────────────────────────────────────────────────
BUY_STRONG_THRESH  =  0.008   # +0.8% → STRONG BUY
BUY_MOD_THRESH     =  0.003   # +0.3% → MODERATE BUY
SELL_STRONG_THRESH = -0.008   # -0.8% → STRONG SELL
SELL_MOD_THRESH    = -0.003   # -0.3% → MODERATE SELL


def _horizon_label(horizon: int, interval: str) -> str:
    unit_map = {
        "1m": "min", "5m": "min", "15m": "min", "30m": "min",
        "1h": "hr",  "2h": "hr",  "4h": "hr",
        "1d": "day", "1wk": "week",
    }
    unit = unit_map.get(interval, "bar")
    val  = horizon
    if unit == "min":  val *= int(interval.replace("m", ""))
    if val == 1:
        return f"1 {unit}"
    return f"{val} {unit}s"


def predict(
    result: MLTrainingResult,
    df: pd.DataFrame,
    interval: str = "1d",
) -> Optional[MLPrediction]:
    """
    Generate a prediction from a trained MLTrainingResult.

    Parameters
    ----------
    result   : output of ml.trainer.train()
    df       : current market DataFrame (OHLCV + indicators)
    interval : chart interval string for horizon labelling
    """
    if result is None or result.model is None:
        return None

    try:
        feat = build_features(df)
        if len(feat) == 0:
            return None

        # Use the latest row for prediction
        X_latest = feat.iloc[[-1]].copy()
        for col in X_latest.columns:
            X_latest[col] = rank_standardise(feat[col]).iloc[-1]
        X_arr = X_latest.values.astype(np.float32)

        raw_pred = float(result.model.predict(X_arr)[0])
        current_price = float(df["Close"].iloc[-1])

        # Ensemble returns rank scores in [-0.5, 0.5]; scale to return range
        # using the empirical std of OOS actual returns for that symbol.
        if result.model_type == "ensemble" and result.oos_actual:
            oos_std = float(np.std(result.oos_actual)) or 0.01
            pred_return = raw_pred * oos_std * 2  # scale: ±0.5 rank → ±1σ return
        else:
            pred_return = raw_pred

        predicted_price = current_price * (1 + pred_return)

        # Per-model breakdown (ensemble)
        individual_preds: Dict[str, float] = {}
        if hasattr(result.model, "predict_individual"):
            for mname, mpred in result.model.predict_individual(X_arr).items():
                individual_preds[mname] = float(mpred[0])

        # Confidence: higher when all models agree on direction
        if individual_preds:
            signs = [np.sign(v) for v in individual_preds.values()]
            agreement = abs(sum(signs)) / len(signs)  # 1.0 = all agree
            spread = np.std(list(individual_preds.values()))
            base_conf = agreement * 100
            # Reduce confidence if spread is very wide
            spread_penalty = min(spread / (abs(pred_return) + 1e-6) * 10, 30)
            confidence = max(min(base_conf - spread_penalty + 20, 95), 30)
        else:
            # Single model: use directional accuracy as confidence proxy
            confidence = max(min(result.directional_acc * 100, 90), 40)

        # Signal
        if pred_return >= BUY_STRONG_THRESH:
            signal, strength = "BUY", "STRONG"
        elif pred_return >= BUY_MOD_THRESH:
            signal, strength = "BUY", "MODERATE"
        elif pred_return <= SELL_STRONG_THRESH:
            signal, strength = "SELL", "STRONG"
        elif pred_return <= SELL_MOD_THRESH:
            signal, strength = "SELL", "MODERATE"
        elif abs(pred_return) < BUY_MOD_THRESH * 0.5:
            signal, strength = "HOLD", "WEAK"
        else:
            signal, strength = "HOLD", "MODERATE"

        # Risk levels via ATR
        atr = float(df["atr"].iloc[-1]) if "atr" in df.columns else current_price * 0.01
        sl_mult = 1.5
        tp_mult = 2.5
        if signal == "BUY":
            stop_loss   = current_price - atr * sl_mult
            take_profit = current_price + atr * tp_mult
        elif signal == "SELL":
            stop_loss   = current_price + atr * sl_mult
            take_profit = current_price - atr * tp_mult
        else:
            stop_loss   = current_price - atr * sl_mult
            take_profit = current_price + atr * sl_mult

        risk   = abs(current_price - stop_loss)
        reward = abs(take_profit - current_price)
        rr     = reward / risk if risk > 0 else 0.0

        # Feature contributions (top drivers)
        feat_imp = result.feature_importance
        feat_vals_raw = X_latest.values[0]
        contributions: Dict[str, float] = {}
        for i, fname in enumerate(FEATURE_COLS):
            imp = feat_imp.get(fname, 0.0)
            val = float(feat_vals_raw[i]) if i < len(feat_vals_raw) else 0.0
            contributions[fname] = imp * val

        # Reasoning bullets
        reasoning: List[str] = []
        rsi_v = float(df["rsi"].iloc[-1]) if "rsi" in df.columns else 50
        ema_f = float(df["ema_fast"].iloc[-1]) if "ema_fast" in df.columns else current_price
        ema_s = float(df["ema_slow"].iloc[-1]) if "ema_slow" in df.columns else current_price
        macd_h = float(df["macd_hist"].iloc[-1]) if "macd_hist" in df.columns else 0
        vol_r  = float(df["vol_ratio"].iloc[-1]) if "vol_ratio" in df.columns else 1

        reasoning.append(
            f"ML ensemble predicts {pred_return*100:+.2f}% return over next {_horizon_label(result.horizon, interval)}"
        )
        if ema_f > ema_s:
            reasoning.append("EMA fast > slow → uptrend regime")
        else:
            reasoning.append("EMA fast < slow → downtrend regime")
        if rsi_v < 35:
            reasoning.append(f"RSI {rsi_v:.0f} — oversold territory supports reversal")
        elif rsi_v > 65:
            reasoning.append(f"RSI {rsi_v:.0f} — overbought, momentum may stall")
        else:
            reasoning.append(f"RSI {rsi_v:.0f} — neutral momentum")
        if macd_h > 0:
            reasoning.append("MACD histogram positive — bullish crossover momentum")
        else:
            reasoning.append("MACD histogram negative — bearish crossover momentum")
        if vol_r > 1.5:
            reasoning.append(f"Volume {vol_r:.1f}× above average — strong conviction")
        reasoning.append(
            f"Model directional accuracy (OOS): {result.directional_acc*100:.1f}%"
        )

        return MLPrediction(
            symbol            = result.symbol,
            current_price     = current_price,
            predicted_return  = pred_return,
            predicted_price   = predicted_price,
            confidence        = confidence,
            signal            = signal,
            signal_strength   = strength,
            horizon           = result.horizon,
            horizon_label     = _horizon_label(result.horizon, interval),
            individual_preds  = individual_preds,
            feature_contributions = contributions,
            stop_loss         = stop_loss,
            take_profit       = take_profit,
            risk_reward       = rr,
            reasoning         = reasoning,
        )

    except Exception:
        return None


def multi_horizon_predict(
    df: pd.DataFrame,
    symbol: str,
    model_type: str = "ensemble",
    horizons: Tuple[int, ...] = (1, 5, 20),
    interval: str = "1d",
) -> Dict[int, MLPrediction]:
    """
    Quick multi-horizon predictions (train on-the-fly with fewer CV folds).
    Returns dict of {horizon: MLPrediction}.
    """
    from ml.trainer import train
    results = {}
    for h in horizons:
        try:
            res = train(df, symbol, model_type=model_type, horizon=h, n_cv_folds=2)
            pred = predict(res, df, interval)
            if pred:
                results[h] = pred
        except Exception:
            pass
    return results
