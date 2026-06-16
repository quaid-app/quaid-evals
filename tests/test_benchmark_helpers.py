#!/usr/bin/env python3

from __future__ import annotations

import importlib.util
from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]


def load_module(name: str, relative_path: str):
    spec = importlib.util.spec_from_file_location(name, ROOT / relative_path)
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(module)
    return module


class BenchmarkHelperTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.beam = load_module("beam_adapter", "benchmarks/beam/beam_adapter.py")
        cls.lme = load_module("longmemeval_adapter", "benchmarks/longmemeval/quaid_adapter.py")
        cls.locomo = load_module("locomo_adapter", "benchmarks/locomo/quaid_adapter.py")
        cls.gbrain = load_module("gbrain_quaid_adapter", "benchmarks/gbrain-evals/quaid_adapter.py")

    def test_beam_context_uses_quaid_summary_fields(self):
        backend = self.beam.QuaidBackend("/tmp/unused.db")
        context = backend.get_context([
            {"summary": "remember the API key failure"},
            {"snippet": "fallback snippet"},
            {"title": "last resort title"},
        ])
        self.assertIn("remember the API key failure", context)
        self.assertIn("fallback snippet", context)
        self.assertIn("last resort title", context)

    def test_longmemeval_namespace_prefix_does_not_change_recall_ids(self):
        backend = self.lme.QuaidBackend("/tmp/unused.db", namespace="q0042")
        session_id = backend._session_id({"session_id": "abc"})
        self.assertEqual(session_id, "q0042-lme-session-abc")
        self.assertEqual(
            self.lme.normalize_lme_session_id(session_id),
            "lme-session-abc",
        )
        score, expected, retrieved = self.lme.recall_score(
            [{"metadata": {"session_id": session_id}}],
            ["abc"],
            5,
        )
        self.assertEqual(score, 1.0)
        self.assertEqual(expected, ["lme-session-abc"])
        self.assertIn("lme-session-abc", retrieved)

    def test_gbrain_recall_is_bounded_by_full_relevance_set(self):
        class Backend:
            def search(self, _query, top_k=5):
                return [
                    {"slug": "docs::passages/a/one.md"},
                    {"slug": "docs::passages/a/two.md"},
                ]

        scores = self.gbrain.run_evaluation(
            Backend(),
            [{
                "id": "q1",
                "query": "bounded recall",
                "relevant_ids": ["one"],
                "relevant_files": ["two"],
            }],
            k=5,
        )
        self.assertLessEqual(scores["r_at_5"], 100.0)
        self.assertEqual(scores["r_at_5"], 100.0)

    def test_gbrain_refuses_queries_without_ground_truth(self):
        class Backend:
            def search(self, _query, top_k=5):
                return [{"slug": "docs::passages/a/one.md"}]

        with self.assertRaises(ValueError):
            self.gbrain.run_evaluation(Backend(), [{"id": "q1", "query": "fallback"}], k=5)

    def test_locomo_max_questions_filters_ingested_conversations(self):
        class Backend:
            def __init__(self):
                self.added = []
                self._page_count = 0

            def add(self, text, metadata):
                self.added.append((text, metadata))
                self._page_count += 1
                return True

            def flush_to_quaid(self):
                return True

            def search(self, _question, top_k=50):
                return [{"summary": "answer is red"}]

            def get_context(self, results):
                return results[0]["summary"]

        backend = Backend()
        conversations = [
            {
                "conversation_id": "keep",
                "sessions": [{
                    "session_id": 1,
                    "turns": [{"speaker": "A", "text": "useful"}],
                }],
            },
            {
                "conversation_id": "skip",
                "sessions": [{
                    "session_id": 1,
                    "turns": [{"speaker": "A", "text": "expensive"}],
                }],
            },
        ]
        qa_pairs = [
            {"conversation_id": "keep", "question": "color?", "answer": "red", "type": "single-hop"},
        ]

        original_generate = self.locomo.generate_answer
        original_judge = self.locomo.judge_answer
        try:
            self.locomo.generate_answer = lambda *_args, **_kwargs: "red"
            self.locomo.judge_answer = lambda *_args, **_kwargs: 1.0
            scores = self.locomo.run_locomo(
                backend,
                conversations,
                qa_pairs,
                "unused-answerer",
                "unused-judge",
                "openai",
                max_questions=1,
            )
        finally:
            self.locomo.generate_answer = original_generate
            self.locomo.judge_answer = original_judge

        self.assertEqual([text for text, _ in backend.added], ["useful"])
        self.assertEqual(scores["total_questions"], 1)
        self.assertEqual(scores["overall"], 1.0)


if __name__ == "__main__":
    unittest.main()
