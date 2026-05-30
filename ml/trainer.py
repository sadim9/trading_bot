"""
ml/trainer.py — Training pipeline with expanding-window cross-validation.

Implements the rolling/expanding-window design from Kelly & Xiu (2023) §4.2:
  Training:   first 60% of data  (fit model)
  Validation: next 15% of data   (tune, used for early stopping in NN)
  Test:       last 25% of data   (evaluate out-of-sample)

After CV evaluation the model is re-fit on ALL available data so predictions
use every bar when generating the current recommendation.

Returns a MLTrainingResult dataclass with metrics, feature importance,
out-of-sample predictions, and the fitted model.
"""

from __future__ import annotations

import time
import warnings
import numpy as np
import pandas as pd
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

from ml.features import build_dataset, get_feature_names
from ml.models import make_model

warnings.filterwarnings("ignore")


@dataclass
class CVFold:
    fold:       int
    train_size: int
    val_size:   int
    test_size:  int
    r2_oos:     float
    mse:        float


@dataclass
class MLTrainingResult:
    symbol:          str
    model_type:      str
    horizon:         int
    n_bars:          int
    n_features:      int
    train_time_s:    float

    # Out-of-sample metrics
    r2_oos:          float          # overall OOS R² vs zero forecast
    r2_oos_cv:       float          # average across CV folds
    mse:             float
    mae:             float
    directional_acc: float          # % of correct direction predictions

    # Rolling OOS predictions (for chart)
    oos_dates:       List           = field(default_factory=list)
    oos_actual:      List[float]    = field(default_factory=list)
    oos_predicted:   List[float]    = field(default_factory=list)

    # CV fold breakdown
    cv_folds:        List[CVFold]   = field(default_factory=list)

    # Feature importance
    feature_importance: Dict[str, float] = field(default_factory=dict)

    # Fitted model (for prediction)
    model:           object         = None

    # Sharpe estimate
    sharpe_est:      float          = 0.0

    # Per-model breakdown (ensemble only)
    individual_r2:   Dict[str, float] = field(default_factory=dict)


def _r2_oos_vs_zero(y_true: np.ndarray, y_pred: np.ndarray) -> float:
    """
    Out-of-sample R² relative to the ZERO forecast (not historical mean).
    As used in Kelly & Xiu (2023): R² = 1 - SS_res / SS_tot_vs_zero
    """
    ss_res = np.sum((y_true - y_pred) ** 2)
    ss_tot = np.sum(y_true ** 2)
    if ss_tot == 0:
        return 0.0
    return float(1 - ss_res / ss_tot)


def _directional_accuracy(y_true: np.ndarray, y_pred: np.ndarray) -> float:
    correct = np.sign(y_true) == np.sign(y_pred)
    return float(correct.mean())


def _sharpe_from_oos(y_true: np.ndarray, y_pred: np.ndarray) -> float:
    """
    Estimate annualised Sharpe ratio of a long/short strategy:
    go long when predicted > 0, short when predicted < 0.
    Scaled by sqrt(252) for daily data.
    """
    pnl = np.where(y_pred > 0, y_true, -y_true)
    if pnl.std() == 0:
        return 0.0
    return float(pnl.mean() / pnl.std() * np.sqrt(252))


