"""Initial database schema

Revision ID: 001
Revises:
Create Date: 2026-04-25
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID

revision = "001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ── users ──────────────────────────────────────────────────
    op.create_table("users",
        sa.Column("id",                    UUID(as_uuid=False), primary_key=True),
        sa.Column("email",                 sa.String(255),  nullable=False),
        sa.Column("username",              sa.String(100),  nullable=False),
        sa.Column("password_hash",         sa.String(255),  nullable=False),
        sa.Column("role",                  sa.String(20),   nullable=False, server_default="trader"),
        sa.Column("is_active",             sa.Boolean(),    nullable=False, server_default="true"),
        sa.Column("is_verified",           sa.Boolean(),    nullable=False, server_default="false"),
        sa.Column("created_at",            sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at",            sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_login",            sa.DateTime(timezone=True), nullable=True),
        sa.Column("failed_login_attempts", sa.Integer(),    nullable=False, server_default="0"),
        sa.Column("locked_until",          sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_users_email",    "users", ["email"],    unique=True)
    op.create_index("ix_users_username", "users", ["username"], unique=True)

    # ── api_keys ───────────────────────────────────────────────
    op.create_table("api_keys",
        sa.Column("id",          UUID(as_uuid=False), primary_key=True),
        sa.Column("user_id",     UUID(as_uuid=False), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("name",        sa.String(100), nullable=False),
        sa.Column("key_prefix",  sa.String(12),  nullable=False),
        sa.Column("key_hash",    sa.String(255), nullable=False, unique=True),
        sa.Column("scopes",      sa.JSON(),      nullable=False),
        sa.Column("is_active",   sa.Boolean(),   nullable=False, server_default="true"),
        sa.Column("last_used",   sa.DateTime(timezone=True), nullable=True),
        sa.Column("expires_at",  sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at",  sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_api_keys_user_id", "api_keys", ["user_id"])

    # ── signals ────────────────────────────────────────────────
    op.create_table("signals",
        sa.Column("id",                    UUID(as_uuid=False), primary_key=True),
        sa.Column("user_id",               UUID(as_uuid=False), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=True),
        sa.Column("symbol",                sa.String(30),  nullable=False),
        sa.Column("signal_type",           sa.String(10),  nullable=False),
        sa.Column("composite_score",       sa.Float(),     nullable=False),
        sa.Column("entry_price",           sa.Float(),     nullable=True),
        sa.Column("stop_loss",             sa.Float(),     nullable=True),
        sa.Column("take_profit",           sa.Float(),     nullable=True),
        sa.Column("position_size_pct",     sa.Float(),     nullable=True),
        sa.Column("trend_score",           sa.Float(),     nullable=True),
        sa.Column("momentum_score",        sa.Float(),     nullable=True),
        sa.Column("mean_reversion_score",  sa.Float(),     nullable=True),
        sa.Column("ai_model_score",        sa.Float(),     nullable=True),
        sa.Column("markov_score",          sa.Float(),     nullable=True),
        sa.Column("strategy_breakdown",    sa.JSON(),      nullable=True),
        sa.Column("risk_check_passed",     sa.Boolean(),   nullable=True),
        sa.Column("risk_reasons",          sa.JSON(),      nullable=True),
        sa.Column("data_source",           sa.String(50),  nullable=True),
        sa.Column("interval",              sa.String(10),  nullable=True),
        sa.Column("created_at",            sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_signals_user_id",      "signals", ["user_id"])
    op.create_index("ix_signals_symbol",       "signals", ["symbol"])
    op.create_index("ix_signals_created_at",   "signals", ["created_at"])
    op.create_index("ix_signals_user_created", "signals", ["user_id", "created_at"])

    # ── trades ─────────────────────────────────────────────────
    op.create_table("trades",
        sa.Column("id",                  UUID(as_uuid=False), primary_key=True),
        sa.Column("user_id",             UUID(as_uuid=False), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("signal_id",           UUID(as_uuid=False), sa.ForeignKey("signals.id"), nullable=True),
        sa.Column("symbol",              sa.String(30),   nullable=False),
        sa.Column("side",                sa.String(10),   nullable=False),
        sa.Column("order_type",          sa.String(20),   nullable=False, server_default="market"),
        sa.Column("quantity",            sa.Float(),      nullable=False),
        sa.Column("entry_price",         sa.Float(),      nullable=False),
        sa.Column("exit_price",          sa.Float(),      nullable=True),
        sa.Column("stop_loss",           sa.Float(),      nullable=True),
        sa.Column("take_profit",         sa.Float(),      nullable=True),
        sa.Column("limit_price",         sa.Float(),      nullable=True),
        sa.Column("status",              sa.String(20),   nullable=False, server_default="pending"),
        sa.Column("pnl",                 sa.Float(),      nullable=True),
        sa.Column("pnl_pct",             sa.Float(),      nullable=True),
        sa.Column("commission",          sa.Float(),      nullable=True),
        sa.Column("slippage",            sa.Float(),      nullable=True),
        sa.Column("strategy",            sa.String(50),   nullable=True),
        sa.Column("broker",              sa.String(50),   nullable=True),
        sa.Column("broker_order_id",     sa.String(100),  nullable=True),
        sa.Column("is_paper",            sa.Boolean(),    nullable=False, server_default="true"),
        sa.Column("discord_message_id",  sa.String(100),  nullable=True),
        sa.Column("discord_confirmed",   sa.Boolean(),    nullable=True),
        sa.Column("confirmed_by",        sa.String(100),  nullable=True),
        sa.Column("notes",               sa.Text(),       nullable=True),
        sa.Column("metadata",            sa.JSON(),       nullable=True),
        sa.Column("opened_at",           sa.DateTime(timezone=True), nullable=False),
        sa.Column("closed_at",           sa.DateTime(timezone=True), nullable=True),
        sa.Column("updated_at",          sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_trades_user_id",      "trades", ["user_id"])
    op.create_index("ix_trades_symbol",       "trades", ["symbol"])
    op.create_index("ix_trades_status",       "trades", ["status"])
    op.create_index("ix_trades_opened_at",    "trades", ["opened_at"])
    op.create_index("ix_trades_user_symbol",  "trades", ["user_id", "symbol"])

    # ── positions ──────────────────────────────────────────────
    op.create_table("positions",
        sa.Column("id",                  UUID(as_uuid=False), primary_key=True),
        sa.Column("user_id",             UUID(as_uuid=False), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("trade_id",            UUID(as_uuid=False), sa.ForeignKey("trades.id"), nullable=True),
        sa.Column("symbol",              sa.String(30),  nullable=False),
        sa.Column("side",                sa.String(10),  nullable=False),
        sa.Column("quantity",            sa.Float(),     nullable=False),
        sa.Column("entry_price",         sa.Float(),     nullable=False),
        sa.Column("current_price",       sa.Float(),     nullable=True),
        sa.Column("stop_loss",           sa.Float(),     nullable=True),
        sa.Column("take_profit",         sa.Float(),     nullable=True),
        sa.Column("unrealized_pnl",      sa.Float(),     nullable=True),
        sa.Column("unrealized_pnl_pct",  sa.Float(),     nullable=True),
        sa.Column("broker",              sa.String(50),  nullable=True),
        sa.Column("is_paper",            sa.Boolean(),   nullable=False, server_default="true"),
        sa.Column("opened_at",           sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at",          sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_positions_user_id", "positions", ["user_id"])
    op.create_unique_constraint("uq_position_user_symbol_broker", "positions", ["user_id", "symbol", "broker"])

    # ── strategy_configs ───────────────────────────────────────
    op.create_table("strategy_configs",
        sa.Column("id",          UUID(as_uuid=False), primary_key=True),
        sa.Column("user_id",     UUID(as_uuid=False), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("name",        sa.String(100), nullable=False),
        sa.Column("description", sa.Text(),      nullable=True),
        sa.Column("config_json", sa.JSON(),      nullable=False),
        sa.Column("is_active",   sa.Boolean(),   nullable=False, server_default="false"),
        sa.Column("is_default",  sa.Boolean(),   nullable=False, server_default="false"),
        sa.Column("created_at",  sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at",  sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_strategy_configs_user_id", "strategy_configs", ["user_id"])
    op.create_unique_constraint("uq_strategy_config_user_name", "strategy_configs", ["user_id", "name"])

    # ── backtest_results ───────────────────────────────────────
    op.create_table("backtest_results",
        sa.Column("id",               UUID(as_uuid=False), primary_key=True),
        sa.Column("user_id",          UUID(as_uuid=False), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("name",             sa.String(100), nullable=True),
        sa.Column("symbols",          sa.JSON(),      nullable=False),
        sa.Column("interval",         sa.String(10),  nullable=False),
        sa.Column("period",           sa.String(20),  nullable=False),
        sa.Column("data_source",      sa.String(50),  nullable=False),
        sa.Column("config_json",      sa.JSON(),      nullable=False),
        sa.Column("metrics_json",     sa.JSON(),      nullable=False),
        sa.Column("equity_curve",     sa.JSON(),      nullable=True),
        sa.Column("trades_summary",   sa.JSON(),      nullable=True),
        sa.Column("initial_capital",  sa.Float(),     nullable=False),
        sa.Column("final_equity",     sa.Float(),     nullable=True),
        sa.Column("total_return_pct", sa.Float(),     nullable=True),
        sa.Column("sharpe_ratio",     sa.Float(),     nullable=True),
        sa.Column("max_drawdown_pct", sa.Float(),     nullable=True),
        sa.Column("win_rate_pct",     sa.Float(),     nullable=True),
        sa.Column("created_at",       sa.DateTime(timezone=True), nullable=False),
        sa.Column("duration_seconds", sa.Float(),     nullable=True),
    )
    op.create_index("ix_backtest_results_user_id",    "backtest_results", ["user_id"])
    op.create_index("ix_backtest_results_created_at", "backtest_results", ["created_at"])

    # ── audit_logs ─────────────────────────────────────────────
    op.create_table("audit_logs",
        sa.Column("id",          UUID(as_uuid=False), primary_key=True),
        sa.Column("user_id",     UUID(as_uuid=False), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("action",      sa.String(100), nullable=False),
        sa.Column("resource",    sa.String(100), nullable=True),
        sa.Column("resource_id", sa.String(100), nullable=True),
        sa.Column("details",     sa.JSON(),      nullable=True),
        sa.Column("ip_address",  sa.String(45),  nullable=True),
        sa.Column("user_agent",  sa.String(255), nullable=True),
        sa.Column("status",      sa.String(20),  nullable=False, server_default="success"),
        sa.Column("created_at",  sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_audit_logs_user_id",       "audit_logs", ["user_id"])
    op.create_index("ix_audit_logs_action",        "audit_logs", ["action"])
    op.create_index("ix_audit_logs_created_at",    "audit_logs", ["created_at"])
    op.create_index("ix_audit_logs_action_status", "audit_logs", ["action", "status"])


def downgrade() -> None:
    op.drop_table("audit_logs")
    op.drop_table("backtest_results")
    op.drop_table("strategy_configs")
    op.drop_table("positions")
    op.drop_table("trades")
    op.drop_table("signals")
    op.drop_table("api_keys")
    op.drop_table("users")
