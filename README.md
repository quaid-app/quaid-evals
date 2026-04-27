<div align="center">
  <h1>Quaid Evals</h1>
  <p><strong>Automated benchmark suite for <a href="https://quaid.app">Quaid</a> — the local-first persistent memory system for AI agents.</strong></p>

  <a href="https://github.com/quaid-app/quaid-evals/actions"><img src="https://github.com/quaid-app/quaid-evals/workflows/Run%20Benchmarks%20(Manual)/badge.svg" alt="Benchmarks"></a>
  <a href="https://github.com/quaid-app/quaid-evals/blob/main/LICENSE"><img src="https://img.shields.io/badge/license-MIT-blue.svg" alt="License"></a>
  <a href="https://quaid-app.github.io/quaid-evals"><img src="https://img.shields.io/badge/results-live-brightgreen" alt="Live Results"></a>
  <a href="https://github.com/quaid-app/quaid"><img src="https://img.shields.io/badge/quaid-v0.9.9-orange" alt="Quaid Version"></a>

  <br><br>

  <a href="https://quaid-app.github.io/quaid-evals">📊 Live Results</a> •
  <a href="https://github.com/quaid-app/quaid">Quaid Repo</a> •
  <a href="https://quaid.app">quaid.app</a>
</div>

---

## Latest Results

| Benchmark | Score | Reference |
|-----------|-------|-----------|
| **DAB** | 193/215 (90%) | — |
| **MSMARCO P@5** | — | GBrain: 49.1% |
| **MSMARCO R@5** | — | GBrain: 97.9% |
| **LoCoMo** | — | Mem0: 91.6% |

> Results update automatically on every Quaid release. [View full history →](https://quaid-app.github.io/quaid-evals)

---

## Why benchmark memory systems?

Memory is the hardest part of building AI agents at scale. Without a rigorous eval framework:

- You can't tell if a change actually improves retrieval
- You can't compare against alternatives with confidence
- You can't catch regressions before they hit production

Quaid Evals runs industry-standard benchmarks (MSMARCO, LoCoMo, BEAM) alongside our own [DAB](benchmarks/dab/README.md) benchmark — giving you apples-to-apples numbers against Mem0, GBrain, and other memory systems.

---

## Benchmarks

| Benchmark | Corpus | What it measures | Ground truth |
|-----------|--------|-----------------|--------------|
| **[DAB](benchmarks/dab/README.md)** | MSMARCO dev (4K passages) | FTS, semantic, MCP, performance, integrity | ✅ Human qrels |
| **[gbrain-evals](benchmarks/gbrain-evals/README.md)** | MSMARCO dev (500 queries) | P@5, R@5 — same harness as GBrain | ✅ Human qrels |
| **[LoCoMo](benchmarks/locomo/README.md)** | 10 dialogues, ~300 questions | Multi-session conversational recall | ✅ Human labels |
| **[BEAM](benchmarks/beam/README.md)** | 100K / 1M / 10M tokens | Extreme-scale memory retrieval | ✅ LLM-as-judge |

**Reference scores:**

| System | P@5 | R@5 | LoCoMo | BEAM 1M | BEAM 10M |
|--------|-----|-----|--------|---------|---------|
| **Quaid v0.9.9** | — | — | — | — | — |
| GBrain ([source](https://x.com/garrytan/status/2048503081911128119)) | 49.1% | 97.9% | — | — | — |
| Mem0 v3 | — | — | 91.6% | 64.1% | 48.6% |

---

## Run locally

```bash
git clone https://github.com/quaid-app/quaid-evals
cd quaid-evals

# Install Quaid (builds from source if no binary release found)
bash scripts/install-quaid.sh

# Set up MSMARCO corpus (~50MB stream from HuggingFace)
bash scripts/setup-corpus.sh

# Run benchmarks
bash benchmarks/dab/run.sh
bash benchmarks/gbrain-evals/run.sh

# Generate report + serve site
python3 scripts/generate-report.py
cd site && npm install && npm run dev
```

### Run with a specific Quaid version

```bash
bash scripts/install-quaid.sh v0.9.9
```

### Use Anthropic instead of OpenAI for LoCoMo

```bash
LLM_PROVIDER=anthropic \
ANTHROPIC_API_KEY=sk-ant-... \
bash benchmarks/locomo/run.sh
```

---

## CI / Automated runs

Benchmarks run automatically via GitHub Actions:

- **On demand**: [Run Benchmarks (Manual)](https://github.com/quaid-app/quaid-evals/actions/workflows/eval-manual.yml) — pick a version, pick which benchmarks
- **On release**: Triggered via `repository_dispatch` when Quaid ships a new release

Results are committed to `results/` and the site redeploys automatically to [quaid-app.github.io/quaid-evals](https://quaid-app.github.io/quaid-evals).

---

## Architecture

```
quaid-evals/
├── benchmarks/
│   ├── dab/            DAB: FTS + semantic + MCP + performance (215 pts max)
│   ├── gbrain-evals/   P@5 / R@5 on MSMARCO dev (same harness as GBrain)
│   ├── locomo/         Multi-session conversational memory recall
│   └── beam/           Extreme-scale memory (100K–10M tokens)
├── scripts/
│   ├── install-quaid.sh        Download binary or build from source
│   ├── setup-corpus.sh         Stream MSMARCO from HuggingFace (~50MB)
│   ├── build-msmarco-subset.py MSMARCO streaming corpus builder
│   └── generate-report.py      Aggregate results → site data
├── site/               Astro site → GitHub Pages
│   └── src/pages/      Score cards, history chart, comparison table
└── results/            JSON benchmark results (committed, versioned)
```

The site reads `site/src/data/report.json` (generated from `results/*.json`) and renders everything statically — no backend required.

---

## Corpus

Benchmarks use the [MSMARCO passage ranking dev set](https://microsoft.github.io/msmarco/) — the industry standard for passage retrieval evaluation.

- **500 dev queries** with human relevance judgments
- **~4,000 passages** covering a broad range of topics
- Streamed from HuggingFace at run time (~50MB, no 2.9GB download)
- Fallback: [quaid-app/msmarco-corpus](https://github.com/quaid-app/msmarco-corpus) (FiQA financial QA, pre-built)

---

## License

MIT — benchmark scripts and site code.

Corpus data: MSMARCO ([Microsoft Research License](https://microsoft.github.io/msmarco/)), FiQA ([CC BY 4.0](https://creativecommons.org/licenses/by/4.0/)).

---

<div align="center">
  <sub>Memory that persists. Intelligence that compounds.</sub>
</div>
