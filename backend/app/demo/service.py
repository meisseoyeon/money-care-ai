from sqlalchemy import select
from app.core.time import aware
from app.accounts.models import Account
from app.accounts.service import account_response
from app.budgets.service import budget_context
from app.users.serializers import user_response
from app.users.roles import user_role


def demo_context(db, principal):
    user_id = principal.user.user_id
    if user_role(user_id) == "SUPPORTER":
        return {"user": user_response(principal.user), "expires_at": aware(principal.session.expires_at),
                "account": None, "settings": None, "expenses": []}
    account = db.scalar(select(Account).where(Account.user_id == user_id))
    return {"user": user_response(principal.user), "expires_at": aware(principal.session.expires_at),
            "account": account_response(account), **budget_context(db, user_id)}
