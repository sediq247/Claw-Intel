"""Use fixed UTC-aligned crypto/rest/stocks/idle War Room phases."""
from alembic import op

revision = "0022_hourly_market_phases"
down_revision = "0021_provider_daily_budgets"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.drop_constraint("ck_autonomous_schedule_phase", "autonomous_schedule", type_="check")
    # Replace rows written by the former working/draining/resting scheduler with
    # the fixed UTC block active at migration time before adding the new check.
    op.execute("""
        UPDATE autonomous_schedule
        SET phase = CASE
                WHEN EXTRACT(MINUTE FROM timezone('UTC', now())) < 15 THEN 'crypto'
                WHEN EXTRACT(MINUTE FROM timezone('UTC', now())) < 30 THEN 'resting'
                WHEN EXTRACT(MINUTE FROM timezone('UTC', now())) < 45 THEN 'stocks'
                ELSE 'idle'
            END,
            phase_started_at = (date_trunc('hour', timezone('UTC', now()))
                + floor(EXTRACT(MINUTE FROM timezone('UTC', now())) / 15) * interval '15 minutes') AT TIME ZONE 'UTC',
            phase_ends_at = (date_trunc('hour', timezone('UTC', now()))
                + (floor(EXTRACT(MINUTE FROM timezone('UTC', now())) / 15) + 1) * interval '15 minutes') AT TIME ZONE 'UTC'
    """)
    op.create_check_constraint(
        "ck_autonomous_schedule_phase", "autonomous_schedule",
        "phase IN ('crypto','resting','stocks','idle')",
    )


def downgrade() -> None:
    op.execute("UPDATE autonomous_schedule SET phase='resting' WHERE phase IN ('crypto','stocks','idle')")
    op.drop_constraint("ck_autonomous_schedule_phase", "autonomous_schedule", type_="check")
    op.create_check_constraint(
        "ck_autonomous_schedule_phase", "autonomous_schedule",
        "phase IN ('working','draining','resting')",
    )
