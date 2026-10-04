"""Remember which lead alert went out (email, Google Sheet), so a retry only
resends the one that failed.

Revision ID: 0002
Revises: 0001
Create Date: 2026-10-04
"""

import sqlalchemy as sa
from alembic import op

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("leads", sa.Column("emailed_at", sa.DateTime(timezone=True)))
    op.add_column("leads", sa.Column("sheet_added_at", sa.DateTime(timezone=True)))
    # Leads alerted before this change got both alerts.
    op.execute("UPDATE leads SET emailed_at = notified_at, sheet_added_at = notified_at "
               "WHERE notified_at IS NOT NULL")


def downgrade() -> None:
    op.drop_column("leads", "sheet_added_at")
    op.drop_column("leads", "emailed_at")
