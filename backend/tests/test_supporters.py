"""실제 DDL로 소유권, 원자성, 동시 실행과 철회를 검증합니다."""
import asyncio
import os
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import Barrier
from unittest.mock import patch
from uuid import uuid4

from fastapi import HTTPException
from sqlalchemy import text

from app.alerts.router import router as alerts_router
from app.alerts.service import save_response
from app.supporters import service
from app.supporters.router import router as supporters_router
from tests.support import AuthTestCase


@unittest.skipUnless(os.getenv("DEMO_TEST_DATABASE_URL"), "PostgreSQL integration mode required")
class SupporterTests(AuthTestCase):
    def setUp(self):
        super().setUp()
        self.app.include_router(alerts_router)
        self.app.include_router(supporters_router)

    async def setup_accounts(self):
        owner = await self.create()
        self.assertEqual(owner.status_code, 200, owner.text)
        self.seed_supporter()
        with patch("app.auth.service.ensure_initial_preparation", side_effect=AssertionError("supporter preparation")):
            supporter = await self.login("supporter1")
        self.assertEqual(supporter.status_code, 200, supporter.text)
        self.assertEqual(supporter.json()["user"]["role"], "SUPPORTER")
        return self.auth(owner), self.auth(supporter)

    def seed_supporter(self):
        script = (Path(__file__).resolve().parents[2] / "database/seeds/supporter1.sql").read_text(encoding="utf-8")
        script = script.replace("SET LOCAL search_path = public, pg_catalog;",
                                f'SET LOCAL search_path = "{self.schema}", public, pg_catalog;')
        with self.engine.connect().execution_options(isolation_level="AUTOCOMMIT") as conn:
            with conn.connection.driver_connection.cursor() as cursor:
                cursor.execute(script, prepare=False)

    def alert(self, user_id="user1"):
        alert_id, tx_id = str(uuid4()), str(uuid4())
        with self.sessions() as db:
            db.execute(text("""
                INSERT INTO transactions (id,account_id,user_id,occurred_at,received_at,direction,
                    amount,balance_after,tx_type,channel,source)
                VALUES (:tx,:account,:user,CURRENT_TIMESTAMP,CURRENT_TIMESTAMP,'OUT',120000,
                    680000,'TRANSFER','BANK_TRANSFER','DEMO')
            """), {"tx": tx_id, "account": user_id+"-account", "user": user_id})
            detection = db.execute(text("""
                INSERT INTO detections (user_id,transaction_id,detection_type,detection_method,
                    detector_version,execution_mode,event_key,evidence)
                VALUES (:user,:tx,'LARGE_OUTFLOW','RULE','test','LIVE',:tx,'{}') RETURNING id
            """), {"user": user_id, "tx": tx_id}).scalar_one()
            db.execute(text("""
                INSERT INTO alerts (id,user_id,detection_id,alert_type,dedupe_key)
                VALUES (CAST(:id AS uuid),:user,:detection,'LARGE_OUTFLOW',:tx)
            """), {"id": alert_id, "user": user_id, "detection": detection, "tx": tx_id})
            db.execute(text("""
                INSERT INTO alert_explanations (alert_id,generation_status,text,method,
                    template_version,validated,latency_ms,generated_at)
                VALUES (CAST(:id AS uuid),'SUCCEEDED','함께 확인해 주세요.','FALLBACK','test',true,0,CURRENT_TIMESTAMP)
            """), {"id": alert_id})
            db.commit()
        return alert_id

    def rows(self, sql):
        with self.sessions() as db:
            return [dict(row) for row in db.execute(text(sql)).mappings()]

    async def help(self, headers, alert_id):
        return await self.client.post(f"/alerts/{alert_id}/response", headers=headers,
                                      json={"response": "HELP_REQUESTED"})

    async def test_login_shared_whitelist_and_account_isolation(self):
        owner, supporter = await self.setup_accounts()
        alert_id = self.alert()
        self.alert()  # 공유하지 않은 다른 알림은 반환하지 않습니다.
        context = await self.client.get("/demo/me", headers=supporter)
        self.assertIsNone(context.json()["account"])
        self.assertEqual((await self.client.get("/auth/me", headers=supporter)).json()["user"]["role"], "SUPPORTER")
        self.assertEqual((await self.help(owner, alert_id)).status_code, 200)
        result = await self.client.get("/shared-alerts", headers=supporter)
        self.assertEqual(result.headers["cache-control"], "no-store")
        self.assertEqual(len(result.json()), 1)
        item = result.json()[0]
        self.assertEqual(item["alert_id"], alert_id)
        self.assertEqual(item["explanation"], "함께 확인해 주세요.")
        self.assertEqual(set(item), {"share_id","alert_id","owner_name","shared_at","title","alert_type",
                                     "explanation","guide","amount","created_at"})
        self.assertEqual((await self.client.get("/transactions?user_id=user1", headers=supporter)).json()["items"], [])
        self.assertEqual((await self.client.get("/demo/accounts/user1-account", headers=supporter)).status_code, 404)
        self.assertEqual((await self.client.get("/alerts", headers=supporter)).json(), [])
        self.assertEqual((await self.help(supporter, alert_id)).status_code, 404)
        self.assertEqual((await self.client.get("/shared-alerts", headers=owner)).status_code, 403)
        self.assertEqual((await self.client.get("/supporter-links", headers=supporter)).status_code, 403)
        self.assertEqual((await self.client.get("/shared-alerts", headers={"X-User-Id":"supporter1"})).status_code, 401)

    async def test_repeated_help_and_single_revocation_preserve_times(self):
        owner, supporter = await self.setup_accounts()
        alert_id = self.alert()
        self.assertEqual((await self.help(owner, alert_id)).status_code, 200)
        first = self.rows("SELECT * FROM alert_shares")[0]
        response_time = self.rows("SELECT responded_at FROM alerts")[0]["responded_at"]
        self.assertEqual((await self.help(owner, alert_id)).status_code, 200)
        self.assertEqual(self.rows("SELECT * FROM alert_shares"), [first])
        self.assertEqual(self.rows("SELECT responded_at FROM alerts")[0]["responded_at"], response_time)
        path = f'/alert-shares/{first["id"]}/revoke'
        revoked = await self.client.post(path, headers=owner)
        self.assertEqual(revoked.status_code, 200)
        self.assertEqual((await self.client.post(path, headers=owner)).json(), revoked.json())
        self.assertEqual((await self.client.get("/shared-alerts", headers=supporter)).json(), [])
        self.assertEqual((await self.help(owner, alert_id)).status_code, 409)

    async def test_link_revocation_cascades_and_seed_does_not_reactivate(self):
        owner, supporter = await self.setup_accounts()
        for _ in range(2):
            self.assertEqual((await self.help(owner, self.alert())).status_code, 200)
        link = (await self.client.get("/supporter-links", headers=owner)).json()[0]
        revoked = await self.client.post(f'/supporter-links/{link["id"]}/revoke', headers=owner)
        self.assertEqual(revoked.status_code, 200)
        self.assertEqual((await self.client.post(f'/supporter-links/{link["id"]}/revoke', headers=owner)).json(), revoked.json())
        self.seed_supporter()
        self.assertEqual(self.rows("SELECT status FROM supporter_links"), [{"status":"REVOKED"}])
        self.assertEqual(self.rows("SELECT status FROM alert_shares"), [{"status":"REVOKED"}]*2)
        self.assertEqual((await self.client.get("/shared-alerts", headers=supporter)).json(), [])
        alert_id = self.alert()
        self.assertEqual((await self.help(owner, alert_id)).status_code, 409)
        self.assertIsNone(next(row for row in self.rows("SELECT id,user_response FROM alerts") if str(row["id"]) == alert_id)["user_response"])

    async def test_wrong_owner_and_inactive_participants(self):
        owner, supporter = await self.setup_accounts()
        other = self.auth(await self.create())
        alert_id = self.alert()
        self.assertEqual((await self.help(other, alert_id)).status_code, 404)
        self.assertEqual((await self.help(owner, alert_id)).status_code, 200)
        share = self.rows("SELECT id FROM alert_shares")[0]["id"]
        link = self.rows("SELECT id FROM supporter_links")[0]["id"]
        self.assertEqual((await self.client.get("/alert-shares", headers=other)).json(), [])
        self.assertEqual((await self.client.get("/supporter-links", headers=other)).json(), [])
        for path in [f"/alert-shares/{share}/revoke", f"/supporter-links/{link}/revoke"]:
            self.assertEqual((await self.client.post(path, headers=other)).status_code, 404)
        with self.sessions() as db:
            db.execute(text("UPDATE users SET status='INACTIVE' WHERE user_id='user1'"))
            db.commit()
        self.assertEqual((await self.client.get("/shared-alerts", headers=supporter)).json(), [])
        with self.sessions() as db:
            db.execute(text("UPDATE users SET status='INACTIVE' WHERE user_id='supporter1'"))
            db.commit()
        self.assertEqual((await self.client.get("/shared-alerts", headers=supporter)).status_code, 401)

    async def test_failed_response_rolls_back_inserted_share(self):
        await self.setup_accounts()
        alert_id = self.alert()
        with self.sessions() as db, patch("app.alerts.service._save_response", side_effect=RuntimeError("test failure")):
            with self.assertRaises(RuntimeError):
                save_response(db, "user1", alert_id, "HELP_REQUESTED")
        self.assertEqual(self.rows("SELECT * FROM alert_shares"), [])
        self.assertEqual(self.rows("SELECT status,user_response FROM alerts"), [{"status":"NEW","user_response":None}])

    async def test_failed_share_rolls_back_response_and_existing_response_survives(self):
        owner, _ = await self.setup_accounts()
        alert_id = self.alert()
        await self.client.post(f"/alerts/{alert_id}/response", headers=owner, json={"response":"PLANNED"})
        with self.sessions() as db:
            db.execute(text("UPDATE users SET status='INACTIVE' WHERE user_id='supporter1'"))
            db.commit()
        self.assertEqual((await self.help(owner, alert_id)).status_code, 409)
        self.assertEqual(self.rows("SELECT user_response FROM alerts"), [{"user_response":"PLANNED"}])
        self.assertEqual(self.rows("SELECT * FROM alert_shares"), [])

    async def test_concurrent_help_is_one_share(self):
        await self.setup_accounts()
        alert_id, barrier = self.alert(), Barrier(4)
        def submit():
            with self.sessions() as db:
                barrier.wait(timeout=10)
                return save_response(db,"user1",alert_id,"HELP_REQUESTED")
        def run():
            with ThreadPoolExecutor(max_workers=4) as pool:
                return list(pool.map(lambda _: submit(), range(4)))
        results = await asyncio.to_thread(run)
        self.assertEqual(len(results), 4)
        self.assertEqual(len(self.rows("SELECT * FROM alert_shares")), 1)

    async def test_help_and_link_revocation_leave_no_active_share(self):
        await self.setup_accounts()
        alert_id, barrier = self.alert(), Barrier(2)
        link_id = self.rows("SELECT id FROM supporter_links")[0]["id"]
        def submit_help():
            with self.sessions() as db:
                barrier.wait(timeout=10)
                try:
                    save_response(db,"user1",alert_id,"HELP_REQUESTED")
                    return 200
                except HTTPException as exc:
                    return exc.status_code
        def revoke():
            with self.sessions() as db:
                barrier.wait(timeout=10)
                service.revoke_link(db,"user1",link_id)
                db.commit()
        def run():
            with ThreadPoolExecutor(max_workers=2) as pool:
                help_future, revoke_future = pool.submit(submit_help), pool.submit(revoke)
                result = help_future.result(timeout=15)
                revoke_future.result(timeout=15)
                return result
        self.assertIn(await asyncio.to_thread(run), (200,409))
        self.assertEqual(self.rows("SELECT * FROM alert_shares WHERE status='ACTIVE'"), [])

    async def test_revocation_started_before_sharing_uses_time_after_lock(self):
        owner, supporter = await self.setup_accounts()
        alert_id = self.alert()
        link_id = self.rows("SELECT id FROM supporter_links")[0]["id"]
        with self.sessions() as db:
            # 먼저 시작한 요청이 인증 이후 잠금을 늦게 얻는 상황을 재현합니다.
            db.execute(text("SELECT CURRENT_TIMESTAMP"))
            self.assertEqual((await self.help(owner, alert_id)).status_code, 200)
            service.revoke_link(db, "user1", link_id)
            db.commit()
        self.assertEqual((await self.client.get("/shared-alerts", headers=supporter)).json(), [])
