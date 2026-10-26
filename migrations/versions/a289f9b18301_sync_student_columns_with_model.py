"""sync student columns with model"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect

# Update this if your current migration head is different.
revision = "a289f9b18301"
down_revision = "a3ed03b1498a"
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    columns = {
        column["name"]
        for column in inspect(bind).get_columns("students")
    }

    if "campus_id_active" not in columns:
        op.add_column(
            "students",
            sa.Column(
                "campus_id_active",
                sa.Boolean(),
                nullable=False,
                server_default=sa.true(),
            ),
        )

    if "id_expiry_override" not in columns:
        op.add_column(
            "students",
            sa.Column("id_expiry_override", sa.Date(), nullable=True),
        )


def downgrade():
    bind = op.get_bind()
    columns = {
        column["name"]
        for column in inspect(bind).get_columns("students")
    }

    if "id_expiry_override" in columns:
        op.drop_column("students", "id_expiry_override")

    if "campus_id_active" in columns:
        op.drop_column("students", "campus_id_active")

