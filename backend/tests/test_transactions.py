import asyncio
from unittest.mock import patch
from uuid import uuid4
from sqlalchemy import event
from app.core.time import utc_now
from app.transactions.models import Transaction
from app.transactions import service as transfer_service
from tests.support import AuthTestCase


class TransactionTests(AuthTestCase):
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
        await self.client.post("/auth/logout", headers=self.auth(session))
        self.assertEqual((await self.send(session)).status_code, 401)
        self.assertEqual((await self.client.get("/transactions", headers=self.auth(session))).status_code, 401)


    async def test_transfer_insert_failure_rolls_back_balance(self):
        session = await self.create()

        def fail(*args):
            raise RuntimeError("simulated transaction insert failure")

        event.listen(Transaction, "before_insert", fail)
        try:
            with self.assertLogs("app.transactions.service", level="ERROR"):
                response = await self.send(session)
            self.assertEqual(response.status_code, 503)
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

