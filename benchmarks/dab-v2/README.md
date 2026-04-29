# DAB v2 - Agent Memory Benchmark v2.0

The next-generation benchmark for agent memory systems. Tests what actually matters for AI agents in production.

## Why DAB v2?

DAB v1 scores Quaid at 99% (213/215) but Quaid still can't replace qmd in real sessions. DAB v2 makes the gap visible:

| Section | Points | Quaid v0.11.6 | qmd | GBrain | Mem0 v3 |
|---------|--------|---------------|-----|--------|---------|
| §1 Infrastructure | 40 | ~38 | ~35 | ~38 | ~30 |
| §2 Real-World Retrieval | 100 | ~55 | ~55 | ~75 | ~30 |
| §3 Conversation Memory | 100 | **0** | **0** | **0** | **82** |
| §4 Knowledge Graph | 80 | ~5 | **0** | ~60 | **0** |
| §5 Agent Intelligence | 80 | ~25 | ~5 | ~15 | ~10 |
| **Total** | 400 | **~123 (31%)** | **~95 (24%)** | **~188 (47%)** | **~152 (38%)** |

**No current system passes 50%.** Quaid is the only system architected to win all 5 sections.

## Sections

### §1 Infrastructure (40pts) — Phase 1 ✅
Basic operational correctness. Every production system should pass this.
- S1.1 Install and version string (5pts)
- S1.2 Corpus ingestion speed + completeness (10pts)
- S1.3 Exact FTS keyword queries (10pts)
- S1.4 Direct semantic queries (10pts)
- S1.5 API surface / MCP server (5pts)

### §2 Real-World Retrieval (100pts) — Phase 1 ✅
Tests whether retrieval works on realistic vault content.
- S2.1 Paraphrase recall: query wording ≠ document wording (25pts)
- S2.2 Cross-domain compound queries (25pts)
- S2.3 Temporal/recency: most recent result should rank first (25pts)
- S2.4 Negative recall: absent topics return empty/low-confidence (25pts)

### §3 Conversation Memory (100pts) — Phase 2 (requires quaid-app/quaid#105)
Multi-session conversational recall.

### §4 Knowledge Graph (80pts) — Phase 3 (requires quaid-app/quaid#107)
Entity extraction, relationship traversal, multi-hop queries.

### §5 Agent Intelligence (80pts) — Phase 4
Contradiction detection, knowledge gaps, write safety.

## Running

### Against Quaid
```bash
bash benchmarks/dab-v2/run.sh
```

### Against qmd
```bash
MEMORY_CMD=qmd bash benchmarks/dab-v2/run.sh
```

### Against GBrain (requires gbrain installed)
```bash
MEMORY_CMD=gbrain bash benchmarks/dab-v2/run.sh
```

## Corpus

DAB v2 requires the FiQA/MSMARCO corpus **plus** the DAB v2 supplement (9 pages covering BTC prices, neural networks, decision logs, temporal test pages).

The supplement is included in [quaid-app/msmarco-corpus](https://github.com/quaid-app/msmarco-corpus).

## Grade Thresholds

- 🟢 **Excellent:** 340+/400 (85%)
- 🟡 **Good:** 280+/400 (70%)
- 🟠 **Acceptable:** 200+/400 (50%)
- 🔴 **Needs Work:** <200/400

**Migration trigger (qmd → Quaid):** 300+/400 (75%) across 2 consecutive releases.
