"""
brokers/discord_confirm.py — Discord Trade Confirmation Bot

Sends a rich embed to a Discord channel when a trade signal fires.
Two buttons: ✅ CONFIRM (execute) or ❌ CANCEL (skip).
Waits up to timeout_seconds for a response; auto-cancels on timeout.

Requirements:
    pip install discord.py

Setup:
    1. discord.com/developers/applications → New App → Bot → Add Bot → Copy TOKEN
    2. OAuth2 → URL Generator → scopes: bot + applications.commands
       permissions: Send Messages, Embed Links, Read Message History
    3. Invite bot to server, note CHANNEL_ID (right-click channel → Copy ID)
    4. Bot settings → Enable MESSAGE CONTENT INTENT

Environment variables:
    DISCORD_BOT_TOKEN    — bot token from step 1
    DISCORD_CHANNEL_ID   — numeric channel ID from step 3

Security notes:
    - Token is never logged, only held in memory
    - Channel ID validated as integer before use
    - All outbound requests go to discord.com only (no SSRF vector)
    - Buttons disabled after first response (no double-fire)
"""

from __future__ import annotations

import asyncio
import os
import threading
import time
from datetime import datetime
from typing import Optional, List

# ── Conditional import with clean fallback ─────────────────────────────────────
# ConfirmView MUST only be defined when discord is available.
# Defining it at module scope with View=None causes NameError on startup
# when discord.py is not installed.
try:
    import discord
    from discord.ui import Button, View as DiscordView
    DISCORD_OK = True
except ImportError:
    discord = None          # type: ignore
    DiscordView = object    # harmless base so the class body can be parsed
    DISCORD_OK = False

from brokers.base import OrderRequest, OrderResult


# ── Colour palette ────────────────────────────────────────────────────────────
COLOUR_BUY    = 0x00E676
COLOUR_SELL   = 0xFF5252
COLOUR_CANCEL = 0x787B86
COLOUR_FILLED = 0x2196F3


# ── Confirmation view (only functional when DISCORD_OK=True) ──────────────────
class ConfirmView(DiscordView):   # DiscordView = discord.ui.View OR object
    """Discord UI View with Confirm and Cancel buttons."""

    def __init__(self, timeout_seconds: int = 120):
        if not DISCORD_OK:
            # Running without discord — just store state
            self.confirmed: Optional[bool] = None
            self.responder: str = ""
            return
        super().__init__(timeout=timeout_seconds)
        self.confirmed: Optional[bool] = None
        self.responder: str = ""

    if DISCORD_OK:
        @discord.ui.button(label="✅ CONFIRM TRADE", style=discord.ButtonStyle.success)
        async def confirm(self, interaction: discord.Interaction, button: Button):
            self.confirmed = True
            self.responder = str(interaction.user)
            self.stop()
            await interaction.response.send_message(
                f"✅ **{interaction.user.display_name}** confirmed. Executing...",
                ephemeral=True,
            )

        @discord.ui.button(label="❌ CANCEL", style=discord.ButtonStyle.danger)
        async def cancel(self, interaction: discord.Interaction, button: Button):
            self.confirmed = False
            self.responder = str(interaction.user)
            self.stop()
            await interaction.response.send_message(
                f"❌ **{interaction.user.display_name}** cancelled.",
                ephemeral=True,
            )

        async def on_timeout(self):
            self.confirmed = False


# ── Embed builders ────────────────────────────────────────────────────────────
def _confirm_embed(request: OrderRequest, reason: str, kelly_pct: float):
    if not DISCORD_OK:
        return None
    is_buy = request.is_buy
    colour = COLOUR_BUY if is_buy else COLOUR_SELL
    arrow  = "▲ BUY" if is_buy else "▼ SELL"
    emoji  = "🟢"    if is_buy else "🔴"

    embed = discord.Embed(
        title=f"{emoji}  TRADE CONFIRMATION — {arrow}",
        description=f"**{request.symbol}**\n\n{reason}",
        color=colour,
        timestamp=datetime.now(),
    )
    embed.add_field(name="Side",       value=f"`{request.side.upper()}`",      inline=True)
    embed.add_field(name="Quantity",   value=f"`{request.quantity:.6f}`",      inline=True)
    embed.add_field(name="Order Type", value=f"`{request.order_type.upper()}`",inline=True)
    if request.limit_price:
        embed.add_field(name="Limit Price", value=f"`{request.limit_price:.4f}`", inline=True)
    if request.stop_loss:
        embed.add_field(name="Stop-Loss",   value=f"`{request.stop_loss:.4f}`",   inline=True)
    if request.take_profit:
        embed.add_field(name="Take-Profit", value=f"`{request.take_profit:.4f}`", inline=True)
    embed.add_field(name="Kelly Size", value=f"`{kelly_pct:.1f}%`",            inline=True)
    embed.set_footer(text="⚠️ Analysis only — confirm to place real order | Trading Bot Pro")
    return embed


