#!/usr/bin/env python3
"""test_eval_gate.py — holdout_eval 하니스 단위테스트 (TimesFM 미설치로도 통과).

순수 stdlib unittest + 합성 시계열(표준 random seed). numpy 의존 없음.
검증 포인트:
  ⓐ dummy(last-value) 가 seasonal-naive 보다 나쁜 케이스 → gate exit 1
  ⓑ 완벽예측(seasonal-naive 가 정확히 맞는 주기 신호) → MASE≈0 · gate pass
  ⓒ 분위수 coverage 계산 정확성
  ⓓ MASE 분모 0 보호 (상수 시계열 → 분모 None → 측정 불가 hard fail)

실행: python3 test_eval_gate.py  (또는 python3 -m unittest test_eval_gate -v)
"""

import json
import os
import subprocess
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import holdout_eval as H  # noqa: E402

SCRIPT = os.path.join(HERE, "holdout_eval.py")


class TestMetrics(unittest.TestCase):
    def test_seasonal_naive_denominator_basic(self):
        # m=2 주기 [1,3,1,3,1,3] → 인접 seasonal diff 모두 0 → 분모 0 보호 → None
        self.assertIsNone(H.seasonal_naive_denominator([1, 3, 1, 3, 1, 3], 2))
        # 비주기 → 양수 분모
        denom = H.seasonal_naive_denominator([1, 2, 4, 7, 11], 1)
        # |2-1|+|4-2|+|7-4|+|11-7| = 1+2+3+4 = 10, /4 = 2.5
        self.assertAlmostEqual(denom, 2.5, places=9)

    def test_seasonal_naive_denominator_insufficient(self):
        # 데이터가 m 이하 → None
        self.assertIsNone(H.seasonal_naive_denominator([5.0], 1))
        self.assertIsNone(H.seasonal_naive_denominator([5.0, 6.0], 7))

    def test_mase_denom_zero_protection(self):
        # ⓓ 분모 0(None) → mase None (silent-exclude 가 아니라 명시적 None)
        self.assertIsNone(H.mase([1.0, 2.0], [1.0, 2.0], None))

    def test_mase_perfect(self):
        # 완벽예측 → 분자 0 → MASE 0
        self.assertEqual(H.mase([3.0, 4.0], [3.0, 4.0], 2.5), 0.0)

    def test_mase_value(self):
        # mean(|a-f|)=mean(1,1)=1, denom=2 → 0.5
        self.assertAlmostEqual(H.mase([3.0, 4.0], [2.0, 5.0], 2.0), 0.5, places=9)

    def test_smape_perfect(self):
        self.assertEqual(H.smape([3.0, 4.0], [3.0, 4.0]), 0.0)

    def test_smape_zero_denom_protection(self):
        # a=f=0 항은 0 기여 (분모 0 보호)
        self.assertEqual(H.smape([0.0, 0.0], [0.0, 0.0]), 0.0)

    def test_smape_value(self):
        # a=100 f=110 → 200*10/210; a=100 f=90 → 200*10/190; 평균
        expected = (200.0 * 10 / 210 + 200.0 * 10 / 190) / 2
        self.assertAlmostEqual(H.smape([100.0, 100.0], [110.0, 90.0]), expected, places=9)

    def test_coverage_exact(self):
        # ⓒ coverage: 3개 중 2개만 구간 안 → 2/3
        actual = [5.0, 15.0, 25.0]
        lower = [0.0, 10.0, 30.0]   # 25 는 [30,40] 밖
        upper = [10.0, 20.0, 40.0]
        self.assertAlmostEqual(H.coverage(actual, lower, upper), 2.0 / 3.0, places=9)

    def test_coverage_full(self):
        self.assertEqual(H.coverage([5.0], [0.0], [10.0]), 1.0)

    def test_coverage_none_band(self):
        self.assertIsNone(H.coverage([5.0], None, None))


class TestForecasters(unittest.TestCase):
    def test_dummy_last_value(self):
        out = H.forecaster_dummy([1.0, 2.0, 9.0], 3, 1)
        self.assertEqual(out["point"], [9.0, 9.0, 9.0])
        self.assertIsNone(out["lower"])

    def test_seasonal_naive_repeats_period(self):
        # m=2, 마지막 주기 [..., 8, 9] → ŷ = 8,9,8,9
        out = H.forecaster_seasonal_naive([1.0, 2.0, 8.0, 9.0], 4, 2)
        self.assertEqual(out["point"], [8.0, 9.0, 8.0, 9.0])


