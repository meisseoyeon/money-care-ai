from sqlalchemy import select
from app.transactions.models import Transaction
from app.recipients.catalog import RECIPIENTS


def list_recipients(db, user_id):
    familiar_ids = set(db.scalars(select(Transaction.counterparty_id).where(
        Transaction.user_id == user_id, Transaction.tx_type == "TRANSFER", Transaction.direction == "OUT",
    ).distinct()))
    return [{**recipient, "familiar": recipient["id"] in familiar_ids} for recipient in RECIPIENTS]
