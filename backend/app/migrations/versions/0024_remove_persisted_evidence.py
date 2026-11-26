"""Remove raw evidence retention and all durable references to evidence blobs."""
from alembic import op


revision = "0024_remove_persisted_evidence"
down_revision = "0023_a2a_reception_queue"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Stop retaining provider payloads, forecast source snapshots, and pointers
    # to evidence records. Analysis outputs and token identifiers remain.
    op.execute("""
        UPDATE conversation_messages
        SET attachments = COALESCE((
            SELECT jsonb_agg(item - 'evidence_ids')
            FROM jsonb_array_elements(attachments) AS item
        ), '[]'::jsonb)
        WHERE attachments::text LIKE '%evidence_ids%'
    """)
    op.execute("""
        UPDATE durable_events
        SET payload = payload - 'evidence_id' - 'evidence_ids'
        WHERE payload ? 'evidence_id' OR payload ? 'evidence_ids'
    """)
    op.execute("""
        UPDATE agent_jobs
        SET status = 'dead', completed_at = now(), locked_at = NULL,
            last_error = 'Discarded because raw evidence is no longer retained',
            payload = payload - 'evidence_id'
        WHERE payload ? 'evidence_id' AND status IN ('queued','processing','retrying')
    """)
    op.execute("""
        UPDATE agent_jobs
        SET payload = payload - 'evidence_id' - 'evidence_ids',
            result = CASE WHEN result IS NULL THEN NULL
                          ELSE result - 'evidence_id' - 'evidence_ids' END
        WHERE payload ? 'evidence_id' OR payload ? 'evidence_ids'
           OR result ? 'evidence_id' OR result ? 'evidence_ids'
    """)
    op.execute("""
        UPDATE market_forecasts
        SET forecast = forecast - 'supporting_evidence_ids' - 'contradicting_evidence_ids'
        WHERE forecast ? 'supporting_evidence_ids' OR forecast ? 'contradicting_evidence_ids'
    """)
    # IF EXISTS is required because clean installs no longer create these
    # columns/tables in the historical schema revisions.
    op.execute("ALTER TABLE market_forecasts DROP CONSTRAINT IF EXISTS market_forecasts_evidence_id_fkey")
    op.execute("ALTER TABLE market_forecasts DROP COLUMN IF EXISTS evidence_id")
    op.execute("ALTER TABLE market_forecasts DROP COLUMN IF EXISTS source_snapshot")
    op.execute("ALTER TABLE investigation_findings DROP COLUMN IF EXISTS evidence_ids")
    op.execute("DROP TABLE IF EXISTS evidence")


def downgrade() -> None:
    # Removed source evidence is intentionally not restored by downgrade.
    pass
