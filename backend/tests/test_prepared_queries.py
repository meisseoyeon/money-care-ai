import os
import unittest
from datetime import timedelta
from unittest.mock import patch

from sqlalchemy import func, literal, select, text
from sqlalchemy.dialects.postgresql import insert

from app.auth.models import AuthSession
from app.baselines.models import UserBaseline
from app.baselines.service import ensure_baseline
from app.budgets.models import BudgetForecast, BudgetInputSnapshot
from app.budgets.snapshots import ensure_budget_input_snapshot
from app.core.time import utc_now
from app.demo.models import InitializationRun
from tests.support import AuthTestCase

PATHS = ("/baselines/current", "/budget-forecasts/latest")


@unittest.skipUnless(os.getenv("DEMO_TEST_DATABASE_URL"), "PostgreSQL integration mode required")
class PreparedQueryTests(AuthTestCase):
    def result_counts(self):
        return tuple(self.count(model) for model in
                     (UserBaseline, BudgetInputSnapshot, BudgetForecast, InitializationRun, AuthSession))

    async def test_reads_prepared_results_without_writes_or_internal_metadata(self):
        session = await self.create()
        ready = session.json()["initialization"]
        before = self.result_counts()
        for _ in range(2):
            baseline = await self.client.get(PATHS[0], headers=self.auth(session))
            forecast = await self.client.get(PATHS[1], headers=self.auth(session))
            self.assertEqual(baseline.status_code, 200, baseline.text)
            self.assertEqual(forecast.status_code, 200, forecast.text)
            self.assertEqual(baseline.json()["user_id"], "user1")
            self.assertEqual(baseline.json()["out_count_30d"], 0)
            self.assertIsNone(baseline.json()["std_out_amount"])
            self.assertEqual(forecast.json()["id"], str(ready["forecast_id"]))
            self.assertEqual(forecast.json()["snapshot_id"], str(ready["snapshot_id"]))
            self.assertEqual(forecast.json()["current_balance"], 800000)
            self.assertNotIn("airflow_run_id", baseline.json())
            self.assertNotIn("accounts_snapshot", forecast.json())
            for response in (baseline, forecast):
                self.assertEqual(response.headers["cache-control"], "no-store")
        self.assertEqual(self.result_counts(), before)

    async def test_query_and_header_user_ids_cannot_access_another_user(self):
        first, second = await self.create(), await self.create()
        headers = {**self.auth(first), "X-User-Id": "user2"}
        for path in PATHS:
            response = await self.client.get(path + "?user_id=user2", headers=headers)
            self.assertEqual(response.status_code, 200, response.text)
            self.assertEqual(response.json()["user_id"], "user1")
        forecast = (await self.client.get(PATHS[1], headers=self.auth(first))).json()
        self.assertNotEqual(forecast["id"], str(second.json()["initialization"]["forecast_id"]))

    async def test_missing_revoked_and_expired_auth_is_rejected(self):
        for path in PATHS:
            self.assertEqual((await self.client.get(path)).status_code, 401)
            self.assertEqual((await self.client.get(path, headers={"X-User-Id": "user1"})).status_code, 401)
        session = await self.create()
        with self.sessions() as db:
            row = db.scalar(select(AuthSession))
            row.revoked_at = utc_now()
            db.commit()
        for path in PATHS:
            self.assertEqual((await self.client.get(path, headers=self.auth(session))).status_code, 401)
        session = await self.login()
        with self.sessions() as db:
            row = db.scalar(select(AuthSession).where(AuthSession.revoked_at.is_(None)))
            row.created_at = utc_now() - timedelta(days=2)
            row.expires_at = utc_now() - timedelta(days=1)
            db.commit()
        for path in PATHS:
            self.assertEqual((await self.client.get(path, headers=self.auth(session))).status_code, 401)

    async def test_missing_today_baseline_does_not_fall_back_to_yesterday(self):
        session = await self.create()
        with self.sessions() as db:
            db.execute(text("DELETE FROM user_baselines WHERE user_id='user1'"))
            now = db.scalar(select(func.clock_timestamp()))
            ensure_baseline(db, user_id="user1", as_of=now - timedelta(days=1), run_id="test:yesterday")
            db.commit()
        before = self.result_counts()
        response = await self.client.get(PATHS[0], headers=self.auth(session))
        self.assertEqual(response.status_code, 404)
        self.assertEqual(response.headers["cache-control"], "no-store")
        self.assertEqual(self.result_counts(), before)

    async def test_latest_input_without_result_does_not_return_older_forecast(self):
        session = await self.create()
        with self.sessions() as db:
            ensure_budget_input_snapshot(db, user_id="user1", run_id="test:missing-forecast")
            db.commit()
        before = self.result_counts()
        response = await self.client.get(PATHS[1], headers=self.auth(session))
        self.assertEqual(response.status_code, 404)
        self.assertEqual(response.headers["cache-control"], "no-store")
        self.assertEqual(self.result_counts(), before)

    async def test_transfer_refreshes_forecast_without_relogin(self):
        session = await self.create()
        self.assertEqual((await self.send(session, amount=100000)).status_code, 200)
        before = self.result_counts()
        response = await self.client.get(PATHS[1], headers=self.auth(session))
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.headers["cache-control"], "no-store")
        self.assertEqual(self.result_counts(), before)
        self.assertEqual((await self.client.get(PATHS[0], headers=self.auth(session))).status_code, 200)
        self.assertEqual(response.json()["current_balance"], 700000)

    async def test_setting_and_expense_changes_require_fresh_results(self):
        session = await self.create()
        changes = (
            "UPDATE budget_settings SET daily_living_budget=25000 WHERE user_id='user1'",
            "UPDATE budget_settings SET expected_income_amount=1200000 WHERE user_id='user1'",
            "UPDATE budget_settings SET next_income_date=next_income_date+1 WHERE user_id='user1'",
            "INSERT INTO scheduled_expenses(user_id,title,amount,due_date) SELECT user_id,'전기요금',10000,next_income_date-1 FROM budget_settings WHERE user_id='user1'",
            "UPDATE scheduled_expenses SET status='PAID' WHERE user_id='user1'",
        )
        for sql in changes:
            with self.subTest(change=sql):
                with self.sessions() as db:
                    db.execute(text(sql))
                    db.commit()
                before = self.result_counts()
                response = await self.client.get(PATHS[1], headers=self.auth(session))
                self.assertEqual(response.status_code, 409, response.text)
                self.assertEqual(self.result_counts(), before)
                session = await self.login()
                self.assertEqual((await self.client.get(PATHS[1], headers=self.auth(session))).status_code, 200)

    async def test_new_day_rejects_old_results_without_generating_new_ones(self):
        session = await self.create()
        before = self.result_counts()
        tomorrow = utc_now() + timedelta(days=1)
        with patch("app.budgets.queries.func.clock_timestamp", return_value=literal(tomorrow)):
            self.assertEqual((await self.client.get(PATHS[0], headers=self.auth(session))).status_code, 404)
            self.assertEqual((await self.client.get(PATHS[1], headers=self.auth(session))).status_code, 409)
        self.assertEqual(self.result_counts(), before)

    async def test_wrong_version_and_future_inputs_are_not_selected(self):
        session = await self.create()
        ready = session.json()["initialization"]
        with self.sessions() as db:
            row = db.get(BudgetInputSnapshot, ready["snapshot_id"])
            values = {column.name: getattr(row, column.name) for column in BudgetInputSnapshot.__table__.columns
                      if column.name != "id"}
            values["calculation_version"] = "budget-v0"
            db.execute(insert(BudgetInputSnapshot).values(**values))
            values["calculation_version"] = "budget-v1"
            values["as_of"] += timedelta(days=1)
            db.execute(insert(BudgetInputSnapshot).values(**values))
            baseline = db.scalar(select(UserBaseline).where(UserBaseline.user_id == "user1"))
            values = {column.name: getattr(baseline, column.name) for column in UserBaseline.__table__.columns}
            values["calculation_version"] = "baseline-v0"
            db.execute(insert(UserBaseline).values(**values))
            db.execute(text("DELETE FROM user_baselines WHERE user_id='user1' AND calculation_version='baseline-v1'"))
            db.commit()
        response = await self.client.get(PATHS[1], headers=self.auth(session))
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()["snapshot_id"], str(ready["snapshot_id"]))
        self.assertEqual((await self.client.get(PATHS[0], headers=self.auth(session))).status_code, 404)

    async def test_read_permissions_do_not_require_monitoring_consent(self):
        session = await self.create(consent=False)
        for path in PATHS:
            response = await self.client.get(path, headers=self.auth(session))
            self.assertEqual(response.status_code, 200, response.text)

    async def test_decimal_statistics_keep_four_places_in_json(self):
        session = await self.create()
        with self.sessions() as db:
            db.execute(text("DELETE FROM user_baselines WHERE user_id='user1'"))
            db.execute(text("""INSERT INTO transactions
                (id,account_id,user_id,occurred_at,direction,amount,balance_after,tx_type)
                VALUES ('test-out','user1-account','user1',clock_timestamp()-interval '1 day','OUT',1000,800000,'PURCHASE')"""))
            db.commit()
        session = await self.login()
        response = await self.client.get(PATHS[0], headers=self.auth(session))
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()["avg_out_amount"], "1000.0000")
        self.assertEqual(response.json()["avg_daily_spend"], "33.3333")
        self.assertIsNone(response.json()["std_out_amount"])


if __name__ == "__main__":
    unittest.main()
