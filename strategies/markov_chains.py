"""
strategies/markov_chains.py — Markov Chains Strategy

Implements the mathematical framework described in the Markov Chains Strategy PDF:

  "There's a mathematical framework behind every single trade — one that has been
   in academic literature since the 1950s.  It's called Markov Chains."

Core algorithm (both conditions must hold simultaneously — eq. 2.2 AND 2.3):

  Δ(w) = p̂(w) − q(w)  ≥  ε          (eq. 2.2 — arbitrage gap)
  p(j*, j*)             ≥  τ = 0.87   (eq. 2.3 — state persistence)

Where:
  j*      = argmax P[current_state]    optimal next state
  p̂       = P[current_state][j*]       model probability
  q       = market-implied position    normalized price in recent range [0,1]
  τ       = 0.87                       persistence threshold (diagonal of P)
  ε       = 0.05                       minimum arbitrage gap

State discretization:
  • Price RETURNS (not levels) are binned into N quantile-based states
  • States 0 … N-1 are ordered: most-bearish return → most-bullish return
  • Current state = which quantile bin the latest return falls in

Score mapping:
  • Both conditions met → full score (magnitude ∈ [0,1])
  • Partial (only direction, not threshold) → 30% score
  • Sign = +1 if j* ≥ N/2 (bullish), −1 if j* < N/2 (bearish)
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from strategies.base import BaseStrategy, StrategyResult, score_to_signal


class MarkovChainsStrategy(BaseStrategy):
    """
    Markov Chains market-state model.

    Builds a transition matrix P from historical price return states,
    then fires an entry signal when the state persistence and arbitrage
    gap conditions from the PDF are both satisfied.
    """

    def __init__(
        self,
        n_states: int   = 8,     # number of discrete price states
        tau:      float = 0.87,  # persistence threshold τ — eq.(2.3)
        eps:      float = 0.05,  # arbitrage gap threshold ε — eq.(2.2)
        lookback: int   = 200,   # bars used to build the transition matrix
        warmup:   int   = 40,    # minimum bars needed before scoring
    ):
        super().__init__("markov_chains")
        self.n_states = max(2, n_states)
        self.tau      = tau
        self.eps      = eps
        self.lookback = lookback
        self.warmup   = warmup

    # ─────────────────────────────────────────────────────────────────────────
    #  Public API
    # ─────────────────────────────────────────────────────────────────────────
    def score(self, df: pd.DataFrame) -> StrategyResult:
        """
        Analyse recent OHLCV data using the Markov Chains framework.

        Returns a StrategyResult with:
          score    ∈ [-1, +1]
          signal   = BUY | SELL | HOLD
          sub_scores containing the full transition-matrix diagnostics
        """
        reasons: list[str] = []

        if len(df) < self.warmup:
            return StrategyResult(
                score=0.0, signal="HOLD",
                reasons=[f"Insufficient data ({len(df)} bars, need {self.warmup})"],
                strategy_name=self.name,
                sub_scores={},
            )

        # ── Step 1: compute 1-period returns ─────────────────────────────────
        close   = df["Close"].values.astype(float)
        returns = np.diff(close) / np.maximum(close[:-1], 1e-12)

        # Use the most-recent `lookback` returns for the transition matrix
        hist    = returns[-self.lookback:] if len(returns) >= self.lookback else returns

        if len(hist) < 8:
            return StrategyResult(
                score=0.0, signal="HOLD",
                reasons=["Too few returns for Markov model"],
                strategy_name=self.name,
                sub_scores={},
            )

        # ── Step 2: define state boundaries via quantile bins ─────────────────
        # States 0..N-1 ordered by return magnitude (0 = most bearish)
        bins      = np.quantile(hist, np.linspace(0.0, 1.0, self.n_states + 1))
        bins[0]   = -np.inf
        bins[-1]  =  np.inf
        # Remove duplicate bin edges (can happen in flat/illiquid markets)
        bins      = np.unique(bins)
        n_eff     = len(bins) - 1   # effective state count after dedup

        state_seq = np.clip(
            np.digitize(hist, bins[1:-1]),
            0, n_eff - 1,
        )

        # ── Step 3: build transition matrix P ────────────────────────────────
        P = self._build_transition_matrix(state_seq, n_eff)

        # ── Step 4: identify current state ───────────────────────────────────
        current_return = float(returns[-1]) if len(returns) > 0 else 0.0
        current_state  = int(np.clip(np.digitize(current_return, bins[1:-1]), 0, n_eff - 1))

        # ── Step 5: apply entry filter — eq.(2.2) and eq.(2.3) ───────────────
        row     = P[current_state]           # probability row for current state
        j_star  = int(np.argmax(row))        # optimal predicted next state
        p_hat   = float(row[j_star])         # model probability = p̂(w)
        persist = float(P[j_star, j_star])   # diagonal — state persistence

        # Market-implied probability q(w) = normalised price position in
        # a recent window (proxies the crowd's certainty about the next move)
        window    = min(50, len(close))
        lo, hi    = np.min(close[-window:]), np.max(close[-window:])
        market_q  = float((close[-1] - lo) / (hi - lo)) if hi > lo else 0.5

        gap       = p_hat - market_q          # arbitrage gap Δ(w) — eq.(2.2)

        # Both conditions from the PDF must hold simultaneously
        cond_gap     = gap     >= self.eps
        cond_persist = persist >= self.tau
        entry_ok     = cond_gap and cond_persist

        # ── Step 6: determine direction ──────────────────────────────────────
        # States are ordered bearish → bullish, so upper half = bullish signal
        mid_state  = n_eff / 2.0
        is_bullish = j_star >= mid_state
        is_bearish = not is_bullish

        # ── Step 7: compute output score ─────────────────────────────────────
        # Magnitude components:
        #   persist_factor: how far persist exceeds τ, clamped to [0,1]
        #   gap_factor:     how far gap exceeds ε, clamped to [0,1]
        persist_room   = 1.0 - self.tau
        persist_factor = float(np.clip((persist - self.tau) / max(persist_room, 1e-6), 0, 1))
        gap_room       = 0.3   # 30-pt gap = full score
        gap_factor     = float(np.clip((gap - self.eps) / max(gap_room, 1e-6), 0, 1))

        if entry_ok:
            magnitude = 0.50 * persist_factor + 0.50 * gap_factor
            magnitude = max(0.25, magnitude)   # floor: at least modest conviction
        else:
            # Partial signal — directional hint but conditions not fully met
            magnitude = 0.0

        raw_score  = magnitude if is_bullish else -magnitude
        raw_score  = float(np.clip(raw_score, -1.0, 1.0))
        signal     = score_to_signal(raw_score)

        # ── Step 8: build human-readable reasoning ────────────────────────────
        state_dir = "BULLISH" if current_return >= 0 else "BEARISH"
        reasons.append(
            f"State {current_state}/{n_eff-1} "
            f"({state_dir} return {current_return*100:+.3f}%)"
        )
        reasons.append(
            f"j*={j_star} ({'upper-half bullish' if is_bullish else 'lower-half bearish'})"
        )
        reasons.append(
            f"p̂={p_hat:.4f}  q={market_q:.4f}  "
            f"gap={gap:+.4f} {'≥' if cond_gap else '<'} ε={self.eps} "
            f"{'✓' if cond_gap else '✗'}"
        )
        reasons.append(
            f"Persist p({j_star},{j_star})={persist:.4f} "
            f"{'≥' if cond_persist else '<'} τ={self.tau} "
            f"{'✓' if cond_persist else '✗'}"
        )
        if entry_ok:
            reasons.append(
                f"BOTH CONDITIONS MET → "
                f"{'LONG ▲' if is_bullish else 'SHORT ▼'} "
                f"(score {raw_score:+.3f})"
            )
        else:
            blocked = []
            if not cond_gap:     blocked.append(f"gap {gap:+.4f} < ε {self.eps}")
            if not cond_persist: blocked.append(f"persist {persist:.4f} < τ {self.tau}")
            reasons.append(f"Entry blocked: {' | '.join(blocked)}")

        diag_mean = float(np.mean(np.diag(P)))
        reasons.append(
            f"Matrix: {n_eff}×{n_eff} states · "
            f"diag mean={diag_mean:.4f} · "
            f"lookback={len(hist)} bars"
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
                "p_hat":          round(p_hat,   4),
                "market_q":       round(market_q, 4),
                "gap":            round(gap,      4),
                "persist":        round(persist,  4),
                "entry_ok":       int(entry_ok),
                "is_bullish":     int(is_bullish),
                "diag_mean":      round(diag_mean, 4),
                "cond_gap":       int(cond_gap),
                "cond_persist":   int(cond_persist),
                "transition_matrix": P.tolist(),  # for heatmap visualisation
            },
        )

    def get_transition_matrix(
        self, df: pd.DataFrame
    ) -> tuple:
        """
        Return (P, current_state, n_states) for external visualisation.
        Returns (None, 0, 0) if insufficient data.
        """
        if len(df) < self.warmup:
            return None, 0, 0

        close   = df["Close"].values.astype(float)
        returns = np.diff(close) / np.maximum(close[:-1], 1e-12)
        hist    = returns[-self.lookback:] if len(returns) >= self.lookback else returns

        bins    = np.quantile(hist, np.linspace(0.0, 1.0, self.n_states + 1))
        bins[0] = -np.inf;  bins[-1] = np.inf
        bins    = np.unique(bins)
        n_eff   = len(bins) - 1

        state_seq     = np.clip(np.digitize(hist, bins[1:-1]), 0, n_eff - 1)
        P             = self._build_transition_matrix(state_seq, n_eff)
        current_ret   = float(returns[-1]) if len(returns) > 0 else 0.0
        current_state = int(np.clip(np.digitize(current_ret, bins[1:-1]), 0, n_eff - 1))
        return P, current_state, n_eff

    # ─────────────────────────────────────────────────────────────────────────
    #  Internal helpers
    # ─────────────────────────────────────────────────────────────────────────
    def _build_transition_matrix(
        self, states: np.ndarray, n: int
    ) -> np.ndarray:
        """
        Maximum-likelihood estimate of the N×N transition matrix.

        P[i, j] = count(i→j) / sum_j count(i→j)

        Laplace smoothing (pseudocount = 0.5) prevents zero rows and
        avoids degenerate probabilities on sparse data.
        """
        # Laplace prior: 0.5 pseudo-observations per cell
        P = np.full((n, n), 0.5)

        for t in range(len(states) - 1):
            i = int(np.clip(states[t],     0, n - 1))
            j = int(np.clip(states[t + 1], 0, n - 1))
            P[i, j] += 1.0

        # Row-normalise
        row_sums = P.sum(axis=1, keepdims=True)
        P        = P / np.maximum(row_sums, 1e-12)
        return P
