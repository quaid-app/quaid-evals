"""
beam_adapter.py - BEAM benchmark adapter for Quaid.

BEAM (ICLR 2026) - "Beyond a Million Tokens"
Tests memory at extreme scale: 100K, 500K, 1M, and 10M token conversations.

Datasets (CC BY-SA 4.0):
  Mohammadta/BEAM     - 100K, 500K, 1M splits
  Mohammadta/BEAM-10M - 10M split

Run order: 100K -> 500K -> 1M -> 10M
(catch failures cheaply before 10M)

Mem0 v3 reference: BEAM 1M=64.1%, BEAM 10M=48.6%
Hindsight: SOTA on BEAM 10M

Usage:
  python3 benchmarks/beam/beam_adapter.py --split 100K --output results/beam-100k-v0.13.0.json
  python3 benchmarks/beam/beam_adapter.py --split 1M   --output results/beam-1m-v0.13.0.json
  python3 benchmarks/beam/beam_adapter.py --split 10M  --output results/beam-10m-v0.13.0.json

Requires: OPENAI_API_KEY (or ANTHROPIC_API_KEY with --provider anthropic)
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import tempfile
from datetime import date
from pathlib import Path


# ─── Quaid backend ────────────────────────────────────────────────────────────

class QuaidBackend:
    def __init__(self, db_path: str):
        self.db_path = db_path
        self._tmp_dir = None
        self._page_count = 0
        self._env = {**os.environ, "QUAID_DB": db_path}

    def init(self):
        subprocess.run(["quaid", "init", self.db_path], env=self._env, capture_output=True)

    def reset(self):
        """Clear DB for a fresh per-conversation ingest."""
        if Path(self.db_path).exists():
            Path(self.db_path).unlink()
        self._tmp_dir = tempfile.mkdtemp(prefix="beam-pages-")
        self._page_count = 0
        self.init()

    def add(self, content: str, metadata: dict):
        if not self._tmp_dir:
            self._tmp_dir = tempfile.mkdtemp(prefix="beam-pages-")
        page_path = Path(self._tmp_dir) / f"turn-{self._page_count:06d}.md"
        role = metadata.get("role", metadata.get("speaker", "unknown"))
        meta_str = "\n".join(f"{k}: {v}" for k, v in metadata.items() if v)
        page_path.write_text(f"---\n{meta_str}\n---\n\n{role}: {content}\n")
        self._page_count += 1

    def flush(self) -> bool:
        if not self._tmp_dir or self._page_count == 0:
            return False
        r = subprocess.run(
            ["quaid", "collection", "add", "beam", self._tmp_dir, "--db", self.db_path],
            env=self._env, capture_output=True, text=True, timeout=300
        )
        if r.returncode != 0:
            return False
        e = subprocess.run(
            ["quaid", "embed", "--db", self.db_path],
            env=self._env, capture_output=True, text=True, timeout=300
        )
        return e.returncode == 0

    def query(self, q: str, top_k: int = 20) -> list:
        r = subprocess.run(
            ["quaid", "query", q, "--db", self.db_path, "--limit", str(top_k), "--json"],
            env=self._env, capture_output=True, text=True, timeout=30
        )
        if r.returncode != 0:
            return []
        try:
            return json.loads(r.stdout)
        except Exception:
            return []

    def get_context(self, results: list) -> str:
        parts = [r.get("content", r.get("text", "")).strip() for r in results if r.get("content") or r.get("text")]
        return "\n\n".join(parts[:15]) or "No relevant memories found."

    def token_count(self, results: list) -> int:
        """Rough token estimate for retrieved context."""
        text = self.get_context(results)
        return len(text) // 4  # ~4 chars per token


# ─── LLM helpers ──────────────────────────────────────────────────────────────

def call_llm(prompt: str, model: str, provider: str) -> str:
    if provider == "openai":
        import openai
        client = openai.OpenAI(api_key=os.environ["OPENAI_API_KEY"])
        resp = client.chat.completions.create(
            model=model,
            messages=[{"role": "user", "content": prompt}],
            max_tokens=256, temperature=0.0
        )
        return resp.choices[0].message.content.strip()
    elif provider == "anthropic":
        import anthropic
        client = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])
        resp = client.messages.create(
            model=model, max_tokens=256,
            messages=[{"role": "user", "content": prompt}]
        )
        return resp.content[0].text.strip()
    raise ValueError(f"Unknown provider: {provider}")


def generate_answer(context: str, question: str, model: str, provider: str) -> str:
    prompt = f"""You are answering a question based on conversation memories.

