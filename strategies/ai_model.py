"""
strategies/ai_model.py — AI / ML Strategy Layer (Weight: 20%)

Model: Gradient Boosting Classifier (sklearn)
Task:  Predict probability that next-bar return > 0 (binary classification)

Features (engineered from OHLCV + technical indicators):
  - RSI, MACD, MACD histogram, BB%, EMA cross signal
  - Rolling returns (1d, 5d, 20d), volatility
  - Volume ratio
  - Lagged versions of all features (configurable lookback)

Training:
  - Trained on the first N% of data (train_size)
  - Walk-forward split — future data never leaks into training
  - Calibrated probabilities via CalibratedClassifierCV

Score:
  prob_up → mapped to [-1, +1] score  (0.5 → 0, 1.0 → +1, 0.0 → -1)
"""

import warnings
from typing import List, Optional, Tuple

import numpy as np
import pandas as pd

warnings.filterwarnings("ignore")

try:
    from sklearn.calibration import CalibratedClassifierCV
    from sklearn.ensemble import GradientBoostingClassifier, RandomForestClassifier
    from sklearn.metrics import accuracy_score, roc_auc_score
    from sklearn.preprocessing import StandardScaler
    SKLEARN_AVAILABLE = True
except ImportError:
    SKLEARN_AVAILABLE = False

from strategies.base import BaseStrategy, StrategyResult, score_to_signal


# ─── FEATURE ENGINEERING ──────────────────────────────────────────────────────
FEATURE_COLS = [
    "rsi", "macd", "macd_signal", "macd_hist",
    "bb_pct", "ema_cross",
    "returns_1d", "returns_5d", "returns_20d",
    "volatility", "vol_ratio",
    "price_vs_ema_fast", "price_vs_ema_slow",
]


def build_feature_matrix(df: pd.DataFrame, lags: int = 3) -> pd.DataFrame:
    """
    Build feature matrix including lagged versions of each indicator.
    Returns a clean DataFrame with no NaN rows.
    """
    feats = df[FEATURE_COLS].copy()
    for lag in range(1, lags + 1):
        lagged = df[FEATURE_COLS].shift(lag)
        lagged.columns = [f"{c}_lag{lag}" for c in FEATURE_COLS]
        feats = pd.concat([feats, lagged], axis=1)

    # Target: will next bar's close be higher?
    feats["target"] = (df["Close"].shift(-1) > df["Close"]).astype(int)
    feats.dropna(inplace=True)
    return feats


