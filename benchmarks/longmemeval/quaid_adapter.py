"""
longmemeval_adapter.py - LongMemEval benchmark adapter for Quaid.

LongMemEval (ICLR 2025) tests long-term memory across 500 questions, 6 types:
  multi-session, temporal-reasoning, knowledge-update,
  single-session-user, single-session-assistant, single-session-preference

Each question has its own haystack_sessions that are ingested fresh per question
through Quaid's conversation memory pipeline.
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
import re
import sqlite3
import subprocess
import sys
import tempfile
import urllib.request
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

# ─── Quaid backend ────────────────────────────────────────────────────────────

class QuaidBackend:
    """Thin wrapper around the quaid CLI for conversation memory."""

    _extraction_cache_checked = False

    def __init__(self, db_path: str):
        self.db_path = db_path
        self._workspace_dir = Path(tempfile.mkdtemp(prefix="lme-quaid-"))
        self._vault_dir = self._workspace_dir / "vault"
        self._page_count = 0
        self._sessions: set[str] = set()
        self._env = {**os.environ, "QUAID_DB": db_path}

    def init(self):
        self._vault_dir.mkdir(parents=True, exist_ok=True)
        self._run_quaid(["init", self.db_path], timeout=60)
        self._configure_write_target()
        if not QuaidBackend._extraction_cache_checked:
            result = self._run_quaid(["extraction", "enable"], timeout=900)
            if result.returncode != 0:
                detail = (result.stderr or result.stdout).strip()
                print(f"Warning: quaid extraction enable failed: {detail}", file=sys.stderr)
            else:
                QuaidBackend._extraction_cache_checked = True
        else:
            self._enable_extraction_config()

    def _run_quaid(self, args: list[str], timeout: int = 120) -> subprocess.CompletedProcess:
        return subprocess.run(
            ["quaid", *args],
            env=self._env,
            capture_output=True,
            text=True,
            timeout=timeout,
        )

    def _configure_write_target(self) -> None:
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

    def _enable_extraction_config(self) -> None:
        with sqlite3.connect(self.db_path, timeout=30) as conn:
            conn.execute(
                "INSERT OR REPLACE INTO config(key, value) VALUES ('extraction.enabled', 'true')"
            )
            conn.execute(
                "INSERT OR REPLACE INTO config(key, value) VALUES ('extraction.model_alias', 'phi-3.5-mini')"
            )

    def reset(self):
        """Clear DB for a fresh per-question ingest."""
        if Path(self.db_path).exists():
            Path(self.db_path).unlink()
        self._workspace_dir = Path(tempfile.mkdtemp(prefix="lme-quaid-"))
        self._vault_dir = self._workspace_dir / "vault"
        self._page_count = 0
        self._sessions = set()
        self.init()

    def add(self, content: str, metadata: dict):
        session_id = self._session_id(metadata)
        payload = {
            "session_id": session_id,
            "role": self._role_for(metadata.get("role", metadata.get("speaker", "user"))),
            "content": content,
            "metadata": {
                "benchmark": "longmemeval",
                **{k: v for k, v in metadata.items() if v is not None},
            },
            "timestamp": self._timestamp_for(metadata),
        }
        result = self._run_quaid(
            ["call", "memory_add_turn", json.dumps(payload)],
            timeout=30,
        )
        if result.returncode != 0:
            detail = (result.stderr or result.stdout).strip()
            print(f"Warning: memory_add_turn failed: {detail}", file=sys.stderr)
            return False
        self._sessions.add(session_id)
        self._page_count += 1
        return True

    def flush_to_quaid(self, skip_embed: bool = False) -> bool:
        del skip_embed  # Conversation extraction owns indexing for this adapter.
        ok = True
        for session_id in sorted(self._sessions):
            result = self._run_quaid(["extract", session_id], timeout=120)
            if result.returncode != 0:
                detail = (result.stderr or result.stdout).strip()
                print(f"Warning: quaid extract failed for {session_id}: {detail}", file=sys.stderr)
                ok = False
        return ok

    def search(self, query: str, top_k: int = 20, recall: bool = False) -> list:
        if recall:
            payload = {"query": query, "limit": top_k}
            result = self._run_quaid(
                ["call", "memory_query", json.dumps(payload), "--json"],
                timeout=30,
            )
        else:
            result = self._run_quaid(
                ["query", query, "--json", "--limit", str(top_k)],
                timeout=30,
            )
        if result.returncode != 0:
            return []
        try:
            parsed = json.loads(result.stdout)
            if isinstance(parsed, list):
                return parsed[:top_k]
            if isinstance(parsed, dict):
                results = (
                    parsed.get("results")
                    or parsed.get("items")
                    or parsed.get("memories")
                    or parsed.get("matches")
                    or []
                )
                if isinstance(results, list):
                    return results[:top_k]
                if results:
                    return [results]
                if recall:
                    return [parsed]
            return []
        except Exception:
            return []

    def get_context(self, results: list) -> str:
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
        return "\n\n".join(parts[:10])

    def _session_id(self, metadata: dict) -> str:
        session_id = metadata.get("session_id", "unknown")
        return f"lme-session-{session_id}"

    def _role_for(self, role: str) -> str:
        normalized = str(role or "").strip().lower()
        if normalized in {"user", "assistant", "system", "tool"}:
            return normalized
        if "assistant" in normalized or "agent" in normalized:
            return "assistant"
        return "user"

    def _timestamp_for(self, metadata: dict) -> str:
        value = metadata.get("timestamp")
        if isinstance(value, str) and value.strip():
            normalized = self._normalize_timestamp(value)
            if normalized:
                return normalized
        try:
            session_offset = int(metadata.get("session_id", 0))
        except (TypeError, ValueError):
            session_offset = 0
        try:
            turn_offset = int(metadata.get("turn_id", self._page_count))
        except (TypeError, ValueError):
            turn_offset = self._page_count
        base = datetime(2026, 1, 1, tzinfo=timezone.utc)
        return (base + timedelta(days=session_offset, minutes=turn_offset)).isoformat().replace("+00:00", "Z")

    def _normalize_timestamp(self, value: str) -> str | None:
        candidate = value.strip()
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

LME_SESSION_RE = re.compile(r"\blme-session-([A-Za-z0-9_:-]+)\b")
CONVERSATION_PATH_SESSION_RE = re.compile(
    r"(?:^|/)conversations/[^/\s]+/(lme-session-[A-Za-z0-9_:-]+)\.md\b"
)


def normalize_lme_session_id(session_id) -> str:
    value = str(session_id).strip()
    if value.startswith("lme-session-"):
        return value
    return f"lme-session-{value}"


def haystack_session_id(session, fallback_idx: int):
    if isinstance(session, dict):
        return session.get("session_id", session.get("id", fallback_idx))
    return fallback_idx


def haystack_turns(session) -> list:
    if isinstance(session, list):
        return session
    if isinstance(session, dict):
        return session.get("conversation", session.get("turns", []))
    return []


def result_session_ids(result) -> set[str]:
    """Extract LongMemEval session IDs from Quaid result metadata or memory paths."""
    found: set[str] = set()

    def visit(value) -> None:
        if value is None:
            return
        if isinstance(value, dict):
            for key, nested in value.items():
                if key in {"session_id", "source_session_id"}:
                    found.add(normalize_lme_session_id(nested))
                visit(nested)
            return
        if isinstance(value, list):
            for item in value:
                visit(item)
            return
        if isinstance(value, str):
            for match in CONVERSATION_PATH_SESSION_RE.findall(value):
                found.add(normalize_lme_session_id(match))
            for match in LME_SESSION_RE.findall(value):
                found.add(normalize_lme_session_id(match))

    visit(result)
    return found


def session_id_values(value) -> list:
    if value is None:
        return []
    if isinstance(value, (list, tuple, set)):
        return list(value)
    return [value]


def recall_score(retrieved: list, answer_session_ids, k: int) -> tuple[float, list[str], list[str]]:
    expected = {
        normalize_lme_session_id(session_id)
        for session_id in session_id_values(answer_session_ids)
    }
    retrieved_ids: list[str] = []
    for result in retrieved[:k]:
        for session_id in sorted(result_session_ids(result)):
            if session_id not in retrieved_ids:
                retrieved_ids.append(session_id)
    score = 1.0 if expected and any(session_id in expected for session_id in retrieved_ids) else 0.0
    return score, sorted(expected), retrieved_ids

def run_longmemeval(
    questions: list,
    quaid_db_base: str,
    answerer_model: str,
    judge_model: str,
    provider: str,
    metric: str = "qa",
    top_k: int | None = None,
    checkpoint_path: str = None,
    skip_embed: bool = False,
) -> dict:
    """Run LongMemEval: per-question ingest + retrieve + evaluate.
    
    skip_embed is retained for CLI compatibility; conversation extraction now owns
    indexing, so it no longer skips a separate page-embedding step.
    
    Supports checkpoint/resume: saves progress every 10 questions so
    a timed-out run can be resumed without restarting from scratch.
    """
    import time
    top_k = top_k if top_k is not None else (5 if metric == "recall" else 20)

    # Load checkpoint if exists
    completed = {}
    if checkpoint_path and Path(checkpoint_path).exists():
        try:
            checkpoint = json.loads(Path(checkpoint_path).read_text())
            if checkpoint.get("metric") in {None, metric}:
                completed = {item["question_id"]: item for item in checkpoint.get("results", [])}
                print(f"Resuming from checkpoint: {len(completed)} questions already done")
            else:
                print(f"Ignoring checkpoint for metric={checkpoint.get('metric')}; running metric={metric}")
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

    metric_label = f"recall_at_{top_k}" if metric == "recall" else "qa"
    print(f"Evaluating {len(questions)} questions (metric={metric_label}, per-question ingest)...")

    for i, qa in enumerate(questions):
        q_id = qa.get("question_id", str(i))

        # Skip already completed
        if q_id in completed:
            continue

        question = qa["question"]
        ground_truth = qa["answer"]
        q_type = qa.get("question_type", "unknown")
        sessions = qa.get("haystack_sessions", [])
        answer_session_ids = qa.get("answer_session_ids", [])

        # Fresh DB per question
        db_path = f"{quaid_db_base}-q{i:04d}.db"
        backend = QuaidBackend(db_path)
        backend.init()

        # Ingest all haystack sessions for this question
        for sess_idx, session in enumerate(sessions):
            session_id = haystack_session_id(session, sess_idx)
            turns = haystack_turns(session)
            for turn_idx, turn in enumerate(turns):
                role = turn.get("role", "unknown")
                content = turn.get("content", "")
                if content and len(content.strip()) > 10:
                    backend.add(content, {
                        "role": role,
                        "session_id": session_id,
                        "turn_id": turn_idx,
                    })

        # Trigger extraction
        flushed = backend.flush_to_quaid(skip_embed=skip_embed)

        retrieved = []
        if flushed:
            retrieved = backend.search(question, top_k=top_k, recall=(metric == "recall"))

        if metric == "recall":
            score, expected_session_ids, retrieved_session_ids = recall_score(
                retrieved,
                answer_session_ids,
                top_k,
            )
            completed[q_id] = {
                "question_id": q_id,
                "score": score,
                "type": q_type,
                "answer_session_ids": expected_session_ids,
                "retrieved_session_ids": retrieved_session_ids,
                "retrieved_count": len(retrieved),
            }
        else:
            # Retrieve + Answer + Judge
            if flushed:
                context = backend.get_context(retrieved)
                predicted = generate_answer(context, question, answerer_model, provider)
            else:
                predicted = "I don't know"
            score = judge_answer(question, predicted, ground_truth, judge_model, provider)
            completed[q_id] = {"question_id": q_id, "score": score, "type": q_type}

        all_scores.append(score)
        if q_type not in results_by_type:
            results_by_type[q_type] = []
        results_by_type[q_type].append(score)

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
                        "metric": metric,
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
    print(f"  Metric: {metric_label}")
    print(f"  Overall: {overall:.3f} ({overall*100:.1f}%)")
    for t, v in sorted(by_type.items()):
        print(f"  {t}: {v['avg']:.3f} ({v['count']} questions)")

    scores = {
        "metric": metric_label,
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
    if metric == "recall":
        scores["top_k"] = top_k
        scores[f"r_at_{top_k}"] = scores["overall"]
    return scores


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--db", required=True, help="Base path for per-question DBs")
    parser.add_argument("--output", required=True)
    parser.add_argument("--quaid-version", default="unknown")
    parser.add_argument("--answerer-model", default="gpt-4o")
    parser.add_argument("--judge-model", default="gpt-4o")
    parser.add_argument("--provider", default="openai", choices=["openai", "anthropic"])
    parser.add_argument("--metric", default="qa", choices=["qa", "recall"],
                        help="Evaluation metric: qa uses LLM answer generation and judging; recall computes R@k from answer_session_ids")
    parser.add_argument("--top-k", type=int, default=None,
                        help="Number of Quaid query results to retrieve (default: 20 for qa, 5 for recall)")
    parser.add_argument("--max-questions", type=int, default=None,
                        help="Limit questions for faster runs (e.g. 50)")
    parser.add_argument("--skip-embed", action="store_true",
                        help="Skip vector embedding (FTS only, ~10x faster, use for baseline runs)")
    args = parser.parse_args()
    top_k = args.top_k if args.top_k is not None else (5 if args.metric == "recall" else 20)

    print(f"LongMemEval adapter - Quaid {args.quaid_version}")
    metric_label = f"recall_at_{top_k}" if args.metric == "recall" else "qa"
    print(f"Metric: {metric_label}")
    if args.metric == "qa":
        print(f"Provider: {args.provider} | Answerer: {args.answerer_model} | Judge: {args.judge_model}")
    else:
        print("Provider: not used in recall mode")
    print(f"NOTE: Per-question ingest - each question has its own memory store")
    if args.metric == "recall":
        print("NOTE: Uses Quaid conversation memory: memory_add_turn -> extract -> memory_query")
    else:
        print("NOTE: Uses Quaid conversation memory: memory_add_turn -> extract -> query")
    print()

    questions = load_longmemeval(args.max_questions)
    print(f"Loaded {len(questions)} questions")

    scores = run_longmemeval(
        questions,
        quaid_db_base=args.db,
        answerer_model=args.answerer_model,
        judge_model=args.judge_model,
        provider=args.provider,
        metric=args.metric,
        top_k=top_k,
        checkpoint_path=f"{args.db}-{args.metric}-checkpoint.json",
        skip_embed=args.skip_embed,
    )

    output = {
        "quaid_version": args.quaid_version,
        "date": str(date.today()),
        "benchmark": "longmemeval",
        "metric": scores["metric"],
        "longmemeval": scores,
        "config": {
            "metric": args.metric,
            "answerer_model": args.answerer_model,
            "judge_model": args.judge_model,
            "provider": args.provider,
            "top_k": top_k,
            "total_questions": len(questions),
        }
    }

    Path(args.output).write_text(json.dumps(output, indent=2))
    print(f"\nResults written to: {args.output}")
    print(f"Overall: {scores['overall']:.3f}")


if __name__ == "__main__":
    main()
