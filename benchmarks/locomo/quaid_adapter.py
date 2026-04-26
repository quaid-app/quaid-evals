#!/usr/bin/env python3
"""
quaid_adapter.py - LoCoMo benchmark adapter for Quaid.

LoCoMo tests multi-session conversational memory across 4 question types:
  single-hop, multi-hop, open-domain, temporal

Adapter strategy:
  - INGEST: Convert each conversation turn into a markdown page, indexed into Quaid
  - SEARCH: Use memory_query to retrieve relevant turns for each question
  - EVALUATE: Feed retrieved context + question to LLM for answer, then judge vs ground truth

Important caveat:
  Quaid is doc-native (markdown pages), NOT conversational (structured facts).
  LoCoMo is designed for systems that extract and store discrete facts from conversation.
  This adapter stores whole conversation turns as pages - a baseline, not optimal.
  Low scores here = direct roadmap signal for conversation memory feature.

Usage:
  python3 benchmarks/locomo/quaid_adapter.py \
    --db /tmp/locomo-eval.db \
    --benchmarks-dir /tmp/memory-benchmarks \
    --output results/locomo-v1.0.0-2026-04-27.json \
    --quaid-version v1.0.0
"""

import argparse
import json
import os
import subprocess
import sys
import textwrap
from pathlib import Path
from datetime import date
from typing import Optional


# ─── Quaid backend ────────────────────────────────────────────────────────────

class QuaidBackend:
    """Quaid memory backend - stores conversation turns as markdown pages."""

    def __init__(self, db_path: str):
        self.db_path = db_path
        self._page_count = 0

    def add(self, text: str, metadata: dict = None) -> bool:
        """Store a conversation turn as a markdown page."""
        metadata = metadata or {}
        speaker = metadata.get("speaker", "unknown")
        session_id = metadata.get("session_id", "unknown")
        turn_id = metadata.get("turn_id", self._page_count)
        timestamp = metadata.get("timestamp", "")

        # Format as a readable markdown page
        content = textwrap.dedent(f"""\
            ---
            speaker: "{speaker}"
            session: "{session_id}"
            turn: {turn_id}
            timestamp: "{timestamp}"
            type: conversation_turn
            ---

            **{speaker}** (session {session_id}, turn {turn_id}):

            {text}
        """)

        page_path = f"/tmp/locomo-pages/turn-{self._page_count:06d}.md"
        os.makedirs("/tmp/locomo-pages", exist_ok=True)
        Path(page_path).write_text(content)
        self._page_count += 1
        return True

    def flush_to_quaid(self) -> bool:
        """Index all conversation pages into Quaid."""
        try:
            result = subprocess.run(
                ["quaid", "collection", "add", "locomo", "/tmp/locomo-pages",
                 "--db", self.db_path],
                capture_output=True, text=True, timeout=120
            )
            return result.returncode == 0
        except Exception as e:
            print(f"Error indexing into Quaid: {e}", file=sys.stderr)
            return False

    def search(self, query: str, top_k: int = 50) -> list[dict]:
        """Retrieve relevant conversation turns for a question."""
        try:
            result = subprocess.run(
                ["quaid", "memory_query", query, "--db", self.db_path,
                 "--limit", str(top_k), "--json"],
                capture_output=True, text=True, timeout=30
            )
            if result.returncode == 0 and result.stdout.strip():
                return json.loads(result.stdout)
        except Exception as e:
            print(f"Warning: search failed for '{query[:50]}': {e}", file=sys.stderr)
        return []

    def get_context(self, results: list[dict]) -> str:
        """Format retrieved pages into a context string for the LLM."""
        if not results:
            return "No relevant memories found."
        parts = []
        for r in results:
            content = r.get("content", r.get("text", ""))
            if content:
                parts.append(content.strip())
        return "\n\n---\n\n".join(parts[:20])  # cap at 20 turns for context window


# ─── LLM answerer and judge ───────────────────────────────────────────────────

def call_llm(prompt: str, model: str, provider: str, api_key: str = None) -> str:
    """Call an LLM to generate an answer or judge correctness."""
    if provider == "openai":
        import urllib.request
        import urllib.error

        api_key = api_key or os.environ.get("OPENAI_API_KEY", "")
        if not api_key:
            raise ValueError("OPENAI_API_KEY not set")

        payload = json.dumps({
            "model": model,
            "messages": [{"role": "user", "content": prompt}],
            "max_tokens": 500,
            "temperature": 0,
        }).encode()

        req = urllib.request.Request(
            "https://api.openai.com/v1/chat/completions",
            data=payload,
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            }
        )
        with urllib.request.urlopen(req, timeout=30) as resp:
            data = json.loads(resp.read())
            return data["choices"][0]["message"]["content"].strip()

    elif provider == "anthropic":
        import urllib.request
        api_key = api_key or os.environ.get("ANTHROPIC_API_KEY", "")
        if not api_key:
            raise ValueError("ANTHROPIC_API_KEY not set")

        payload = json.dumps({
            "model": model,
            "max_tokens": 500,
            "messages": [{"role": "user", "content": prompt}],
        }).encode()

        req = urllib.request.Request(
            "https://api.anthropic.com/v1/messages",
            data=payload,
            headers={
                "x-api-key": api_key,
                "anthropic-version": "2023-06-01",
                "Content-Type": "application/json",
            }
        )
        with urllib.request.urlopen(req, timeout=30) as resp:
            data = json.loads(resp.read())
            return data["content"][0]["text"].strip()

    else:
        raise ValueError(f"Unsupported provider: {provider}")