class AIModelStrategy(BaseStrategy):
    """Gradient Boosting price-direction classifier."""

    def __init__(
        self,
        train_size: float = 0.75,
        n_estimators: int = 200,
        lags: int = 3,
        model_type: str = "gradient_boosting",
    ):
        super().__init__("AI Model (Gradient Boosting)")
        self.train_size   = train_size
        self.n_estimators = n_estimators
        self.lags         = lags
        self.model_type   = model_type

        self._model   = None
        self._scaler  = StandardScaler() if SKLEARN_AVAILABLE else None
        self._is_fit  = False
        self._metrics = {}
        self._feature_names: List[str] = []
        self._importances: dict = {}

    # ── Public API ─────────────────────────────────────────────────────────
    def fit(self, df: pd.DataFrame) -> dict:
        """Train the model on the training portion of df. Returns eval metrics."""
        if not SKLEARN_AVAILABLE:
            raise ImportError("scikit-learn not installed. Run: pip install scikit-learn")

        feat_df = build_feature_matrix(df, self.lags)
        self._feature_names = [c for c in feat_df.columns if c != "target"]

        X = feat_df[self._feature_names].values
        y = feat_df["target"].values

        split = int(len(X) * self.train_size)
        X_train, X_test = X[:split], X[split:]
        y_train, y_test = y[:split], y[split:]

        self._scaler.fit(X_train)
        X_train_s = self._scaler.transform(X_train)
        X_test_s  = self._scaler.transform(X_test)

        # Base model
        if self.model_type == "random_forest":
            base = RandomForestClassifier(
                n_estimators=self.n_estimators, max_depth=6,
                min_samples_leaf=10, random_state=42, n_jobs=-1
            )
        else:
            base = GradientBoostingClassifier(
                n_estimators=self.n_estimators, learning_rate=0.05,
                max_depth=4, min_samples_leaf=10, subsample=0.8,
                random_state=42
            )

        # Probability calibration for well-calibrated confidence scores
        self._model = CalibratedClassifierCV(base, cv=3, method="isotonic")
        self._model.fit(X_train_s, y_train)

        # Evaluation
        preds_test  = self._model.predict(X_test_s)
        probas_test = self._model.predict_proba(X_test_s)[:, 1]

        acc  = accuracy_score(y_test, preds_test)
        try:
            auc = roc_auc_score(y_test, probas_test)
        except Exception:
            auc = 0.5

        self._metrics = {"accuracy": round(acc, 4), "auc_roc": round(auc, 4),
                         "n_train": split, "n_test": len(X_test)}
        self._is_fit  = True

        # Feature importances (only available on gradient boosting base)
        try:
            base_est = self._model.calibrated_classifiers_[0].estimator
            importances = base_est.feature_importances_
            self._importances = dict(
                sorted(
                    zip(self._feature_names, importances),
                    key=lambda x: x[1], reverse=True
                )
            )
        except Exception:
            self._importances = {}

        return self._metrics

    def score(self, df: pd.DataFrame) -> StrategyResult:
        reasons = []

        if not SKLEARN_AVAILABLE:
            reasons.append("⚠️ scikit-learn not available — AI agent disabled")
            return StrategyResult(score=0.0, signal="HOLD",
                                  reasons=reasons, strategy_name=self.name)

        if not self._is_fit:
            # Auto-train on the full df before scoring the last bar
            self.fit(df)
            reasons.append(
                f"🤖 Model auto-trained | Accuracy: {self._metrics.get('accuracy',0):.1%}"
                f" | AUC: {self._metrics.get('auc_roc',0):.3f}"
            )

        feat_df = build_feature_matrix(df, self.lags)
        if feat_df.empty:
            reasons.append("⚠️ Insufficient data for AI features")
            return StrategyResult(score=0.0, signal="HOLD",
                                  reasons=reasons, strategy_name=self.name)

        last_row  = feat_df[self._feature_names].iloc[[-1]]
        X_scaled  = self._scaler.transform(last_row.values)
        prob_up   = float(self._model.predict_proba(X_scaled)[0, 1])
        prob_down = 1.0 - prob_up

        # Map probability to [-1, +1] score
        raw_score = (prob_up - 0.5) * 2   # 0.5→0, 1.0→+1, 0.0→-1
        signal    = score_to_signal(raw_score, buy_thresh=0.15, sell_thresh=-0.15)

        confidence = max(prob_up, prob_down) * 100

        if prob_up > 0.60:
            reasons.append(
                f"🤖 AI predicts UP with {prob_up:.1%} probability (confidence: {confidence:.0f}%)"
            )
        elif prob_up < 0.40:
            reasons.append(
                f"🤖 AI predicts DOWN with {prob_down:.1%} probability (confidence: {confidence:.0f}%)"
            )
        else:
            reasons.append(
                f"🤖 AI uncertain — P(up)={prob_up:.1%}, P(down)={prob_down:.1%}"
            )

        # Top feature influence
        if self._importances:
            top_feats = list(self._importances.items())[:3]
            feat_str  = ", ".join(f"{k}={v:.3f}" for k, v in top_feats)
            reasons.append(f"📊 Top features: {feat_str}")

        reasons.append(
            f"📈 Model metrics — Accuracy: {self._metrics.get('accuracy',0):.1%}, "
            f"AUC: {self._metrics.get('auc_roc',0):.3f}"
        )

        return StrategyResult(
            score=raw_score,
            signal=signal,
            reasons=reasons,
            strategy_name=self.name,
            sub_scores={
                "prob_up": round(prob_up, 4),
                "prob_down": round(prob_down, 4),
                "accuracy": self._metrics.get("accuracy", 0),
                "auc": self._metrics.get("auc_roc", 0),
            },
        )

    @property
    def metrics(self) -> dict:
        return self._metrics

    @property
    def feature_importances(self) -> dict:
        return self._importances
