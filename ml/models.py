"""
ml/models.py — Return-prediction model wrappers.

Implements three model classes from Kelly & Xiu (2023):
  - ElasticNetPredictor  (penalised linear, fast, stable)
  - RandomForestPredictor (tree ensemble, best single model on small data)
  - NNPredictor           (3-layer MLP, good only on large daily datasets)

All expose a unified fit(X, y) / predict(X) interface.

Dataset size guidance (from the paper):
  < 500 bars  → ElasticNet only (linear models win on tiny data)
  500-2000    → ElasticNet + RF
  > 2000      → Full ensemble including NN3
"""

from __future__ import annotations

import numpy as np
import warnings
from typing import Dict, List, Optional

warnings.filterwarnings("ignore")

# ── Minimum bars for each model to be meaningful ──────────────────────────────
MIN_BARS_ENET = 60
MIN_BARS_RF   = 200
MIN_BARS_NN   = 600   # NN3 is unreliable below this; needs enough for val split


# ── Elastic Net ────────────────────────────────────────────────────────────────
class ElasticNetPredictor:
    """
    Penalised linear return predictor. Works on any dataset size.
    L(β) = MSE + α·[(1-l1_ratio)·||β||² + l1_ratio·||β||₁]
    """

    name = "Elastic Net"
    color = "#4B9FFF"

    def __init__(self, alpha: float = 5e-4, l1_ratio: float = 0.5):
        from sklearn.linear_model import ElasticNet
        self._model = ElasticNet(
            alpha=alpha, l1_ratio=l1_ratio,
            fit_intercept=False, max_iter=5000, tol=1e-4,
        )
        self.fitted = False

    def fit(self, X: np.ndarray, y: np.ndarray) -> "ElasticNetPredictor":
        from sklearn.preprocessing import StandardScaler
        self._scaler = StandardScaler()
        Xs = self._scaler.fit_transform(X)
        self._model.fit(Xs, y)
        self.fitted = True
        return self

    def predict(self, X: np.ndarray) -> np.ndarray:
        Xs = self._scaler.transform(X)
        return self._model.predict(Xs)

    def feature_importance(self, feature_names: List[str]) -> Dict[str, float]:
        coefs = np.abs(self._model.coef_)
        total = coefs.sum() or 1.0
        return {n: float(c / total) for n, c in zip(feature_names, coefs)}


# ── Random Forest ──────────────────────────────────────────────────────────────
class RandomForestPredictor:
    """
    Random Forest. Best performer on medium-sized datasets (200-2000 bars).
    Shallow trees + sqrt feature sampling prevent overfitting.
    """

    name = "Random Forest"
    color = "#00C9A7"

    def __init__(self, n_estimators: int = 200, max_depth: int = 4):
        from sklearn.ensemble import RandomForestRegressor
        self._model = RandomForestRegressor(
            n_estimators=n_estimators,
            max_depth=max_depth,      # shallow → regularised
            max_features="sqrt",
            min_samples_leaf=5,
            n_jobs=-1,
            random_state=42,
        )
        self.fitted = False

    def fit(self, X: np.ndarray, y: np.ndarray) -> "RandomForestPredictor":
        self._model.fit(X, y)
        self.fitted = True
        return self

    def predict(self, X: np.ndarray) -> np.ndarray:
        return self._model.predict(X)

    def feature_importance(self, feature_names: List[str]) -> Dict[str, float]:
        imp = self._model.feature_importances_
        return {n: float(v) for n, v in zip(feature_names, imp)}


# ── Neural Network (NN3 equivalent) ───────────────────────────────────────────
class NNPredictor:
    """
    3-layer feed-forward MLP.  Architecture is scaled DOWN aggressively for
    small datasets to prevent the catastrophic overfitting seen on intraday data.

    Dataset-adaptive sizing:
      n < 600   → disabled (raises ValueError — caller should skip)
      600-1500  → (32, 16) tiny architecture, very high alpha
      > 1500    → (128, 64, 32) standard architecture
    """

    name = "Neural Net (NN3)"
    color = "#9B6DFF"

    def __init__(self, n_samples: int = 2000):
        from sklearn.neural_network import MLPRegressor
        from sklearn.preprocessing import StandardScaler
        self._scaler = StandardScaler()
        self._n_samples = n_samples

        if n_samples < MIN_BARS_NN:
            raise ValueError(
                f"Neural Net requires at least {MIN_BARS_NN} training bars; "
                f"got {n_samples}. Use ElasticNet or RandomForest instead, "
                f"or switch to daily interval with 2y+ period."
            )
        elif n_samples < 1500:
            # Tiny architecture — prevents overfitting on small datasets
            arch  = (32, 16)
            alpha = 0.1     # very strong L2
        else:
            arch  = (128, 64, 32)
            alpha = 1e-3

        self._model = MLPRegressor(
            hidden_layer_sizes=arch,
            activation="relu",
            solver="adam",
            alpha=alpha,
            batch_size="auto",
            learning_rate="adaptive",
            learning_rate_init=1e-3,
            max_iter=200,
            early_stopping=True,
            validation_fraction=0.20,
            n_iter_no_change=20,
            tol=1e-4,
            random_state=42,
        )
        self.fitted = False

    def fit(self, X: np.ndarray, y: np.ndarray) -> "NNPredictor":
        Xs = self._scaler.fit_transform(X)
        self._model.fit(Xs, y)
        self.fitted = True
        return self

    def predict(self, X: np.ndarray) -> np.ndarray:
        Xs = self._scaler.transform(X)
        return self._model.predict(Xs)

    def feature_importance(self, feature_names: List[str]) -> Dict[str, float]:
        W = self._model.coefs_[0]
        imp = np.linalg.norm(W, axis=1)
        total = imp.sum() or 1.0
        return {n: float(v / total) for n, v in zip(feature_names, imp)}


