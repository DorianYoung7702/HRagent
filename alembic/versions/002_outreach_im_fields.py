"""Add IM conversation fields to outreach_conversations."""

from alembic import op
import sqlalchemy as sa

revision = "002"
down_revision = "001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("outreach_conversations") as batch_op:
        batch_op.add_column(
            sa.Column("conversation_type", sa.String(), nullable=False, server_default="followup")
        )
        batch_op.add_column(sa.Column("im_contact_key", sa.String(), nullable=True))
        batch_op.add_column(sa.Column("last_agent_reason", sa.Text(), nullable=True))
        batch_op.add_column(
            sa.Column("need_resume_request", sa.Boolean(), nullable=False, server_default=sa.false())
        )


def downgrade() -> None:
    with op.batch_alter_table("outreach_conversations") as batch_op:
        batch_op.drop_column("need_resume_request")
        batch_op.drop_column("last_agent_reason")
        batch_op.drop_column("im_contact_key")
        batch_op.drop_column("conversation_type")
