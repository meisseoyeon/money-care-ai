import os
import asyncio
import hashlib
import unittest
from datetime import timedelta
from unittest.mock import patch
from uuid import uuid4

from sqlalchemy import func, literal, select, text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.baselines.models import UserBaseline
from app.budgets.models import BudgetForecast, BudgetInputSnapshot
from app.transactions.models import Transaction
from app.transactions.budgets import create_transfer_forecast
from tests.support import AuthTestCase


@unittest.skipUnless(os.getenv("DEMO_TEST_DATABASE_URL"), "PostgreSQL integration mode required")
class TransferBudgetTests(AuthTestCase):
    def counts(self):
        return tuple(self.count(model) for model in (Transaction, UserBaseline, BudgetInputSnapshot, BudgetForecast))

    async def balance(self, session):
        return (await self.client.get("/demo/me", headers=self.auth(session))).json()["account"]["current_balance"]

    async def test_transfer_stores_and_returns_post_balance_forecast(self):
        session = await self.create()
        before = (await self.client.get("/budget-forecasts/latest", headers=self.auth(session))).json()
        response = await self.send(session, amount=300000)
        self.assertEqual(response.status_code, 200, response.text)
        result = response.json()
        forecast = result["forecast"]
        self.assertEqual(forecast["current_balance"], 500000)
        self.assertEqual(forecast["available_amount"], before["available_amount"] - 300000)
        self.assertEqual(forecast["shortage_amount"], max(0, 300000 - before["available_amount"]))
        self.assertEqual(forecast["expected_living_cost"], before["expected_living_cost"])
        self.assertNotEqual(forecast["id"], before["id"])
        self.assertEqual(result["alert_ids"], [])
        current = await self.client.get("/budget-forecasts/latest", headers=self.auth(session))
        self.assertEqual(current.status_code, 200, current.text)
        self.assertEqual(current.json(), forecast)
        self.assertEqual(self.counts(), (1, 1, 2, 2))
        with self.sessions() as db:
            snapshot = db.get(BudgetInputSnapshot, int(forecast["snapshot_id"]))
            transaction = db.get(Transaction, result["transaction"]["id"])
            self.assertEqual(snapshot.airflow_run_id, f"transfer:{transaction.id}")
            self.assertGreaterEqual(snapshot.as_of, transaction.occurred_at)
            self.assertEqual(snapshot.current_balance, transaction.balance_after)

    async def test_missing_baseline_or_result_blocks_before_balance_changes(self):
        for table in ("user_baselines", "budget_forecasts"):
            with self.subTest(missing=table):
                session = await self.create()
                user_id = session.json()["user"]["user_id"]
                with self.sessions() as db:
                    db.execute(text(f"DELETE FROM {table} WHERE user_id=:id"), dict(id=user_id))
                    db.commit()
                before = self.counts()
                response = await self.send(session, amount=1000)
                self.assertEqual(response.status_code, 409, response.text)
                self.assertEqual(self.counts(), before)
                self.assertEqual(await self.balance(session), 800000)

    async def test_changed_budget_settings_block_direct_transfer_requests(self):
        session = await self.create()
        with self.sessions() as db:
            db.execute(text("UPDATE budget_settings SET daily_living_budget=25000 WHERE user_id='user1'"))
            db.commit()
        before = self.counts()
        response = await self.send(session)
        self.assertEqual(response.status_code, 409, response.text)
        self.assertEqual(self.counts(), before)
        self.assertEqual(await self.balance(session), 800000)
        refreshed = await self.login()
        self.assertEqual((await self.send(refreshed)).status_code, 200)

    async def test_new_date_requires_today_preparation_before_new_transfer(self):
        session = await self.create()
        with self.sessions() as db:
            tomorrow = db.scalar(select(func.clock_timestamp())) + timedelta(days=1)
        before = self.counts()
        with patch("app.baselines.service.func.clock_timestamp", return_value=literal(tomorrow)):
            response = await self.send(session)
        self.assertEqual(response.status_code, 409, response.text)
        self.assertEqual(self.counts(), before)
        self.assertEqual(await self.balance(session), 800000)

    async def test_retry_after_later_transfer_returns_original_forecast_without_writes(self):
        session = await self.create()
        key = str(uuid4())
        original = await self.send(session, amount=100000, request_id=key)
        self.assertEqual(original.status_code, 200, original.text)
        self.assertEqual((await self.send(session, amount=1000)).status_code, 200)
        before = self.counts()
        replay = await self.send(session, amount=100000, request_id=key)
        self.assertEqual(replay.json(), original.json())
        self.assertEqual(self.counts(), before)
        self.assertEqual(await self.balance(session), 699000)
        current = (await self.client.get("/budget-forecasts/latest", headers=self.auth(session))).json()
        self.assertEqual(current["current_balance"], 699000)
        self.assertNotEqual(current["id"], original.json()["forecast"]["id"])

    async def test_completed_request_replay_does_not_require_new_preparation(self):
        session = await self.create()
        key = str(uuid4())
        original = await self.send(session, request_id=key)
        with self.sessions() as db:
            db.execute(text("DELETE FROM user_baselines WHERE user_id='user1'"))
            db.commit()
        before = self.counts()
        replay = await self.send(session, request_id=key)
        self.assertEqual(replay.status_code, 200, replay.text)
        self.assertEqual(replay.json(), original.json())
        self.assertEqual(self.counts(), before)
        self.assertEqual((await self.send(session)).status_code, 409)

    async def test_forecast_database_failure_rolls_back_transaction_balance_and_snapshot(self):
        session = await self.create()
        key = str(uuid4())
        before = self.counts()

        def fail(db, **kwargs):
            db.execute(text("SELECT 1 / 0"))

        with patch("app.transactions.budgets.ensure_budget_forecast", side_effect=fail):
            with self.assertLogs("app.transactions.service", level="ERROR"):
                response = await self.send(session, request_id=key)
        self.assertEqual(response.status_code, 503, response.text)
        self.assertEqual(self.counts(), before)
        self.assertEqual(await self.balance(session), 800000)
        self.assertEqual((await self.send(session, request_id=key)).status_code, 200)
        self.assertEqual(self.counts(), (1, 1, 2, 2))

    async def test_commit_failure_rolls_back_all_flushed_changes_and_same_key_can_retry(self):
        session = await self.create()
        key = str(uuid4())
        before = self.counts()

        def fail(db):
            db.flush()
            raise SQLAlchemyError("commit-failed")

        with patch.object(Session, "commit", fail):
            with self.assertLogs("app.transactions.service", level="ERROR"):
                response = await self.send(session, request_id=key)
        self.assertEqual(response.status_code, 503)
        self.assertEqual(self.counts(), before)
        self.assertEqual(await self.balance(session), 800000)
        self.assertEqual((await self.send(session, request_id=key)).status_code, 200)

    async def test_date_rollover_during_transfer_rolls_back_before_commit(self):
        session = await self.create()
        before = self.counts()
        with self.sessions() as db:
            tomorrow = db.scalar(select(func.clock_timestamp())) + timedelta(days=1)

        def next_day(db, **kwargs):
            with patch("app.budgets.snapshots.func.clock_timestamp", return_value=literal(tomorrow)):
                return create_transfer_forecast(db, **kwargs)

        with patch("app.transactions.service.create_transfer_forecast", side_effect=next_day):
            response = await self.send(session)
        self.assertEqual(response.status_code, 409, response.text)
        self.assertEqual(self.counts(), before)
        self.assertEqual(await self.balance(session), 800000)

    async def test_different_sessions_share_user_lock_for_retries_and_overdraft(self):
        first, second = await self.create(), await self.login()
        key = str(uuid4())
        responses = await asyncio.gather(self.send(first, amount=100000, request_id=key),
                                         self.send(second, amount=100000, request_id=key))
        self.assertTrue(all(response.status_code == 200 for response in responses), [r.text for r in responses])
        self.assertEqual(responses[0].json(), responses[1].json())
        self.assertEqual(self.counts(), (1, 1, 2, 2))
        responses = await asyncio.gather(self.send(first, amount=500000), self.send(second, amount=500000))
        self.assertEqual(sorted(response.status_code for response in responses), [200, 409])
        self.assertEqual(self.counts(), (2, 1, 3, 3))
        self.assertEqual(await self.balance(first), 200000)

    async def test_missing_saved_transfer_forecast_never_recharges_or_fakes_current_result(self):
        session = await self.create()
        key = str(uuid4())
        original = await self.send(session, request_id=key)
        with self.sessions() as db:
            db.execute(text("DELETE FROM budget_forecasts WHERE id=:id"), dict(id=int(original.json()["forecast"]["id"])))
            db.commit()
        before = self.counts()
        replay = await self.send(session, request_id=key)
        self.assertEqual(replay.status_code, 503, replay.text)
        self.assertEqual(self.counts(), before)
        self.assertEqual(await self.balance(session), 680000)

    async def test_legacy_completed_transfer_without_snapshot_is_not_recreated(self):
        session = await self.create()
        key = str(uuid4())
        transaction_id = "demo-" + hashlib.sha256(f"user1:{key}".encode()).hexdigest()
        with self.sessions() as db:
            db.execute(text("""INSERT INTO transactions
                (id,account_id,user_id,occurred_at,direction,amount,balance_after,tx_type,counterparty_id,source)
                VALUES (:id,'user1-account','user1',clock_timestamp()-interval '1 hour',
                        'OUT',100000,700000,'TRANSFER','demo-payee-1','DEMO')"""), dict(id=transaction_id))
            db.execute(text("UPDATE accounts SET current_balance=700000,balance_as_of=clock_timestamp() WHERE user_id='user1'"))
            db.commit()
        before = self.counts()
        replay = await self.send(session, amount=100000, request_id=key)
        self.assertEqual(replay.status_code, 200, replay.text)
        self.assertEqual(replay.json()["transaction"]["id"], transaction_id)
        self.assertIsNone(replay.json()["forecast"])
        self.assertEqual(self.counts(), before)
        self.assertEqual(await self.balance(session), 700000)


if __name__ == "__main__":
    unittest.main()
