# Quantitative Inconsistency Detection in Scientific Papers

> Master's Thesis — Lý Minh Uyên, 2026

---

## Abstract

Scientific papers frequently contain quantitative inconsistencies — discrepancies between numbers reported in text, tables, and figures that may indicate errors introduced during revision or generation. This project builds an automated pipeline to detect such inconsistencies in the **Results** section of ML/AI papers, using Large Language Models (LLMs).

The system operates in two stages:
1. **Extraction** — an LLM with prompt engineering extracts structured numerical claims from LaTeX source.
2. **Consistency Check** — a two-layer checker first applies rule-based heuristics (e.g., percentages summing to 100%, matching sample sizes), then escalates complex cases to an LLM with Chain-of-Thought reasoning.

The approach is evaluated on **FLAWS**, a benchmark of 265 ML papers with synthetically injected errors, covering numerical mismatches, statistical inconsistencies, and missing formula terms.

---

## Pipeline

```
Paper (LaTeX)
     │
     ▼
Module 1: LLM + Prompt Engineering
          → Extract numerical claims → Structured JSON
     │
     ▼
Module 2: Consistency Check
          ├─ Layer 1: Rule-based  (sum %, sample size, units...)
          └─ Layer 2: LLM + CoT  (complex semantic checks)
     │
     ▼
Output: Inconsistency detected / Not detected
```

---

## Dataset

**FLAWS** ([HuggingFace](https://huggingface.co/datasets/xasayi/FLAWS)) — 265 ML/AI papers with GPT-injected errors.

- 70.2% contain quantitative errors (186 / 265 papers)
- Error types: numerical mismatch, statistical inconsistency, dropped formula terms, wrong units/magnitude
- Each sample: `original_text` + `modified_text` (with injected error) + `explanation`

---

## Project Structure

```
ALL_OPENAI/
├── inserted_error/        # Raw error samples (original / modified / explanation)
├── altered_papers/        # LaTeX source per paper
├── generated_claims/      # Extracted claims (GPT-5)
├── identified_error/      # Error identification outputs
├── location_error/        # Error paragraph locations
├── evaluation_errors/     # Model evaluation results
├── classify_errors.py     # Classify quantitative vs non-quantitative
├── extract_numbers.py     # Extract & compare numbers via Ollama
└── quantitative_papers.txt
```

---

## Current Progress

| Step | Status | Notes |
|------|--------|-------|
| Dataset acquisition (FLAWS) | ✅ Done | 265 papers downloaded |
| Error classification | ✅ Done | `classify_errors.py` |
| Number extraction (Ollama) | ✅ Done | `extract_numbers.py` — needs output normalization |
| External evaluation (GPT-5) | ✅ Done | Results in `evaluation_errors/` |
| Module 1: Structured extraction | 🔄 In progress | Prompt engineering |
| Module 2: Rule-based checker | 🔄 In progress | Basic rules implemented |
| Module 2: LLM + CoT checker | 📋 Planned | |
| Multi-model benchmarking | 📋 Planned | GPT-5, Claude, DeepSeek |
| Evaluation & metrics | 📋 Planned | Precision, Recall, F1 |

---

## Models Used

- **Local**: Ollama `llama3.2` (number extraction, prototyping)
- **External**: GPT-5, Claude Sonnet, DeepSeek Reasoner (evaluation)

---

## Requirements

- Python 3.8+
- [Ollama](https://ollama.ai/) with `llama3.2`

```bash
pip install -r requirements.txt
ollama pull llama3.2
```

---

## Usage

```bash
# Classify quantitative vs non-quantitative errors
cd ALL_OPENAI && python classify_errors.py

# Extract and compare numbers via Ollama
cd ALL_OPENAI && python extract_numbers.py
```

---

## License

MIT