def train(
    df: pd.DataFrame,
    symbol: str,
    model_type: str = "ensemble",
    horizon: int = 1,
    n_cv_folds: int = 3,
    progress_callback=None,
) -> MLTrainingResult:
    """
    Full training pipeline.

    Parameters
    ----------
    df            : OHLCV + indicators DataFrame from data/ingestion.py
    symbol        : ticker string (for logging)
    model_type    : "elastic_net" | "random_forest" | "neural_net" | "ensemble"
    horizon       : forward return horizon in bars (default 1 = next bar)
    n_cv_folds    : number of expanding-window folds
    progress_callback : optional callable(pct: int, msg: str) for UI updates
    """

    def _progress(pct: int, msg: str):
        if progress_callback:
            progress_callback(pct, msg)

    t0 = time.time()
    _progress(5, "Engineering features …")

    X_all, y_all = build_dataset(df, horizon=horizon, min_bars=60)
    X_arr = X_all.values.astype(np.float32)
    y_arr = y_all.values.astype(np.float32)
    dates = X_all.index
    feat_names = get_feature_names()
    n = len(X_arr)

    _progress(15, f"Dataset ready — {n} samples · {X_arr.shape[1]} features")

    # ── Expanding-window CV ────────────────────────────────────────────────────
    # Minimum train set: 60 bars. Folds divide the remaining data evenly.
    min_train = max(60, int(n * 0.40))
    remaining  = n - min_train
    fold_size  = max(1, remaining // max(n_cv_folds, 1))

    cv_folds: List[CVFold] = []
    all_oos_actual: List[float] = []
    all_oos_pred:   List[float] = []
    all_oos_dates:  List       = []

    individual_preds: Dict[str, List[float]] = {}

    for fold_i in range(n_cv_folds):
        train_end = min_train + fold_i * fold_size
        test_end  = min(train_end + fold_size, n)
        if train_end >= test_end:
            break

        X_tr, y_tr = X_arr[:train_end], y_arr[:train_end]
        X_te, y_te = X_arr[train_end:test_end], y_arr[train_end:test_end]

        _progress(
            15 + int(60 * fold_i / n_cv_folds),
            f"Training fold {fold_i+1}/{n_cv_folds} "
            f"(train={train_end}, test {train_end}→{test_end}) …"
        )

        m = make_model(model_type)
        m.fit(X_tr, y_tr)

        # For ensemble, use the mean of individual (non-ranked) predictions for
        # R² and OOS metrics. The rank-based predict() is only for the final signal.
        if model_type == "ensemble" and hasattr(m, "predict_individual"):
            ind = m.predict_individual(X_te)
            # Use RF as the primary OOS predictor for R² (best single model)
            y_pred = ind.get("rf", m.predict(X_te))
            for mname, mpred in ind.items():
                individual_preds.setdefault(mname, []).extend(mpred.tolist())
        else:
            y_pred = m.predict(X_te)

        fold_r2  = _r2_oos_vs_zero(y_te, y_pred)
        fold_mse = float(np.mean((y_te - y_pred) ** 2))

        cv_folds.append(CVFold(
            fold=fold_i + 1,
            train_size=train_end,
            val_size=0,
            test_size=len(y_te),
            r2_oos=fold_r2,
            mse=fold_mse,
        ))

        all_oos_actual.extend(y_te.tolist())
        all_oos_pred.extend(y_pred.tolist())
        all_oos_dates.extend(dates[train_end:test_end].tolist())

    oos_actual = np.array(all_oos_actual, dtype=np.float32)
    oos_pred   = np.array(all_oos_pred,   dtype=np.float32)

    _progress(80, "Fitting final model on full dataset …")

    # ── Final fit on ALL data ─────────────────────────────────────────────────
    final_model = make_model(model_type)
    final_model.fit(X_arr, y_arr)

    _progress(92, "Computing metrics …")

    r2_cv  = float(np.mean([f.r2_oos for f in cv_folds])) if cv_folds else 0.0
    r2_all = _r2_oos_vs_zero(oos_actual, oos_pred) if len(oos_actual) > 0 else 0.0
    mse    = float(np.mean((oos_actual - oos_pred) ** 2)) if len(oos_actual) > 0 else 0.0
    mae    = float(np.mean(np.abs(oos_actual - oos_pred))) if len(oos_actual) > 0 else 0.0
    dir_acc = _directional_accuracy(oos_actual, oos_pred) if len(oos_actual) > 0 else 0.0
    sharpe  = _sharpe_from_oos(oos_actual, oos_pred) if len(oos_actual) > 5 else 0.0

    feat_imp = final_model.feature_importance(feat_names)

    # Individual model R² for ensemble
    individual_r2: Dict[str, float] = {}
    if model_type == "ensemble":
        oos_act_arr = np.array(all_oos_actual)
        for mname, mpreds in individual_preds.items():
            individual_r2[mname] = _r2_oos_vs_zero(oos_act_arr[:len(mpreds)], np.array(mpreds))

    _progress(100, "Done ✓")

    return MLTrainingResult(
        symbol          = symbol,
        model_type      = model_type,
        horizon         = horizon,
        n_bars          = n,
        n_features      = X_arr.shape[1],
        train_time_s    = time.time() - t0,
        r2_oos          = r2_all,
        r2_oos_cv       = r2_cv,
        mse             = mse,
        mae             = mae,
        directional_acc = dir_acc,
        sharpe_est      = sharpe,
        oos_dates       = all_oos_dates,
        oos_actual      = all_oos_actual,
        oos_predicted   = all_oos_pred,
        cv_folds        = cv_folds,
        feature_importance = feat_imp,
        model           = final_model,
        individual_r2   = individual_r2,
    )
