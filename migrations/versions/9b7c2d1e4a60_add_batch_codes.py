"""Add unique batch codes.

Revision ID: 9b7c2d1e4a60
Revises: 000c35fa820f
"""
from alembic import op
import sqlalchemy as sa

revision = "9b7c2d1e4a60"
down_revision = "000c35fa820f"
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table("batches") as batch_op:
        batch_op.add_column(
            sa.Column("batch_code", sa.String(length=40), nullable=True)
        )

    connection = op.get_bind()
    rows = connection.execute(
        sa.text("SELECT id FROM batches ORDER BY id")
    ).fetchall()

    for row in rows:
        connection.execute(
            sa.text("UPDATE batches SET batch_code = :code WHERE id = :id"),
            {"code": f"BATCH-{row.id:04d}", "id": row.id},
        )

    with op.batch_alter_table("batches") as batch_op:
        batch_op.alter_column(
            "batch_code",
            existing_type=sa.String(length=40),
            nullable=False,
        )
        batch_op.create_unique_constraint(
            "uq_batches_batch_code", ["batch_code"]
        )


def downgrade():
    with op.batch_alter_table("batches") as batch_op:
        batch_op.drop_constraint("uq_batches_batch_code", type_="unique")
        batch_op.drop_column("batch_code")
