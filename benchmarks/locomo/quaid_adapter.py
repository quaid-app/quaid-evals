#!/usr/bin/env python3
"""
quaid_adapter.py - LoCoMo benchmark adapter for Quaid.

LoCoMo tests multi-session conversational memory across 4 question types:
  single-hop, multi-hop, open-domain, temporal

Adapter strategy:
  - INGEST: Append each conversation turn through Quaid's memory_add_turn tool
  - EXTRACT: Enqueue per-session extraction so the conversation memory pipeline runs
  - SEARCH: Use quaid query to retrieve relevant memories for each question
  - EVALUATE: Feed retrieved context + question to LLM for answer, then judge vs ground truth

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
import sqlite3
import subprocess
import sys
import tempfile
from pathlib import Path
from datetime import date, datetime, timedelta, timezone


# ─── Quaid backend ────────────────────────────────────────────────────────────

class QuaidBackend:
    """Quaid memory backend using the conversation memory pipeline."""

    _extraction_cache_checked = False

    def __init__(self, db_path: str):
        self.db_path = db_path
        self._env = {**os.environ, "QUAID_DB": db_path}
        self._workspace_dir = Path(tempfile.mkdtemp(prefix="locomo-quaid-"))
        self._vault_dir = self._workspace_dir / "vault"
        self._page_count = 0
        self._sessions: set[str] = set()
        self._speaker_roles: dict[tuple[str, str], str] = {}
        self.init()

    def _run_quaid(self, args: list[str], timeout: int = 120) -> subprocess.CompletedProcess:
        return subprocess.run(
            ["quaid", *args],
            env=self._env,
            capture_output=True,
            text=True,
            timeout=timeout,
        )

    def init(self) -> None:
        """Initialize a DB, configure a writable memory root, and enable extraction."""
        self._vault_dir.mkdir(parents=True, exist_ok=True)
        self._run_quaid(["init", self.db_path], timeout=60)
        self._configure_write_target()

        result = self._run_quaid(["extraction", "enable"], timeout=900)
        if result.returncode != 0:
            detail = (result.stderr or result.stdout).strip()
            print(f"Warning: quaid extraction enable failed: {detail}", file=sys.stderr)
        else:
            QuaidBackend._extraction_cache_checked = True

    def _configure_write_target(self) -> None:
        """Point Quaid's default write-target collection at this benchmark vault."""
        with sqlite3.connect(self.db_path, timeout=30) as conn:
            conn.execute(
                """
                INSERT OR IGNORE INTO collections
                    (id, name, root_path, state, writable, is_write_target, needs_full_sync)
                VALUES (1, 'default', '', 'detached', 1, 1, 0)
                """
            )
            conn.execute("UPDATE collections SET is_write_target = 0 WHERE name <> 'default'")
            conn.execute(
                """
                UPDATE collections
                   SET root_path = ?1,
                       state = 'active',
                       writable = 1,
                       is_write_target = 1,
                       needs_full_sync = 0
                 WHERE name = 'default'
                """,
                (str(self._vault_dir),),
            )

    def add(self, text: str, metadata: dict = None) -> bool:
        """Store a conversation turn via memory_add_turn."""
        metadata = metadata or {}
        speaker = metadata.get("speaker", "unknown")
        session_id = self._session_id(metadata)
        payload = {
            "session_id": session_id,
            "role": self._role_for(session_id, speaker),
            "content": text,
            "metadata": {
                "benchmark": "locomo",
                "speaker": speaker,
                **{k: v for k, v in metadata.items() if v is not None},
            },
        }
        timestamp = self._timestamp_for(metadata)
        if timestamp:
            payload["timestamp"] = timestamp

        try:
            result = self._run_quaid(
                ["call", "memory_add_turn", json.dumps(payload)],
                timeout=30,
            )
        except Exception as e:
            print(f"Error adding turn to Quaid: {e}", file=sys.stderr)
            return False

        if result.returncode != 0:
            detail = (result.stderr or result.stdout).strip()
            print(f"Error adding turn to Quaid: {detail}", file=sys.stderr)
            return False

        self._sessions.add(session_id)
        self._page_count += 1
        return True

    def flush_to_quaid(self) -> bool:
        """Enqueue extraction for each ingested conversation session."""
        ok = True
        for session_id in sorted(self._sessions):
            try:
                result = self._run_quaid(["extract", session_id], timeout=120)
            except Exception as e:
                print(f"Error triggering extraction for {session_id}: {e}", file=sys.stderr)
                ok = False
                continue
            if result.returncode != 0:
                detail = (result.stderr or result.stdout).strip()
                print(f"Error triggering extraction for {session_id}: {detail}", file=sys.stderr)
                ok = False
        return ok

    def search(self, query: str, top_k: int = 50) -> list[dict]:
        """Retrieve relevant memories for a question."""
        try:
            result = self._run_quaid(
                ["query", query, "--json", "--limit", str(top_k)],
                timeout=30,
            )
            if result.returncode == 0 and result.stdout.strip():
                parsed = json.loads(result.stdout)
                if isinstance(parsed, list):
                    return parsed
                if isinstance(parsed, dict):
                    return parsed.get("results", parsed.get("items", []))
        except Exception as e:
            print(f"Warning: search failed for '{query[:50]}': {e}", file=sys.stderr)
        return []

    def get_context(self, results: list[dict]) -> str:
        """Format retrieved memories into a context string for the LLM."""
        if not results:
            return "No relevant memories found."
        parts = []
        for r in results:
            content = (
                r.get("content")
                or r.get("text")
                or r.get("compiled_truth")
                or r.get("summary")
                or r.get("snippet")
                or r.get("title")
                or ""
            )
            if content:
                parts.append(content.strip())
        return "\n\n---\n\n".join(parts[:20])  # cap at 20 turns for context window

    def _session_id(self, metadata: dict) -> str:
        conv_id = metadata.get("conv_id")
        session_id = metadata.get("session_id", "unknown")
        if conv_id:
            return f"locomo-{conv_id}-session-{session_id}"
        return f"locomo-{session_id}"

    def _role_for(self, session_id: str, speaker: str) -> str:
        raw = str(speaker or "").strip()
        lower = raw.lower()
        if lower in {"user", "assistant", "system", "tool"}:
            return lower
        if lower in {"speaker_a", "human"} or "user" in lower:
            return "user"
        if lower in {"speaker_b", "agent"} or "assistant" in lower:
            return "assistant"

        key = (session_id, raw)
        if key not in self._speaker_roles:
            existing = {role for (sid, _), role in self._speaker_roles.items() if sid == session_id}
            self._speaker_roles[key] = "assistant" if "user" in existing else "user"
        return self._speaker_roles[key]

    def _timestamp_for(self, metadata: dict) -> str | None:
        date_value = metadata.get("date") or metadata.get("timestamp")
        if isinstance(date_value, str) and date_value.strip():
            normalized = self._normalize_timestamp(date_value)
            if normalized:
                return normalized
        turn_id = metadata.get("turn_id", self._page_count)
        try:
            offset = int(turn_id)
        except (TypeError, ValueError):
            offset = self._page_count
        base = datetime(2026, 1, 1, tzinfo=timezone.utc)
        return (base + timedelta(minutes=offset)).isoformat().replace("+00:00", "Z")

    def _normalize_timestamp(self, value: str) -> str | None:
        candidate = value.strip()
        if not candidate:
            return None
        if len(candidate) == 10:
            candidate = f"{candidate}T00:00:00Z"
        normalized = candidate.replace("Z", "+00:00")
        try:
            parsed = datetime.fromisoformat(normalized)
        except ValueError:
            return None
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


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

