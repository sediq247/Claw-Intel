"""One-time user-authorized reset and removal of legacy demo schema."""
from alembic import op


revision = "0027_clear_existing_data"
down_revision = "0026_no_a2a_response"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Clear every public-schema row once, preserving only Alembic's revision."""
    op.execute("""
        DO $$
        DECLARE app_table record;
        BEGIN
            FOR app_table IN
                SELECT tablename FROM pg_tables
                WHERE schemaname = 'public' AND tablename <> 'alembic_version'
            LOOP
                EXECUTE format('TRUNCATE TABLE %I.%I RESTART IDENTITY CASCADE', 'public', app_table.tablename);
            END LOOP;
        END $$;
    """)

    # Legacy deployments may still carry simulation-only schema. Clean installs
    # no longer create these fields/tables; IF EXISTS makes both paths converge.
    op.execute("ALTER TABLE public.investigations DROP COLUMN IF EXISTS scenario_id")
    op.execute("ALTER TABLE public.conversation_messages DROP COLUMN IF EXISTS simulated")
    op.execute("DROP TABLE IF EXISTS public.demo_positions, public.demo_quotes, public.demo_trades, public.demo_wallets CASCADE")


def downgrade() -> None:
    # The user-authorized data reset is irreversible. Recreating empty legacy
    # demo tables would reintroduce mocked behavior the application removed.
    pass
