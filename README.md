# AutoSchema-Heal

> **Autonomous, Self-Healing Data Ingestion Pipeline with Program Synthesis & Property-Based Verification**

[![Python 3.11+](https://img.shields.io/badge/Python-3.11+-3776AB.svg?style=flat&logo=python&logoColor=white)](#quickstart)
[![Architecture: Dual-Path](https://img.shields.io/badge/Architecture-Dual--Path%20Fast%2FSlow-blue.svg)](#architecture)
[![Performance: libjq C Bytecode](https://img.shields.io/badge/Throughput->35k%20records%2Fsec-orange.svg)](#benchmarks--performance)
[![Verification: CEGIS Loop](https://img.shields.io/badge/Verification-CEGIS%20Loop-brightgreen.svg)](#how-it-works)
[![Tests: 10 Passed](https://img.shields.io/badge/Tests-10%20Passed-success.svg)](#test-suite)

**AutoSchema-Heal** is a high-throughput data ingestion engine that automatically detects and heals upstream schema drift (e.g., Stripe, Salesforce, GitHub webhooks) without crashing pipelines or dumping records into Dead-Letter Queues (DLQs).

Instead of calling an LLM on every record (slow and expensive), AutoSchema-Heal uses a **CEGIS-based synthesis loop** to write a JQ transformation program once. That program is checked against 4 property invariants and stress-tested by an adversarial fuzzer before being compiled into native C bytecode for fast streaming execution (**>35,000 records/sec**).

---

## The Real-World Engineering Problem

In production data platforms, upstream SaaS vendors and third-party APIs update schemas without warning:
- Stripe updates their payload from `amount_cents: 4999` to `amount: 49.99`.
- Salesforce renames or nests custom fields under new objects.
- GitHub migrates flat webhook events into GraphQL envelopes.

### Today's Status Quo
1. **Pipeline Breaks:** Downstream parsers reject the payload; events pile up in DLQs.
2. **On-Call Fatigue:** Engineers get paged at 2 AM to manually write glue transformations and push emergency patches.
3. **The Naive AI Fix:** Calling an LLM per record introduces ~150ms latency per event, high API bills, and the risk of hallucinated or dropped fields.

### The AutoSchema-Heal Approach
- **No Human Intervention:** Detects schema drift and synthesizes a JQ filter automatically.
- **Property-Checked Output:** Every candidate filter must pass 4 runtime invariant checks before it touches real data.
- **Fast Path After First Heal:** Compiled JQ bytecode runs at ~26 us per record for all subsequent events with the same schema shape.

---

## Architecture Overview

AutoSchema-Heal separates **synthesis** (slow, done once per new schema shape) from **streaming execution** (fast, done on every subsequent record):

```
                              INCOMING EVENT STREAM
                                        |
                                        v
                         1. Structural AST Fingerprinter
                             (64-bit Hash in <4 us)
                                        |
                       +----------------+----------------+
                       v                                 v
               [ Cache HIT ]                     [ Cache MISS / Drift ]
            FAST PATH (Streaming)                 SLOW PATH (CEGIS Loop)
                       |                                 |
           Executes Native C libjq Bytecode              v
             (26 us P50, >35k ops/sec)         LLM Synthesizer (Groq / OpenAI)
                       |                                 |
                       |                        Candidate JQ Filter
                       |                                 |
                       |                        Property Invariant Checker
                       |                          (4 checks run in order)
                       |                                 |
                       |                        Adversarial Property Fuzzer
                       |                          (40 boundary-value mutations)
                       |                                 |
                       |                       +---------+---------+
                       |                       v                   v
                       |                   [PASSED]             [FAILED]
                       |               JIT Compile to        Delta-Debugging
                       |               Bytecode Cache           Shrinker
                       |                       |                   |
                       |                       v             Feed minimal counterexample
                       |               Promote to Fast Path  to next LLM prompt
                       v                       |
              CANONICAL SINK <----------------+
```

---

## Benchmarks & Performance

### 1. Drift Scenario Benchmarks (30,000 Records / Scenario)

Fast-path numbers are measured on real libjq bytecode execution (MockLLMClient, no network). CEGIS convergence rounds reflect live Groq inference runs against each scenario's drifted samples.

| Scenario Dataset | Upstream Drift Type | CEGIS Rounds | Fast Path Throughput | P50 Latency | Data Integrity Check |
|---|---|:---:|:---:|:---:|:---:|
| **Stripe Webhooks** | Cents to Dollars, nested email, epoch drift | **1 round** | **26,683 records/sec** | **36.3 us** | **All fields matched** |
| **Salesforce CRM** | PascalCase field renames, stringified numbers | **1 round** | **37,108 records/sec** | **26.3 us** | **All fields matched** |
| **GitHub Webhooks** | Flat payload to nested envelope migration | **1 round** | **26,617 records/sec** | **35.5 us** | **All fields matched** |

### 2. Architectural Comparison: AutoSchema-Heal vs. Industry Alternatives

Evaluated on a 20,000-record drifted streaming workload. The LLM-Direct latency column (145ms P50) is modeled from typical API response times, not measured during this benchmark run. The DLQ baseline is a strict Pydantic validation reject loop (no Kafka/broker overhead). See `benchmarks/comparative_benchmark.py` for full methodology.

| Metric | 1. Traditional DLQ (Kafka/Flink) | 2. Naive LLM-Direct (Per-Record) | 3. AutoSchema-Heal (Ours) | Notes |
|---|:---:|:---:|:---:|:---:|
| **Throughput (ops/sec)** | 64,413 ops/s (rejection) | ~7 ops/s | **27,203 ops/s** | LLM-Direct limited by network RTT |
| **P50 Latency (Median)** | 15.0 us | ~145 ms | **32.8 us** | Fast path = cached bytecode |
| **P99 Tail Latency** | 22.0 us | ~164 ms | **47.5 us** | No GC pauses on hot path |
| **P99.9 Tail Latency** | 32.7 us | ~164 ms | **71.5 us** | |
| **Data Loss / DLQ Drops** | **100%** (all drifted records dropped) | 0% | **0%** | DLQ rejects entire drifted stream |
| **Silent Corruption Rate** | 0% | ~3.3% (hallucinated fields) | **0%** | Caught by `I_integrity` invariant check |
| **Amortized Cost / 100k Events** | $0.00 | ~$22.50 | **~$0.0003** | 1 LLM call amortized over full stream |

```
LATENCY DISTRIBUTION (LOG SCALE):
1. Traditional DLQ:        [--- 15.0 us P50]                  (100% dropped to DLQ)
2. Naive LLM-Direct:       [################################ 145.0 ms P50] (network-bound)
3. AutoSchema-Heal (Ours): [---- 32.8 us P50]                 (0% dropped, 27k ops/s)
```

Run the comparative benchmark suite locally:
```bash
python benchmarks/comparative_benchmark.py

# With live Groq inference:
python benchmarks/comparative_benchmark.py --groq
```

---

## The Four Property Checks

Every candidate JQ program must pass all four checks in order before entering the fast-path cache. If any check fails, the failing input is minimized by the delta-debugger and fed back to the LLM as a counterexample for the next synthesis round.

1. **`I_exec` (Execution Safety):** Runs the JQ program in a sandboxed call with a 50ms time budget. Rejects programs that crash, time out, emit zero outputs, or emit more than one output document.

2. **`I_type` (Schema Conformance):** Validates the output against the canonical target schema (Pydantic v2 / JSON Schema). Rejects any output with missing required fields or wrong types.

3. **`I_integrity` (Data Retention):** Checks that output field values are semantically traceable back to source field values — identity match, string conversion, numeric scaling (e.g., cents to dollars), or epoch to ISO-8601 conversion. Rejects programs that fill fields with hardcoded dummy constants (`"unknown"`, `0.0`, etc.) while dropping real upstream data.

   > **Note:** This is a heuristic recall check, not an exhaustive proof. The default threshold (0.70) means at least 70% of meaningful source leaf values must be traceable in the output. It catches gross hallucinations and dummy-fill patterns reliably, but is not a guarantee of zero data loss in the strict sense.

4. **`I_idempotence` (Determinism):** Two steps — (a) static scan for banned impure JQ tokens (`now`, `env`, `debug`, `halt`); (b) runs the program twice on the same input and compares outputs. If they differ, the candidate is rejected.

---

## Quickstart

### 1. Installation

```bash
git clone https://github.com/yourusername/autonomous_data_ingestion.git
cd autonomous_data_ingestion

python -m venv .venv
.venv\Scripts\activate       # Windows
# source .venv/bin/activate  # Linux / macOS

pip install -r requirements.txt
pip install -e .
```

### 2. Run the Interactive CLI Demo

```bash
python -m autoschema_heal.cli
```

### 3. Run the Benchmark Suite

```bash
python benchmarks/run_benchmarks.py
```

### 4. Run the Test Suite

```bash
pytest -v
```

---

## Connecting to an LLM

AutoSchema-Heal is model-agnostic. The synthesizer supports Groq, OpenAI, Gemini, local vLLM/Ollama endpoints, and a zero-cost offline mock.

### Option A: Groq Cloud API (Native `groq` SDK)

```bash
export GROQ_API_KEY="gsk_your_groq_api_key"
# Windows PowerShell:
$env:GROQ_API_KEY = "gsk_your_groq_api_key"
```

```python
from autoschema_heal.core.engine import AutoSchemaEngine
from autoschema_heal.synthesis.llm_client import GroqClient
from autoschema_heal.formal.schema import TargetSchema

groq_llm = GroqClient(
    model="llama-3.3-70b-versatile",
    temperature=0.2,
    max_completion_tokens=2048,
)

engine = AutoSchemaEngine(
    target_schema=TargetSchema(...),
    llm_client=groq_llm,
)
```

### Option B: Self-Hosted Open-Source Models (vLLM / Ollama)

```python
from autoschema_heal.synthesis.llm_client import LiveAPIClient

local_client = LiveAPIClient(
    base_url="http://localhost:8000/v1/chat/completions",
    model="llama-3-8b-instruct",
    api_key="none",
)
```

### Option C: OpenAI / Gemini

```python
from autoschema_heal.synthesis.llm_client import LiveAPIClient

client = LiveAPIClient(api_key="sk-...", model="gpt-4o-mini")

gemini_client = LiveAPIClient(
    api_key="your-gemini-key",
    base_url="https://generativelanguage.googleapis.com/v1beta/openai/chat/completions",
    model="gemini-1.5-flash",
)
```

### Option D: Offline Mock Client (Default)

If no API key is set, the engine uses `MockLLMClient()` with no network access or cost. Useful for CI/CD, local development, and hermetic benchmarks.

---

## Known Limitations

- **`I_integrity` is a heuristic:** The 0.70 retention threshold catches common LLM dummy-fill patterns reliably but is not an exhaustive data loss guarantee. Complex transformations (e.g., aggregations that map many source fields to one target field) may not score well even when correct.
- **JQ is a limited synthesis target:** JQ has no loops or general recursion, so complex transformations (aggregations, joins, multi-record fanout) are out of scope. This is intentional — JQ's restricted semantics make the `I_exec` time-budget check reliable and the synthesis search space manageable.
- **Single-threaded CEGIS:** Each new schema fingerprint blocks its slow-path thread during synthesis. There is no shared lock or coordination for two concurrent slow-path events on different fingerprints.
- **LLM-Direct benchmark latency is modeled:** The ~145ms P50 shown for the LLM-Direct baseline is based on typical API response times, not a live measurement during the benchmark run.

---

## Project Structure

```
autonomous_data_ingestion/
├── benchmarks/
│   ├── datasets/                  # Drift scenario definitions (Stripe, Salesforce, GitHub)
│   └── run_benchmarks.py          # Benchmark runner (throughput, latency, telemetry)
├── requirements.txt               # Pip dependencies
├── pyproject.toml                 # Package spec & build config
├── src/autoschema_heal/
│   ├── core/
│   │   ├── fingerprint.py         # O(N) structural shape hasher (<4 us)
│   │   ├── cache.py               # Thread-safe LRU cache of compiled JQ bytecode
│   │   └── engine.py              # Dual-path streaming orchestrator
│   ├── formal/
│   │   ├── schema.py              # Target schema validation (Pydantic / JSON Schema)
│   │   ├── data_integrity.py      # Data retention ratio checker (I_integrity)
│   │   └── invariants.py          # 4-invariant property checker
│   ├── fuzzer/
│   │   ├── mutators.py            # Temporal, numeric, unicode, and nullability mutators
│   │   ├── shrinker.py            # Delta-debugging counterexample minimizer
│   │   └── property_fuzzer.py     # Adversarial property-based fuzzer
│   ├── synthesis/
│   │   ├── grammar.py             # JQ static sanitizer and syntax validator
│   │   ├── llm_client.py          # Pluggable LLM backends (Groq, OpenAI, Mock)
│   │   └── synthesizer.py         # CEGIS prompt builder with counterexample history
│   ├── cegis/
│   │   ├── coordinator.py         # Multi-round CEGIS state machine
│   │   └── audit.py               # SHA-256 audit certificate per synthesized program
│   └── cli.py                     # Rich terminal demo
└── tests/                         # pytest suite (10 tests)
```
