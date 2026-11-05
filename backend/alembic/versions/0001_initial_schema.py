"""initial schema

Revision ID: 4f41b2b201e9
Revises: 
Create Date: 2026-11-05 08:06:56.404282
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = '4f41b2b201e9'
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table('assets',
    sa.Column('symbol', sa.String(length=32), nullable=False),
    sa.Column('name', sa.String(length=120), nullable=False),
    sa.Column('asset_class', sa.Enum('crypto', 'stock', 'forex', name='assetclass', native_enum=False, length=16), nullable=False),
    sa.Column('base_currency', sa.String(length=16), nullable=False),
    sa.Column('quote_currency', sa.String(length=16), nullable=False),
    sa.Column('provider', sa.String(length=32), nullable=False),
    sa.Column('provider_symbol', sa.String(length=64), nullable=False),
    sa.Column('is_active', sa.Boolean(), nullable=False),
    sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('(CURRENT_TIMESTAMP)'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('(CURRENT_TIMESTAMP)'), nullable=False),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_assets'))
    )
    with op.batch_alter_table('assets', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_assets_asset_class'), ['asset_class'], unique=False)
        batch_op.create_index(batch_op.f('ix_assets_symbol'), ['symbol'], unique=True)

    op.create_table('users',
    sa.Column('email', sa.String(length=320), nullable=False),
    sa.Column('hashed_password', sa.String(length=255), nullable=False),
    sa.Column('full_name', sa.String(length=120), nullable=False),
    sa.Column('role', sa.Enum('user', 'admin', name='userrole', native_enum=False, length=16), nullable=False),
    sa.Column('is_active', sa.Boolean(), nullable=False),
    sa.Column('last_login_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('(CURRENT_TIMESTAMP)'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('(CURRENT_TIMESTAMP)'), nullable=False),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_users'))
    )
    with op.batch_alter_table('users', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_users_email'), ['email'], unique=True)

    op.create_table('ai_analysis_results',
    sa.Column('user_id', sa.Integer(), nullable=True),
    sa.Column('asset_id', sa.Integer(), nullable=False),
    sa.Column('timeframe', sa.String(length=8), nullable=False),
    sa.Column('trend', sa.String(length=16), nullable=False),
    sa.Column('summary', sa.Text(), nullable=False),
    sa.Column('narrative', sa.Text(), nullable=False),
    sa.Column('narrative_source', sa.String(length=32), nullable=False),
    sa.Column('indicators', sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), 'postgresql'), nullable=False),
    sa.Column('patterns', sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), 'postgresql'), nullable=False),
    sa.Column('ml', sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), 'postgresql'), nullable=False),
    sa.Column('data_source', sa.String(length=32), nullable=False),
    sa.Column('data_as_of', sa.DateTime(timezone=True), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
    sa.ForeignKeyConstraint(['asset_id'], ['assets.id'], name=op.f('fk_ai_analysis_results_asset_id_assets'), ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], name=op.f('fk_ai_analysis_results_user_id_users'), ondelete='SET NULL'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_ai_analysis_results'))
    )
    with op.batch_alter_table('ai_analysis_results', schema=None) as batch_op:
        batch_op.create_index('ix_ai_analysis_asset_created', ['asset_id', 'created_at'], unique=False)

    op.create_table('ai_conversations',
    sa.Column('user_id', sa.Integer(), nullable=False),
    sa.Column('title', sa.String(length=160), nullable=False),
    sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('(CURRENT_TIMESTAMP)'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('(CURRENT_TIMESTAMP)'), nullable=False),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], name=op.f('fk_ai_conversations_user_id_users'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_ai_conversations'))
    )
    with op.batch_alter_table('ai_conversations', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_ai_conversations_user_id'), ['user_id'], unique=False)

    op.create_table('audit_logs',
    sa.Column('user_id', sa.Integer(), nullable=True),
    sa.Column('action', sa.String(length=64), nullable=False),
    sa.Column('entity_type', sa.String(length=64), nullable=True),
    sa.Column('entity_id', sa.String(length=64), nullable=True),
    sa.Column('ip_address', sa.String(length=64), nullable=True),
    sa.Column('details', sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), 'postgresql'), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], name=op.f('fk_audit_logs_user_id_users'), ondelete='SET NULL'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_audit_logs'))
    )
    with op.batch_alter_table('audit_logs', schema=None) as batch_op:
        batch_op.create_index('ix_audit_logs_action', ['action'], unique=False)
        batch_op.create_index('ix_audit_logs_user_created', ['user_id', 'created_at'], unique=False)

    op.create_table('market_data',
    sa.Column('id', sa.BigInteger().with_variant(sa.Integer(), 'sqlite'), autoincrement=True, nullable=False),
    sa.Column('asset_id', sa.Integer(), nullable=False),
    sa.Column('timeframe', sa.String(length=8), nullable=False),
    sa.Column('ts', sa.DateTime(timezone=True), nullable=False),
    sa.Column('open', sa.Numeric(precision=28, scale=10, asdecimal=False), nullable=False),
    sa.Column('high', sa.Numeric(precision=28, scale=10, asdecimal=False), nullable=False),
    sa.Column('low', sa.Numeric(precision=28, scale=10, asdecimal=False), nullable=False),
    sa.Column('close', sa.Numeric(precision=28, scale=10, asdecimal=False), nullable=False),
    sa.Column('volume', sa.Numeric(precision=28, scale=10, asdecimal=False), nullable=False),
    sa.Column('source', sa.String(length=32), nullable=False),
    sa.ForeignKeyConstraint(['asset_id'], ['assets.id'], name=op.f('fk_market_data_asset_id_assets'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_market_data')),
    sa.UniqueConstraint('asset_id', 'timeframe', 'ts', name='uq_market_data_asset_tf_ts')
    )
    with op.batch_alter_table('market_data', schema=None) as batch_op:
        batch_op.create_index('ix_market_data_asset_tf_ts', ['asset_id', 'timeframe', 'ts'], unique=False)

    op.create_table('paper_portfolios',
    sa.Column('user_id', sa.Integer(), nullable=False),
    sa.Column('name', sa.String(length=80), nullable=False),
    sa.Column('starting_balance', sa.Numeric(precision=28, scale=10, asdecimal=False), nullable=False),
    sa.Column('cash_balance', sa.Numeric(precision=28, scale=10, asdecimal=False), nullable=False),
    sa.Column('realized_pnl', sa.Numeric(precision=28, scale=10, asdecimal=False), nullable=False),
    sa.Column('total_fees', sa.Numeric(precision=28, scale=10, asdecimal=False), nullable=False),
    sa.Column('max_position_pct', sa.Float(), nullable=False),
    sa.Column('max_open_positions', sa.Integer(), nullable=False),
    sa.Column('daily_loss_limit_pct', sa.Float(), nullable=False),
    sa.Column('is_active', sa.Boolean(), nullable=False),
    sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('(CURRENT_TIMESTAMP)'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('(CURRENT_TIMESTAMP)'), nullable=False),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], name=op.f('fk_paper_portfolios_user_id_users'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_paper_portfolios'))
    )
    with op.batch_alter_table('paper_portfolios', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_paper_portfolios_user_id'), ['user_id'], unique=False)

    op.create_table('strategies',
    sa.Column('user_id', sa.Integer(), nullable=False),
    sa.Column('name', sa.String(length=120), nullable=False),
    sa.Column('description', sa.Text(), nullable=False),
    sa.Column('is_archived', sa.Boolean(), nullable=False),
    sa.Column('current_version', sa.Integer(), nullable=False),
    sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('(CURRENT_TIMESTAMP)'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('(CURRENT_TIMESTAMP)'), nullable=False),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], name=op.f('fk_strategies_user_id_users'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_strategies')),
    sa.UniqueConstraint('user_id', 'name', name='uq_strategies_user_name')
    )
    with op.batch_alter_table('strategies', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_strategies_user_id'), ['user_id'], unique=False)

    op.create_table('user_sessions',
    sa.Column('user_id', sa.Integer(), nullable=False),
    sa.Column('token_hash', sa.String(length=64), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('last_seen_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('expires_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('revoked_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('ip_address', sa.String(length=64), nullable=True),
    sa.Column('user_agent', sa.String(length=255), nullable=True),
    sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], name=op.f('fk_user_sessions_user_id_users'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_user_sessions'))
    )
    with op.batch_alter_table('user_sessions', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_user_sessions_token_hash'), ['token_hash'], unique=True)
        batch_op.create_index('ix_user_sessions_user_active', ['user_id', 'revoked_at'], unique=False)

    op.create_table('user_settings',
    sa.Column('user_id', sa.Integer(), nullable=False),
    sa.Column('default_timeframe', sa.String(length=8), nullable=False),
    sa.Column('default_symbol', sa.String(length=32), nullable=False),
    sa.Column('risk_tolerance', sa.String(length=16), nullable=False),
    sa.Column('preferences', sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), 'postgresql'), nullable=False),
    sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('(CURRENT_TIMESTAMP)'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('(CURRENT_TIMESTAMP)'), nullable=False),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], name=op.f('fk_user_settings_user_id_users'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_user_settings')),
    sa.UniqueConstraint('user_id', name=op.f('uq_user_settings_user_id'))
    )
    op.create_table('watchlists',
    sa.Column('user_id', sa.Integer(), nullable=False),
    sa.Column('name', sa.String(length=80), nullable=False),
    sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('(CURRENT_TIMESTAMP)'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('(CURRENT_TIMESTAMP)'), nullable=False),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], name=op.f('fk_watchlists_user_id_users'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_watchlists')),
    sa.UniqueConstraint('user_id', 'name', name='uq_watchlists_user_name')
    )
    with op.batch_alter_table('watchlists', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_watchlists_user_id'), ['user_id'], unique=False)

    op.create_table('ai_messages',
    sa.Column('conversation_id', sa.Integer(), nullable=False),
    sa.Column('role', sa.Enum('user', 'assistant', name='messagerole', native_enum=False, length=16), nullable=False),
    sa.Column('content', sa.Text(), nullable=False),
    sa.Column('meta', sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), 'postgresql'), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
    sa.ForeignKeyConstraint(['conversation_id'], ['ai_conversations.id'], name=op.f('fk_ai_messages_conversation_id_ai_conversations'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_ai_messages'))
    )
    with op.batch_alter_table('ai_messages', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_ai_messages_conversation_id'), ['conversation_id'], unique=False)

    op.create_table('portfolio_positions',
    sa.Column('portfolio_id', sa.Integer(), nullable=False),
    sa.Column('asset_id', sa.Integer(), nullable=False),
    sa.Column('quantity', sa.Numeric(precision=28, scale=10, asdecimal=False), nullable=False),
    sa.Column('avg_entry_price', sa.Numeric(precision=28, scale=10, asdecimal=False), nullable=False),
    sa.Column('realized_pnl', sa.Numeric(precision=28, scale=10, asdecimal=False), nullable=False),
    sa.Column('opened_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
    sa.ForeignKeyConstraint(['asset_id'], ['assets.id'], name=op.f('fk_portfolio_positions_asset_id_assets')),
    sa.ForeignKeyConstraint(['portfolio_id'], ['paper_portfolios.id'], name=op.f('fk_portfolio_positions_portfolio_id_paper_portfolios'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_portfolio_positions')),
    sa.UniqueConstraint('portfolio_id', 'asset_id', name='uq_portfolio_positions_pf_asset')
    )
    with op.batch_alter_table('portfolio_positions', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_portfolio_positions_portfolio_id'), ['portfolio_id'], unique=False)

    op.create_table('portfolio_snapshots',
    sa.Column('portfolio_id', sa.Integer(), nullable=False),
    sa.Column('ts', sa.DateTime(timezone=True), nullable=False),
    sa.Column('equity', sa.Numeric(precision=28, scale=10, asdecimal=False), nullable=False),
    sa.Column('cash', sa.Numeric(precision=28, scale=10, asdecimal=False), nullable=False),
    sa.Column('positions_value', sa.Numeric(precision=28, scale=10, asdecimal=False), nullable=False),
    sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
    sa.ForeignKeyConstraint(['portfolio_id'], ['paper_portfolios.id'], name=op.f('fk_portfolio_snapshots_portfolio_id_paper_portfolios'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_portfolio_snapshots'))
    )
    with op.batch_alter_table('portfolio_snapshots', schema=None) as batch_op:
        batch_op.create_index('ix_portfolio_snapshots_pf_ts', ['portfolio_id', 'ts'], unique=False)

    op.create_table('simulated_orders',
    sa.Column('portfolio_id', sa.Integer(), nullable=False),
    sa.Column('asset_id', sa.Integer(), nullable=False),
    sa.Column('side', sa.Enum('buy', 'sell', name='orderside', native_enum=False, length=16), nullable=False),
    sa.Column('order_type', sa.Enum('market', 'limit', name='ordertype', native_enum=False, length=16), nullable=False),
    sa.Column('quantity', sa.Numeric(precision=28, scale=10, asdecimal=False), nullable=False),
    sa.Column('limit_price', sa.Numeric(precision=28, scale=10, asdecimal=False), nullable=True),
    sa.Column('status', sa.Enum('open', 'filled', 'cancelled', 'rejected', name='orderstatus', native_enum=False, length=16), nullable=False),
    sa.Column('filled_price', sa.Numeric(precision=28, scale=10, asdecimal=False), nullable=True),
    sa.Column('fee', sa.Numeric(precision=28, scale=10, asdecimal=False), nullable=False),
    sa.Column('reject_reason', sa.String(length=255), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('filled_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
    sa.ForeignKeyConstraint(['asset_id'], ['assets.id'], name=op.f('fk_simulated_orders_asset_id_assets')),
    sa.ForeignKeyConstraint(['portfolio_id'], ['paper_portfolios.id'], name=op.f('fk_simulated_orders_portfolio_id_paper_portfolios'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_simulated_orders'))
    )
    with op.batch_alter_table('simulated_orders', schema=None) as batch_op:
        batch_op.create_index('ix_simulated_orders_pf_created', ['portfolio_id', 'created_at'], unique=False)
        batch_op.create_index('ix_simulated_orders_status', ['status'], unique=False)

    op.create_table('strategy_configurations',
    sa.Column('strategy_id', sa.Integer(), nullable=False),
    sa.Column('version', sa.Integer(), nullable=False),
    sa.Column('asset_id', sa.Integer(), nullable=False),
    sa.Column('timeframe', sa.String(length=8), nullable=False),
    sa.Column('entry_rules', sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), 'postgresql'), nullable=False),
    sa.Column('exit_rules', sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), 'postgresql'), nullable=False),
    sa.Column('risk', sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), 'postgresql'), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
    sa.ForeignKeyConstraint(['asset_id'], ['assets.id'], name=op.f('fk_strategy_configurations_asset_id_assets')),
    sa.ForeignKeyConstraint(['strategy_id'], ['strategies.id'], name=op.f('fk_strategy_configurations_strategy_id_strategies'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_strategy_configurations')),
    sa.UniqueConstraint('strategy_id', 'version', name='uq_strategy_configurations_version')
    )
    with op.batch_alter_table('strategy_configurations', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_strategy_configurations_strategy_id'), ['strategy_id'], unique=False)

    op.create_table('trading_signals',
    sa.Column('analysis_id', sa.Integer(), nullable=False),
    sa.Column('asset_id', sa.Integer(), nullable=False),
    sa.Column('timeframe', sa.String(length=8), nullable=False),
    sa.Column('action', sa.Enum('buy', 'sell', 'hold', name='signalaction', native_enum=False, length=8), nullable=False),
    sa.Column('score', sa.Float(), nullable=False),
    sa.Column('confidence', sa.Float(), nullable=False),
    sa.Column('price_at_signal', sa.Numeric(precision=28, scale=10, asdecimal=False), nullable=False),
    sa.Column('components', sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), 'postgresql'), nullable=False),
    sa.Column('risks', sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), 'postgresql'), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
    sa.ForeignKeyConstraint(['analysis_id'], ['ai_analysis_results.id'], name=op.f('fk_trading_signals_analysis_id_ai_analysis_results'), ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['asset_id'], ['assets.id'], name=op.f('fk_trading_signals_asset_id_assets'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_trading_signals')),
    sa.UniqueConstraint('analysis_id', name=op.f('uq_trading_signals_analysis_id'))
    )
    with op.batch_alter_table('trading_signals', schema=None) as batch_op:
        batch_op.create_index('ix_trading_signals_asset_created', ['asset_id', 'created_at'], unique=False)

    op.create_table('watchlist_items',
    sa.Column('watchlist_id', sa.Integer(), nullable=False),
    sa.Column('asset_id', sa.Integer(), nullable=False),
    sa.Column('position', sa.Integer(), nullable=False),
    sa.Column('added_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
    sa.ForeignKeyConstraint(['asset_id'], ['assets.id'], name=op.f('fk_watchlist_items_asset_id_assets'), ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['watchlist_id'], ['watchlists.id'], name=op.f('fk_watchlist_items_watchlist_id_watchlists'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_watchlist_items')),
    sa.UniqueConstraint('watchlist_id', 'asset_id', name='uq_watchlist_items_wl_asset')
    )
    with op.batch_alter_table('watchlist_items', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_watchlist_items_watchlist_id'), ['watchlist_id'], unique=False)

    op.create_table('backtest_sessions',
    sa.Column('user_id', sa.Integer(), nullable=False),
    sa.Column('strategy_id', sa.Integer(), nullable=False),
    sa.Column('strategy_config_id', sa.Integer(), nullable=False),
    sa.Column('asset_id', sa.Integer(), nullable=False),
    sa.Column('timeframe', sa.String(length=8), nullable=False),
    sa.Column('start_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('end_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('initial_capital', sa.Numeric(precision=28, scale=10, asdecimal=False), nullable=False),
    sa.Column('fee_bps', sa.Float(), nullable=False),
    sa.Column('slippage_bps', sa.Float(), nullable=False),
    sa.Column('status', sa.Enum('pending', 'running', 'completed', 'failed', name='backteststatus', native_enum=False, length=16), nullable=False),
    sa.Column('error', sa.Text(), nullable=True),
    sa.Column('data_source', sa.String(length=32), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('completed_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
    sa.ForeignKeyConstraint(['asset_id'], ['assets.id'], name=op.f('fk_backtest_sessions_asset_id_assets')),
    sa.ForeignKeyConstraint(['strategy_config_id'], ['strategy_configurations.id'], name=op.f('fk_backtest_sessions_strategy_config_id_strategy_configurations'), ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['strategy_id'], ['strategies.id'], name=op.f('fk_backtest_sessions_strategy_id_strategies'), ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], name=op.f('fk_backtest_sessions_user_id_users'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_backtest_sessions'))
    )
    with op.batch_alter_table('backtest_sessions', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_backtest_sessions_strategy_id'), ['strategy_id'], unique=False)
        batch_op.create_index('ix_backtest_sessions_user_created', ['user_id', 'created_at'], unique=False)

    op.create_table('simulated_trades',
    sa.Column('order_id', sa.Integer(), nullable=False),
    sa.Column('portfolio_id', sa.Integer(), nullable=False),
    sa.Column('asset_id', sa.Integer(), nullable=False),
    sa.Column('side', sa.Enum('buy', 'sell', name='orderside', native_enum=False, length=16), nullable=False),
    sa.Column('quantity', sa.Numeric(precision=28, scale=10, asdecimal=False), nullable=False),
    sa.Column('price', sa.Numeric(precision=28, scale=10, asdecimal=False), nullable=False),
    sa.Column('fee', sa.Numeric(precision=28, scale=10, asdecimal=False), nullable=False),
    sa.Column('realized_pnl', sa.Numeric(precision=28, scale=10, asdecimal=False), nullable=False),
    sa.Column('executed_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
    sa.ForeignKeyConstraint(['asset_id'], ['assets.id'], name=op.f('fk_simulated_trades_asset_id_assets')),
    sa.ForeignKeyConstraint(['order_id'], ['simulated_orders.id'], name=op.f('fk_simulated_trades_order_id_simulated_orders'), ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['portfolio_id'], ['paper_portfolios.id'], name=op.f('fk_simulated_trades_portfolio_id_paper_portfolios'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_simulated_trades')),
    sa.UniqueConstraint('order_id', name=op.f('uq_simulated_trades_order_id'))
    )
    with op.batch_alter_table('simulated_trades', schema=None) as batch_op:
        batch_op.create_index('ix_simulated_trades_pf_executed', ['portfolio_id', 'executed_at'], unique=False)

    op.create_table('backtest_results',
    sa.Column('session_id', sa.Integer(), nullable=False),
    sa.Column('total_return_pct', sa.Float(), nullable=False),
    sa.Column('buy_hold_return_pct', sa.Float(), nullable=False),
    sa.Column('max_drawdown_pct', sa.Float(), nullable=False),
    sa.Column('win_rate', sa.Float(), nullable=True),
    sa.Column('profit_factor', sa.Float(), nullable=True),
    sa.Column('sharpe_ratio', sa.Float(), nullable=True),
    sa.Column('num_trades', sa.Integer(), nullable=False),
    sa.Column('final_equity', sa.Numeric(precision=28, scale=10, asdecimal=False), nullable=False),
    sa.Column('metrics', sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), 'postgresql'), nullable=False),
    sa.Column('equity_curve', sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), 'postgresql'), nullable=False),
    sa.Column('trades', sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), 'postgresql'), nullable=False),
    sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
    sa.ForeignKeyConstraint(['session_id'], ['backtest_sessions.id'], name=op.f('fk_backtest_results_session_id_backtest_sessions'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_backtest_results')),
    sa.UniqueConstraint('session_id', name=op.f('uq_backtest_results_session_id'))
    )


def downgrade() -> None:
    op.drop_table('backtest_results')
    with op.batch_alter_table('simulated_trades', schema=None) as batch_op:
        batch_op.drop_index('ix_simulated_trades_pf_executed')

    op.drop_table('simulated_trades')
    with op.batch_alter_table('backtest_sessions', schema=None) as batch_op:
        batch_op.drop_index('ix_backtest_sessions_user_created')
        batch_op.drop_index(batch_op.f('ix_backtest_sessions_strategy_id'))

    op.drop_table('backtest_sessions')
    with op.batch_alter_table('watchlist_items', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_watchlist_items_watchlist_id'))

    op.drop_table('watchlist_items')
    with op.batch_alter_table('trading_signals', schema=None) as batch_op:
        batch_op.drop_index('ix_trading_signals_asset_created')

    op.drop_table('trading_signals')
    with op.batch_alter_table('strategy_configurations', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_strategy_configurations_strategy_id'))

    op.drop_table('strategy_configurations')
    with op.batch_alter_table('simulated_orders', schema=None) as batch_op:
        batch_op.drop_index('ix_simulated_orders_status')
        batch_op.drop_index('ix_simulated_orders_pf_created')

    op.drop_table('simulated_orders')
    with op.batch_alter_table('portfolio_snapshots', schema=None) as batch_op:
        batch_op.drop_index('ix_portfolio_snapshots_pf_ts')

    op.drop_table('portfolio_snapshots')
    with op.batch_alter_table('portfolio_positions', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_portfolio_positions_portfolio_id'))

    op.drop_table('portfolio_positions')
    with op.batch_alter_table('ai_messages', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_ai_messages_conversation_id'))

    op.drop_table('ai_messages')
    with op.batch_alter_table('watchlists', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_watchlists_user_id'))

    op.drop_table('watchlists')
    op.drop_table('user_settings')
    with op.batch_alter_table('user_sessions', schema=None) as batch_op:
        batch_op.drop_index('ix_user_sessions_user_active')
        batch_op.drop_index(batch_op.f('ix_user_sessions_token_hash'))

    op.drop_table('user_sessions')
    with op.batch_alter_table('strategies', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_strategies_user_id'))

    op.drop_table('strategies')
    with op.batch_alter_table('paper_portfolios', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_paper_portfolios_user_id'))

    op.drop_table('paper_portfolios')
    with op.batch_alter_table('market_data', schema=None) as batch_op:
        batch_op.drop_index('ix_market_data_asset_tf_ts')

    op.drop_table('market_data')
    with op.batch_alter_table('audit_logs', schema=None) as batch_op:
        batch_op.drop_index('ix_audit_logs_user_created')
        batch_op.drop_index('ix_audit_logs_action')

    op.drop_table('audit_logs')
    with op.batch_alter_table('ai_conversations', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_ai_conversations_user_id'))

    op.drop_table('ai_conversations')
    with op.batch_alter_table('ai_analysis_results', schema=None) as batch_op:
        batch_op.drop_index('ix_ai_analysis_asset_created')

    op.drop_table('ai_analysis_results')
    with op.batch_alter_table('users', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_users_email'))

    op.drop_table('users')
    with op.batch_alter_table('assets', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_assets_symbol'))
        batch_op.drop_index(batch_op.f('ix_assets_asset_class'))

    op.drop_table('assets')
