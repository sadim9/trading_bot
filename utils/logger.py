"""
utils/logger.py — Structured trade and signal logger.
Writes to CSV (trades) and JSON (signals) for downstream analytics.

Windows fix: all file handles opened with encoding="utf-8" to avoid
cp932/cp1252 codec errors on systems with non-UTF-8 default locales.
Emoji characters are stripped from the CSV reasoning column (preserved
in JSON where encoding is always UTF-8 by spec).
"""

import csv
import json
import logging
import os
import re
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional


# ── Emoji stripping for CSV ───────────────────────────────────────────────────
def _strip_emoji(text: str) -> str:
    """
    Remove emoji and non-BMP characters that cause codec errors on
    Windows systems whose default encoding is cp932/cp1252.
    Standard ASCII and Latin-1 characters are kept intact.
    """
    if not isinstance(text, str):
        return str(text)
    emoji_re = re.compile(
        "["
        "\U0001F300-\U0001F9FF"
        "\U00002702-\U000027B0"
        "\U000024C2-\U0001F251"
        "\U0001F004-\U0001F0CF"
        "\U0001F170-\U0001F17F"
        "\U0001F18E"
        "\U0001F1E0-\U0001F1FF"
        "\u2640-\u2642"
        "\u2600-\u2B55"
        "\u23cf\u23e9\u231a\ufe0f\u3030\u200d"
        "]+",
        flags=re.UNICODE,
    )
    cleaned = emoji_re.sub("", text)
    # Final safety: replace anything still un-encodable as ASCII
    return cleaned.encode("ascii", errors="replace").decode("ascii")


def _sanitise_for_csv(record: Dict[str, Any]) -> Dict[str, Any]:
    """Return a copy of record with all strings safe for ASCII CSV output."""
    return {k: (_strip_emoji(v) if isinstance(v, str) else v) for k, v in record.items()}


# ── Logger factory ────────────────────────────────────────────────────────────
def setup_logger(name: str, log_dir: str = "logs", level: str = "INFO") -> logging.Logger:
    """Create a module-level logger with UTF-8 file + console handlers."""
    Path(log_dir).mkdir(parents=True, exist_ok=True)
    logger = logging.getLogger(name)
    logger.setLevel(getattr(logging, level.upper(), logging.INFO))

    if not logger.handlers:
        fmt = logging.Formatter(
            "%(asctime)s | %(name)-22s | %(levelname)-8s | %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S",
        )

        # Console — reconfigure to UTF-8 where possible (Python 3.7+)
        ch = logging.StreamHandler()
        ch.setFormatter(fmt)
        try:
            if hasattr(ch.stream, "reconfigure"):
                ch.stream.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass
        logger.addHandler(ch)

        # File — always UTF-8 explicitly
        fh = logging.FileHandler(
            os.path.join(log_dir, "bot.log"), encoding="utf-8"
        )
        fh.setFormatter(fmt)
        logger.addHandler(fh)

    return logger


# ── Trade / signal logger ─────────────────────────────────────────────────────
class TradeLogger:
    """Persists every signal recommendation to CSV (Excel-safe) and JSON."""

    SIGNAL_COLS = [
        "timestamp", "symbol", "signal", "score", "confidence_pct",
        "trend_score", "momentum_score", "reversion_score", "ai_score",
        "entry_price", "stop_loss", "take_profit", "reasoning",
    ]

    def __init__(
        self,
        trade_log: str = "logs/trades.csv",
        signal_log: str = "logs/signals.json",
    ):
        self.trade_log  = trade_log
        self.signal_log = signal_log
        Path("logs").mkdir(parents=True, exist_ok=True)
        self._init_csv()

    def _init_csv(self):
        """Write CSV header if the file does not exist yet."""
        if not os.path.exists(self.trade_log):
            # utf-8-sig = UTF-8 with BOM so Excel opens it correctly on Windows
            with open(self.trade_log, "w", newline="", encoding="utf-8-sig") as f:
                writer = csv.DictWriter(f, fieldnames=self.SIGNAL_COLS)
                writer.writeheader()

    def log_signal(self, record: Dict[str, Any]):
        """
        Append one signal record.

        CSV  — emoji stripped, utf-8-sig encoding (Excel-safe on Windows)
        JSON — full Unicode preserved, utf-8 encoding
        """
        record = dict(record)
        record.setdefault("timestamp", datetime.utcnow().isoformat())

        # CSV — sanitised for Windows code-page safety
        with open(self.trade_log, "a", newline="", encoding="utf-8-sig") as f:
            writer = csv.DictWriter(
                f, fieldnames=self.SIGNAL_COLS, extrasaction="ignore"
            )
            writer.writerow(_sanitise_for_csv(record))

        # JSON — full Unicode, no stripping
        with open(self.signal_log, "a", encoding="utf-8") as f:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")

    def read_signals(self) -> List[Dict[str, Any]]:
        """Return all logged signals from the JSON log (full Unicode)."""
        signals = []
        if os.path.exists(self.signal_log):
            with open(self.signal_log, encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if line:
                        try:
                            signals.append(json.loads(line))
                        except json.JSONDecodeError:
                            pass
        return signals

    def read_trades_csv(self) -> List[Dict[str, Any]]:
        """Return all rows from the CSV trade log as a list of dicts."""
        rows = []
        if os.path.exists(self.trade_log):
            with open(self.trade_log, encoding="utf-8-sig") as f:
                for row in csv.DictReader(f):
                    rows.append(dict(row))
        return rows
