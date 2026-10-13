"""사용 한도 게이지 (backend/limits.py): Codex 세션 기록의 rate_limits 읽기."""
import json
import unittest
from datetime import datetime, timezone

from backend import limits

NOW = datetime(2026, 10, 11, 6, 0, tzinfo=timezone.utc).timestamp()


def line(primary, secondary=None, ts="2026-10-11T05:00:00Z"):
    rl = {"primary": primary}
    if secondary:
        rl["secondary"] = secondary
    return json.dumps({"timestamp": ts, "type": "event_msg", "payload": {"type": "token_count", "rate_limits": rl}})


class CodexLimits(unittest.TestCase):
    def test_last_rate_limits_wins(self):
        got = limits.parse_codex([
            line({"used_percent": 10, "resets_in_seconds": 9000}),
            '{"type": "response_item"}',
            line({"used_percent": 38.4, "resets_in_seconds": 7200}, {"used_percent": 61, "resets_at": NOW + 86400}),
        ], now=NOW)
        self.assertEqual(got["five_hour"]["used"], 38.4)
        self.assertEqual(got["five_hour"]["resets_at"], "2026-10-11T07:00:00+00:00")   # 기록 시각 + 남은 초
        self.assertEqual(got["week"]["used"], 61.0)

    def test_window_already_reset_reads_zero(self):
        got = limits.parse_codex([line({"used_percent": 90, "resets_in_seconds": 600})], now=NOW)
        self.assertEqual(got["five_hour"]["used"], 0.0)

    def test_nothing_or_broken(self):
        self.assertIsNone(limits.parse_codex(['{"type": "response_item"}'], now=NOW))
        self.assertIsNone(limits.parse_codex([line({"used_percent": "많이"})], now=NOW))   # 형식이 바뀌면 게이지 없음
        self.assertIsNone(limits.parse_codex([line({"used_percent": 140})], now=NOW))


class ClaudeLimits(unittest.TestCase):
    def test_parse(self):
        got = limits.parse_claude({"five_hour": {"utilization": 23.0, "resets_at": "2026-10-11T09:00:00+00:00"},
                                   "seven_day": {"utilization": 47, "resets_at": None}, "seven_day_opus": None})
        self.assertEqual(got, {"five_hour": {"used": 23.0, "resets_at": "2026-10-11T09:00:00+00:00"}, "week": {"used": 47.0, "resets_at": None}})

    def test_changed_format_raises(self):   # 형식이 바뀌면 claude_usage가 None → 화면에서 Claude 칸이 사라져요
        for body in ({"five_hour": {"used": 23}}, {"five_hour": {"utilization": 23}}, {"five_hour": {"utilization": 0.5e3}, "seven_day": {"utilization": 1}}):
            with self.assertRaises((KeyError, ValueError, TypeError)):
                limits.parse_claude(body)


class ClaudeStale(unittest.TestCase):
    def test_last_value_as_of(self):
        import tempfile
        from pathlib import Path
        from unittest import mock
        with tempfile.TemporaryDirectory() as tmp, mock.patch.object(limits, "LAST", Path(tmp) / "last.json"):
            self.assertIsNone(limits.stale_claude(now=NOW))                       # 읽은 적이 없으면 칸이 없어요
            limits._save_last({"five_hour": {"used": 23.0, "resets_at": "2026-10-11T05:30:00+00:00"},
                               "week": {"used": 44.0, "resets_at": "2026-10-15T06:00:00+00:00"}})
            got = limits.stale_claude(now=NOW)
            self.assertTrue(got["stale"])
            self.assertEqual(got["five_hour"], {"used": 0.0, "resets_at": None})   # 그 뒤 풀린 5시간 창은 0%
            self.assertEqual(got["week"]["used"], 44.0)


if __name__ == "__main__":
    unittest.main()