def generate_answer(context: str, question: str, model: str, provider: str) -> str:
    """Generate an answer from retrieved context."""
    prompt = f"""You are answering questions about a person based on their conversation history.

Retrieved conversation context:
{context}

Question: {question}

Answer concisely and only from the provided context. If the context doesn't contain the answer, say "I don't know"."""
    return call_llm(prompt, model, provider)


def judge_answer(question: str, predicted: str, ground_truth: str,
                 model: str, provider: str) -> float:
    """Score a predicted answer against ground truth (0.0 - 1.0)."""
    prompt = f"""You are evaluating the quality of an answer to a question.

Question: {question}
Ground truth answer: {ground_truth}
Predicted answer: {predicted}

Score the predicted answer on a scale from 0 to 1:
- 1.0: Correct, complete answer
- 0.5: Partially correct
- 0.0: Incorrect or missing key information

Respond with ONLY a number between 0 and 1."""
    try:
        score_str = call_llm(prompt, model, provider).strip()
        return float(score_str)
    except (ValueError, Exception):
        # Fallback: exact match check
        return 1.0 if predicted.lower().strip() == ground_truth.lower().strip() else 0.0


# ─── LoCoMo dataset loading ───────────────────────────────────────────────────

def load_locomo_data(benchmarks_dir: str) -> tuple[list, list]:
    """Load LoCoMo conversations and questions from the benchmark repo."""
    base = Path(benchmarks_dir)

    # Try multiple possible paths in the repo
    conv_paths = [
        base / "data" / "locomo" / "conversations.json",
        base / "benchmarks" / "locomo" / "data" / "conversations.json",
        base / "locomo" / "conversations.json",
    ]
    qa_paths = [
        base / "data" / "locomo" / "qa.json",
        base / "benchmarks" / "locomo" / "data" / "qa.json",
        base / "locomo" / "qa.json",
    ]

    conversations = None
    qa_pairs = None

    for p in conv_paths:
        if p.exists():
            conversations = json.loads(p.read_text())
            print(f"Loaded conversations from: {p}")
            break

    for p in qa_paths:
        if p.exists():
            qa_pairs = json.loads(p.read_text())
            print(f"Loaded QA pairs from: {p}")
            break

    if conversations is None or qa_pairs is None:
        # Fallback: search recursively
        for f in base.rglob("*.json"):
            try:
                data = json.loads(f.read_text())
                if isinstance(data, list) and data:
                    first = data[0]
                    if "conversation" in first or "turns" in first:
                        conversations = data
                        print(f"Found conversations at: {f}")
                    elif "question" in first and "answer" in first:
                        qa_pairs = data
                        print(f"Found QA at: {f}")
            except Exception:
                pass

    if conversations is None:
        raise FileNotFoundError(
            f"Could not find LoCoMo conversation data in {benchmarks_dir}. "
            "Ensure mem0ai/memory-benchmarks is cloned correctly."
        )
    if qa_pairs is None:
        raise FileNotFoundError(
            f"Could not find LoCoMo QA data in {benchmarks_dir}."
        )

    return conversations, qa_pairs


# ─── Main evaluation loop ─────────────────────────────────────────────────────