LOCOMO_DATASET_URL = "https://raw.githubusercontent.com/snap-research/locomo/main/data/locomo10.json"

def load_locomo_data(benchmarks_dir: str) -> tuple[list, list]:
    """Load LoCoMo conversations and questions.
    
    Uses the locomo10.json from snap-research/locomo (same source as mem0ai benchmark).
    Downloads automatically if not cached.
    """
    import urllib.request

    # Cache path
    cache_dir = Path("/tmp/locomo-dataset")
    cache_dir.mkdir(exist_ok=True)
    dataset_path = cache_dir / "locomo10.json"

    if not dataset_path.exists():
        print(f"Downloading LoCoMo dataset from snap-research/locomo...")
        urllib.request.urlretrieve(LOCOMO_DATASET_URL, dataset_path)
        print(f"Downloaded to: {dataset_path}")

    raw = json.loads(dataset_path.read_text())

    # locomo10.json structure:
    # List of 10 conversation objects, each with:
    #   - sample_id: str
    #   - conversation: {speaker_a, speaker_b, session_1..N (list of turns), session_N_date_time}
    #   - qa: list of {question, answer, evidence, category}
    # category: 1=single-hop, 2=multi-hop, 3=temporal, 4=open-domain, 5=adversarial
    CATEGORY_MAP = {1: "single-hop", 2: "multi-hop", 3: "temporal", 4: "open-domain", 5: "adversarial"}

    conversations = []
    qa_pairs = []
    for item in raw:
        conv_id = item.get("sample_id", str(len(conversations)))
        conv_data = item.get("conversation", {})
        # Collect all sessions
        sessions = []
        i = 1
        while f"session_{i}" in conv_data:
            turns = conv_data[f"session_{i}"]
            date = conv_data.get(f"session_{i}_date_time", "")
            sessions.append({"session_id": i, "date": date, "turns": turns})
            i += 1
        conv = {"conversation_id": conv_id, "sessions": sessions}
        conversations.append(conv)
        for qa in item.get("qa", []):
            cat_num = qa.get("category", 0)
            qa_pairs.append({
                "conversation_id": conv_id,
                "question": qa.get("question", ""),
                "answer": qa.get("answer", ""),
                "type": CATEGORY_MAP.get(cat_num, f"cat_{cat_num}"),
                "evidence": qa.get("evidence", ""),
            })

    print(f"Loaded {len(conversations)} conversations, {len(qa_pairs)} QA pairs from locomo10.json")
    return conversations, qa_pairs


