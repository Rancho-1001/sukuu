"""payments are not Stripe-shaped

Revision ID: 5c1e7a2b9d40
Revises: 234bcc6ffbe3
Create Date: 2026-09-15 10:12:00.000000

The payments table was built when Stripe was the only processor, so "stripe"
was both the method and the company, and the two id columns had its name on
them. With a second processor the row needs to say three separate things: how
the parent paid (method), who processed it (provider), and the ids the
provider knows it by.

Every existing online payment was Stripe, and Stripe was only ever offered
cards - so the backfill is exact, not a guess.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "5c1e7a2b9d40"
down_revision: str | Sequence[str] | None = "234bcc6ffbe3"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    # The method enum: "stripe" becomes "card", and the channels Paystack
    # offers are added. ADD VALUE cannot run inside the transaction that then
    # uses the value, so it runs in its own.
    with op.get_context().autocommit_block():
        op.execute("ALTER TYPE payment_method RENAME VALUE 'stripe' TO 'card'")
        op.execute("ALTER TYPE payment_method ADD VALUE IF NOT EXISTS 'mobile_money'")
        op.execute("ALTER TYPE payment_method ADD VALUE IF NOT EXISTS 'bank'")

    payment_provider = sa.Enum("stripe", "paystack", name="payment_provider")
    payment_provider.create(op.get_bind())
    op.add_column("payments", sa.Column("provider", payment_provider, nullable=True))
    op.execute("UPDATE payments SET provider = 'stripe' WHERE method = 'card'")

    op.alter_column("payments", "stripe_payment_intent_id", new_column_name="provider_reference")
    op.alter_column("payments", "stripe_event_id", new_column_name="provider_event_id")

    op.drop_constraint("stripe_event_id", "payments", type_="unique")
    op.create_unique_constraint("provider_event_id", "payments", ["provider", "provider_event_id"])

    op.drop_constraint(op.f("ck_payments_stripe_ids_match_method"), "payments", type_="check")
    op.create_check_constraint(
        op.f("ck_payments_provider_fields_match_method"),
        "payments",
        "(method = 'cash' AND provider IS NULL AND provider_reference IS NULL"
        " AND provider_event_id IS NULL)"
        " OR (method <> 'cash' AND provider IS NOT NULL AND provider_reference IS NOT NULL"
        " AND provider_event_id IS NOT NULL)",
    )


def downgrade() -> None:
    """Downgrade schema.

    Postgres cannot remove a value from an enum, so the old type is rebuilt.
    Any mobile-money or bank payment recorded after the upgrade has no
    representation in the old schema; the downgrade refuses rather than
    relabelling money.
    """
    bind = op.get_bind()
    stranded = bind.execute(
        sa.text("SELECT count(*) FROM payments WHERE method IN ('mobile_money', 'bank')")
    ).scalar_one()
    if stranded:
        raise RuntimeError(
            f"{stranded} payment(s) are mobile money or bank transfers, which the previous "
            "schema cannot represent. Refusing to downgrade."
        )

    op.drop_constraint(op.f("ck_payments_provider_fields_match_method"), "payments", type_="check")
    op.drop_constraint("provider_event_id", "payments", type_="unique")

    op.alter_column("payments", "provider_reference", new_column_name="stripe_payment_intent_id")
    op.alter_column("payments", "provider_event_id", new_column_name="stripe_event_id")
    op.drop_column("payments", "provider")
    op.execute("DROP TYPE payment_provider")

    op.execute("ALTER TYPE payment_method RENAME TO payment_method_old")
    op.execute("CREATE TYPE payment_method AS ENUM ('stripe', 'cash')")
    op.execute(
        "ALTER TABLE payments ALTER COLUMN method TYPE payment_method"
        " USING (CASE method::text WHEN 'card' THEN 'stripe' ELSE method::text END)"
        "::payment_method"
    )
    op.execute("DROP TYPE payment_method_old")

    op.create_unique_constraint("stripe_event_id", "payments", ["stripe_event_id"])
    op.create_check_constraint(
        op.f("ck_payments_stripe_ids_match_method"),
        "payments",
        "(method = 'stripe' AND stripe_payment_intent_id IS NOT NULL)"
        " OR (method = 'cash' AND stripe_payment_intent_id IS NULL)",
    )
