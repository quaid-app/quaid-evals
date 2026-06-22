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
import contextlib
import json
import os
import re
import select
import sqlite3
import subprocess
import sys
import tempfile
import threading
import time
import urllib.request
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

# ─── Shared daemon context manager ────────────────────────────────────────────

class SharedDaemon:
    """Context manager that owns ONE quaid daemon for the full benchmark run.

    Usage::

        with SharedDaemon(db_path) as daemon:
            # daemon.db_path is the shared DB
            backend = QuaidBackend(daemon.db_path, namespace="q0001")
            ...
    """

    def __init__(self, db_path: str, cleanup_on_exit: bool = False):
        self.db_path = db_path
        self.quaid_bin = os.environ.get("QUAID_BIN") or "quaid"
        self._cleanup_on_exit = cleanup_on_exit
        self._daemon: subprocess.Popen[str] | None = None
        self._daemon_output: list[str] = []
        self._drain_thread: threading.Thread | None = None
        self._env = {**os.environ, "QUAID_DB": db_path}

    def __enter__(self) -> "SharedDaemon":
        # Init the shared DB
        result = subprocess.run(
            [self.quaid_bin, "init", self.db_path],
            env=self._env,
            capture_output=True,
            text=True,
            timeout=60,
        )
        if result.returncode != 0:
            detail = (result.stderr or result.stdout).strip()
            raise RuntimeError(f"quaid init failed: {detail}")

        # Start the daemon
        self._daemon_output = []
        self._daemon = subprocess.Popen(
            [self.quaid_bin, "daemon", "run", "--http", "--trust-loopback"],
            env=self._env,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
        )
        try:
            self._wait_for_daemon_ready(timeout_s=60)
        except Exception:
            self._stop()
            raise

        # Start drain thread to keep output buffer from filling up
        self._drain_thread = threading.Thread(
            target=self._drain_daemon_output,
            name="lme-shared-daemon-output",
            daemon=True,
        )
        self._drain_thread.start()

        print(f"[SharedDaemon] daemon ready, db={self.db_path}", file=sys.stderr)
        return self

    def __exit__(self, *_) -> None:
        self._stop()
        if self._cleanup_on_exit:
            try:
                Path(self.db_path).unlink(missing_ok=True)
            except Exception:
                pass

    def _wait_for_daemon_ready(self, timeout_s: int) -> None:
        if self._daemon is None or self._daemon.stdout is None:
            raise RuntimeError("quaid daemon stdout was not captured")
        deadline = time.monotonic() + timeout_s
        poller = select.poll()
        poller.register(self._daemon.stdout.fileno(), select.POLLIN)
        while time.monotonic() < deadline:
            if self._daemon.poll() is not None:
                self._collect_daemon_remainder()
                detail = "\n".join(self._daemon_output[-20:])
                raise RuntimeError(f"quaid daemon exited before daemon_ready\n{detail}")
            wait_ms = max(0, int(min(500, (deadline - time.monotonic()) * 1000)))
            events = poller.poll(wait_ms)
            if not events:
                continue
            line = self._daemon.stdout.readline()
            if not line:
                continue
            self._record_output(line)
            if "daemon_ready" in line:
                return
        detail = "\n".join(self._daemon_output[-20:])
        raise TimeoutError(f"Timed out waiting for quaid daemon_ready\n{detail}")

    def _drain_daemon_output(self) -> None:
        process = self._daemon
        if process is None or process.stdout is None:
            return
        for line in process.stdout:
            self._record_output(line)

    def _collect_daemon_remainder(self) -> None:
        if self._daemon is None or self._daemon.stdout is None:
            return
        try:
            for line in self._daemon.stdout.readlines():
                self._record_output(line)
        except Exception:
            pass

    def _record_output(self, line: str) -> None:
        self._daemon_output.append(line.rstrip())
        if len(self._daemon_output) > 200:
            del self._daemon_output[: len(self._daemon_output) - 200]

    def _stop(self) -> None:
        process = self._daemon
        drain_thread = self._drain_thread
        self._daemon = None
        self._drain_thread = None
        if process is None:
            return
        if process.poll() is None:
            process.kill()
            try:
                process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                pass
        if drain_thread and drain_thread.is_alive():
            drain_thread.join(timeout=1)
        print("[SharedDaemon] daemon stopped.", file=sys.stderr)


# ─── Quaid backend ────────────────────────────────────────────────────────────