class TestHoldoutGate(unittest.TestCase):
    def _periodic(self, cycles, period_vals):
        s = []
        for _ in range(cycles):
            s.extend(period_vals)
        return s

    def test_perfect_seasonal_pass(self):
        # ⓑ seasonal-naive forecaster 가 hold-out 을 정확히 맞춤 → MASE≈0.
        # 첫 주기만 살짝 다르게(=in-sample seasonal diff 0 회피, 분모>0) + 나머지는 정확 반복.
        series = [11.0, 19.0, 31.0, 39.0] + self._periodic(5, [10.0, 20.0, 30.0, 40.0])  # m=4, 24점
        res = H.holdout_eval(series, k=4, m=4, forecaster="seasonal-naive",
                             gate_vs=None, timesfm_script="/nonexistent")
        self.assertIsNotNone(res["metrics"]["mase_denominator"])
        self.assertGreater(res["metrics"]["mase_denominator"], 0.0)
        self.assertAlmostEqual(res["metrics"]["MASE"], 0.0, places=9)

    def test_dummy_worse_than_seasonal_gate_fail(self):
        # ⓐ 주기 신호에서 dummy(last-value)는 seasonal-naive 보다 나쁨 → gate-vs seasonal-naive → fail.
        # 분모>0 보장 위해 첫 주기만 다르게(측정불가가 아니라 '실제로 더 나빠서' fail 임을 보증).
        series = [11.0, 19.0, 31.0, 39.0] + self._periodic(5, [10.0, 20.0, 30.0, 40.0])
        res = H.holdout_eval(series, k=4, m=4, forecaster="dummy",
                             gate_vs="seasonal-naive", timesfm_script="/nonexistent")
        self.assertIsNotNone(res["metrics"]["MASE"])
        self.assertGreater(res["baseline_compare"]["forecaster_MASE"],
                           res["baseline_compare"]["baseline_MASE"])
        self.assertFalse(res["gate_pass"])
        self.assertFalse(res["baseline_compare"]["forecaster_better"])

    def test_seasonal_not_strictly_better_denied(self):
        # seasonal-naive vs seasonal-naive → 동률 → strictly-better 아님 → deny-by-default fail.
        series = [11.0, 19.0, 31.0, 39.0] + self._periodic(5, [10.0, 20.0, 30.0, 40.0])
        res = H.holdout_eval(series, k=4, m=4, forecaster="seasonal-naive",
                             gate_vs="seasonal-naive", timesfm_script="/nonexistent")
        self.assertIsNotNone(res["metrics"]["MASE"])
        self.assertFalse(res["gate_pass"])  # 동률은 우위 입증 실패

    def test_constant_series_denom_zero_hardfail(self):
        # ⓓ 상수 시계열 → seasonal-naive 분모 0 → MASE None → gate 측정불가 hard fail
        series = [5.0] * 30
        res = H.holdout_eval(series, k=3, m=1, forecaster="dummy",
                             gate_vs="seasonal-naive", timesfm_script="/nonexistent")
        self.assertIsNone(res["metrics"]["MASE"])
        self.assertFalse(res["gate_pass"])
        self.assertIn("측정 불가", res["gate_reason"])

    def test_label_present(self):
        series = self._periodic(6, [10.0, 20.0, 30.0, 40.0])
        res = H.holdout_eval(series, k=4, m=4, forecaster="seasonal-naive",
                             gate_vs=None, timesfm_script="/nonexistent")
        self.assertEqual(res["label"], "hold-out 실측·self-reported 아님")

    def test_insufficient_length_raises(self):
        with self.assertRaises(ValueError):
            H.holdout_eval([1.0, 2.0, 3.0], k=2, m=2, forecaster="dummy",
                           gate_vs=None, timesfm_script="/nonexistent")


class TestCLIExitCodes(unittest.TestCase):
    """결정론 게이트=exit code 가 사실. CLI 끝단까지 검증."""

    def _run(self, series, extra):
        proc = subprocess.run(
            [sys.executable, SCRIPT, "--series", "-"] + extra,
            input=json.dumps(series),
            capture_output=True,
            text=True,
        )
        return proc

    def test_cli_dummy_gate_fail_exit1(self):
        # ⓐ CLI: dummy vs seasonal-naive gate → exit 1 (분모>0 보장 → '더 나빠서' fail)
        series = [11.0, 19.0, 31.0, 39.0] + [10.0, 20.0, 30.0, 40.0] * 5
        proc = self._run(series, ["--k", "4", "--seasonality", "4",
                                  "--forecaster", "dummy", "--gate-vs", "seasonal-naive"])
        self.assertEqual(proc.returncode, 1, msg=proc.stdout + proc.stderr)
        out = json.loads(proc.stdout)
        self.assertFalse(out["gate_pass"])
        self.assertIsNotNone(out["metrics"]["MASE"])

    def test_cli_no_gate_exit0(self):
        series = [10.0, 20.0, 30.0, 40.0] * 6
        proc = self._run(series, ["--k", "4", "--seasonality", "4", "--forecaster", "dummy"])
        self.assertEqual(proc.returncode, 0, msg=proc.stdout + proc.stderr)

    def test_cli_constant_denom_zero_exit1(self):
        # ⓓ CLI: 상수 시계열 gate → 측정불가 exit 1
        proc = self._run([5.0] * 30, ["--k", "3", "--seasonality", "1",
                                      "--forecaster", "dummy", "--gate-vs", "seasonal-naive"])
        self.assertEqual(proc.returncode, 1, msg=proc.stdout + proc.stderr)

    def test_cli_timesfm_missing_script_exit2(self):
        # TimesFM 미설치 + timesfm forecaster + 스크립트 없음 → RuntimeError → exit 2 (measurement failure)
        proc = self._run([10.0, 20.0, 30.0, 40.0] * 6,
                         ["--k", "4", "--seasonality", "4", "--forecaster", "timesfm",
                          "--timesfm-script", "/nonexistent/timesfm_forecast.py"])
        self.assertEqual(proc.returncode, 2, msg=proc.stdout + proc.stderr)
        out = json.loads(proc.stdout)
        self.assertFalse(out["gate_pass"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
