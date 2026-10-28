import unittest
from datetime import datetime, timedelta, timezone
from decimal import Decimal, ROUND_DOWN, localcontext
from types import SimpleNamespace

from app.baselines.calculator import calculate_baseline


class BaselineCalculatorTests(unittest.TestCase):
    def setUp(self):
        self.as_of = datetime(2026, 10, 21, 0, 0, tzinfo=timezone.utc)

    def transaction(self, amount=1000, **overrides):
        fields = dict(user_id="user1", direction="OUT", amount=amount,
                      occurred_at=self.as_of - timedelta(days=1))
        fields.update(overrides)
        return SimpleNamespace(**fields)

    def calculate(self, rows, **overrides):
        return calculate_baseline(rows, user_id="user1", as_of=overrides.get("as_of", self.as_of))

    def test_known_sample_and_linear_percentile(self):
        result = self.calculate(self.transaction(amount) for amount in (4000, 1000, 3000, 2000))
        self.assertEqual(result.out_count_30d, 4)
        self.assertEqual(result.avg_out_amount, Decimal("2500.0000"))
        self.assertEqual(result.std_out_amount, Decimal("1290.9944"))
        self.assertEqual(result.p95_out_amount, Decimal("3850.0000"))
        self.assertEqual(result.avg_daily_spend, Decimal("333.3333"))

    def test_excludes_income_other_users_and_outside_half_open_window(self):
        start = self.as_of - timedelta(days=30)
        rows = [self.transaction(1000, occurred_at=start),
                self.transaction(2000, occurred_at=self.as_of - timedelta(microseconds=1)),
                self.transaction(9000, occurred_at=start - timedelta(microseconds=1)),
                self.transaction(9000, occurred_at=self.as_of),
                self.transaction(9000, occurred_at=self.as_of + timedelta(days=1)),
                self.transaction(9000, direction="IN"),
                self.transaction(9000, user_id="user2")]
        result = self.calculate(rows)
        self.assertEqual(result.out_count_30d, 2)
        self.assertEqual(result.avg_out_amount, Decimal("1500.0000"))
        self.assertEqual(result.avg_daily_spend, Decimal("100.0000"))
        self.assertEqual(result.window_start, start)
        self.assertEqual(result.window_end, self.as_of)

    def test_no_outflows_produces_null_statistics(self):
        for rows in ([], [self.transaction(direction="IN")]):
            with self.subTest(rows=rows):
                result = self.calculate(rows)
                self.assertEqual(result.out_count_30d, 0)
                self.assertIsNone(result.avg_out_amount)
                self.assertIsNone(result.std_out_amount)
                self.assertIsNone(result.p95_out_amount)
                self.assertIsNone(result.avg_daily_spend)

    def test_one_outflow_has_no_sample_standard_deviation(self):
        result = self.calculate([self.transaction(1000)])
        self.assertEqual(result.out_count_30d, 1)
        self.assertEqual(result.avg_out_amount, Decimal("1000.0000"))
        self.assertEqual(result.p95_out_amount, Decimal("1000.0000"))
        self.assertEqual(result.avg_daily_spend, Decimal("33.3333"))
        self.assertIsNone(result.std_out_amount)

    def test_equal_outflows_have_zero_deviation(self):
        self.assertEqual(self.calculate([self.transaction()] * 3).std_out_amount, Decimal("0.0000"))

    def test_seoul_date_and_equivalent_timezones(self):
        instant = datetime(2026, 10, 20, 16, 0, tzinfo=timezone.utc)
        seoul = timezone(timedelta(hours=9))
        row = self.transaction(occurred_at=(instant - timedelta(days=1)).astimezone(seoul))
        result = self.calculate([row], as_of=instant.astimezone(seoul))
        self.assertEqual(result.base_date.isoformat(), "2026-10-21")
        self.assertEqual(result.as_of, instant)
        self.assertEqual(result.as_of.tzinfo, timezone.utc)
        self.assertEqual(result, self.calculate([row], as_of=instant))

    def test_ignores_labels_and_source_and_does_not_mutate_input(self):
        row = self.transaction(scenario_label="RISK", source="DEMO")
        before = vars(row).copy()
        self.assertEqual(self.calculate([row]).out_count_30d, 1)
        self.assertEqual(vars(row), before)
        self.assertEqual(self.calculate([row]), self.calculate(iter([row])))

    def test_large_integer_amounts_and_rounding_do_not_use_float(self):
        rows = [self.transaction(9000000000000000000), self.transaction(9000000000000000001)]
        with localcontext() as context:
            context.prec = 6
            context.rounding = ROUND_DOWN
            result = self.calculate(rows)
        self.assertEqual(result.avg_out_amount, Decimal("9000000000000000000.5000"))
        self.assertEqual(result.std_out_amount, Decimal("0.7071"))
        self.assertEqual(result.p95_out_amount, Decimal("9000000000000000000.9500"))

    def test_rounds_half_up_at_four_decimal_places(self):
        rows = [self.transaction(1)] * 31 + [self.transaction(2)]
        self.assertEqual(self.calculate(rows).avg_out_amount, Decimal("1.0313"))

    def test_rejects_naive_times(self):
        with self.assertRaises(ValueError):
            self.calculate([], as_of=self.as_of.replace(tzinfo=None))
        with self.assertRaises(ValueError):
            self.calculate([self.transaction(occurred_at=self.as_of.replace(tzinfo=None))])

    def test_rejects_invalid_amounts_and_empty_user(self):
        for amount in (0, -1, 1.5, True, 2**63):
            with self.subTest(amount=amount), self.assertRaises(ValueError):
                self.calculate([self.transaction(amount)])
        with self.assertRaises(ValueError):
            calculate_baseline([], user_id=" ", as_of=self.as_of)


if __name__ == "__main__":
    unittest.main()
