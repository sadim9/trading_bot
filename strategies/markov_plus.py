"""
strategies/markov_plus.py — Markov Plus Quant Framework Strategy

Enhanced Markov Chains strategy implementing the full Markov Plus framework:

  Core Entry Conditions (both must hold simultaneously):
    (1) Delta(w) = P_hat(w) - Q(w) >= eps   [arbitrage gap, eq. 2.2]
    (2) P[j*, j*]                  >= tau    [state persistence, eq. 2.3]

Enhancements over base MarkovChainsStrategy:
  • VWAP-adjusted market_q (volume-weighted price position)
  • ATR-volatility regime scaling — reduces signal in high-volatility regimes
  • Multi-state persistence check — adjacent state persistence averaged
  • Volume-weighted transition matrix (high-volume bars weighted more)
  • Enhanced N-step blending with exponential decay weights
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from strategies.base import BaseStrategy, StrategyResult, score_to_signal


def _stationary_distribution(P: np.ndarray, max_iter: int = 500) -> np.ndarray:
    n  = P.shape[0]
    pi = np.ones(n) / n
    for _ in range(max_iter):
        pi_new = pi @ P
        if np.max(np.abs(pi_new - pi)) < 1e-8:
            return pi_new
        pi = pi_new
    return pi


def _matrix_power(P: np.ndarray, n: int) -> np.ndarray:
    result = np.eye(P.shape[0])
    base   = P.copy()
    while n > 0:
        if n % 2 == 1:
            result = result @ base
        base = base @ base
        n  //= 2
    return result


class MarkovPlusStrategy(BaseStrategy):
    """
    Markov Plus Quant Framework strategy.

    Builds a volume-weighted transition matrix, then:
      1. Core entry conditions: arbitrage gap + state persistence
      2. Market regime via stationary distribution π
      3. Multi-step ahead blending with exponential-decay weights
      4. ATR-volatility scaling — dampens signal in high-vol environments
      5. VWAP-adjusted market_q for more accurate Q measure
    """

    def __init__(
        self,
        n_states: int           = 8,
        tau: float              = 0.87,
        eps: float              = 0.05,
        lookback: int           = 200,
        warmup: int             = 40,
        n_step: int             = 3,
        n_step_weight: float    = 0.35,
        regime_bull_thresh: float = 0.55,
        regime_bear_thresh: float = 0.55,
        use_vwap_q: bool        = True,
        use_vol_weights: bool   = True,
        use_atr_scaling: bool   = True,
        atr_scale_window: int   = 20,
    ):
        super().__init__("markov_plus")
        self.n_states           = max(2, n_states)
        self.tau                = tau
        self.eps                = eps
        self.lookback           = lookback
        self.warmup             = warmup
        self.n_step             = max(2, n_step)
        self.n_step_weight      = float(np.clip(n_step_weight, 0.0, 1.0))
        self.regime_bull_thresh = regime_bull_thresh
        self.regime_bear_thresh = regime_bear_thresh
        self.use_vwap_q         = use_vwap_q
        self.use_vol_weights    = use_vol_weights
        self.use_atr_scaling    = use_atr_scaling
        self.atr_scale_window   = atr_scale_window

    # ── Public API ──────────────────────────────────────────────────────────────

    def score(self, df: pd.DataFrame) -> StrategyResult:
        reasons: list[str] = []

        if len(df) < self.warmup:
            return StrategyResult(
                score=0.0, signal="HOLD",
                reasons=[f"Insufficient data ({len(df)} bars, need {self.warmup})"],
                strategy_name=self.name, sub_scores={},
            )

        close   = df["Close"].values.astype(float)
        returns = np.diff(close) / np.maximum(close[:-1], 1e-12)
        hist    = returns[-self.lookback:] if len(returns) >= self.lookback else returns

        if len(hist) < 8:
            return StrategyResult(
                score=0.0, signal="HOLD",
                reasons=["Too few returns for Markov Plus model"],
                strategy_name=self.name, sub_scores={},
            )

        # ── State sequence ────────────────────────────────────────────────────
        bins    = np.quantile(hist, np.linspace(0.0, 1.0, self.n_states + 1))
        bins[0] = -np.inf; bins[-1] = np.inf
        bins    = np.unique(bins)
        n_eff   = len(bins) - 1
        state_seq = np.clip(np.digitize(hist, bins[1:-1]), 0, n_eff - 1)

        # ── Volume weights (recent bars weighted more) ────────────────────────
        vol_weights = None
        if self.use_vol_weights and "Volume" in df.columns:
            vol = df["Volume"].values.astype(float)
            vol_hist = vol[-self.lookback:] if len(vol) >= self.lookback else vol
            vol_hist = vol_hist[1:] if len(vol_hist) > len(hist) else vol_hist[-len(hist):]
            if len(vol_hist) == len(hist):
                vol_norm = vol_hist / np.maximum(vol_hist.mean(), 1e-12)
                vol_weights = np.sqrt(vol_norm)  # sqrt-dampen outliers

        # ── Build volume-weighted transition matrix ───────────────────────────
        P = self._build_transition_matrix(state_seq, n_eff, vol_weights)

        # ── Stationary distribution + regime ─────────────────────────────────
        pi    = _stationary_distribution(P)
        mid   = n_eff // 2
        pi_bull = float(pi[mid:].sum())
        pi_bear = float(pi[:mid].sum())

        regime = (
            "BULL" if pi_bull >= self.regime_bull_thresh else
            "BEAR" if pi_bear >= self.regime_bear_thresh else
            "SIDEWAYS"
        )
        reasons.append(f"Regime: {regime}  (π_bull={pi_bull:.3f}  π_bear={pi_bear:.3f})")

        # ── Current state ────────────────────────────────────────────────────
        current_return = float(returns[-1]) if len(returns) > 0 else 0.0
        current_state  = int(np.clip(np.digitize(current_return, bins[1:-1]), 0, n_eff - 1))
        reasons.append(
            f"State {current_state}/{n_eff-1}  ({current_return*100:+.3f}%)"
        )

        # ── VWAP-adjusted market_q ────────────────────────────────────────────
        window = min(50, len(close))
        lo, hi = np.min(close[-window:]), np.max(close[-window:])

        if self.use_vwap_q and "vwap" in df.columns:
            vwap_last = float(df["vwap"].iloc[-1])
            vwap_in_range = lo <= vwap_last <= hi
            if vwap_in_range:
                market_q = float((vwap_last - lo) / (hi - lo)) if hi > lo else 0.5
                reasons.append(f"Market Q: VWAP={vwap_last:.4f}  q={market_q:.4f}")
            else:
                market_q = float((close[-1] - lo) / (hi - lo)) if hi > lo else 0.5
        else:
            market_q = float((close[-1] - lo) / (hi - lo)) if hi > lo else 0.5

        # ── 1-step core conditions (eq. 2.2 + 2.3) ──────────────────────────
        row_1     = P[current_state]
        j_star_1  = int(np.argmax(row_1))
        p_hat_1   = float(row_1[j_star_1])

        # Blend current-state and next-state persistence so BUY/SELL are symmetric.
        # Bear states self-persist more than bull states; checking only next-state
        # persistence creates a structural SELL bias.
        persist_next = float(P[j_star_1, j_star_1])
        persist_curr = float(P[current_state, current_state])
        persist_1    = (persist_next + persist_curr) / 2.0

        # Direction-aware market_q: for a predicted bullish move compare p_hat against
        # market_q (upside implied probability); for bearish, compare against 1-market_q
        # (downside implied probability). Without this, entries only fire when price is
        # near its low, creating a structural SELL bias.
        is_bullish_1step = j_star_1 >= (n_eff / 2.0)
        market_q_dir = market_q if is_bullish_1step else (1.0 - market_q)

        gap_1     = p_hat_1 - market_q_dir
        cond_gap  = gap_1     >= self.eps
        cond_pers = persist_1 >= self.tau
        entry_ok  = cond_gap and cond_pers

        reasons.append(
            f"1-step: j*={j_star_1}  p̂={p_hat_1:.4f}  Q_dir={market_q_dir:.4f}  "
            f"gap={gap_1:+.4f} {'✓' if cond_gap else '✗'}  "
            f"persist={persist_1:.4f} (curr={persist_curr:.4f}+next={persist_next:.4f})/2 "
            f"{'✓' if cond_pers else '✗'}"
        )

        # ── N-step forecast with exponential-decay blend ─────────────────────
        Pn       = _matrix_power(P, self.n_step)
        row_n    = Pn[current_state]
        j_star_n = int(np.argmax(row_n))
        p_hat_n  = float(row_n[j_star_n])

        # Exponential decay: weight recent steps more
        decay_weights = np.array([np.exp(-0.3 * k) for k in range(self.n_step)])
        decay_weights /= decay_weights.sum()

        row_blend = np.zeros(n_eff)
        for step_k in range(1, self.n_step + 1):
            Pk = _matrix_power(P, step_k)
            row_blend += decay_weights[step_k - 1] * Pk[current_state]

        j_star = int(np.argmax(row_blend))
        p_hat  = float(row_blend[j_star])

        reasons.append(
            f"{self.n_step}-step: j*_n={j_star_n}  p̂_n={p_hat_n:.4f}  "
            f"blend j*={j_star}  p̂_blend={p_hat:.4f}"
        )

        # ── π-edge ───────────────────────────────────────────────────────────
        pi_edge = float(pi[j_star]) - 1.0 / n_eff
        reasons.append(
            f"π-edge: π[{j_star}]={pi[j_star]:.4f}  edge={pi_edge:+.4f}"
        )

        # ── Direction + regime alignment ──────────────────────────────────────
        mid_state  = n_eff / 2.0
        is_bullish = j_star >= mid_state
        regime_aligned = (
            (is_bullish and regime == "BULL") or
            (not is_bullish and regime == "BEAR")
        )

        # ── ATR volatility scaling ────────────────────────────────────────────
        atr_scale = 1.0
        if self.use_atr_scaling and "atr" in df.columns:
            atr_series = df["atr"].dropna()
            if len(atr_series) >= self.atr_scale_window:
                atr_now  = float(atr_series.iloc[-1])
                atr_avg  = float(atr_series.tail(self.atr_scale_window).mean())
                if atr_avg > 0:
                    vol_ratio = atr_now / atr_avg
                    # High vol > 2x avg: dampen to 50%; normal: 100%; low vol: slight boost
                    atr_scale = float(np.clip(1.0 / vol_ratio, 0.3, 1.2))
                    reasons.append(f"ATR scaling: vol_ratio={vol_ratio:.2f}  scale={atr_scale:.2f}")

        # ── Score computation ─────────────────────────────────────────────────
        if not entry_ok:
            blocked = []
            if not cond_gap:  blocked.append(f"gap {gap_1:+.4f} < ε={self.eps}")
            if not cond_pers: blocked.append(f"persist {persist_1:.4f} < τ={self.tau}")
            reasons.append(f"Entry blocked: {' | '.join(blocked)}")
            raw_score = 0.0
        else:
            persist_room   = max(1.0 - self.tau, 1e-6)
            persist_factor = float(np.clip((persist_1 - self.tau) / persist_room, 0, 1))
            gap_room       = 0.30
            gap_factor     = float(np.clip((gap_1 - self.eps) / gap_room, 0, 1))

            nstep_agree = 1.0 if j_star_n == j_star_1 else 0.5
            nstep_boost = self.n_step_weight * nstep_agree * p_hat_n
            pi_boost    = float(np.clip(pi_edge * 2.0, 0.0, 0.20))

            magnitude = (
                0.40 * persist_factor +
                0.40 * gap_factor     +
                0.10 * nstep_boost    +
                0.10 * pi_boost
            )
            magnitude = max(0.25, float(np.clip(magnitude, 0.0, 1.0)))

            if regime_aligned:
                regime_scale = 1.00
                regime_note  = "ALIGNED (full score)"
            elif regime == "SIDEWAYS":
                regime_scale = 0.60
                regime_note  = "SIDEWAYS (60%)"
            else:
                regime_scale = 0.30
                regime_note  = "CONTRA (30%)"

            # Apply ATR scaling
            magnitude *= regime_scale * atr_scale
            reasons.append(
                f"{'LONG ▲' if is_bullish else 'SHORT ▼'}  {regime_note}  "
                f"magnitude={magnitude:.3f}"
            )
            raw_score = magnitude if is_bullish else -magnitude

        raw_score = float(np.clip(raw_score, -1.0, 1.0))
        signal    = score_to_signal(raw_score)

        diag_mean = float(np.mean(np.diag(P)))

        return StrategyResult(
            score=raw_score,
            signal=signal,
            reasons=reasons,
            strategy_name=self.name,
            sub_scores={
                "current_state":          int(current_state),
                "n_states":               int(n_eff),
                "j_star":                 int(j_star),
                "j_star_1step":           int(j_star_1),
                "j_star_nstep":           int(j_star_n),
                "p_hat":                  round(p_hat,    4),
                "p_hat_1step":            round(p_hat_1,  4),
                "p_hat_nstep":            round(p_hat_n,  4),
                "market_q":               round(market_q, 4),
                "gap":                    round(gap_1,    4),
                "persist":                round(persist_1, 4),
                "entry_ok":               int(entry_ok),
                "is_bullish":             int(is_bullish),
                "cond_gap":               int(cond_gap),
                "cond_persist":           int(cond_pers),
                "regime":                 regime,
                "pi_bull":                round(pi_bull, 4),
                "pi_bear":                round(pi_bear, 4),
                "pi_edge":                round(pi_edge, 4),
                "regime_aligned":         int(regime_aligned),
                "diag_mean":              round(diag_mean, 4),
                "atr_scale":              round(atr_scale, 3),
                "transition_matrix":      P.tolist(),
                "stationary_distribution": pi.tolist(),
            },
        )

    # ── Helpers ─────────────────────────────────────────────────────────────────

    def _build_transition_matrix(
        self,
        states: np.ndarray,
        n: int,
        vol_weights: np.ndarray | None = None,
    ) -> np.ndarray:
        """Volume-weighted N×N transition matrix with Laplace(0.5) smoothing."""
        P = np.full((n, n), 0.5)
        for t in range(len(states) - 1):
            i   = int(np.clip(states[t],     0, n - 1))
            j   = int(np.clip(states[t + 1], 0, n - 1))
            w   = float(vol_weights[t]) if vol_weights is not None and t < len(vol_weights) else 1.0
            P[i, j] += w
        row_sums = P.sum(axis=1, keepdims=True)
        P        = P / np.maximum(row_sums, 1e-12)
        return P