# ── Ensemble ───────────────────────────────────────────────────────────────────
class EnsemblePredictor:
    """
    Adaptive rank-average ensemble.
    Only includes models that have enough data AND performed reasonably well
    (R² > -500%). This prevents one catastrophically bad model from dominating.

    Which models are included depends on n_samples:
      < 200   → ElasticNet only
      200-600 → ElasticNet + RandomForest
      > 600   → ElasticNet + RF + NN3 (if NN3 doesn't catastrophically overfit)
    """

    name = "Ensemble (Best)"
    color = "#FFB800"

    def __init__(self):
        self.models: Dict[str, object] = {}
        self.active_models: List[str]  = []
        self.fitted = False

    def fit(self, X: np.ndarray, y: np.ndarray) -> "EnsemblePredictor":
        n = len(X)

        # Build candidate set based on dataset size
        candidates: Dict[str, object] = {"enet": ElasticNetPredictor()}
        if n >= MIN_BARS_RF:
            candidates["rf"] = RandomForestPredictor()
        if n >= MIN_BARS_NN:
            try:
                candidates["nn3"] = NNPredictor(n_samples=n)
            except ValueError:
                pass  # NN not suitable for this dataset size

        # Train all candidates; keep only those with valid OOS R²
        # Use a quick 80/20 split to evaluate each before full fit
        split = max(MIN_BARS_ENET, int(n * 0.80))
        X_tr, y_tr = X[:split], y[:split]
        X_val, y_val = X[split:], y[split:]

        self.models = {}
        for name, m in candidates.items():
            try:
                m.fit(X_tr, y_tr)
                if len(X_val) > 5:
                    y_pred_val = m.predict(X_val)
                    ss_res = np.sum((y_val - y_pred_val) ** 2)
                    ss_tot = np.sum(y_val ** 2) or 1e-9
                    r2_quick = 1 - ss_res / ss_tot
                    # Exclude catastrophically overfitting models
                    if r2_quick < -500.0:
                        continue
                self.models[name] = m
            except Exception:
                pass

        # Ensure at least ElasticNet is always included
        if not self.models:
            fallback = ElasticNetPredictor()
            fallback.fit(X, y)
            self.models["enet"] = fallback

        # Final fit on ALL data
        for m in self.models.values():
            m.fit(X, y)

        self.active_models = list(self.models.keys())
        self.fitted = True
        return self

    def predict(self, X: np.ndarray) -> np.ndarray:
        import pandas as pd
        preds = {k: pd.Series(m.predict(X)) for k, m in self.models.items()}
        # Rank-average across active models
        ranks = np.stack([s.rank(pct=True).values for s in preds.values()], axis=1)
        return ranks.mean(axis=1) - 0.5   # centre on zero

    def predict_individual(self, X: np.ndarray) -> Dict[str, np.ndarray]:
        return {k: m.predict(X) for k, m in self.models.items()}

    def feature_importance(self, feature_names: List[str]) -> Dict[str, float]:
        # Average importance across all active non-NN models
        imps = []
        for k, m in self.models.items():
            if k != "nn3":
                imps.append(m.feature_importance(feature_names))
        if not imps:
            return {n: 1.0 / len(feature_names) for n in feature_names}
        return {n: float(np.mean([d.get(n, 0) for d in imps])) for n in feature_names}


def make_model(model_type: str, n_samples: int = 2000) -> object:
    """Factory — creates model appropriate for the dataset size."""
    if model_type == "elastic_net":
        return ElasticNetPredictor()
    elif model_type == "random_forest":
        return RandomForestPredictor()
    elif model_type == "neural_net":
        return NNPredictor(n_samples=n_samples)
    elif model_type == "ensemble":
        return EnsemblePredictor()
    raise ValueError(f"Unknown model type: {model_type!r}")
