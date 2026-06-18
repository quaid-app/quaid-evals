#!/usr/bin/env python3

from __future__ import annotations

import importlib.util
import urllib.error
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
        cls.collector = load_module("artifact_collector", "scripts/collect-benchmark-artifacts.py")

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

    def test_locomo_evidence_scope_filters_ingested_sessions(self):
        conversations = [
            {
                "conversation_id": "conv-1",
                "sessions": [
                    {"session_id": 1, "turns": [{"speaker": "A", "text": "needed"}]},
                    {"session_id": 2, "turns": [{"speaker": "A", "text": "also needed"}]},
                    {"session_id": 3, "turns": [{"speaker": "A", "text": "expensive"}]},
                ],
            },
            {
                "conversation_id": "conv-2",
                "sessions": [{"session_id": 1, "turns": [{"speaker": "A", "text": "skip"}]}],
            },
        ]
        qa_pairs = [{
            "conversation_id": "conv-1",
            "question": "what mattered?",
            "answer": "needed",
            "evidence": ["D1:3", "D2:8"],
        }]

        filtered = self.locomo.filter_conversations_for_questions(
            conversations,
            qa_pairs,
            "evidence",
        )

        self.assertEqual(len(filtered), 1)
        self.assertEqual(filtered[0]["conversation_id"], "conv-1")
        self.assertEqual(
            [session["session_id"] for session in filtered[0]["sessions"]],
            [1, 2],
        )

    def test_locomo_evidence_turn_scope_trims_sessions_to_cited_turns(self):
        conversations = [
            {
                "conversation_id": "conv-1",
                "sessions": [
                    {
                        "session_id": 1,
                        "turns": [
                            {"speaker": "A", "text": "before"},
                            {"speaker": "A", "text": "needed"},
                            {"speaker": "A", "text": "after"},
                            {"speaker": "A", "text": "drop"},
                        ],
                    },
                    {
                        "session_id": 2,
                        "turns": [
                            {"speaker": "A", "text": "skip"},
                            {"speaker": "A", "text": "also needed"},
                            {"speaker": "A", "text": "also after"},
                        ],
                    },
                ],
            },
        ]
        qa_pairs = [{
            "conversation_id": "conv-1",
            "question": "what mattered?",
            "answer": "needed",
            "evidence": ["D1:2", "D2:2"],
        }]

        filtered = self.locomo.filter_conversations_for_questions(
            conversations,
            qa_pairs,
            "evidence-turns",
            evidence_context_turns=1,
        )

        sessions = filtered[0]["sessions"]
        self.assertEqual(
            [[turn["text"] for turn in session["turns"]] for session in sessions],
            [
                ["before", "needed", "after"],
                ["skip", "also needed", "also after"],
            ],
        )

    def test_artifact_download_drops_auth_after_redirect(self):
        requests = []

        class FakeOpener:
            def open(self, request, timeout=30):
                requests.append(request)
                raise urllib.error.HTTPError(
                    request.full_url,
                    302,
                    "Found",
                    {"Location": "https://blob.example/artifact.zip?sig=abc"},
                    None,
                )

        class FakeResponse:
            def __enter__(self):
                return self

            def __exit__(self, *_args):
                return False

            def read(self):
                return b"zip-bytes"

        original_build_opener = self.collector.urllib.request.build_opener
        original_urlopen = self.collector.urllib.request.urlopen
        try:
            self.collector.urllib.request.build_opener = lambda *_args: FakeOpener()

            def fake_urlopen(request, timeout=120):
                requests.append(request)
                return FakeResponse()

            self.collector.urllib.request.urlopen = fake_urlopen
            dest = ROOT / ".tmp-artifact-test.zip"
            try:
                self.collector.download_zip(
                    "https://api.github.com/repos/o/r/actions/artifacts/1/zip",
                    "secret-token",
                    dest,
                )
                self.assertEqual(dest.read_bytes(), b"zip-bytes")
            finally:
                if dest.exists():
                    dest.unlink()
        finally:
            self.collector.urllib.request.build_opener = original_build_opener
            self.collector.urllib.request.urlopen = original_urlopen

        self.assertTrue(requests[0].has_header("Authorization"))
        self.assertFalse(requests[1].has_header("Authorization"))
        self.assertEqual(requests[1].full_url, "https://blob.example/artifact.zip?sig=abc")


if __name__ == "__main__":
    unittest.main()
