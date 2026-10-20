import os
from datetime import timedelta
from unittest.mock import patch
import jwt
from sqlalchemy import select
from app.auth.dependencies import AUDIENCE
from app.core.time import utc_now
from app.auth.models import AuthSession
from app.users.models import User
from app.accounts.models import Account
from app.auth.passwords import verify_password
from app.monitoring.service import monitored_demo_user_ids
from tests.support import AuthTestCase, TEST_SECRET


class AuthTests(AuthTestCase):
    async def test_username_password_login_and_restore(self):
        response = await self.create()
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()["user"]["user_id"], "user1")
        self.assertNotIn("password_hash", response.json()["user"])
        claims = jwt.decode(response.json()["access_token"], TEST_SECRET, algorithms=["HS256"], audience=AUDIENCE)
        self.assertEqual(claims["sub"], "user1")
        restored = await self.client.get("/auth/me", headers=self.auth(response))
        self.assertEqual(restored.json()["user"], response.json()["user"])
        self.assertEqual(restored.headers["cache-control"], "no-store")
        self.assertEqual(self.count(User), 1)
        self.assertEqual(self.count(Account), 1)


    async def test_wrong_unknown_and_inactive_accounts_do_not_create_users_or_sessions(self):
        await self.create()
        for username, password in [("user1", "wrong"), ("nobody", "demo1234!")]:
            response = await self.login(username, password)
            self.assertEqual(response.status_code, 401)
            self.assertNotIn("access_token", response.json())
        with self.sessions() as db:
            db.get(User, "user1").status = "INACTIVE"
            db.commit()
        self.assertEqual((await self.login()).status_code, 401)
        self.assertEqual(self.count(User), 1)
        self.assertEqual(self.count(AuthSession), 1)


    async def test_shared_account_independent_sessions_and_persistent_balance(self):
        first = await self.create()
        second = await self.login()
        self.assertNotEqual(first.json()["access_token"], second.json()["access_token"])
        self.assertEqual(first.json()["user"]["user_id"], second.json()["user"]["user_id"])
        self.assertEqual((await self.send(first, amount=10000)).status_code, 200)
        me = (await self.client.get("/demo/me", headers=self.auth(second))).json()
        self.assertEqual(me["account"]["current_balance"], 790000)
        self.assertEqual((await self.client.post("/auth/logout", headers=self.auth(first))).status_code, 204)
        self.assertEqual((await self.client.get("/auth/me", headers=self.auth(first))).status_code, 401)
        self.assertEqual((await self.client.get("/auth/me", headers=self.auth(second))).status_code, 200)
        third = await self.login()
        me = (await self.client.get("/demo/me", headers=self.auth(third))).json()
        self.assertEqual(me["account"]["current_balance"], 790000)
        self.assertEqual(self.count(User), 1)


    async def test_removed_auto_creation_endpoint_cannot_create_anything(self):
        for body in [{"acknowledged": True, "monitoring_consented": True}, {"restart": True}]:
            response = await self.client.post("/demo/sessions", json=body)
            self.assertEqual(response.status_code, 404)
        self.assertEqual(self.count(User), 0)
        self.assertEqual(self.count(AuthSession), 0)


    async def test_invalid_forged_expired_and_legacy_tokens_are_rejected(self):
        response = await self.create()
        headers = self.auth(response)
        self.assertEqual((await self.client.get("/auth/me", headers={"X-User-Id": "user1"})).status_code, 401)
        claims = jwt.decode(response.json()["access_token"], TEST_SECRET, algorithms=["HS256"], audience=AUDIENCE)
        forged = jwt.encode(claims, "wrong-"*10, algorithm="HS256")
        self.assertEqual((await self.client.get("/auth/me", headers={"Authorization":"Bearer "+forged})).status_code, 401)
        claims["aud"] = "money-care-demo"
        legacy = jwt.encode(claims, TEST_SECRET, algorithm="HS256")
        self.assertEqual((await self.client.get("/auth/me", headers={"Authorization":"Bearer "+legacy})).status_code, 401)
        with self.sessions() as db:
            session = db.scalar(select(AuthSession))
            session.created_at = utc_now()-timedelta(days=2)
            session.expires_at = utc_now()-timedelta(days=1)
            db.commit()
        self.assertEqual((await self.client.get("/auth/me", headers=headers)).status_code, 401)
        fresh = await self.login()
        claims = jwt.decode(fresh.json()["access_token"], TEST_SECRET, algorithms=["HS256"], audience=AUDIENCE)
        claims["iat"] = int((utc_now()-timedelta(days=2)).timestamp())
        claims["exp"] = int((utc_now()-timedelta(days=1)).timestamp())
        token = jwt.encode(claims, TEST_SECRET, algorithm="HS256")
        self.assertEqual((await self.client.get("/auth/me", headers={"Authorization":"Bearer "+token})).status_code, 401)


    async def test_login_validation_and_bad_config_never_create_sessions(self):
        for body in [{"username": "user1", "password": "demo1234!", "user_id": "other"},
                     {"username": "user1", "password": 123}, {"username": "", "password": "x"}]:
            self.assertEqual((await self.client.post("/auth/login", json=body)).status_code, 422)
        await self.create()
        with patch.dict(os.environ, {"DEMO_JWT_SECRET": ""}):
            self.assertEqual((await self.login()).status_code, 503)
        with patch.dict(os.environ, {"AUTH_SESSION_TTL_SECONDS": "bad"}):
            self.assertEqual((await self.login()).status_code, 503)
        self.assertEqual(self.count(AuthSession), 1)


    async def test_invalid_password_hash_and_subject_mismatch(self):
        first, second = await self.create(), await self.create()
        self.assertFalse(verify_password("demo1234!", "plaintext"))
        self.assertFalse(verify_password("demo1234!", "scrypt$999999999$8$1$00$00"))
        headers = {**self.auth(first), "X-User-Id": "user2"}
        self.assertEqual((await self.client.get("/auth/me", headers=headers)).json()["user"]["user_id"], "user1")
        claims = jwt.decode(first.json()["access_token"], TEST_SECRET, algorithms=["HS256"], audience=AUDIENCE)
        claims["sub"] = "user2"
        bad = jwt.encode(claims, TEST_SECRET, algorithm="HS256")
        self.assertEqual((await self.client.get("/auth/me", headers={"Authorization":"Bearer "+bad})).status_code, 401)
        with self.sessions() as db:
            db.get(User,"user1").password_hash = "invalid"
            db.commit()
        self.assertEqual((await self.login()).status_code, 401)


    async def test_monitoring_batch_returns_shared_user_once_and_respects_logout(self):
        first = await self.create()
        second = await self.login()
        await self.create(consent=False)
        with self.sessions() as db:
            self.assertEqual(monitored_demo_user_ids(db), ["user1"])
        await self.client.post("/auth/logout", headers=self.auth(first))
        with self.sessions() as db:
            self.assertEqual(monitored_demo_user_ids(db), ["user1"])
        await self.client.post("/auth/logout", headers=self.auth(second))
        with self.sessions() as db:
            self.assertEqual(monitored_demo_user_ids(db), [])