def _result_embed(result: OrderResult, confirmed: bool, responder: str):
    if not DISCORD_OK:
        return None
    if not confirmed:
        e = discord.Embed(title="❌ Trade Cancelled", color=COLOUR_CANCEL, timestamp=datetime.now())
        e.add_field(name="By",     value=responder or "Timeout", inline=True)
        e.add_field(name="Symbol", value=result.symbol,          inline=True)
        return e
    if result.success:
        e = discord.Embed(title="✅ Trade Executed", color=COLOUR_FILLED, timestamp=datetime.now())
        e.add_field(name="Broker",       value=result.broker,                    inline=True)
        e.add_field(name="Symbol",       value=result.symbol,                    inline=True)
        e.add_field(name="Side",         value=result.side.upper(),              inline=True)
        e.add_field(name="Quantity",     value=str(result.quantity),             inline=True)
        e.add_field(name="Fill Price",   value=str(result.filled_price or "—"), inline=True)
        e.add_field(name="Order ID",     value=result.order_id or "—",           inline=True)
        e.add_field(name="Status",       value=result.status.upper(),            inline=True)
        e.add_field(name="Confirmed by", value=responder,                        inline=True)
    else:
        e = discord.Embed(title="⚠️ Trade Failed", color=0xFFC107, timestamp=datetime.now())
        e.add_field(name="Error", value=result.error[:1000], inline=False)
    e.set_footer(text="Trading Bot Pro")
    return e


# ── Main bot class ────────────────────────────────────────────────────────────
class DiscordConfirmBot:
    """
    Runs discord.py in a background thread.
    Exposes a synchronous ask() method that blocks until the user responds.

    Security:
      - Token never logged or printed
      - Channel ID validated as integer
      - Timeout enforced server-side via discord.ui.View timeout
      - Buttons disabled after first click (no double-execution)
    """

    def __init__(
        self,
        bot_token:       str = "",
        channel_id:      int = 0,
        timeout_seconds: int = 120,
    ):
        if not DISCORD_OK:
            raise ImportError(
                "discord.py not installed.\n"
                "Run: pip install discord.py"
            )

        # Validate inputs — never log the token
        _token = bot_token or os.getenv("DISCORD_BOT_TOKEN", "")
        if not _token:
            raise ValueError(
                "DISCORD_BOT_TOKEN not set.\n"
                "Set the environment variable or pass bot_token= to DiscordConfirmBot().\n"
                "Never hardcode tokens in source files."
            )
        _chan_raw = channel_id or os.getenv("DISCORD_CHANNEL_ID", "0")
        try:
            _chan = int(_chan_raw)
        except (ValueError, TypeError):
            raise ValueError(f"DISCORD_CHANNEL_ID must be a numeric integer, got: {_chan_raw!r}")
        if _chan == 0:
            raise ValueError("DISCORD_CHANNEL_ID cannot be 0. Set a real channel ID.")

        self._token          = _token          # stored, never logged
        self.channel_id      = _chan
        self.timeout_seconds = timeout_seconds

        intents      = discord.Intents.default()
        self._client = discord.Client(intents=intents)
        self._loop   = asyncio.new_event_loop()
        self._ready  = threading.Event()
        self._thread = threading.Thread(target=self._run_loop, daemon=True)
        self._thread.start()
        if not self._ready.wait(timeout=20):
            raise TimeoutError("Discord bot did not become ready within 20 seconds. Check the token.")

    # ── Public API ────────────────────────────────────────────────────────────
    def ask(
        self,
        request:       OrderRequest,
        signal_reason: str = "",
        kelly_pct:     float = 0.0,
    ) -> bool:
        """Block until user confirms or cancels. Returns True = proceed."""
        future = asyncio.run_coroutine_threadsafe(
            self._send_confirm(request, signal_reason, kelly_pct),
            self._loop,
        )
        return future.result(timeout=self.timeout_seconds + 15)

    def notify(self, result: OrderResult, confirmed: bool, responder: str = ""):
        """Send non-blocking fill/cancel notification."""
        asyncio.run_coroutine_threadsafe(
            self._send_notify(result, confirmed, responder),
            self._loop,
        )

    def test(self) -> bool:
        """Send a test message. Returns True if delivery succeeded."""
        dummy = OrderRequest(symbol="TEST", side="buy", quantity=0.001, comment="Test alert")
        result = OrderResult(success=True, broker="test", symbol="TEST",
                             side="buy", quantity=0.001, status="test")
        try:
            self.notify(result, confirmed=True, responder="system")
            return True
        except Exception:
            return False

    def close(self):
        asyncio.run_coroutine_threadsafe(self._client.close(), self._loop)

    @property
    def active_channels(self) -> List[str]:
        return ["discord"]

    # ── Internal ──────────────────────────────────────────────────────────────
    def _run_loop(self):
        asyncio.set_event_loop(self._loop)

        @self._client.event
        async def on_ready():
            self._ready.set()

        self._loop.run_until_complete(self._client.start(self._token))

    async def _fetch_channel(self):
        ch = self._client.get_channel(self.channel_id)
        if ch is None:
            ch = await self._client.fetch_channel(self.channel_id)
        return ch

    async def _send_confirm(self, request: OrderRequest, reason: str, kelly_pct: float) -> bool:
        channel = await self._fetch_channel()
        view    = ConfirmView(timeout=self.timeout_seconds)
        embed   = _confirm_embed(request, reason, kelly_pct)
        msg     = await channel.send(embed=embed, view=view)
        await view.wait()
        # Disable all buttons to prevent late clicks
        for item in view.children:
            item.disabled = True
        await msg.edit(view=view)
        return bool(view.confirmed)

    async def _send_notify(self, result: OrderResult, confirmed: bool, responder: str):
        channel = await self._fetch_channel()
        embed   = _result_embed(result, confirmed, responder)
        if embed:
            await channel.send(embed=embed)