def extraction_counts(db_path: str, session_ids: set[str] | None = None) -> dict[str, int]:
    """Return extraction queue counts, optionally filtered by session_ids."""
    with sqlite3.connect(db_path, timeout=30) as conn:
        if session_ids:
            placeholders = ",".join("?" for _ in session_ids)
            row = conn.execute(
                f"""
                SELECT
                    COALESCE(SUM(CASE WHEN status = 'pending' THEN 1 ELSE 0 END), 0),
                    COALESCE(SUM(CASE WHEN status = 'running' THEN 1 ELSE 0 END), 0),
                    COALESCE(SUM(CASE WHEN status = 'done' THEN 1 ELSE 0 END), 0),
                    COALESCE(SUM(CASE WHEN status = 'failed' THEN 1 ELSE 0 END), 0)
                FROM extraction_queue
                WHERE session_id IN ({placeholders})
                """,
                list(session_ids),
            ).fetchone()
        else:
            row = conn.execute(
                """
                SELECT
                    COALESCE(SUM(CASE WHEN status = 'pending' THEN 1 ELSE 0 END), 0),
                    COALESCE(SUM(CASE WHEN status = 'running' THEN 1 ELSE 0 END), 0),
                    COALESCE(SUM(CASE WHEN status = 'done' THEN 1 ELSE 0 END), 0),
                    COALESCE(SUM(CASE WHEN status = 'failed' THEN 1 ELSE 0 END), 0)
                FROM extraction_queue
                """
            ).fetchone()
    pending, running, done, failed = row or (0, 0, 0, 0)
    return {
        "pending": int(pending),
        "running": int(running),
        "done": int(done),
        "failed": int(failed),
    }


def recent_failed_jobs(db_path: str, session_ids: set[str] | None = None) -> list[dict]:
    with sqlite3.connect(db_path, timeout=30) as conn:
        conn.row_factory = sqlite3.Row
        if session_ids:
            placeholders = ",".join("?" for _ in session_ids)
            rows = conn.execute(
                f"""
                SELECT session_id, attempts, COALESCE(last_error, '') AS last_error
                FROM extraction_queue
                WHERE status = 'failed' AND session_id IN ({placeholders})
                ORDER BY id DESC
                LIMIT 5
                """,
                list(session_ids),
            ).fetchall()
        else:
            rows = conn.execute(
                """
                SELECT session_id, attempts, COALESCE(last_error, '') AS last_error
                FROM extraction_queue
                WHERE status = 'failed'
                ORDER BY id DESC
                LIMIT 5
                """
            ).fetchall()
    return [dict(row) for row in rows]


def wait_for_extraction_completion(
    db_path: str,
    session_ids: set[str] | None = None,
    timeout_s: int = 300,
    poll_interval_s: float = 0.5,
    settle_s: float = 2.0,
) -> dict[str, int]:
    """Wait for extraction queue to drain.

    If session_ids is provided, waits only for those sessions (per-question
    isolation with the shared DB). Falls back to waiting for all pending=0
    if session_ids is None.
    """
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        counts = extraction_counts(db_path, session_ids)
        if counts["failed"] > 0:
            raise RuntimeError(
                "Extraction worker reported failed jobs: "
                + json.dumps(recent_failed_jobs(db_path, session_ids), indent=2)
            )
        if counts["pending"] == 0 and counts["running"] == 0:
            time.sleep(settle_s)
            return extraction_counts(db_path, session_ids)
        time.sleep(poll_interval_s)
    raise TimeoutError(
        f"Timed out waiting for extraction queue to drain: {extraction_counts(db_path, session_ids)}"
    )