def _load_locomo_data_legacy(benchmarks_dir: str) -> tuple[list, list]:
    """Legacy loader - kept for reference."""
    base = Path(benchmarks_dir)
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
        raise FileNotFoundError(
            f"Legacy data paths not found in {benchmarks_dir}."
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
        conv_id = conv.get("conversation_id", str(conv_idx))
        sessions = conv.get("sessions", [])
        # Support both new format (list of session dicts) and old flat turns list
        if sessions and isinstance(sessions[0], dict) and "turns" in sessions[0]:
            # New format: [{session_id, date, turns: [...]}, ...]
            for session in sessions:
                session_id = session.get("session_id", conv_id)
                session_date = session.get("date", "")
                for turn_idx, turn in enumerate(session.get("turns", [])):
                    speaker = turn.get("speaker", turn.get("role", "unknown"))
                    text = turn.get("text", turn.get("content", ""))
                    if text:
                        backend.add(text, {
                            "speaker": speaker,
                            "conv_id": conv_id,
                            "session_id": str(session_id),
                            "turn_id": turn_idx,
                            "date": session_date,
                        })
        else:
            # Old flat format
            for turn_idx, turn in enumerate(sessions):
                speaker = turn.get("speaker", turn.get("role", "unknown"))
                text = turn.get("text", turn.get("content", ""))
                if text:
                    backend.add(text, {
                        "speaker": speaker,
                        "session_id": conv_id,
                        "turn_id": turn_idx,
                    })

    print(f"  Added {backend._page_count} conversation turns")
    print("  Triggering Quaid extraction...")
    if not backend.flush_to_quaid():
        print("  WARNING: Quaid extraction trigger failed - results may be empty")

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
    print("NOTE: Uses Quaid conversation memory: memory_add_turn -> extract -> query.")
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
