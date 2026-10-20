import asyncio
import os
import tempfile
import unittest
from datetime import timedelta
from pathlib import Path
from unittest.mock import patch
from uuid import uuid4

import jwt
from fastapi import Depends, FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy import create_engine, event, func, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.schema import CreateSchema, DropSchema

from app.core.auth import AUDIENCE, ISSUER, require_monitoring_consent, utc_now
from app.db.session import get_db
from app.models.demo_session import Account, Base, BudgetSetting, DemoSession, ScheduledExpense, User
from app.models.transaction import Transaction
from app.routers.demo import router
from app.routers.transfers import router as transfers_router
from app.services import demo_service
from app.services import transfer as transfer_service
from app.services.demo_monitoring import monitored_demo_user_ids

TEST_SECRET = "auth-unit-tests-only-" + "x" * 48
ROOT = Path(__file__).resolve().parents[2]


class DemoTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.env = patch.dict(os.environ, {"DEMO_JWT_SECRET": TEST_SECRET, "DEMO_SESSION_TTL_SECONDS": "86400"})
        self.env.start()
        self.postgres = os.getenv("DEMO_TEST_DATABASE_URL")
        if self.postgres:
            self.base_engine = create_engine(self.postgres, pool_pre_ping=True)
            self.schema = "auth_test_" + uuid4().hex
            with self.base_engine.begin() as conn:
                conn.exec_driver_sql("CREATE EXTENSION IF NOT EXISTS vector WITH SCHEMA public")
                conn.execute(CreateSchema(self.schema))
                conn.exec_driver_sql(f'SET LOCAL search_path = "{self.schema}", public, pg_catalog')
                migrations = sorted((ROOT / "database/migrations").glob("V*__*.sql"),
                                    key=lambda path: tuple(int(part) for part in path.name.split("__")[0][1:].split(".")))
                for migration in migrations:
                    script = migration.read_text(encoding="utf-8")
                    script = script.replace("SET LOCAL search_path = public, pg_catalog;", f'SET LOCAL search_path = "{self.schema}", public, pg_catalog;')
                    # 매개변수가 없는 전체 DDL을 전달합니다. 함수 본문의 %도 보존합니다.
                    with conn.connection.driver_connection.cursor() as cursor:
                        cursor.execute(script, prepare=False)
            self.engine = self.base_engine.execution_options(schema_translate_map={None: self.schema})
        else:
            self.temp = tempfile.TemporaryDirectory()
            self.engine = create_engine("sqlite:///" + str(Path(self.temp.name) / "auth.db"), connect_args={"check_same_thread": False})
            Base.metadata.create_all(self.engine)
        self.sessions = sessionmaker(self.engine, expire_on_commit=False)
        self.app = FastAPI()
        self.app.include_router(router)
        self.app.include_router(transfers_router)

        @self.app.get("/test/transfer-guard")
        def protected(principal=Depends(require_monitoring_consent)):
            return {"user_id": principal.user.user_id}

        def override_db():
            with self.sessions() as db:
                try:
                    yield db
                except Exception:
                    db.rollback()
                    raise

        self.app.dependency_overrides[get_db] = override_db
        self.client = AsyncClient(transport=ASGITransport(app=self.app), base_url="http://test")

    async def asyncTearDown(self):
        await self.client.aclose()
        if self.postgres:
            assert self.schema.startswith("auth_test_") and len(self.schema) == 42
            with self.base_engine.begin() as conn:
                conn.execute(DropSchema(self.schema, cascade=True))
            self.base_engine.dispose()
        else:
            self.engine.dispose()
            self.temp.cleanup()
        self.env.stop()

    async def create(self, *, key=None, consent=True, restart=False, token=None):
        headers = {"Idempotency-Key": key or str(uuid4())}
        if token:
            headers["Authorization"] = "Bearer " + token
        return await self.client.post("/demo/sessions", headers=headers,
                                      json={"acknowledged": True, "monitoring_consented": consent, "restart": restart})

    def auth(self, response):
        return {"Authorization": "Bearer " + response.json()["access_token"]}

    def count(self, model):
        with self.sessions() as db:
            return db.scalar(select(func.count()).select_from(model))

    async def test_create_and_refresh_keep_same_user_and_initial_data(self):
        response = await self.create()
        self.assertEqual(response.status_code, 200, response.text)
        data = response.json()
        self.assertTrue(data["user"]["email"].endswith("@example.invalid"))
        self.assertNotIn("password_hash", data["user"])
        first = await self.client.get("/demo/me", headers=self.auth(response))
        second = await self.client.get("/demo/me", headers=self.auth(response))
        self.assertEqual(first.json(), second.json())
        self.assertEqual(first.json()["account"]["current_balance"], 800000)
        self.assertEqual(len(first.json()["expenses"]), 2)
        self.assertEqual(self.count(BudgetSetting), 1)
        self.assertEqual(self.count(ScheduledExpense), 2)

    async def test_browser_users_and_accounts_are_isolated(self):
        a, b = await self.create(), await self.create()
        a_data = (await self.client.get("/demo/me", headers=self.auth(a))).json()
        b_data = (await self.client.get("/demo/me", headers=self.auth(b))).json()
        self.assertNotEqual(a_data["user"]["user_id"], b_data["user"]["user_id"])
        self.assertNotEqual(a_data["account"]["account_id"], b_data["account"]["account_id"])
        stolen = await self.client.get("/demo/accounts/" + b_data["account"]["account_id"], headers=self.auth(a))
        self.assertEqual(stolen.status_code, 404)
        own = await self.client.get("/demo/accounts/" + a_data["account"]["account_id"], headers=self.auth(a))
        self.assertEqual(own.status_code, 200)

    async def test_creation_key_replays_same_token_and_detects_changed_payload(self):
        key = str(uuid4())
        a, b = await self.create(key=key), await self.create(key=key)
        self.assertEqual(a.json(), b.json())
        self.assertEqual(self.count(User), 1)
        self.assertEqual((await self.create(key=key, consent=False)).status_code, 409)

    async def test_valid_token_reuses_existing_session_even_with_new_key(self):
        a = await self.create()
        b = await self.create(token=a.json()["access_token"])
        self.assertEqual(a.json(), b.json())
        self.assertEqual(self.count(User), 1)

    async def test_creation_key_cannot_switch_an_authenticated_user(self):
        key = str(uuid4())
        a = await self.create(key=key)
        b = await self.create()
        replay = await self.create(key=key, token=b.json()["access_token"])
        self.assertEqual(replay.status_code, 409)
        self.assertNotIn("access_token", replay.json())
        own = await self.client.get("/demo/me", headers=self.auth(b))
        self.assertEqual(own.json()["user"]["user_id"], b.json()["user"]["user_id"])
        await self.client.delete("/demo/sessions/current", headers=self.auth(b))
        self.assertEqual((await self.create(key=key, token=b.json()["access_token"])).status_code, 401)
        # 익명 최초 생성의 응답 유실 복구는 유지합니다.
        self.assertEqual((await self.create(key=key)).json(), a.json())

    async def test_restart_revokes_old_session_and_retry_does_not_create_more(self):
        old = await self.create()
        key = str(uuid4())
        new = await self.create(key=key, restart=True, token=old.json()["access_token"], consent=False)
        again = await self.create(key=key, restart=True, token=old.json()["access_token"], consent=False)
        self.assertEqual(new.status_code, 200, new.text)
        self.assertEqual(new.json(), again.json())
        self.assertNotEqual(old.json()["user"]["user_id"], new.json()["user"]["user_id"])
        self.assertEqual((await self.client.get("/demo/me", headers=self.auth(old))).status_code, 401)
        self.assertEqual((await self.client.get("/demo/me", headers=self.auth(new))).status_code, 200)
        self.assertEqual(self.count(User), 2)

    async def test_missing_forged_expired_and_header_only_auth_are_rejected(self):
        self.assertEqual((await self.client.get("/demo/me", headers={"X-User-Id": str(uuid4())})).status_code, 401)
        response = await self.create()
        token = response.json()["access_token"]
        wrong = jwt.encode({"sub": response.json()["user"]["user_id"]}, "wrong-" * 10, algorithm="HS256")
        self.assertEqual((await self.client.get("/demo/me", headers={"Authorization": "Bearer " + wrong})).status_code, 401)
        claims = jwt.decode(token, TEST_SECRET, algorithms=["HS256"], audience=AUDIENCE, issuer=ISSUER)
        claims["iat"] = int((utc_now() - timedelta(days=2)).timestamp())
        claims["exp"] = int((utc_now() - timedelta(days=1)).timestamp())
        expired = jwt.encode(claims, TEST_SECRET, algorithm="HS256")
        self.assertEqual((await self.client.get("/demo/me", headers={"Authorization": "Bearer " + expired})).status_code, 401)

    async def test_database_expiry_is_enforced_even_if_token_is_not_expired(self):
        response = await self.create()
        with self.sessions() as db:
            session = db.scalar(select(DemoSession))
            session.created_at = utc_now() - timedelta(days=2)
            session.expires_at = utc_now() - timedelta(days=1)
            db.commit()
        self.assertEqual((await self.client.get("/demo/me", headers=self.auth(response))).status_code, 401)

    async def test_consent_withdrawal_allows_reads_but_denies_protected_actions(self):
        response = await self.create(consent=False)
        headers = self.auth(response)
        self.assertEqual((await self.client.get("/demo/me", headers=headers)).status_code, 200)
        self.assertEqual((await self.client.get("/test/transfer-guard", headers=headers)).status_code, 403)
        await self.client.put("/demo/me/monitoring-consent", headers=headers, json={"consented": True})
        self.assertEqual((await self.client.get("/test/transfer-guard", headers=headers)).status_code, 200)
        first = await self.client.put("/demo/me/monitoring-consent", headers=headers, json={"consented": False})
        second = await self.client.put("/demo/me/monitoring-consent", headers=headers, json={"consented": False})
        self.assertEqual(first.json()["monitoring_revoked_at"], second.json()["monitoring_revoked_at"])
        self.assertEqual((await self.client.get("/demo/me", headers=headers)).status_code, 200)
        self.assertEqual((await self.client.get("/test/transfer-guard", headers=headers)).status_code, 403)

    async def test_seed_failure_rolls_back_all_rows(self):
        original = demo_service.seed_demo_user

        def fail(db, now, consented):
            original(db, now, consented)
            raise RuntimeError("simulated seed failure")

        with patch.object(demo_service, "seed_demo_user", fail):
            with self.assertRaises(RuntimeError):
                await self.create()
        for model in [User, Account, BudgetSetting, ScheduledExpense, DemoSession]:
            self.assertEqual(self.count(model), 0)

    async def test_logout_revokes_token_and_unacknowledged_or_injected_requests_fail(self):
        response = await self.create()
        headers = self.auth(response)
        self.assertEqual((await self.client.delete("/demo/sessions/current", headers=headers)).status_code, 204)
        self.assertEqual((await self.client.get("/demo/recipients", headers=headers)).status_code, 401)
        for body in [{"acknowledged": False, "monitoring_consented": True},
                     {"acknowledged": True, "monitoring_consented": True, "user_id": str(uuid4())}]:
            result = await self.client.post("/demo/sessions", headers={"Idempotency-Key": str(uuid4())}, json=body)
            self.assertEqual(result.status_code, 422)

    async def test_concurrent_creations_are_idempotent_on_postgres(self):
        if not self.postgres:
            self.skipTest("PostgreSQL integration mode required")
        key = str(uuid4())
        responses = await asyncio.gather(*(self.create(key=key) for _ in range(5)))
        self.assertTrue(all(r.status_code == 200 for r in responses), [r.text for r in responses])
        self.assertEqual(len({r.json()["access_token"] for r in responses}), 1)
        self.assertEqual(self.count(User), 1)
        self.assertEqual(self.count(Account), 1)

    async def test_monitoring_batch_excludes_expired_revoked_and_nonconsenting_users(self):
        active = await self.create()
        await self.create(consent=False)
        revoked = await self.create()
        await self.client.delete('/demo/sessions/current', headers=self.auth(revoked))
        expired = await self.create()
        with self.sessions() as db:
            session = db.scalar(select(DemoSession).where(DemoSession.user_id == expired.json()['user']['user_id']))
            session.created_at = utc_now() - timedelta(days=2)
            session.expires_at = utc_now() - timedelta(days=1)
            db.commit()
            self.assertEqual(monitored_demo_user_ids(db), [active.json()['user']['user_id']])

    async def test_concurrent_restart_replays_same_session_on_postgres(self):
        if not self.postgres:
            self.skipTest('PostgreSQL integration mode required')
        old = await self.create()
        key = str(uuid4())
        responses = await asyncio.gather(*(self.create(key=key, restart=True, token=old.json()['access_token']) for _ in range(4)))
        self.assertTrue(all(r.status_code == 200 for r in responses), [r.text for r in responses])
        self.assertEqual(len({r.json()['access_token'] for r in responses}), 1)
        self.assertEqual(self.count(User), 2)

    async def test_expired_original_token_only_recovers_an_existing_restart(self):
        old = await self.create()
        key = str(uuid4())
        new = await self.create(key=key, restart=True, token=old.json()['access_token'])
        claims = jwt.decode(old.json()['access_token'], TEST_SECRET, algorithms=['HS256'], audience=AUDIENCE)
        claims['iat'] = int((utc_now() - timedelta(days=2)).timestamp())
        claims['exp'] = int((utc_now() - timedelta(days=1)).timestamp())
        expired = jwt.encode(claims, TEST_SECRET, algorithm='HS256')
        replay = await self.create(key=key, restart=True, token=expired)
        self.assertEqual(new.json(), replay.json())
        self.assertEqual((await self.create(restart=True, token=expired)).status_code, 401)
        self.assertEqual((await self.client.get('/demo/me', headers={'Authorization': 'Bearer ' + expired})).status_code, 401)
        self.assertEqual(self.count(User), 2)

    async def test_user_header_and_mismatched_subject_cannot_change_identity(self):
        a, b = await self.create(), await self.create()
        headers = {**self.auth(a), 'X-User-Id': b.json()['user']['user_id']}
        response = await self.client.get('/demo/me', headers=headers)
        self.assertEqual(response.json()['user']['user_id'], a.json()['user']['user_id'])
        claims = jwt.decode(a.json()['access_token'], TEST_SECRET, algorithms=['HS256'], audience=AUDIENCE)
        claims['sub'] = b.json()['user']['user_id']
        mismatched = jwt.encode(claims, TEST_SECRET, algorithm='HS256')
        self.assertEqual((await self.client.get('/demo/me', headers={'Authorization': 'Bearer ' + mismatched})).status_code, 401)

    async def test_strict_consent_and_configuration_fail_before_writing(self):
        for body in [
            {'acknowledged': 1, 'monitoring_consented': True},
            {'acknowledged': True, 'monitoring_consented': 'true'},
        ]:
            response = await self.client.post('/demo/sessions', headers={'Idempotency-Key': str(uuid4())}, json=body)
            self.assertEqual(response.status_code, 422)
        with patch.dict(os.environ, {'DEMO_JWT_SECRET': ''}):
            self.assertEqual((await self.create()).status_code, 503)
        with patch.dict(os.environ, {'DEMO_SESSION_TTL_SECONDS': 'invalid'}):
            self.assertEqual((await self.create()).status_code, 503)
        self.assertEqual(self.count(User), 0)

    async def test_inactive_user_and_revoked_creation_replay_are_denied(self):
        key = str(uuid4())
        response = await self.create(key=key)
        with self.sessions() as db:
            user = db.get(User, response.json()['user']['user_id'])
            user.status = 'INACTIVE'
            db.commit()
        self.assertEqual((await self.client.get('/demo/me', headers=self.auth(response))).status_code, 401)
        self.assertEqual((await self.create(key=key)).status_code, 401)

    async def send(self, session, *, amount=120000, request_id=None, recipient="demo-payee-1"):
        return await self.client.post("/transfers", headers=self.auth(session),
                                      json={"request_id": request_id or str(uuid4()),
                                            "counterparty_id": recipient, "amount": amount})

    async def test_transfer_updates_balance_and_persists_history(self):
        session = await self.create()
        response = await self.send(session)
        self.assertEqual(response.status_code, 200, response.text)
        transaction = response.json()["transaction"]
        self.assertEqual(transaction["amount"], 120000)
        self.assertEqual(transaction["balance_after"], 680000)
        self.assertEqual(transaction["source"], "DEMO")
        context = (await self.client.get("/demo/me", headers=self.auth(session))).json()
        self.assertEqual(context["account"]["current_balance"], 680000)
        history = await self.client.get("/transactions", headers=self.auth(session))
        self.assertEqual(history.json()["items"], [transaction])
        self.assertIsNone(history.json()["next_cursor"])
        self.assertEqual(history.headers["cache-control"], "no-store")

    async def test_transfer_retry_conflicts_and_user_scoped_request_ids(self):
        a, b = await self.create(), await self.create()
        key = str(uuid4())
        first, retry = await self.send(a, request_id=key), await self.send(a, request_id=key)
        self.assertEqual(first.json(), retry.json())
        self.assertEqual((await self.send(a, request_id=key, amount=1)).status_code, 409)
        self.assertEqual((await self.send(a, request_id=key, recipient="demo-payee-2")).status_code, 409)
        self.assertEqual(self.count(Transaction), 1)
        other_history = await self.client.get("/transactions", headers=self.auth(b))
        self.assertEqual(other_history.json()["items"], [])
        other = await self.send(b, request_id=key)
        self.assertEqual(other.status_code, 200)
        self.assertNotEqual(first.json()["transaction"]["id"], other.json()["transaction"]["id"])
        self.assertEqual(self.count(Transaction), 2)

    async def test_transfer_invalid_input_and_insufficient_funds_do_not_write(self):
        session = await self.create()
        base = {"request_id": str(uuid4()), "counterparty_id": "demo-payee-1", "amount": 1000}
        for amount in [0, -1, 1.5, True, "1000", 1000000001]:
            response = await self.client.post("/transfers", headers=self.auth(session), json={**base, "amount": amount})
            self.assertEqual(response.status_code, 422)
        injected = await self.client.post("/transfers", headers=self.auth(session), json={**base, "user_id": str(uuid4())})
        self.assertEqual(injected.status_code, 422)
        self.assertEqual((await self.send(session, recipient="unknown")).status_code, 404)
        self.assertEqual((await self.send(session, amount=800001)).status_code, 409)
        self.assertEqual(self.count(Transaction), 0)
        context = (await self.client.get("/demo/me", headers=self.auth(session))).json()
        self.assertEqual(context["account"]["current_balance"], 800000)

    async def test_transfer_consent_expiry_and_read_permissions(self):
        session = await self.create(consent=False)
        self.assertEqual((await self.send(session)).status_code, 403)
        await self.client.put("/demo/me/monitoring-consent", headers=self.auth(session), json={"consented": True})
        self.assertEqual((await self.send(session)).status_code, 200)
        await self.client.put("/demo/me/monitoring-consent", headers=self.auth(session), json={"consented": False})
        self.assertEqual((await self.send(session)).status_code, 403)
        history = await self.client.get("/transactions", headers=self.auth(session))
        self.assertEqual(len(history.json()["items"]), 1)
        await self.client.delete("/demo/sessions/current", headers=self.auth(session))
        self.assertEqual((await self.send(session)).status_code, 401)
        self.assertEqual((await self.client.get("/transactions", headers=self.auth(session))).status_code, 401)

    async def test_transfer_insert_failure_rolls_back_balance(self):
        session = await self.create()

        def fail(*args):
            raise RuntimeError("simulated transaction insert failure")

        event.listen(Transaction, "before_insert", fail)
        try:
            with self.assertRaises(RuntimeError):
                await self.send(session)
        finally:
            event.remove(Transaction, "before_insert", fail)
        self.assertEqual(self.count(Transaction), 0)
        context = (await self.client.get("/demo/me", headers=self.auth(session))).json()
        self.assertEqual(context["account"]["current_balance"], 800000)

    async def test_transfer_history_cursor_handles_ties_and_rejects_other_users(self):
        session, other = await self.create(), await self.create()
        now = utc_now()
        with patch.object(transfer_service, "utc_now", return_value=now):
            for _ in range(3):
                self.assertEqual((await self.send(session, amount=1000)).status_code, 200)
        first = (await self.client.get("/transactions?limit=2", headers=self.auth(session))).json()
        second = (await self.client.get("/transactions", params={"cursor": first["next_cursor"]}, headers=self.auth(session))).json()
        self.assertEqual(len(first["items"]), 2)
        self.assertEqual(len(second["items"]), 1)
        self.assertEqual(len({item["id"] for item in first["items"] + second["items"]}), 3)
        self.assertIsNone(second["next_cursor"])
        denied = await self.client.get("/transactions", params={"cursor": first["next_cursor"]}, headers=self.auth(other))
        self.assertEqual(denied.status_code, 404)

    async def test_concurrent_transfers_are_idempotent_and_cannot_overdraw_postgres(self):
        if not self.postgres:
            self.skipTest("PostgreSQL integration mode required")
        session = await self.create()
        key = str(uuid4())
        responses = await asyncio.gather(*(self.send(session, amount=100000, request_id=key) for _ in range(4)))
        self.assertTrue(all(response.status_code == 200 for response in responses), [r.text for r in responses])
        self.assertEqual(self.count(Transaction), 1)
        responses = await asyncio.gather(*(self.send(session, amount=500000) for _ in range(2)))
        self.assertEqual(sorted(response.status_code for response in responses), [200, 409])
        self.assertEqual(self.count(Transaction), 2)
        context = (await self.client.get("/demo/me", headers=self.auth(session))).json()
        self.assertEqual(context["account"]["current_balance"], 200000)