class QuaidBackend:
    """Thin wrapper around the quaid CLI for conversation memory.

    When used with a shared daemon (the normal benchmark path), pass
    ``namespace`` to isolate per-question data within the shared DB.
    Daemon lifecycle is managed externally by :class:`SharedDaemon`.
    """

    _extraction_cache_checked = False

    def __init__(self, db_path: str, namespace: str | None = None):
        self.db_path = db_path
        self.namespace = namespace
        self.quaid_bin = os.environ.get("QUAID_BIN") or "quaid"
        self._workspace_dir = Path(tempfile.mkdtemp(prefix="lme-quaid-"))
        self._vault_dir = self._workspace_dir / "vault"
        self._page_count = 0
        self._sessions: set[str] = set()
        self._env = {**os.environ, "QUAID_DB": db_path}

    def init(self):
        self._vault_dir.mkdir(parents=True, exist_ok=True)
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
            [self.quaid_bin, *args],
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
        """Reset per-question state (no daemon to restart with shared architecture)."""
        self._page_count = 0
        self._sessions = set()

    def add(self, content: str, metadata: dict):
        session_id = self._session_id(metadata)
        payload: dict = {
            "session_id": session_id,
            "role": self._role_for(metadata.get("role", metadata.get("speaker", "user"))),
            "content": content,
            "metadata": {
                "benchmark": "longmemeval",
                **{k: v for k, v in metadata.items() if v is not None},
            },
            "timestamp": self._timestamp_for(metadata),
        }
        if self.namespace:
            payload["namespace"] = self.namespace
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
            payload = {"session_id": session_id}
            if self.namespace:
                payload["namespace"] = self.namespace
            result = self._run_quaid(
                ["call", "memory_close_session", json.dumps(payload)],
                timeout=30,
            )
            if result.returncode != 0:
                detail = (result.stderr or result.stdout).strip()
                print(
                    f"Warning: memory_close_session failed for {session_id}: {detail}",
                    file=sys.stderr,
                )
                ok = False
        if ok:
            try:
                # Filter extraction wait to only this question's sessions for
                # per-question isolation in the shared DB. Questions run
                # sequentially, so waiting for all pending is also safe, but
                # filtering by session_id is more precise.
                wait_for_extraction_completion(
                    self.db_path,
                    session_ids=self._queue_session_ids() if self._sessions else None,
                    timeout_s=300,
                )
            except Exception as e:
                print(f"Warning: Quaid extraction queue did not drain: {e}", file=sys.stderr)
                ok = False
        return ok

    def close(self) -> None:
        """Clean up per-question resources. Daemon is NOT stopped here."""
        # Nothing to stop - daemon lifecycle is owned by SharedDaemon.
        pass

    def _queue_session_ids(self) -> set[str]:
        if not self.namespace:
            return set(self._sessions)
        return {f"{self.namespace}::{session_id}" for session_id in self._sessions}

    def __del__(self):
        try:
            self.close()
        except Exception:
            pass

    def search(self, query: str, top_k: int = 20, recall: bool = False) -> list:
        payload: dict = {"query": query, "limit": top_k}
        if self.namespace:
            payload["namespace"] = self.namespace
        result = self._run_quaid(
            ["call", "memory_query", json.dumps(payload), "--json"],
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
        normalized = f"lme-session-{session_id}"
        if self.namespace:
            return f"{self.namespace}-{normalized}"
        return normalized

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
    return call_llm(prompt, model, provider)


def judge_answer(question: str, predicted: str, ground_truth: str, model: str, provider: str) -> float:
    prompt = f"""Score whether the predicted answer correctly answers the question given the ground truth.

Question: {question}
Ground truth: {ground_truth}
Predicted: {predicted}

Score from 0 to 1 (0=wrong, 0.5=partial, 1=correct). Reply with only the number:"""
    score_str = call_llm(prompt, model, provider).strip()
    return float(score_str)


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
    marker = "lme-session-"
    if marker in value and not value.startswith(marker):
        value = value[value.index(marker):]
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

    Uses a single shared Quaid daemon for the full run. Per-question isolation
    is achieved via Quaid namespaces (q0001, q0002, ...) rather than per-question
    DBs with per-question daemon restarts. This gives ~10x throughput improvement
    over the previous architecture which started/stopped 500 daemon instances.

    skip_embed is retained for CLI compatibility; conversation extraction now owns
    indexing, so it no longer skips a separate page-embedding step.

    Supports checkpoint/resume: saves progress every 10 questions so
    a timed-out run can be resumed without restarting from scratch.
    """
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
    print(f"Evaluating {len(questions)} questions (metric={metric_label}, shared daemon, per-question namespaces)...")

    # ONE shared DB + ONE daemon for the full run
    shared_db_path = f"{quaid_db_base}.db"

    with SharedDaemon(shared_db_path) as daemon:
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

            namespace = f"q{i:04d}"
            backend = QuaidBackend(daemon.db_path, namespace=namespace)
            try:
                backend.init()

                # Ingest all haystack sessions for this question.
                # Sessions with many turns are chunked into sub-sessions of
                # MAX_TURNS_PER_SESSION turns to avoid the Quaid conversation
                # file parser limit (fails past ~40-50 lines).
                MAX_TURNS_PER_SESSION = 30
                for sess_idx, session in enumerate(sessions):
                    session_id = haystack_session_id(session, sess_idx)
                    turns = haystack_turns(session)
                    for chunk_start in range(0, max(1, len(turns)), MAX_TURNS_PER_SESSION):
                        chunk = turns[chunk_start:chunk_start + MAX_TURNS_PER_SESSION]
                        chunk_num = chunk_start // MAX_TURNS_PER_SESSION
                        chunk_session_id = (
                            session_id if chunk_num == 0
                            else f"{session_id}-chunk{chunk_num}"
                        )
                        for turn_idx, turn in enumerate(chunk):
                            role = turn.get("role", "unknown")
                            content = turn.get("content", "")
                            if content and len(content.strip()) > 10:
                                backend.add(content, {
                                    "role": role,
                                    "session_id": chunk_session_id,
                                    "turn_id": chunk_start + turn_idx,
                                })

                # Close sessions so the daemon extraction worker drains queued jobs.
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
            finally:
                backend.close()

            all_scores.append(score)
            if q_type not in results_by_type:
                results_by_type[q_type] = []
            results_by_type[q_type].append(score)

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
    parser.add_argument("--db", required=True, help="Base path for shared DB (extension .db is appended)")
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
    print(f"NOTE: Shared daemon architecture - one daemon for full run, per-question namespaces")
    if args.metric == "recall":
        print("NOTE: Uses Quaid conversation memory: memory_add_turn -> daemon extraction -> memory_query")
    else:
        print("NOTE: Uses Quaid conversation memory: memory_add_turn -> daemon extraction -> memory_query")
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
