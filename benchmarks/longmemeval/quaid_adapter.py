"""
longmemeval_adapter.py - LongMemEval benchmark adapter for Quaid.

LongMemEval (ICLR 2025) tests long-term memory across 500 questions, 6 types:
  multi-session, temporal-reasoning, knowledge-update,
  single-session-user, single-session-assistant, single-session-preference

Each question has its own haystack_sessions that are ingested fresh per question.
This is more rigorous than LoCoMo (shared corpus) because it tests per-conversation
fact extraction and retrieval independently.

Mem0 v3 reference scores:
  Overall: 93.4%  (up from 67.8% with old algorithm)
  Agent recall: 100% (assistant role)
  Temporal: 93%

Usage:
  python3 benchmarks/longmemeval/quaid_adapter.py \
    --db /tmp/lme-eval.db \
    --output results/longmemeval-v0.13.0-2026-04-30.json \
    --quaid-version 0.13.0

Requires: OPENAI_API_KEY (or ANTHROPIC_API_KEY with --provider anthropic)
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import tempfile
import urllib.request
from datetime import date
from pathlib import Path

# ─── Quaid backend ────────────────────────────────────────────────────────────

class QuaidBackend:
    """Thin wrapper around the quaid CLI for page-based memory."""

    def __init__(self, db_path: str):
        self.db_path = db_path
        self._tmp_dir = tempfile.mkdtemp(prefix="lme-pages-")
        self._page_count = 0
        self._env = {**os.environ, "QUAID_DB": db_path}

    def init(self):
        subprocess.run(
            ["quaid", "init", self.db_path],
            env=self._env, capture_output=True
        )

    def reset(self):
        """Clear DB for a fresh per-question ingest."""
        import shutil
        if Path(self.db_path).exists():
            Path(self.db_path).unlink()
        self._tmp_dir = tempfile.mkdtemp(prefix="lme-pages-")
        self._page_count = 0
        self.init()

    def add(self, content: str, metadata: dict):
        page_path = Path(self._tmp_dir) / f"turn-{self._page_count:06d}.md"
        speaker = metadata.get("speaker", metadata.get("role", "unknown"))
        meta_str = "\n".join(f"{k}: {v}" for k, v in metadata.items() if v)
        page_path.write_text(f"---\n{meta_str}\n---\n\n{speaker}: {content}\n")
        self._page_count += 1

    def flush_to_quaid(self) -> bool:
        result = subprocess.run(
            ["quaid", "collection", "add", "lme", self._tmp_dir, "--db", self.db_path],
            env=self._env, capture_output=True, text=True, timeout=300
        )
        if result.returncode != 0:
            return False
        embed = subprocess.run(
            ["quaid", "embed", "--db", self.db_path],
            env=self._env, capture_output=True, text=True, timeout=600
        )
        return embed.returncode == 0

    def search(self, query: str, top_k: int = 20) -> list:
        result = subprocess.run(
            ["quaid", "query", query, "--db", self.db_path, "--limit", str(top_k), "--json"],
            env=self._env, capture_output=True, text=True, timeout=30
        )
        if result.returncode != 0:
            return []
        try:
            return json.loads(result.stdout)
        except Exception:
            return []

    def get_context(self, results: list) -> str:
        if not results:
            return "No relevant memories found."
        parts = []
        for r in results:
            content = r.get("content", r.get("text", ""))
            if content:
                parts.append(content.strip())
        return "\n\n".join(parts[:10])


# ─── LLM helpers ──────────────────────────────────────────────────────────────

def call_llm(prompt: str, model: str, provider: str) -> str:
    if provider == "openai":
        import openai
        client = openai.OpenAI(api_key=os.environ.get("OPENAI_API_KEY"))
        resp = client.chat.completions.create(
            model=model,
            messages=[{"role": "user", "content": prompt}],
            max_tokens=256,
            temperature=0.0,
        )
        return resp.choices[0].message.content.strip()
    elif provider == "anthropic":
        import anthropic
        client = anthropic.Anthropic(api_key=os.environ.get("ANTHROPIC_API_KEY"))
        resp = client.messages.create(
            model=model,
            max_tokens=256,
            messages=[{"role": "user", "content": prompt}],
        )
        return resp.content[0].text.strip()
    else:
        raise ValueError(f"Unknown provider: {provider}")


def generate_answer(context: str, question: str, model: str, provider: str) -> str:
    prompt = f"""You are answering a question based on conversation memories.

