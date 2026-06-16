#!/usr/bin/env python3
"""Shared preflight checks for Quaid benchmark runners."""

from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path


def _run(args: list[str], timeout: int = 30, env: dict[str, str] | None = None) -> subprocess.CompletedProcess:
    return subprocess.run(args, capture_output=True, text=True, timeout=timeout, env=env)


def _version(binary: str) -> str:
    result = _run([binary, "--version"], timeout=10)
    if result.returncode != 0:
        detail = (result.stderr or result.stdout).strip()
        raise RuntimeError(f"{binary} --version failed: {detail}")
    text = (result.stdout or result.stderr).strip()
    for token in text.replace("v", " ").split():
        parts = token.strip(",").split(".")
        if len(parts) == 3 and all(part.isdigit() for part in parts):
            return ".".join(parts)
    return text or "unknown"


def _check_api_key(provider: str) -> None:
    key_name = {"openai": "OPENAI_API_KEY", "anthropic": "ANTHROPIC_API_KEY"}.get(provider)
    if key_name and not os.environ.get(key_name):
        raise RuntimeError(f"{key_name} is required for this benchmark")


def _check_extraction(binary: str) -> None:
    with tempfile.TemporaryDirectory(prefix="quaid-preflight-") as tmp:
        db_path = str(Path(tmp) / "preflight.db")
        env = {**os.environ, "QUAID_DB": db_path}
        init = _run([binary, "init", db_path], timeout=60, env=env)
        if init.returncode != 0:
            detail = (init.stderr or init.stdout).strip()
            raise RuntimeError(f"quaid init failed during extraction preflight: {detail}")
        enabled = _run([binary, "extraction", "enable"], timeout=900, env=env)
        if enabled.returncode != 0:
            detail = (enabled.stderr or enabled.stdout).strip()
            raise RuntimeError(f"quaid extraction enable failed: {detail}")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--quaid-bin", default=os.environ.get("QUAID_BIN", "quaid"))
    parser.add_argument("--expected-version", default=os.environ.get("EXPECTED_QUAID_VERSION") or os.environ.get("EXPECTED_VERSION"))
    parser.add_argument("--db", default=None)
    parser.add_argument("--corpus", default=None)
    parser.add_argument("--provider", default=os.environ.get("LLM_PROVIDER", "openai"))
    parser.add_argument("--needs-llm", action="store_true")
    parser.add_argument("--needs-extraction", action="store_true")
    args = parser.parse_args()

    try:
        resolved = shutil.which(args.quaid_bin) if os.sep not in args.quaid_bin else args.quaid_bin
        if not resolved:
            raise RuntimeError(f"Quaid binary not found on PATH: {args.quaid_bin}")
        resolved = str(Path(resolved).expanduser().resolve())
        version = _version(resolved)
        if args.expected_version and version != args.expected_version:
            raise RuntimeError(
                f"Quaid version mismatch: expected {args.expected_version}, got {version} from {resolved}"
            )
        if args.db:
            db = Path(args.db).expanduser()
            parent = db.parent if db.suffix else db.parent
            if not parent.exists():
                raise RuntimeError(f"DB parent directory does not exist: {parent}")
            if not os.access(parent, os.W_OK):
                raise RuntimeError(f"DB parent directory is not writable: {parent}")
        if args.corpus:
            corpus = Path(args.corpus).expanduser()
            if not corpus.exists() or not corpus.is_dir():
                raise RuntimeError(f"Corpus directory does not exist: {corpus}")
            if not any(corpus.iterdir()):
                raise RuntimeError(f"Corpus directory is empty: {corpus}")
        if args.needs_llm:
            _check_api_key(args.provider)
        if args.needs_extraction:
            _check_extraction(resolved)
    except Exception as exc:
        print(f"PRECHECK FAILED: {exc}", file=sys.stderr)
        return 2

    print("=== Quaid preflight ===")
    print(f"binary: {resolved}")
    print(f"version: {version}")
    if args.expected_version:
        print(f"expected_version: {args.expected_version}")
    if args.db:
        print(f"db: {args.db}")
    if args.corpus:
        print(f"corpus: {args.corpus}")
    if args.needs_llm:
        print(f"llm_provider: {args.provider}")
    if args.needs_extraction:
        print("extraction: enabled")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