def run_locomo(
    backend: QuaidBackend,
    conversations: list,
    qa_pairs: list,
    answerer_model: str,
    judge_model: str,
    provider: str,
    top_k: int = 50,
    max_questions: int = None,
) -> dict:
    """Run full LoCoMo ingest → search → evaluate pipeline."""

    # Stage 1: Ingest all conversation turns
    print(f"\n[1/3] Ingesting {len(conversations)} conversations...")
    for conv_idx, conv in enumerate(conversations):
        session_id = conv.get("conversation_id", str(conv_idx))
        turns = conv.get("turns", conv.get("conversation", []))
        for turn_idx, turn in enumerate(turns):
            speaker = turn.get("speaker", turn.get("role", "unknown"))
            text = turn.get("text", turn.get("content", ""))
            timestamp = turn.get("timestamp", turn.get("time", ""))
            if text:
                backend.add(text, {
                    "speaker": speaker,
                    "session_id": session_id,
                    "turn_id": turn_idx,
                    "timestamp": timestamp,
                })

    print(f"  Wrote {backend._page_count} conversation turns")
    print("  Indexing into Quaid...")
    if not backend.flush_to_quaid():
        print("  WARNING: Quaid indexing failed - results will be empty")

    # Stage 2 & 3: Search + Evaluate
    questions = qa_pairs[:max_questions] if max_questions else qa_pairs
    print(f"\n[2/3] Evaluating {len(questions)} questions...")

    results_by_type = {}
    all_scores = []

    for i, qa in enumerate(questions):
        question = qa.get("question", "")
        ground_truth = qa.get("answer", qa.get("ground_truth", ""))
        q_type = qa.get("type", qa.get("question_type", "unknown"))

        if not question or not ground_truth:
            continue

        # Search
        retrieved = backend.search(question, top_k=top_k)
        context = backend.get_context(retrieved)

        # Answer
        try:
            predicted = generate_answer(context, question, answerer_model, provider)
        except Exception as e:
            print(f"  Warning: answer generation failed for q{i}: {e}", file=sys.stderr)
            predicted = "I don't know"

        # Judge
        try:
            score = judge_answer(question, predicted, ground_truth, judge_model, provider)
        except Exception as e:
            print(f"  Warning: judge failed for q{i}: {e}", file=sys.stderr)
            score = 0.0

        all_scores.append(score)

        if q_type not in results_by_type:
            results_by_type[q_type] = []
        results_by_type[q_type].append(score)

        if (i + 1) % 25 == 0:
            avg_so_far = sum(all_scores) / len(all_scores)
            print(f"  Progress: {i+1}/{len(questions)} | running avg: {avg_so_far:.3f}")

    # Aggregate
    overall = sum(all_scores) / len(all_scores) if all_scores else 0.0
    by_type = {
        t: {"avg": round(sum(s)/len(s), 4), "count": len(s)}
        for t, s in results_by_type.items()
    }

    print(f"\n[3/3] Results:")
    print(f"  Overall: {overall:.3f} ({sum(1 for s in all_scores if s >= 0.5)}/{len(all_scores)} pass)")
    for t, v in by_type.items():
        print(f"  {t}: {v['avg']:.3f} ({v['count']} questions)")

    return {
        "overall": round(overall, 4),
        "pass_rate": round(sum(1 for s in all_scores if s >= 0.5) / len(all_scores), 4) if all_scores else 0,
        "total_questions": len(all_scores),
        "by_type": by_type,
        "reference": {
            "mem0_v3": {"overall": 0.916, "source": "mem0ai/memory-benchmarks"},
        }
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--db", required=True)
    parser.add_argument("--benchmarks-dir", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--quaid-version", default="unknown")
    parser.add_argument("--answerer-model", default="gpt-4o")
    parser.add_argument("--judge-model", default="gpt-4o")
    parser.add_argument("--provider", default="openai", choices=["openai", "anthropic"])
    parser.add_argument("--top-k", type=int, default=50)
    parser.add_argument("--max-questions", type=int, default=None,
                        help="Limit questions for faster test runs (e.g. 50)")
    args = parser.parse_args()

    print(f"LoCoMo benchmark adapter - Quaid {args.quaid_version}")
    print(f"Provider: {args.provider} | Answerer: {args.answerer_model} | Judge: {args.judge_model}")
    print(f"DB: {args.db}")
    print()
    print("NOTE: Quaid is doc-native, not conversational.")
    print("This baseline shows retrieval quality before conversation memory is built.")
    print("Low scores on multi-hop/temporal = direct roadmap input for conversation memory feature.")
    print()

    backend = QuaidBackend(args.db)
    conversations, qa_pairs = load_locomo_data(args.benchmarks_dir)

    print(f"Loaded: {len(conversations)} conversations, {len(qa_pairs)} QA pairs")

    scores = run_locomo(
        backend, conversations, qa_pairs,
        args.answerer_model, args.judge_model, args.provider,
        top_k=args.top_k,
        max_questions=args.max_questions,
    )

    output = {
        "quaid_version": args.quaid_version,
        "date": str(date.today()),
        "benchmark": "locomo",
        "locomo": scores,
        "config": {
            "answerer_model": args.answerer_model,
            "judge_model": args.judge_model,
            "provider": args.provider,
            "top_k": args.top_k,
        }
    }

    Path(args.output).write_text(json.dumps(output, indent=2))
    print(f"\nResults written to: {args.output}")
    print(f"Overall: {scores['overall']:.3f} (Mem0 reference: 0.916)")


if __name__ == "__main__":
    main()
