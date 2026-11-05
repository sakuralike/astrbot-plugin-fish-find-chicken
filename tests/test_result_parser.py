from __future__ import annotations

import unittest

from astrbot_plugin_fish_find_chicken.engines import Candidate, EngineResult
from astrbot_plugin_fish_find_chicken.result_parser import (
    format_results,
    merge_candidates,
)


class ResultParserTests(unittest.TestCase):
    def test_strict_consensus_marks_two_engines_trusted(self):
        rows = [
            EngineResult(
                "saucenao",
                [
                    Candidate(
                        "saucenao",
                        "X/Twitter",
                        "demo_user",
                        source_url="https://x.com/demo_user",
                        score=80,
                    )
                ],
            ),
            EngineResult(
                "iqdb",
                [
                    Candidate(
                        "iqdb",
                        "X/Twitter",
                        "demo_user",
                        source_url="https://x.com/demo_user",
                        score=70,
                    )
                ],
            ),
        ]
        merged = merge_candidates(rows, strict_consensus=True)
        self.assertEqual(len(merged), 1)
        self.assertTrue(merged[0].confidence)
        self.assertIn("可信候选", format_results(rows))

    def test_single_engine_candidate_is_reference_only(self):
        rows = [
            EngineResult(
                "saucenao",
                [
                    Candidate(
                        "saucenao",
                        "微博",
                        "demo",
                        source_url="https://weibo.com/demo",
                    )
                ],
            )
        ]
        text = format_results(rows)
        self.assertIn("仅供参考", text)
        self.assertIn("https://weibo.com/demo", text)

