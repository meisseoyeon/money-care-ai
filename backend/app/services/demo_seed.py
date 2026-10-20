import hashlib
import secrets
from datetime import timedelta
from uuid import uuid4
from zoneinfo import ZoneInfo

from app.models.demo_session import Account, BudgetSetting, ScheduledExpense, User

RECIPIENTS = [
    {"id": "demo-payee-1", "name": "박민수", "bank": "체험 은행", "account_hint": "••• 1024", "initial": "민", "familiar": False},
    {"id": "demo-payee-2", "name": "김하늘", "bank": "체험 은행", "account_hint": "••• 7768", "initial": "하", "familiar": False},
]


def seed_demo_user(db, now, consented):
    user_id = str(uuid4())
    salt = secrets.token_bytes(16)
    # 비밀번호는 사용자에게 발급하지 않으며 원문도 저장하지 않습니다.
    password_hash = hashlib.scrypt(secrets.token_bytes(32), salt=salt, n=16384, r=8, p=1).hex()
    user = User(user_id=user_id, email=f"demo-{user_id}@example.invalid",
                password_hash=f"scrypt$16384$8$1${salt.hex()}${password_hash}",
                display_name="체험 사용자", status="ACTIVE", created_at=now, updated_at=now,
                monitoring_consented_at=now if consented else None, monitoring_revoked_at=None)
    db.add(user)
    db.flush()
    today = now.astimezone(ZoneInfo("Asia/Seoul")).date()
    db.add(Account(account_id=str(uuid4()), user_id=user_id, display_name="체험 생활비 통장",
                   current_balance=800000, balance_as_of=now, created_at=now, updated_at=now))
    db.add(BudgetSetting(user_id=user_id, next_income_date=today + timedelta(days=20),
                        expected_income_amount=1000000, daily_living_budget=20000, updated_at=now))
    for title, amount, days in [("월세", 100000, 5), ("통신비", 50000, 10)]:
        db.add(ScheduledExpense(user_id=user_id, title=title, amount=amount,
                                due_date=today + timedelta(days=days), status="PLANNED", created_at=now, updated_at=now))
    db.flush()
    return user
