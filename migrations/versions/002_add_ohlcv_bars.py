"""add ohlcv_bars table

Revision ID: 002
Revises: 001
Create Date: 2026-05-16

Adds the ohlcv_bars table so the background worker can persist historical
OHLCV price bars and the dashboard can display data prior to the current
live fetch window.
"""
from alembic import op
import sqlalchemy as sa

revision = "002"
down_revision = "001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "ohlcv_bars",
        sa.Column("id",         sa.String(36),  primary_key=True),
        sa.Column("symbol",     sa.String(30),  nullable=False),
        sa.Column("interval",   sa.String(10),  nullable=False),
        sa.Column("source",     sa.String(30),  nullable=False),
        sa.Column("ts",         sa.DateTime(),  nullable=False),
        sa.Column("open",       sa.Float(),     nullable=False),
        sa.Column("high",       sa.Float(),     nullable=False),
        sa.Column("low",        sa.Float(),     nullable=False),
        sa.Column("close",      sa.Float(),     nullable=False),
        sa.Column("volume",     sa.Float(),     nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.func.now()),
        sa.UniqueConstraint("symbol", "interval", "source", "ts", name="uq_ohlcv_bar"),
    )
    op.create_index("ix_ohlcv_symbol_interval_ts", "ohlcv_bars",
                    ["symbol", "interval", "ts"])
    op.create_index("ix_ohlcv_bars_symbol",   "ohlcv_bars", ["symbol"])
    op.create_index("ix_ohlcv_bars_ts",       "ohlcv_bars", ["ts"])


def downgrade() -> None:
    op.drop_index("ix_ohlcv_bars_ts",              table_name="ohlcv_bars")
    op.drop_index("ix_ohlcv_bars_symbol",          table_name="ohlcv_bars")
    op.drop_index("ix_ohlcv_symbol_interval_ts",   table_name="ohlcv_bars")
    op.drop_table("ohlcv_bars")
