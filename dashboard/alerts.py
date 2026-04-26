"""
dashboard/alerts.py — Multi-Channel Alert Engine

Channels:
  1. On-screen  — st.session_state queue rendered as feed + st.toast popups
  2. Email       — HTML via smtplib SMTP SSL (Gmail / Outlook)
  3. Discord     — Webhook POST with rich embed (no bot token needed)
  4. WhatsApp    — CallMeBot free API (free, no Twilio account needed)
                   Setup: send "I allow callmebot to send me messages" to
                   +34 644 69 87 99 on WhatsApp first, then use your number here.
  5. Telegram    — Bot API (optional)

Cooldown: same (symbol, signal) pair won't re-fire within COOLDOWN seconds.
"""

from __future__ import annotations

import json
import smtplib
import ssl
import time
import threading
from collections import deque
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from typing import Deque, List, Optional
from urllib.parse import quote

try:
    import requests
    REQUESTS_OK = True
except ImportError:
    REQUESTS_OK = False


# ── Discord colour constants ───────────────────────────────────────────────────
DISCORD_COLORS = {
    "BUY":      0x00E676,   # green
    "SELL":     0xFF5252,   # red
    "RSI_OB":   0xFF5252,
    "RSI_OS":   0x00E676,
    "EMA_CROSS":0x2196F3,   # blue
    "SR_BREAK": 0xFFC107,   # amber
}


# ── Data classes ──────────────────────────────────────────────────────────────
@dataclass
class Alert:
    symbol: str
    signal: str
    price: float
    reason: str
    confidence: float = 0.0
    timestamp: str = field(default_factory=lambda: datetime.now().astimezone().isoformat())
    channel: str = "screen"
    delivered: bool = False

    def to_dict(self) -> dict:
        return asdict(self)

    @property
    def emoji(self) -> str:
        return {"BUY":"🟢","SELL":"🔴","RSI_OB":"🔴","RSI_OS":"🟢",
                "EMA_CROSS":"🔔","SR_BREAK":"⚡"}.get(self.signal, "ℹ️")

    @property
    def title(self) -> str:
        return {"BUY":"BUY SIGNAL","SELL":"SELL SIGNAL","RSI_OB":"RSI OVERBOUGHT",
                "RSI_OS":"RSI OVERSOLD","EMA_CROSS":"EMA CROSSOVER",
                "SR_BREAK":"S/R BREAKOUT"}.get(self.signal, self.signal)

    @property
    def color_hex(self) -> str:
        green = {"BUY","RSI_OS"}
        return "#00E676" if self.signal in green else (
               "#2196F3" if self.signal in {"EMA_CROSS","SR_BREAK"} else "#FF5252")


@dataclass
class EmailConfig:
    sender_email: str = ""
    sender_password: str = ""
    recipient_email: str = ""
    smtp_host: str = "smtp.gmail.com"
    smtp_port: int = 465

    @property
    def enabled(self) -> bool:
        return bool(self.sender_email and self.sender_password and self.recipient_email)


@dataclass
class DiscordConfig:
    """
    Discord Webhook — no bot account needed.
    Create at: Server Settings → Integrations → Webhooks → New Webhook → Copy URL
    Paste the full URL here.
    """
    webhook_url: str = ""

    @property
    def enabled(self) -> bool:
        return bool(self.webhook_url and self.webhook_url.startswith("https://discord.com/api/webhooks/"))


@dataclass
class WhatsAppConfig:
    """
    WhatsApp via CallMeBot (free, no API key purchase needed).

    One-time setup:
      1. Add +34 644 69 87 99 to your WhatsApp contacts as "CallMeBot"
      2. Send this exact message to that number:
         "I allow callmebot to send me messages"
      3. You'll receive an apikey in reply — paste it below.

    Docs: https://www.callmebot.com/blog/free-api-whatsapp-messages/
    """
    phone: str = ""      # International format without + e.g. "447911123456"
    api_key: str = ""

    @property
    def enabled(self) -> bool:
        return bool(self.phone and self.api_key)


@dataclass
class TelegramConfig:
    bot_token: str = ""
    chat_id: str = ""

    @property
    def enabled(self) -> bool:
        return bool(self.bot_token and self.chat_id)


