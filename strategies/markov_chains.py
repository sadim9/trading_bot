"""
strategies/markov_chains.py -- Enhanced Markov Chains Strategy

CORE MODEL (both conditions must hold simultaneously):
  Delta(w) = p_hat(w) - q(w)  >= eps     (eq. 2.2 -- arbitrage gap)
  p(j*, j*)                   >= tau=0.87 (eq. 2.3 -- state persistence)

ENHANCEMENTS:
  1. Market Regime Detection via stationary distribution pi
     pi = lim P^k row -- long-run probability of being in each state
     BULL: pi(upper half) > regime_bull_thresh
     BEAR: pi(lower half) > regime_bear_thresh
     SIDEWAYS: neither met -> dampen signal

  2. N-Step Ahead Forecasting
     Compute P^n for n steps ahead
     Blend 1-step and n-step probability vectors for smoother conviction

  3. Stationary Distribution Edge
     pi_edge = pi[j*] - 1/N  (over-representation of optimal next state)
     Boosts conviction when j* is structurally over-represented

  4. Regime-Adjusted Signal Scaling
     Regime-aligned -> full score
     Sideways       -> 60% score
     Counter-regime -> 30% score
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from strategies.base import BaseStrategy, StrategyResult, score_to_signal


# ---------------------------------------------------------------------------
#  Module-level helpers
# ---------------------------------------------------------------------------

def _stationary_distribution(P, max_iter=500):
    """Power-iteration stationary distribution of row-stochastic matrix P."""
    n  = P.shape[0]
    pi = np.ones(n) / n
    for _ in range(max_iter):
        pi_new = pi @ P
        if np.max(np.abs(pi_new - pi)) < 1e-8:
            return pi_new
        pi = pi_new
    return pi


def _matrix_power(P, n):
    """Efficient matrix power via repeated squaring."""
    result = np.eye(P.shape[0])
    base   = P.copy()
    while n > 0:
        if n % 2 == 1:
            result = result @ base
        base = base @ base
        n  //= 2
    return result


# ---------------------------------------------------------------------------
#  Strategy class
# ---------------------------------------------------------------------------

class MarkovChainsStrategy(BaseStrategy):
    """
    Enhanced Markov Chains market-state model.

    Builds transition matrix P from historical price return states, then:
      1. Checks core entry conditions (persistence tau + arbitrage gap eps)
      2. Detects market regime via stationary distribution pi
      3. Computes n-step ahead probabilities for smoother conviction
      4. Scales signal strength by regime alignment
    """

    def __init__(
        self,
        n_states=8,
        tau=0.87,
        eps=0.05,
        lookback=200,
        warmup=40,
        n_step=3,
        n_step_weight=0.35,
        regime_bull_thresh=0.55,
        regime_bear_thresh=0.55,
    ):
        super().__init__("markov_chains")
        self.n_states           = max(2, n_states)
        self.tau                = tau
        self.eps                = eps
        self.lookback           = lookback
        self.warmup             = warmup
        self.n_step             = max(2, n_step)
        self.n_step_weight      = float(np.clip(n_step_weight, 0.0, 1.0))
        self.regime_bull_thresh = regime_bull_thresh
        self.regime_bear_thresh = regime_bear_thresh

    # -----------------------------------------------------------------------
    #  Public API
    # -----------------------------------------------------------------------

    def score(self, df):
        """Full Markov Chains analysis. Returns StrategyResult with score in [-1, +1]."""
        reasons = []

        if len(df) < self.warmup:
            return StrategyResult(
                score=0.0, signal="HOLD",
                reasons=[f"Insufficient data ({len(df)} bars, need {self.warmup})"],
                strategy_name=self.name, sub_scores={},
            )

        # Step 1: returns + state sequence
        close   = df["Close"].values.astype(float)
        returns = np.diff(close) / np.maximum(close[:-1], 1e-12)
        hist    = returns[-self.lookback:] if len(returns) >= self.lookback else returns

        if len(hist) < 8:
            return StrategyResult(
                score=0.0, signal="HOLD",
                reasons=["Too few returns for Markov model"],
                strategy_name=self.name, sub_scores={},
            )

        # Step 2: quantile bins -> state sequence
        bins    = np.quantile(hist, np.linspace(0.0, 1.0, self.n_states + 1))
        bins[0] = -np.inf
        bins[-1] = np.inf
        bins    = np.unique(bins)
        n_eff   = len(bins) - 1
        state_seq = np.clip(np.digitize(hist, bins[1:-1]), 0, n_eff - 1)

        # Step 3: transition matrix P
        P = self._build_transition_matrix(state_seq, n_eff)

        # Step 4: stationary distribution + regime
        pi      = _stationary_distribution(P)
        mid     = n_eff // 2
        pi_bull = float(pi[mid:].sum())
        pi_bear = float(pi[:mid].sum())

        if pi_bull >= self.regime_bull_thresh:
            regime = "BULL"
        elif pi_bear >= self.regime_bear_thresh:
            regime = "BEAR"
        else:
            regime = "SIDEWAYS"

        reasons.append(
            f"Regime: {regime}  (pi_bull={pi_bull:.3f}  pi_bear={pi_bear:.3f})"
        )

        # Step 5: current state
        current_return = float(returns[-1]) if len(returns) > 0 else 0.0
        current_state  = int(np.clip(np.digitize(current_return, bins[1:-1]), 0, n_eff - 1))
        state_dir = "BULLISH" if current_return >= 0 else "BEARISH"
        reasons.append(
            f"State {current_state}/{n_eff-1} ({state_dir} return {current_return*100:+.3f}%)"
        )

        # Step 6: 1-step core conditions (eq. 2.2 + 2.3)
        row_1     = P[current_state]
        j_star_1  = int(np.argmax(row_1))
        p_hat_1   = float(row_1[j_star_1])
        persist_1 = float(P[j_star_1, j_star_1])

        window   = min(50, len(close))
        lo, hi   = np.min(close[-window:]), np.max(close[-window:])
        market_q = float((close[-1] - lo) / (hi - lo)) if hi > lo else 0.5

        gap_1     = p_hat_1 - market_q
        cond_gap  = gap_1     >= self.eps
        cond_pers = persist_1 >= self.tau
        entry_ok  = cond_gap and cond_pers

        reasons.append(
            f"1-step: j*={j_star_1}  p_hat={p_hat_1:.4f}  q={market_q:.4f}  "
            f"gap={gap_1:+.4f} {'OK' if cond_gap else 'FAIL'} eps={self.eps}  "
            f"persist={persist_1:.4f} {'OK' if cond_pers else 'FAIL'} tau={self.tau}"
        )

        # Step 7: n-step ahead forecast
        Pn       = _matrix_power(P, self.n_step)
        row_n    = Pn[current_state]
        j_star_n = int(np.argmax(row_n))
        p_hat_n  = float(row_n[j_star_n])

        w1        = 1.0 - self.n_step_weight
        wn        = self.n_step_weight
        row_blend = w1 * row_1 + wn * row_n
        j_star    = int(np.argmax(row_blend))
        p_hat     = float(row_blend[j_star])

        reasons.append(
            f"{self.n_step}-step: j*={j_star_n}  p_hat_n={p_hat_n:.4f}  "
            f"blend j*={j_star}  p_hat_blend={p_hat:.4f}"
        )

        # Step 8: stationary distribution edge
        pi_edge = float(pi[j_star]) - 1.0 / n_eff
        reasons.append(
            f"pi-edge: pi[{j_star}]={pi[j_star]:.4f}  "
            f"uniform=1/{n_eff}={1/n_eff:.4f}  edge={pi_edge:+.4f}"
        )

        # Step 9: direction from blended j*
        mid_state  = n_eff / 2.0
        is_bullish = j_star >= mid_state
        regime_aligned = (
            (is_bullish and regime == "BULL") or
            (not is_bullish and regime == "BEAR")
        )

        # Step 10: compute output score
        if not entry_ok:
            blocked = []
            if not cond_gap:  blocked.append(f"gap {gap_1:+.4f} < eps {self.eps}")
            if not cond_pers: blocked.append(f"persist {persist_1:.4f} < tau {self.tau}")
            reasons.append(f"Entry blocked: {' | '.join(blocked)}")
            raw_score = 0.0
        else:
            persist_room   = max(1.0 - self.tau, 1e-6)
            persist_factor = float(np.clip((persist_1 - self.tau) / persist_room, 0, 1))
            gap_room       = 0.30
            gap_factor     = float(np.clip((gap_1 - self.eps) / gap_room, 0, 1))

            nstep_agree  = 1.0 if j_star_n == j_star_1 else 0.5
            nstep_boost  = self.n_step_weight * nstep_agree * p_hat_n

            pi_boost     = float(np.clip(pi_edge * 2.0, 0.0, 0.20))

            magnitude = (
                0.40 * persist_factor +
                0.40 * gap_factor     +
                0.10 * nstep_boost    +
                0.10 * pi_boost
            )
            magnitude = max(0.25, float(np.clip(magnitude, 0.0, 1.0)))

            if regime_aligned:
                regime_scale = 1.00
                regime_note  = "regime ALIGNED (full score)"
            elif regime == "SIDEWAYS":
                regime_scale = 0.60
                regime_note  = "regime SIDEWAYS (60%)"
            else:
                regime_scale = 0.30
                regime_note  = "regime CONTRA (30%)"

            magnitude *= regime_scale
            reasons.append(
                f"BOTH CONDITIONS MET -> {'LONG' if is_bullish else 'SHORT'}  "
                f"{regime_note}  magnitude={magnitude:.3f}"
            )
            raw_score = magnitude if is_bullish else -magnitude

        raw_score = float(np.clip(raw_score, -1.0, 1.0))
        signal    = score_to_signal(raw_score)

        diag_mean = float(np.mean(np.diag(P)))
        reasons.append(
            f"Matrix: {n_eff}x{n_eff}  diag_mean={diag_mean:.4f}  lookback={len(hist)} bars"
        )

        return StrategyResult(
            score=raw_score,
            signal=signal,
            reasons=reasons,
            strategy_name=self.name,
            sub_scores={
                "current_state":  int(current_state),
                "n_states":       int(n_eff),
                "j_star":         int(j_star),
                "j_star_1step":   int(j_star_1),
                "j_star_nstep":   int(j_star_n),
                "p_hat":          round(p_hat,    4),
                "p_hat_1step":    round(p_hat_1,  4),
                "p_hat_nstep":    round(p_hat_n,  4),
                "market_q":       round(market_q, 4),
                "gap":            round(gap_1,    4),
                "persist":        round(persist_1, 4),
                "entry_ok":       int(entry_ok),
                "is_bullish":     int(is_bullish),
                "cond_gap":       int(cond_gap),
                "cond_persist":   int(cond_pers),
                "regime":         regime,
                "pi_bull":        round(pi_bull, 4),
                "pi_bear":        round(pi_bear, 4),
                "pi_edge":        round(pi_edge, 4),
                "regime_aligned": int(regime_aligned),
                "diag_mean":      round(diag_mean, 4),
                "transition_matrix":       P.tolist(),
                "stationary_distribution": pi.tolist(),
            },
        )

    def get_transition_matrix(self, df):
        """Return (P, current_state, n_states, stationary_dist) for visualisation."""
        if len(df) < self.warmup:
            return None, 0, 0, np.array([])

        close   = df["Close"].values.astype(float)
        returns = np.diff(close) / np.maximum(close[:-1], 1e-12)
        hist    = returns[-self.lookback:] if len(returns) >= self.lookback else returns

        bins    = np.quantile(hist, np.linspace(0.0, 1.0, self.n_states + 1))
        bins[0] = -np.inf
        bins[-1] = np.inf
        bins    = np.unique(bins)
        n_eff   = len(bins) - 1

        state_seq     = np.clip(np.digitize(hist, bins[1:-1]), 0, n_eff - 1)
        P             = self._build_transition_matrix(state_seq, n_eff)
        pi            = _stationary_distribution(P)
        current_ret   = float(returns[-1]) if len(returns) > 0 else 0.0
        current_state = int(np.clip(np.digitize(current_ret, bins[1:-1]), 0, n_eff - 1))
        return P, current_state, n_eff, pi

    # -----------------------------------------------------------------------
    #  Internal helpers
    # -----------------------------------------------------------------------

    def _build_transition_matrix(self, states, n):
        """MLE N x N transition matrix with Laplace(0.5) smoothing."""
        P = np.full((n, n), 0.5)
        for t in range(len(states) - 1):
            i = int(np.clip(states[t],     0, n - 1))
            j = int(np.clip(states[t + 1], 0, n - 1))
            P[i, j] += 1.0
        row_sums = P.sum(axis=1, keepdims=True)
        P        = P / np.maximum(row_sums, 1e-12)
        return P
