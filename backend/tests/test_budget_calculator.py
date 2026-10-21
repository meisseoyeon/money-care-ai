import unittest
from dataclasses import asdict
from datetime import date, datetime, timedelta, timezone
from types import SimpleNamespace

from app.budgets.calculator import calculate_forecast


class BudgetCalculatorTests(unittest.TestCase):
    def snapshot(self, **overrides):
        as_of = datetime(2026, 10, 20, 15, tzinfo=timezone.utc)
        values = dict(id=1, user_id="user1", as_of=as_of, balance_as_of=as_of - timedelta(hours=1),
                      next_income_date=date(2026, 11, 10), current_balance=800000,
                      scheduled_expense_total=150000, daily_living_budget=20000,
                      expected_income_amount=1000000, calculation_version="budget-v1")
        values.update(overrides)
        return SimpleNamespace(**values)

    def test_known_forecast_and_unchanged_input(self):
        snapshot = self.snapshot()
        before = vars(snapshot).copy()
        result = calculate_forecast(snapshot)
        self.assertEqual(result.remaining_days, 20)
        self.assertEqual(result.expected_living_cost, 400000)
        self.assertEqual(result.available_amount, 250000)
        self.assertEqual(result.shortage_amount, 0)
        self.assertEqual(result.snapshot_id, snapshot.id)
        self.assertEqual(result.user_id, snapshot.user_id)
        self.assertEqual(result.as_of, snapshot.as_of)
        self.assertEqual(result.balance_as_of, snapshot.balance_as_of)
        self.assertEqual(result.calculation_version, "budget-v1")
        self.assertEqual(vars(snapshot), before)
        self.assertEqual(result, calculate_forecast(snapshot))

    def test_shortage_is_positive_and_available_stays_negative(self):
        result = calculate_forecast(self.snapshot(current_balance=500000))
        self.assertEqual(result.available_amount, -50000)
        self.assertEqual(result.shortage_amount, 50000)

    def test_exactly_enough_has_no_shortage(self):
        result = calculate_forecast(self.snapshot(current_balance=550000))
        self.assertEqual(result.available_amount, 0)
        self.assertEqual(result.shortage_amount, 0)

    def test_expected_income_is_not_added(self):
        self.assertEqual(calculate_forecast(self.snapshot(expected_income_amount=0)),
                         calculate_forecast(self.snapshot(expected_income_amount=900000000)))

    def test_uses_seoul_date_and_not_system_current_date(self):
        snapshot = self.snapshot()
        seoul = timezone(timedelta(hours=9))
        result = calculate_forecast(snapshot)
        self.assertEqual(result.remaining_days, 20)
        self.assertEqual(result, calculate_forecast(self.snapshot(as_of=snapshot.as_of.astimezone(seoul))))

    def test_income_today_has_no_remaining_living_cost(self):
        result = calculate_forecast(self.snapshot(next_income_date=date(2026, 10, 21)))
        self.assertEqual(result.remaining_days, 0)
        self.assertEqual(result.expected_living_cost, 0)
        self.assertEqual(result.available_amount, 650000)

    def test_month_and_leap_year_boundaries(self):
        for year, days in ((2026, 1), (2024, 2)):
            as_of = datetime(year, 2, 28, 0, tzinfo=timezone.utc)
            with self.subTest(year=year):
                result = calculate_forecast(self.snapshot(as_of=as_of, balance_as_of=as_of,
                                                         next_income_date=date(year, 3, 1)))
                self.assertEqual(result.remaining_days, days)

    def test_zero_budget_and_negative_balance_are_supported(self):
        result = calculate_forecast(self.snapshot(current_balance=-1000, daily_living_budget=0,
                                                 scheduled_expense_total=0))
        self.assertEqual(result.expected_living_cost, 0)
        self.assertEqual(result.available_amount, -1000)
        self.assertEqual(result.shortage_amount, 1000)

    def test_money_uses_exact_integer_arithmetic(self):
        result = calculate_forecast(self.snapshot(current_balance=9000000000000000001,
                                                 daily_living_budget=1, scheduled_expense_total=1))
        self.assertEqual(result.available_amount, 8999999999999999980)
        self.assertTrue(all(type(value) is int for key, value in asdict(result).items()
                            if key in ("remaining_days", "expected_living_cost", "available_amount", "shortage_amount")))

    def test_rejects_invalid_times_dates_and_versions(self):
        naive = datetime(2026, 10, 21)
        for overrides in (dict(as_of=naive), dict(balance_as_of=naive),
                          dict(balance_as_of=datetime(2026, 10, 22, tzinfo=timezone.utc)),
                          dict(next_income_date=date(2026, 10, 20)), dict(calculation_version="budget-v0")):
            with self.subTest(overrides=overrides), self.assertRaises(ValueError):
                calculate_forecast(self.snapshot(**overrides))

    def test_rejects_invalid_amounts_and_overflow(self):
        for overrides in (dict(daily_living_budget=-1), dict(scheduled_expense_total=-1),
                          dict(current_balance=1.5), dict(current_balance=True),
                          dict(current_balance=2**63), dict(daily_living_budget=2**63 - 1),
                          dict(current_balance=-(2**63), daily_living_budget=0, scheduled_expense_total=0)):
            with self.subTest(overrides=overrides), self.assertRaises(ValueError):
                calculate_forecast(self.snapshot(**overrides))


if __name__ == "__main__":
    unittest.main()
