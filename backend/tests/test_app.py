import unittest

from httpx import ASGITransport, AsyncClient

from app.main import app


class AppTests(unittest.IsolatedAsyncioTestCase):
    async def test_existing_api_routes_are_registered_once(self):
                expected = {
            ("GET", "/health"),
            ("POST", "/auth/login"),
            ("GET", "/auth/me"),
            ("POST", "/auth/logout"),
            ("GET", "/demo/me"),
            ("GET", "/demo/recipients"),
            ("GET", "/demo/accounts/{account_id}"),
            ("PUT", "/demo/me/monitoring-consent"),
            ("POST", "/transfers"),
            ("GET", "/transactions"),
            ("GET", "/baselines/current"),
            ("GET", "/budget-forecasts/latest"),
            ("GET", "/alerts"),
            ("POST", "/alerts/{alert_id}/seen"),
            ("POST", "/alerts/{alert_id}/response"),
        }
        registered = [(method, path) for path, methods in app.openapi()["paths"].items()
                      for method in (method.upper() for method in methods)]
        self.assertEqual(set(registered), expected)
        self.assertEqual(len(registered), len(expected))

    async def test_health_route_is_registered(self):
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            response = await client.get("/health")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"status": "ok"})

    async def test_frontend_cors_preflight(self):
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            response = await client.options(
                "/health",
                headers={
                    "Origin": "http://localhost:5173",
                    "Access-Control-Request-Method": "GET",
                },
            )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.headers["access-control-allow-origin"],
            "http://localhost:5173",
        )