Memories:
{context}

Question: {question}

Answer concisely (1-2 sentences):"""
    try:
        return call_llm(prompt, model, provider)
    except Exception as e:
        return f"Error: {e}"


def judge_answer(question: str, predicted: str, ground_truth: str, model: str, provider: str) -> float:
    prompt = f"""Score whether the predicted answer correctly answers the question given the ground truth.

Question: {question}
Ground truth: {ground_truth}
Predicted: {predicted}

Score 0-1 (0=wrong, 0.5=partial, 1=correct). Reply with only the number:"""
    try:
        return float(call_llm(prompt, model, provider).strip())
    except Exception:
        return 0.0


# ─── Dataset loading ──────────────────────────────────────────────────────────

def load_beam(split: str, max_conversations: int | None = None) -> list:
    """Load BEAM dataset from HuggingFace."""
    try:
        from datasets import load_dataset
    except ImportError:
        print("Installing datasets library...")
        subprocess.run([sys.executable, "-m", "pip", "install", "datasets", "-q"])
        from datasets import load_dataset

    split_upper = split.upper()
    print(f"Loading BEAM {split_upper} from HuggingFace...")

    if split_upper == "10M":
        ds = load_dataset("Mohammadta/BEAM-10M", split="10M", trust_remote_code=True)
    else:
        ds = load_dataset("Mohammadta/BEAM", split=split_upper, trust_remote_code=True)

    data = list(ds)
    if max_conversations:
        data = data[:max_conversations]
    print(f"Loaded {len(data)} conversations for BEAM {split_upper}")
    return data


def parse_probing_questions(probing_questions) -> dict[str, list]:
    """Parse probing_questions field into {category: [{question, answer}]}."""
    if isinstance(probing_questions, dict):
        return probing_questions
    if isinstance(probing_questions, str):
        try:
            return json.loads(probing_questions)
        except Exception:
            pass
    if isinstance(probing_questions, list):
        result = {}
        for item in probing_questions:
            cat = item.get("category", item.get("type", "general"))
            if cat not in result:
                result[cat] = []
            result[cat].append(item)
        return result
    return {}


# ─── Main evaluation loop ─────────────────────────────────────────────────────

def run_beam(
    conversations: list,
    split: str,
    quaid_db_base: str,
    answerer_model: str,
    judge_model: str,
    provider: str,
    top_k: int = 20,
) -> dict:
    all_scores: list[float] = []
    by_category: dict[str, list[float]] = {}
    token_counts: list[int] = []

    total_q = sum(
        len(q) for conv in conversations
        for questions in parse_probing_questions(conv.get("probing_questions", {})).values()
        for q in [questions]
    )
    print(f"BEAM {split}: {len(conversations)} conversations, ~{total_q} questions")

    for i, conv in enumerate(conversations):
        conv_id = conv.get("conversation_id", str(i))
        chat = conv.get("chat", [])

        # Per-conversation fresh DB
        db_path = f"{quaid_db_base}-{split}-{i:04d}.db"
        backend = QuaidBackend(db_path)
        backend.reset()

        # Ingest all chat turns
        if isinstance(chat, list):
            for turn_idx, turn in enumerate(chat):
                if isinstance(turn, dict):
                    role = turn.get("role", turn.get("speaker", "unknown"))
                    content = turn.get("content", turn.get("text", ""))
                else:
                    role, content = "turn", str(turn)
                if content and len(str(content).strip()) > 5:
                    backend.add(str(content), {"role": role, "turn_id": turn_idx, "conv_id": conv_id})

        # For 10M: also ingest plan sections
        plans = conv.get("plans", [])
        for plan_idx, plan in enumerate(plans):
            plan_chat = plan.get("chat", []) if isinstance(plan, dict) else []
            for turn_idx, turn in enumerate(plan_chat):
                if isinstance(turn, dict):
                    role = turn.get("role", "plan")
                    content = turn.get("content", turn.get("text", ""))
                    if content:
                        backend.add(str(content), {"role": role, "plan_id": plan_idx, "turn_id": turn_idx})

        flushed = backend.flush()

        # Evaluate probing questions
        questions_by_cat = parse_probing_questions(conv.get("probing_questions", {}))
        for category, questions in questions_by_cat.items():
            for qa in questions:
                question = qa.get("question", "")
                ground_truth = qa.get("answer", qa.get("ground_truth", ""))
                if not question or not ground_truth:
                    continue

                if flushed:
                    retrieved = backend.query(question, top_k=top_k)
                    context = backend.get_context(retrieved)
                    token_counts.append(backend.token_count(retrieved))
                    predicted = generate_answer(context, question, answerer_model, provider)
                else:
                    predicted = "I don't know"
                    token_counts.append(0)

                score = judge_answer(question, predicted, ground_truth, judge_model, provider)
                all_scores.append(score)
                if category not in by_category:
                    by_category[category] = []
                by_category[category].append(score)

        # Cleanup
        try:
            Path(db_path).unlink(missing_ok=True)
        except Exception:
            pass

        if (i + 1) % 5 == 0 or i == len(conversations) - 1:
            avg = sum(all_scores) / len(all_scores) if all_scores else 0
            print(f"  Conv {i+1}/{len(conversations)}: running avg={avg:.3f} ({len(all_scores)} questions)")

    overall = sum(all_scores) / len(all_scores) if all_scores else 0.0
    avg_tokens = sum(token_counts) / len(token_counts) if token_counts else 0

    print(f"\nBEAM {split} Results:")
    print(f"  Overall: {overall:.3f} ({overall*100:.1f}%)")
    for cat, scores in sorted(by_category.items()):
        avg = sum(scores) / len(scores)
        print(f"  {cat}: {avg:.3f} ({len(scores)} questions)")
    print(f"  Avg retrieved tokens: {avg_tokens:.0f} (Mem0 reference: ~7K)")

    return {
        "overall": round(overall, 4),
        "total_questions": len(all_scores),
        "by_category": {cat: {"avg": round(sum(s)/len(s), 4), "count": len(s)} for cat, s in by_category.items()},
        "avg_retrieved_tokens": round(avg_tokens),
        "reference": {
            "mem0_v3": {"1m": 0.641, "10m": 0.486, "source": "mem0ai/memory-benchmarks release notes"},
            "hindsight": {"10m": "SOTA", "source": "Vectorize/nicoloboschi"}
        }
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--split", required=True, choices=["100K", "500K", "1M", "10M"],
                        help="BEAM split to evaluate")
    parser.add_argument("--output", required=True)
    parser.add_argument("--quaid-version", default="unknown")
    parser.add_argument("--answerer-model", default="gpt-4o")
    parser.add_argument("--judge-model", default="gpt-4o")
    parser.add_argument("--provider", default="openai", choices=["openai", "anthropic"])
    parser.add_argument("--top-k", type=int, default=20)
    parser.add_argument("--max-conversations", type=int, default=None,
                        help="Limit conversations (e.g. 5 for quick test)")
    args = parser.parse_args()

    print(f"BEAM adapter - Quaid {args.quaid_version} | Split: {args.split}")
    print(f"Provider: {args.provider} | Answerer: {args.answerer_model}")
    print(f"NOTE: Per-conversation ingest. Scores expected to be low until issue #105.")
    print()

    conversations = load_beam(args.split, args.max_conversations)
    scores = run_beam(
        conversations,
        split=args.split,
        quaid_db_base=f"/tmp/quaid-beam-{args.split.lower()}",
        answerer_model=args.answerer_model,
        judge_model=args.judge_model,
        provider=args.provider,
        top_k=args.top_k,
    )

    output = {
        "quaid_version": args.quaid_version,
        "date": str(date.today()),
        "benchmark": f"beam-{args.split.lower()}",
        "split": args.split,
        f"beam_{args.split.lower()}": scores,
        "config": {
            "answerer_model": args.answerer_model,
            "judge_model": args.judge_model,
            "provider": args.provider,
            "top_k": args.top_k,
        }
    }

    Path(args.output).write_text(json.dumps(output, indent=2))
    print(f"\nResults written to: {args.output}")
    ref = 0.641 if args.split == "1M" else 0.486 if args.split == "10M" else "n/a"
    print(f"Score: {scores['overall']:.3f} (Mem0 v3 ref: {ref})")


if __name__ == "__main__":
    main()
