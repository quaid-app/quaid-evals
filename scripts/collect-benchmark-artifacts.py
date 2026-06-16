#!/usr/bin/env python3
"""
Download the newest available benchmark result artifacts from GitHub Actions.

The dashboard workflow runs independently from benchmark workflows. It should
publish with whichever benchmark results are available, instead of requiring
all benchmarks to succeed in a single Actions run.
"""
from __future__ import annotations

import os
import shutil
import tempfile
import urllib.error
import urllib.request
import zipfile
from pathlib import Path


WORKFLOWS = [
    ("benchmark-dab.yml", "dab", "benchmark-results-dab"),
    ("benchmark-gbrain-evals.yml", "gbrain-evals", "benchmark-results-gbrain-evals"),
    ("benchmark-locomo.yml", "locomo", "benchmark-results-locomo"),
    ("benchmark-longmemeval.yml", "longmemeval", "benchmark-results-longmemeval"),
    ("benchmark-beam.yml", "beam", "benchmark-results-beam"),
]

RESULT_PREFIXES = (
    "dab-",
    "gbrain-evals-",
    "locomo-",
    "longmemeval-",
    "beam-",
)


def github_request(url: str, token: str) -> urllib.request.Request:
    return urllib.request.Request(
        url,
        headers={
            "Accept": "application/vnd.github+json",
            "Authorization": f"Bearer {token}",
            "X-GitHub-Api-Version": "2022-11-28",
            "User-Agent": "quaid-evals-artifact-collector",
        },
    )


def read_json(url: str, token: str) -> dict:
    import json

    with urllib.request.urlopen(github_request(url, token), timeout=30) as response:
        return json.loads(response.read().decode("utf-8"))


def download_zip(url: str, token: str, dest: Path) -> None:
    with urllib.request.urlopen(github_request(url, token), timeout=120) as response:
        dest.write_bytes(response.read())


def copy_result_jsons(extracted_dir: Path, results_dir: Path) -> int:
    copied = 0
    results_dir.mkdir(parents=True, exist_ok=True)

    for path in extracted_dir.rglob("*.json"):
        if not path.name.startswith(RESULT_PREFIXES):
            continue
        target = results_dir / path.name
        shutil.copy2(path, target)
        copied += 1
        print(f"Copied {target}")

    return copied


def collect_for_workflow(api_base: str, repo: str, token: str, workflow_file: str, artifact_name: str) -> bool:
    runs_url = f"{api_base}/repos/{repo}/actions/workflows/{workflow_file}/runs?status=completed&branch=main&per_page=10"
    try:
        runs = read_json(runs_url, token).get("workflow_runs", [])
    except urllib.error.HTTPError as exc:
        print(f"Warning: could not list runs for {workflow_file}: HTTP {exc.code}")
        return False

    for run in runs:
        run_id = run.get("id")
        conclusion = run.get("conclusion")
        if conclusion != "success":
            print(f"Skipping {workflow_file} run {run_id} with conclusion: {conclusion}.")
            continue

        artifacts_url = f"{api_base}/repos/{repo}/actions/runs/{run_id}/artifacts?per_page=100"
        artifacts = read_json(artifacts_url, token).get("artifacts", [])
        artifact = next(
            (
                item
                for item in artifacts
                if item.get("name") == artifact_name and not item.get("expired")
            ),
            None,
        )
        if artifact is None:
            continue

        with tempfile.TemporaryDirectory(prefix="benchmark-artifact-") as tmp:
            tmp_dir = Path(tmp)
            zip_path = tmp_dir / f"{artifact_name}.zip"
            extract_dir = tmp_dir / "extracted"
            extract_dir.mkdir()
            download_zip(artifact["archive_download_url"], token, zip_path)
            with zipfile.ZipFile(zip_path) as archive:
                archive.extractall(extract_dir)
            copied = copy_result_jsons(extract_dir, Path("results"))
            if copied:
                print(
                    f"Collected {copied} result file(s) from {workflow_file} "
                    f"run {run_id} ({conclusion})."
                )
                return True

        print(f"Artifact {artifact_name} from run {run_id} had no result JSONs.")

    print(f"Warning: no usable artifact found for {workflow_file}.")
    return False


def main() -> int:
    token = os.environ.get("GITHUB_TOKEN")
    repo = os.environ.get("GITHUB_REPOSITORY")
    api_base = os.environ.get("GITHUB_API_URL", "https://api.github.com")

    if not token or not repo:
        raise SystemExit("GITHUB_TOKEN and GITHUB_REPOSITORY are required.")

    collected = 0
    for workflow_file, label, artifact_name in WORKFLOWS:
        print(f"Checking latest {label} artifacts...")
        if collect_for_workflow(api_base, repo, token, workflow_file, artifact_name):
            collected += 1

    print(f"Collected artifacts for {collected}/{len(WORKFLOWS)} benchmark workflow(s).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
