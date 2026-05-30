"""
ml/models.py — Return-prediction model wrappers.

Implements three model classes from Kelly & Xiu (2023):
  - ElasticNetPredictor  (penalised linear, Layer 2 easiest)
  - RandomForestPredictor (tree ensemble, Layer 2 strong)
  - NNPredictor           (3-layer MLP ≈ NN3, Layer 2 best)

All expose a unified fit(X, y) / predict(X) interface and return
feature_importance() for the RF and coefficient magnitudes for ElasticNet.
"""

from __future__ import annotations

import numpy as np
import warnings
from typing import Dict, List, Optional

warnings.filterwarnings("ignore")


# ── Elastic Net ────────────────────────────────────────────────────────────────
class ElasticNetPredictor:
    """
    Penalised linear return predictor.
    L(β) = MSE + α·[(1-l1_ratio)·||β||² + l1_ratio·||β||₁]
    l1_ratio=1 → Lasso, l1_ratio=0 → Ridge, default 0.5 → Elastic Net.
    """

    name = "Elastic Net"
    color = "#4B9FFF"

    def __init__(self, alpha: float = 5e-4, l1_ratio: float = 0.5):
        from sklearn.linear_model import ElasticNet
        self._model = ElasticNet(
            alpha=alpha,
            l1_ratio=l1_ratio,
            fit_intercept=False,
            max_iter=5000,
            tol=1e-4,
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
    Random Forest return predictor.
    Shallow trees (max_depth=6) + sqrt feature sampling → regularisation.
    """

    name = "Random Forest"
    color = "#00C9A7"

    def __init__(self, n_estimators: int = 200, max_depth: int = 6):
        from sklearn.ensemble import RandomForestRegressor
        self._model = RandomForestRegressor(
            n_estimators=n_estimators,
            max_depth=max_depth,
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
    3-layer feed-forward MLP — sklearn equivalent of NN3 from Gu, Kelly, Xiu (2020).
    Architecture: input → 256 → 128 → 64 → 1
    Uses early stopping on a 15% validation split.
    """

    name = "Neural Net (NN3)"
    color = "#9B6DFF"

    def __init__(
        self,
        hidden_layer_sizes: tuple = (128, 64, 32),
        alpha: float = 1e-3,
        max_iter: int = 200,
        learning_rate_init: float = 5e-4,
    ):
        from sklearn.neural_network import MLPRegressor
        from sklearn.preprocessing import StandardScaler
        self._scaler = StandardScaler()
        self._model = MLPRegressor(
            hidden_layer_sizes=hidden_layer_sizes,
            activation="relu",
            solver="adam",
            alpha=alpha,              # stronger L2 regularisation
            batch_size="auto",
            learning_rate="adaptive",
            learning_rate_init=learning_rate_init,
            max_iter=max_iter,
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
        # Approximate via first-layer weight magnitudes (L2 norm per input neuron)
        W = self._model.coefs_[0]          # shape (n_features, n_hidden_1)
        imp = np.linalg.norm(W, axis=1)    # L2 norm across hidden neurons
        total = imp.sum() or 1.0
        return {n: float(v / total) for n, v in zip(feature_names, imp)}


# ── Ensemble ───────────────────────────────────────────────────────────────────
class EnsemblePredictor:
    """
    Equal-weight rank-average ensemble of ElasticNet + RF + NN3.
    Rank averaging is more robust to outliers than simple mean.
    """

    name = "Ensemble (EN + RF + NN3)"
    color = "#FFB800"

    def __init__(self):
        self.models: Dict[str, object] = {
            "enet": ElasticNetPredictor(),
            "rf":   RandomForestPredictor(),
            "nn3":  NNPredictor(),
        }
        self.fitted = False

    def fit(self, X: np.ndarray, y: np.ndarray) -> "EnsemblePredictor":
        for m in self.models.values():
            m.fit(X, y)
        self.fitted = True
        return self

    def predict(self, X: np.ndarray) -> np.ndarray:
        import pandas as pd
        preds = {k: pd.Series(m.predict(X)) for k, m in self.models.items()}
        # Rank-average: maps each model's predictions to [0,1] percentile ranks
        # then averages. This prevents any single model from dominating via scale.
        ranks = np.stack([s.rank(pct=True).values for s in preds.values()], axis=1)
        avg_rank = ranks.mean(axis=1)          # [0, 1]
        # Re-centre to [-0.5, 0.5] range so predictions are directionally meaningful
        return avg_rank - 0.5

    def predict_individual(self, X: np.ndarray) -> Dict[str, np.ndarray]:
        """Raw per-model predictions (unranked) for display purposes."""
        return {k: m.predict(X) for k, m in self.models.items()}

    def predict_raw(self, X: np.ndarray) -> Dict[str, np.ndarray]:
        return self.predict_individual(X)

    def feature_importance(self, feature_names: List[str]) -> Dict[str, float]:
        # Average importance across RF + EN (NN3 approx is less reliable)
        rf_imp = self.models["rf"].feature_importance(feature_names)
        en_imp = self.models["enet"].feature_importance(feature_names)
        return {n: (rf_imp.get(n, 0) + en_imp.get(n, 0)) / 2 for n in feature_names}


def make_model(model_type: str) -> object:
    """Factory function to create a model by name."""
    return {
        "elastic_net":   ElasticNetPredictor,
        "random_forest": RandomForestPredictor,
        "neural_net":    NNPredictor,
        "ensemble":      EnsemblePredictor,
    }[model_type]()
