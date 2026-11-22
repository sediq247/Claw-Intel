"""Share API rate-limit windows across ClawIntel app replicas."""
from alembic import op
import sqlalchemy as sa

revision = "0013_distributed_rate_limits"
down_revision = "0012_telegram_outbox"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "rate_limit_buckets",
        sa.Column("route", sa.String(128), nullable=False),
        sa.Column("client_key", sa.String(64), nullable=False),
        sa.Column("window_start", sa.DateTime(timezone=True), nullable=False),
        sa.Column("hits", sa.Integer(), nullable=False),
        sa.CheckConstraint("hits > 0", name="ck_rate_limit_buckets_hits_positive"),
        sa.PrimaryKeyConstraint("route", "client_key", "window_start", name="pk_rate_limit_buckets"),
    )
    op.create_index("ix_rate_limit_buckets_window_start", "rate_limit_buckets", ["window_start"])


def downgrade():
    op.drop_index("ix_rate_limit_buckets_window_start", table_name="rate_limit_buckets")
    op.drop_table("rate_limit_buckets")
