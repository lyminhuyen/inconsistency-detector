#!/usr/bin/env python3
"""
Baseline detector for synthetic claim-level numerical inconsistencies.

This intentionally simple baseline compares each corrupted claim against the
original extracted claim text. It is useful as a pipeline sanity check before
adding a real rule-based/LLM detector.

Input:
  paper_collection/synthetic_errors/corrupted_claims.jsonl

Output:
  paper_collection/predictions/baseline_predictions.jsonl
"""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path


DEFAULT_INPUT = Path("paper_collection/synthetic_errors/corrupted_claims.jsonl")
DEFAULT_OUTPUT = Path("paper_collection/predictions/baseline_predictions.jsonl")

NUMBER_RE = re.compile(
    r"(?<![A-Za-z])[-+]?(?:\d+[\.,]\d+|\d{1,3}(?:,\d{3})+|\d+)(?:\s?%|\s?percent|\s?pp|\s?ms|\s?sec|\s?x)?",
    re.IGNORECASE,
)


def load_jsonl(path: Path) -> list[dict]:
    with path.open("r", encoding="utf-8") as file:
        return [json.loads(line) for line in file if line.strip()]


def extract_numbers(text: str) -> list[str]:
    return [match.group(0).strip() for match in NUMBER_RE.finditer(text)]


def normalize_number(value: str) -> str:
    value = value.strip().lower()
    value = value.replace("percent", "%")
    value = value.replace(" ", "")
    return value


def first_numeric_difference(original_text: str, modified_text: str) -> tuple[str, str] | None:
    original_numbers = [normalize_number(value) for value in extract_numbers(original_text)]
    modified_numbers = [normalize_number(value) for value in extract_numbers(modified_text)]
    for original, modified in zip(original_numbers, modified_numbers):
        if original != modified:
            return original, modified
    if len(original_numbers) != len(modified_numbers):
        return ",".join(original_numbers), ",".join(modified_numbers)
    return None


def parse_floatish(value: str) -> float | None:
    cleaned = value.replace("%", "").replace(",", ".")
    cleaned = re.sub(r"[^0-9+\-.]", "", cleaned)
    try:
        return float(cleaned)
    except ValueError:
        return None


def is_integerish(value: str) -> bool:
    if "." in value:
        return False
    if "," in value:
        parts = value.split(",")
        if len(parts[-1]) != 3:
            return False
    cleaned = value.replace(",", "").replace("%", "").strip()
    return bool(re.fullmatch(r"[-+]?\d+", cleaned))


def classify_error(context: str, original_value: str, modified_value: str) -> str:
    lowered = context.lower()
    if "p =" in lowered or "p=" in lowered or "p-value" in lowered or "p value" in lowered:
        return "statistical_significance_mismatch"
    parsed = parse_floatish(modified_value)
    if is_integerish(modified_value) and parsed is not None and parsed <= 50:
        if "fold" in lowered or "sample" in lowered or "dataset" in lowered:
            return "sample_or_protocol_count_mismatch"
    if is_integerish(modified_value) and ("n=" in lowered or "n =" in lowered):
        return "sample_or_protocol_count_mismatch"
    return "metric_value_mismatch"


def predict(row: dict) -> dict:
    diff = first_numeric_difference(row["original_text"], row["modified_text"])
    detected = diff is not None
    original_value = diff[0] if diff else None
    modified_value = diff[1] if diff else None
    error_type = None
    confidence = 0.0

    if detected:
        error_type = classify_error(row["modified_text"], original_value or "", modified_value or "")
        confidence = 1.0

    return {
        "error_id": row["error_id"],
        "claim_id": row["claim_id"],
        "paper_id": row["paper_id"],
        "detected": detected,
        "predicted_error_type": error_type,
        "predicted_original_value": original_value,
        "predicted_modified_value": modified_value,
        "confidence": confidence,
        "detector": "baseline_original_vs_corrupted_numeric_diff",
    }


def write_jsonl(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as file:
        for row in rows:
            file.write(json.dumps(row, ensure_ascii=False) + "\n")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run baseline synthetic error detector.")
    parser.add_argument("--input", type=Path, default=DEFAULT_INPUT)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    rows = load_jsonl(args.input)
    predictions = [predict(row) for row in rows]
    write_jsonl(args.output, predictions)
    detected = sum(1 for row in predictions if row["detected"])
    print(f"Wrote {len(predictions)} predictions to {args.output}")
    print(f"Detected: {detected}/{len(predictions)}")


if __name__ == "__main__":
    main()