# ── Alert engine ───────────────────────────────────────────────────────────────
class AlertEngine:
    MAX_QUEUE = 50
    COOLDOWN  = 300    # seconds between same (symbol, signal) firing again

    def __init__(
        self,
        email_cfg:    Optional[EmailConfig]    = None,
        discord_cfg:  Optional[DiscordConfig]  = None,
        whatsapp_cfg: Optional[WhatsAppConfig] = None,
        telegram_cfg: Optional[TelegramConfig] = None,
    ):
        self.email_cfg    = email_cfg    or EmailConfig()
        self.discord_cfg  = discord_cfg  or DiscordConfig()
        self.whatsapp_cfg = whatsapp_cfg or WhatsAppConfig()
        self.telegram_cfg = telegram_cfg or TelegramConfig()
        self._queue: Deque[Alert] = deque(maxlen=self.MAX_QUEUE)
        self._last_fired: dict    = {}

    # ── Public API ────────────────────────────────────────────────────────────
    def fire(
        self,
        symbol: str,
        signal: str,
        price: float,
        reason: str,
        confidence: float = 0.0,
    ) -> Optional[Alert]:
        """Fire an alert if not within cooldown window. Returns Alert or None."""
        key = (symbol, signal)
        now = time.time()
        if key in self._last_fired and now - self._last_fired[key] < self.COOLDOWN:
            return None

        alert = Alert(symbol=symbol, signal=signal, price=price,
                      reason=reason, confidence=confidence)
        self._last_fired[key] = now
        self._queue.appendleft(alert)

        threading.Thread(target=self._dispatch, args=(alert,), daemon=True).start()
        return alert

    def check_conditions(
        self,
        symbol: str,
        df,
        rec,
        prev_signal: Optional[str] = None,
    ) -> List[Alert]:
        """Evaluate all trigger conditions. Returns list of fired alerts."""
        fired = []
        if df is None or len(df) < 2:
            return fired

        close  = float(df["Close"].iloc[-1])
        rsi    = float(df["rsi"].iloc[-1])       if "rsi"       in df.columns else 50.0
        ema_f  = float(df["ema_fast"].iloc[-1])  if "ema_fast"  in df.columns else close
        ema_s  = float(df["ema_slow"].iloc[-1])  if "ema_slow"  in df.columns else close
        ema_fp = float(df["ema_fast"].iloc[-2])  if len(df) > 1 else ema_f
        ema_sp = float(df["ema_slow"].iloc[-2])  if len(df) > 1 else ema_s

        # BUY / SELL from strategy
        if rec and rec.signal in ("BUY","SELL") and rec.signal != prev_signal:
            a = self.fire(symbol, rec.signal, close,
                          f"Score {rec.composite_score:+.3f} | Conf {rec.confidence_pct:.0f}%",
                          rec.confidence_pct)
            if a:
                fired.append(a)

        # RSI extremes
        if rsi >= 70:
            a = self.fire(symbol, "RSI_OB", close, f"RSI = {rsi:.1f} (overbought > 70)")
            if a: fired.append(a)
        elif rsi <= 30:
            a = self.fire(symbol, "RSI_OS", close, f"RSI = {rsi:.1f} (oversold < 30)")
            if a: fired.append(a)

        # EMA crossover
        if ema_f > ema_s and ema_fp <= ema_sp:
            a = self.fire(symbol, "EMA_CROSS", close, "Golden Cross: EMA50 crossed above EMA200")
            if a: fired.append(a)
        elif ema_f < ema_s and ema_fp >= ema_sp:
            a = self.fire(symbol, "EMA_CROSS", close, "Death Cross: EMA50 crossed below EMA200")
            if a: fired.append(a)

        # S/R breakout
        if "breakout_up" in df.columns and int(df["breakout_up"].iloc[-1]) == 1:
            rh = float(df["roll_high"].iloc[-2]) if "roll_high" in df.columns else close
            a  = self.fire(symbol, "SR_BREAK", close, f"Bullish breakout above resistance {rh:.4f}")
            if a: fired.append(a)
        elif "breakout_dn" in df.columns and int(df["breakout_dn"].iloc[-1]) == 1:
            rl = float(df["roll_low"].iloc[-2]) if "roll_low" in df.columns else close
            a  = self.fire(symbol, "SR_BREAK", close, f"Bearish breakdown below support {rl:.4f}")
            if a: fired.append(a)

        return fired

    def test_channel(self, channel: str) -> tuple[bool, str]:
        """
        Send a test message to a specific channel.
        Returns (success: bool, message: str).
        """
        test = Alert(symbol="TEST", signal="BUY", price=100.0,
                     reason="Test alert from Trading Bot", confidence=99.0)
        try:
            if channel == "discord":
                self._send_discord(test)
            elif channel == "whatsapp":
                self._send_whatsapp(test)
            elif channel == "email":
                self._send_email(test)
            elif channel == "telegram":
                self._send_telegram(test)
            return True, f"{channel.title()} test sent successfully!"
        except Exception as e:
            return False, f"{channel.title()} error: {e}"

    @property
    def queue(self) -> List[Alert]:
        return list(self._queue)

    def clear(self):
        self._queue.clear()

    @property
    def active_channels(self) -> List[str]:
        channels = ["screen"]
        if self.email_cfg.enabled:    channels.append("email")
        if self.discord_cfg.enabled:  channels.append("discord")
        if self.whatsapp_cfg.enabled: channels.append("whatsapp")
        if self.telegram_cfg.enabled: channels.append("telegram")
        return channels

    # ── Dispatch ──────────────────────────────────────────────────────────────
    def _dispatch(self, alert: Alert):
        if self.email_cfg.enabled:
            try:
                self._send_email(alert)
            except Exception as e:
                print(f"[Alert:email] {e}")
        if self.discord_cfg.enabled:
            try:
                self._send_discord(alert)
            except Exception as e:
                print(f"[Alert:discord] {e}")
        if self.whatsapp_cfg.enabled:
            try:
                self._send_whatsapp(alert)
            except Exception as e:
                print(f"[Alert:whatsapp] {e}")
        if self.telegram_cfg.enabled:
            try:
                self._send_telegram(alert)
            except Exception as e:
                print(f"[Alert:telegram] {e}")

    # ── Email ─────────────────────────────────────────────────────────────────
    def _send_email(self, a: Alert):
        msg = MIMEMultipart("alternative")
        msg["Subject"] = f"[TradingBot] {a.title} — {a.symbol} @ {a.price:.4f}"
        msg["From"]    = self.email_cfg.sender_email
        msg["To"]      = self.email_cfg.recipient_email
        html = f"""
        <html><body style="background:#131722;color:#D1D4DC;font-family:monospace;padding:24px">
          <div style="border:1px solid {a.color_hex};border-radius:8px;padding:20px;max-width:480px">
            <h2 style="color:{a.color_hex};margin:0 0 16px">{a.emoji} {a.title}</h2>
            <table style="width:100%;border-collapse:collapse;font-size:13px">
              <tr><td style="color:#787B86;padding:4px 0">Symbol</td>
                  <td style="text-align:right"><b>{a.symbol}</b></td></tr>
              <tr><td style="color:#787B86;padding:4px 0">Price</td>
                  <td style="color:{a.color_hex};text-align:right"><b>{a.price:.4f}</b></td></tr>
              <tr><td style="color:#787B86;padding:4px 0">Confidence</td>
                  <td style="text-align:right">{a.confidence:.1f}%</td></tr>
              <tr><td style="color:#787B86;padding:4px 0">Time (UTC)</td>
                  <td style="color:#787B86;text-align:right">{a.timestamp[:19]}</td></tr>
              <tr><td colspan="2" style="padding-top:12px;border-top:1px solid #2A2E39;
                      color:#D1D4DC;font-size:12px">{a.reason}</td></tr>
            </table>
          </div>
          <p style="color:#787B86;font-size:10px;margin-top:12px">
            Analysis only — no real trades executed by this system.
          </p>
        </body></html>"""
        msg.attach(MIMEText(html, "html"))
        ctx = ssl.create_default_context()
        with smtplib.SMTP_SSL(self.email_cfg.smtp_host, self.email_cfg.smtp_port, context=ctx) as s:
            s.login(self.email_cfg.sender_email, self.email_cfg.sender_password)
            s.sendmail(self.email_cfg.sender_email, self.email_cfg.recipient_email, msg.as_string())

    # ── Discord Webhook ───────────────────────────────────────────────────────
    def _send_discord(self, a: Alert):
        """
        Rich embed POST to a Discord webhook.
        No bot account needed — just a webhook URL from Server Settings.
        """
        if not REQUESTS_OK:
            raise ImportError("pip install requests")
        color_int = DISCORD_COLORS.get(a.signal, 0x787B86)
        payload = {
            "username": "Trading Bot",
            "avatar_url": "https://cdn-icons-png.flaticon.com/512/2721/2721297.png",
            "embeds": [{
                "title":       f"{a.emoji}  {a.title}",
                "color":       color_int,
                "description": a.reason,
                "fields": [
                    {"name": "Symbol",     "value": f"`{a.symbol}`",           "inline": True},
                    {"name": "Price",      "value": f"`{a.price:.4f}`",         "inline": True},
                    {"name": "Confidence", "value": f"`{a.confidence:.1f}%`",   "inline": True},
                ],
                "footer": {"text": f"Trading Bot Pro  •  {a.timestamp[:19]} UTC"},
                "timestamp": a.timestamp,
            }]
        }
        resp = requests.post(self.discord_cfg.webhook_url, json=payload, timeout=8)
        resp.raise_for_status()

    # ── WhatsApp (CallMeBot) ──────────────────────────────────────────────────
    def _send_whatsapp(self, a: Alert):
        """
        Send WhatsApp message via CallMeBot free API.

        One-time setup required per phone number:
          1. Add +34 644 69 87 99 to contacts as 'CallMeBot'
          2. Send: "I allow callmebot to send me messages"
          3. You'll receive your apikey via WhatsApp
          4. Enter phone (international, no +) and apikey in dashboard settings
        """
        if not REQUESTS_OK:
            raise ImportError("pip install requests")
        text = (
            f"{a.emoji} *{a.title}* — {a.symbol}\n"
            f"Price: {a.price:.4f}\n"
            f"Confidence: {a.confidence:.1f}%\n"
            f"{a.reason}\n"
            f"_{a.timestamp[:19]} UTC_"
        )
        # Validate phone is all digits (prevent injection in URL params)
        phone_clean = "".join(c for c in self.whatsapp_cfg.phone if c.isdigit())
        if not phone_clean or len(phone_clean) < 7:
            raise ValueError(f"Invalid WhatsApp phone number: {self.whatsapp_cfg.phone!r}")
        # Validate api_key is alphanumeric
        if not self.whatsapp_cfg.api_key.isalnum():
            raise ValueError("WhatsApp api_key must be alphanumeric")
        # URL is fixed to callmebot.com — not user-supplied (no SSRF)
        url = (
            f"https://api.callmebot.com/whatsapp.php"
            f"?phone={phone_clean}"
            f"&text={quote(text)}"
            f"&apikey={self.whatsapp_cfg.api_key}"
        )
        resp = requests.get(url, timeout=10)
        if resp.status_code != 200:
            raise RuntimeError(f"CallMeBot HTTP {resp.status_code}: {resp.text[:200]}")

    # ── Telegram ──────────────────────────────────────────────────────────────
    def _send_telegram(self, a: Alert):
        if not REQUESTS_OK:
            raise ImportError("pip install requests")
        text = (
            f"{a.emoji} *{a.title}* — `{a.symbol}`\n"
            f"Price: `{a.price:.4f}`\n"
            f"Confidence: `{a.confidence:.1f}%`\n"
            f"{a.reason}"
        )
        # Validate bot_token format (digits:alphanumeric) to prevent injection
        token = self.telegram_cfg.bot_token
        if ":" not in token or not token.split(":")[0].isdigit():
            raise ValueError("Telegram bot token format invalid")
        # chat_id must be numeric (can be negative for groups)
        try:
            int(self.telegram_cfg.chat_id)
        except (ValueError, TypeError):
            raise ValueError(f"Telegram chat_id must be numeric, got: {self.telegram_cfg.chat_id!r}")
        # URL is fixed to api.telegram.org — not user-supplied
        url  = f"https://api.telegram.org/bot{token}/sendMessage"
        resp = requests.post(url, json={"chat_id": self.telegram_cfg.chat_id,
                                        "text": text, "parse_mode": "Markdown"}, timeout=8)
        resp.raise_for_status()