Memories:
{context}

Question: {question}

Answer concisely (1-2 sentences max):"""
    try:
        return call_llm(prompt, model, provider)
    except Exception as e:
        return f"Error: {e}"


def judge_answer(question: str, predicted: str, ground_truth: str, model: str, provider: str) -> float:
    prompt = f"""Score whether the predicted answer correctly answers the question given the ground truth.

Question: {question}
Ground truth: {ground_truth}
Predicted: {predicted}

Score from 0 to 1 (0=wrong, 0.5=partial, 1=correct). Reply with only the number:"""
    try:
        score_str = call_llm(prompt, model, provider).strip()
        return float(score_str)
    except Exception:
        return 0.0


# ─── Dataset loading ──────────────────────────────────────────────────────────

DATASET_URL = (
    "https://huggingface.co/datasets/xiaowu0162/longmemeval-cleaned/"
    "resolve/main/longmemeval_s_cleaned.json"
)

def load_longmemeval(max_questions: int | None = None) -> list:
    cache_dir = Path("/tmp/longmemeval-dataset")
    cache_dir.mkdir(exist_ok=True)
    dataset_path = cache_dir / "longmemeval_s_cleaned.json"

    if not dataset_path.exists():
        print(f"Downloading LongMemEval from HuggingFace...")
        urllib.request.urlretrieve(DATASET_URL, dataset_path)
        print(f"Downloaded to: {dataset_path}")

    data = json.loads(dataset_path.read_text())
    if max_questions:
        # Sample proportionally across question types
        from collections import defaultdict
        by_type = defaultdict(list)
        for q in data:
            by_type[q["question_type"]].append(q)
        n_types = len(by_type)
        per_type = max(1, max_questions // n_types)
        sampled = []
        for items in by_type.values():
            sampled.extend(items[:per_type])
        return sampled[:max_questions]
    return data


# ─── Main evaluation loop ─────────────────────────────────────────────────────

def run_longmemeval(
    questions: list,
    quaid_db_base: str,
    answerer_model: str,
    judge_model: str,
    provider: str,
    top_k: int = 20,
    checkpoint_path: str = None,
) -> dict:
    """Run LongMemEval: per-question ingest + retrieve + evaluate.
    
    Supports checkpoint/resume: saves progress every 10 questions so
    a timed-out run can be resumed without restarting from scratch.
    """
    import time

    # Load checkpoint if exists
    completed = {}
    if checkpoint_path and Path(checkpoint_path).exists():
        try:
            checkpoint = json.loads(Path(checkpoint_path).read_text())
            completed = {item["question_id"]: item for item in checkpoint.get("results", [])}
            print(f"Resuming from checkpoint: {len(completed)} questions already done")
        except Exception as e:
            print(f"Warning: could not load checkpoint: {e}")

    results_by_type: dict[str, list[float]] = {}
    all_scores: list[float] = []

    # Pre-populate from checkpoint
    for item in completed.values():
        score = item["score"]
        q_type = item["type"]
        all_scores.append(score)
        if q_type not in results_by_type:
            results_by_type[q_type] = []
        results_by_type[q_type].append(score)

    print(f"Evaluating {len(questions)} questions (per-question ingest)...")

    for i, qa in enumerate(questions):
        q_id = qa.get("question_id", str(i))

        # Skip already completed
        if q_id in completed:
            continue

        question = qa["question"]
        ground_truth = qa["answer"]
        q_type = qa.get("question_type", "unknown")
        sessions = qa.get("haystack_sessions", [])

        # Fresh DB per question
        db_path = f"{quaid_db_base}-q{i:04d}.db"
        backend = QuaidBackend(db_path)
        backend.init()

        # Ingest all haystack sessions for this question
        for sess_idx, session in enumerate(sessions):
            if isinstance(session, list):
                turns = session
            else:
                turns = session.get("conversation", session.get("turns", []))
            for turn_idx, turn in enumerate(turns):
                role = turn.get("role", "unknown")
                content = turn.get("content", "")
                if content and len(content.strip()) > 10:
                    backend.add(content, {
                        "role": role,
                        "session_id": sess_idx,
                        "turn_id": turn_idx,
                    })

        # Index
        flushed = backend.flush_to_quaid()

        # Retrieve + Answer + Judge
        if flushed:
            retrieved = backend.search(question, top_k=top_k)
            context = backend.get_context(retrieved)
            predicted = generate_answer(context, question, answerer_model, provider)
        else:
            predicted = "I don't know"

        score = judge_answer(question, predicted, ground_truth, judge_model, provider)
        all_scores.append(score)
        if q_type not in results_by_type:
            results_by_type[q_type] = []
        results_by_type[q_type].append(score)

        # Record in completed
        completed[q_id] = {"question_id": q_id, "score": score, "type": q_type}

        # Cleanup DB
        try:
            Path(db_path).unlink(missing_ok=True)
        except Exception:
            pass

        completed_count = len(all_scores)
        if completed_count % 10 == 0:
            avg = sum(all_scores) / len(all_scores)
            print(f"  Progress: {completed_count}/{len(questions)} | running avg: {avg:.3f}")
            # Save checkpoint
            if checkpoint_path:
                try:
                    Path(checkpoint_path).write_text(json.dumps({
                        "completed": completed_count,
                        "total": len(questions),
                        "results": list(completed.values())
                    }))
                except Exception:
                    pass

    overall = sum(all_scores) / len(all_scores) if all_scores else 0.0
    by_type = {
        t: {"avg": round(sum(s) / len(s), 4), "count": len(s)}
        for t, s in results_by_type.items()
    }

    print(f"\nResults:")
    print(f"  Overall: {overall:.3f} ({overall*100:.1f}%)")
    for t, v in sorted(by_type.items()):
        print(f"  {t}: {v['avg']:.3f} ({v['count']} questions)")

    return {
        "overall": round(overall, 4),
        "pass_rate": round(sum(1 for s in all_scores if s >= 0.5) / len(all_scores), 4) if all_scores else 0,
        "total_questions": len(all_scores),
        "by_type": by_type,
        "reference": {
            "mem0_v3": {
                "overall": 0.934,
                "temporal_reasoning": 0.93,
                "agent_recall": 1.0,
                "source": "mem0ai/memory-benchmarks release notes"
            }
        }
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--db", required=True, help="Base path for per-question DBs")
    parser.add_argument("--output", required=True)
    parser.add_argument("--quaid-version", default="unknown")
    parser.add_argument("--answerer-model", default="gpt-4o")
    parser.add_argument("--judge-model", default="gpt-4o")
    parser.add_argument("--provider", default="openai", choices=["openai", "anthropic"])
    parser.add_argument("--top-k", type=int, default=20)
    parser.add_argument("--max-questions", type=int, default=None,
                        help="Limit questions for faster runs (e.g. 50)")
    args = parser.parse_args()

    print(f"LongMemEval adapter - Quaid {args.quaid_version}")
    print(f"Provider: {args.provider} | Answerer: {args.answerer_model} | Judge: {args.judge_model}")
    print(f"NOTE: Per-question ingest - each question has its own memory store")
    print(f"NOTE: Low scores expected until issue #105 (conversation memory) is built")
    print()

    questions = load_longmemeval(args.max_questions)
    print(f"Loaded {len(questions)} questions")

    scores = run_longmemeval(
        questions,
        quaid_db_base=args.db,
        answerer_model=args.answerer_model,
        judge_model=args.judge_model,
        provider=args.provider,
        top_k=args.top_k,
        checkpoint_path=f"{args.db}-checkpoint.json",
    )

    output = {
        "quaid_version": args.quaid_version,
        "date": str(date.today()),
        "benchmark": "longmemeval",
        "longmemeval": scores,
        "config": {
            "answerer_model": args.answerer_model,
            "judge_model": args.judge_model,
            "provider": args.provider,
            "top_k": args.top_k,
            "total_questions": len(questions),
        }
    }

    Path(args.output).write_text(json.dumps(output, indent=2))
    print(f"\nResults written to: {args.output}")
    print(f"Overall: {scores['overall']:.3f} (Mem0 v3 reference: 0.934)")


if __name__ == "__main__":
    main()
