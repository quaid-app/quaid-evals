# LoCoMo Benchmark

Tests multi-session conversational memory recall across 10 dialogues, ~300 questions.

## What LoCoMo measures

| Question Type | What it tests | Mem0 v3 Reference |
|---------------|--------------|-------------------|
| single-hop | Direct factual recall | ~97% |
| multi-hop | Cross-session inference | ~93% |
| temporal | Time-based reasoning | ~93% |
| open-domain | General knowledge + memory | ~76% |
| **Overall** | | **91.6%** |

## Important caveat for Quaid

Quaid is **doc-native** (markdown pages + PARA structure), not **conversational** (structured fact extraction like Mem0).

This adapter stores whole conversation turns as pages. This is a **baseline** - scores will be lower than Mem0's because:
1. No fact extraction (stores raw turns, not distilled facts)
2. No entity resolution across turns
3. Multi-hop questions require joining facts across conversations

**Low scores here = direct roadmap input for the conversation memory feature.**

Once Quaid's conversation memory is built (ADD-only fact extraction from turns), rerun this benchmark and compare.

## Running

```bash
# Set your API key
export OPENAI_API_KEY=sk-...
# or
export ANTHROPIC_API_KEY=sk-ant-...

bash benchmarks/locomo/run.sh
```

### Faster test run (50 questions)
```bash
MAX_QUESTIONS=50 bash benchmarks/locomo/run.sh
```

### Use Anthropic instead of OpenAI
```bash
LLM_PROVIDER=anthropic ANSWERER_MODEL=claude-3-5-haiku-20241022 JUDGE_MODEL=claude-3-5-haiku-20241022 bash benchmarks/locomo/run.sh
```

Output: `results/locomo-<version>-<date>.json`
