#!/usr/bin/env python3
"""
Extract numerical claim candidates from parsed paper JSON.

The output is intentionally simple: one JSONL row per sentence/context that
contains promising numerical values in results-like sections.

Input:
  paper_collection/parsed_json/*.json

Output:
  paper_collection/claims/numerical_claims.jsonl
"""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path


DEFAULT_INPUT_DIR = Path("paper_collection/parsed_json")
DEFAULT_OUTPUT = Path("paper_collection/claims/numerical_claims.jsonl")

METRIC_KEYWORDS = {
    "accuracy",
    "acc",
    "f1",
    "auc",
    "roc",
    "bleu",
    "rouge",
    "map",
    "precision",
    "recall",
    "score",
    "performance",
    "error",
    "loss",
    "rate",
    "significant",
    "p-value",
    "p value",
    "sample",
    "dataset",
    "baseline",
    "outperform",
    "improve",
    "increase",
    "decrease",
    "higher",
    "lower",
    "best",
    "worst",
}


def looks_like_structural_number(value: str, context: str) -> bool:
    raw = value.strip()
    context_lower = context.lower()

    if raw.isdigit():
        number = int(raw.replace(",", ""))
        if 1900 <= number <= 2100 and "year" in context_lower:
            return True
        if number <= 20 and re.search(r"\b(section|figure|fig\.|table|tab\.)\b", context_lower):
            return True
    return False


def claim_score(context: str, values: list[str]) -> int:
    lowered = context.lower()
    score = 0
    score += sum(1 for keyword in METRIC_KEYWORDS if keyword in lowered)
    score += 2 * sum(1 for value in values if "%" in value or "percent" in value.lower())
    score += 2 if re.search(r"\bp\s*[<=>]\s*0?\.\d+", lowered) else 0
    score += 1 if len(values) >= 2 else 0
    score += 1 if re.search(r"\b(table|tab\.|figure|fig\.)\b", lowered) else 0
    return score


def unique_preserve_order(values: list[str]) -> list[str]:
    seen = set()
    output = []
    for value in values:
        if value not in seen:
            seen.add(value)
            output.append(value)
    return output


def iter_claims(parsed: dict, min_score: int) -> list[dict]:
    paper_id = parsed["paper_id"]
    title = parsed.get("metadata", {}).get("title", "")
    result_section_ids = set(parsed.get("result_section_ids", []))
    claims: list[dict] = []

    for section in parsed.get("sections", []):
        if section["section_id"] not in result_section_ids:
            continue
        for paragraph in section.get("paragraphs", []):
            values = [
                mention["value"]
                for mention in paragraph.get("numbers", [])
                if not looks_like_structural_number(mention["value"], mention["context"])
            ]
            values = unique_preserve_order(values)
            if not values:
                continue

            score = claim_score(paragraph["text"], values)
            if score < min_score:
                continue

            claims.append(
                {
                    "claim_id": f"{paper_id}_{len(claims) + 1:04d}",
                    "paper_id": paper_id,
                    "paper_title": title,
                    "section_id": section["section_id"],
                    "section_title": section["title"],
                    "paragraph_id": paragraph["paragraph_id"],
                    "claim_text": paragraph["text"],
                    "values": values,
                    "candidate_score": score,
                    "source": "latex_parsed_results_section",
                }
            )

        for table in section.get("tables", []):
            values = unique_preserve_order(table.get("numbers", []))
            if not values:
                continue
            context = table.get("caption") or table.get("label") or table["table_id"]
            score = claim_score(context, values) + 1
            if score < min_score:
                continue
            claims.append(
                {
                    "claim_id": f"{paper_id}_{len(claims) + 1:04d}",
                    "paper_id": paper_id,
                    "paper_title": title,
                    "section_id": section["section_id"],
                    "section_title": section["title"],
                    "table_id": table["table_id"],
                    "claim_text": context,
                    "values": values,
                    "candidate_score": score,
                    "source": "latex_table_results_section",
                }
            )

    return sorted(claims, key=lambda claim: claim["candidate_score"], reverse=True)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Extract numerical claim candidates.")
    parser.add_argument("--input-dir", type=Path, default=DEFAULT_INPUT_DIR)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--min-score", type=int, default=2)
    parser.add_argument("--limit-per-paper", type=int, default=50)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    rows: list[dict] = []
    for path in sorted(args.input_dir.glob("*.json")):
        parsed = json.loads(path.read_text(encoding="utf-8"))
        claims = iter_claims(parsed, args.min_score)[: args.limit_per_paper]
        rows.extend(claims)
        print(f"{parsed['paper_id']}: claims={len(claims)}")

    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("w", encoding="utf-8") as file:
        for row in rows:
            file.write(json.dumps(row, ensure_ascii=False) + "\n")
    print(f"Wrote {len(rows)} claims to {args.output}")


if __name__ == "__main__":
    main()
