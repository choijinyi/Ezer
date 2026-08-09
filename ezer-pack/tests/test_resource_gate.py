#!/usr/bin/env python3
"""ezer_resource_gate 단위 테스트 — stdlib unittest만 (신규 의존성 0).

대상: 치유 원복 사고로 소실됐다 vendor 흡수된 승인 수정 2건의 회귀 핀.
  ① codex 이중계수 제외(2026-07-11 CSO·CEO B승인) — NODE_EXCLUDE_PATTERNS
  ② nodes hard 동적 부서가산(2026-07-06 CSO 위임·master 승인) — nodes_hard_effective
+ evaluate가 동적 임계(m["nodes_hard_effective"])를 실제로 소비하는지, 측정 실패
  soft 격상(P-ORCH-1)이 유지되는지.
"""
import os
import sys
import types
import unittest
from unittest import mock

BIN = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "bin")
if BIN not in sys.path:
    sys.path.insert(0, BIN)

import ezer_resource_gate as G  # noqa: E402


def make_args(**over):
    """cmd_check가 받는 argparse Namespace의 테스트 대역 — 기본값은 argparse 정의와 동일."""
    a = types.SimpleNamespace(
        servers_override=None, nodes_override=None, load_override=None,
        context=None, nodes_soft=12, nodes_hard=G.NODES_HARD_DEFAULT,
        servers_soft=2, servers_hard=4,
        load_soft_ratio=1.0, load_hard_ratio=2.0,
        context_soft=50, context_hard=60,
    )
    for k, v in over.items():
        setattr(a, k, v)
    return a


class TestCodexDoubleCountExclusion(unittest.TestCase):
    """① codex 노드 1개 = wrapper + darwin-arm64 native 2프로세스 → wrapper만 계수."""

    def test_native_vendor_binary_excluded(self):
        lines = [
            "  101 node /usr/local/bin/codex serve",                 # wrapper — 계수
            "  102 /Users/x/.codex/bin/codex-darwin-arm64 --child",  # native — 제외
        ]
        self.assertEqual(G._count_matching(lines, G.NODE_PATTERNS, G.NODE_EXCLUDE_PATTERNS), 1)

    def test_exclusion_off_reproduces_inflation(self):
        # 제외 패턴이 사라지면 이중계수(2)로 회귀 — 수정 소실을 검출하는 음성 대조군.
        lines = [
            "  101 node /usr/local/bin/codex serve",
            "  102 /Users/x/.codex/bin/codex-darwin-arm64 --child",
        ]
        self.assertEqual(G._count_matching(lines, G.NODE_PATTERNS, ()), 2)

    def test_self_and_nonnode_not_counted(self):
        lines = [
            "  201 python3 bin/ezer_resource_gate.py check",  # 자기 자신 — 제외
            "  202 vim notes.md",                              # 노드 아님
            "  203 claude --dangerously-skip-permissions",     # 계수
        ]
        self.assertEqual(G._count_matching(lines, G.NODE_PATTERNS, G.NODE_EXCLUDE_PATTERNS), 1)


class TestNodesHardDynamic(unittest.TestCase):
    """② nodes hard = max(정적 floor 18, 12 + 활성부서×5) · --nodes-hard 명시 시 그 값 우선."""

    def _measure(self, depts, **arg_over):
        a = make_args(servers_override=0, nodes_override=0, load_override=0.0, **arg_over)
        with mock.patch.object(G, "_active_dept_count", return_value=depts):
            return G.measure(a)

    def test_static_floor_when_no_depts(self):
        self.assertEqual(self._measure(0)["nodes_hard_effective"], G.NODES_HARD_DEFAULT)

    def test_dynamic_overtakes_floor_from_two_depts(self):
        m = self._measure(2)
        self.assertEqual(m["nodes_hard_effective"],
                         G.NODES_HARD_BASE + 2 * G.NODES_HARD_PER_DEPT)  # 22 > floor 18
        self.assertEqual(m["active_depts"], 2)

    def test_explicit_nodes_hard_wins_over_dynamic(self):
        # 테스트 주입 등 명시 지정(기본값과 다름)이면 동적 계산 생략 — 그 값 그대로.
        self.assertEqual(self._measure(5, nodes_hard=7)["nodes_hard_effective"], 7)


class TestEvaluateConsumesDynamicHard(unittest.TestCase):
    def _eval(self, nodes, depts):
        a = make_args(servers_override=0, nodes_override=nodes, load_override=0.0)
        with mock.patch.object(G, "_active_dept_count", return_value=depts):
            m = G.measure(a)
        return G.evaluate(m, a)

    def test_old_static_hard_value_is_now_soft(self):
        # 구 임계(12)라면 hard_block 오탐이던 값이, 동적 임계(depts=2 → 22)에서는 soft.
        worst, checks = self._eval(nodes=13, depts=2)
        self.assertEqual(worst, "soft")
        node_check = next(c for c in checks if c["metric"] == "nodes")
        self.assertEqual(node_check["hard"], 22)

    def test_hard_still_trips_beyond_dynamic_ceiling(self):
        worst, _ = self._eval(nodes=22, depts=2)
        self.assertEqual(worst, "hard")

    def test_measure_errors_escalate_to_soft(self):
        # P-ORCH-1: 측정 실패는 조용한 allow 금지 — 최소 soft 격상 유지 회귀 핀.
        a = make_args(load_override=0.0)
        with mock.patch.object(G, "_active_dept_count", return_value=0), \
                mock.patch.object(G, "_ps_lines", return_value=None):
            m = G.measure(a)
        self.assertIn("nodes(ps)", m["measure_errors"])
        worst, _ = G.evaluate(m, a)
        self.assertEqual(worst, "soft")


if __name__ == "__main__":
    unittest.main()
