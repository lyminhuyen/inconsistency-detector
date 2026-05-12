#!/usr/bin/env python3
"""
Inject simple synthetic numerical errors into extracted claim texts.

This creates claim-level corrupted samples and labels. It does not rewrite the
whole paper yet; that can be added after the claim-level protocol is stable.

Input:
  paper_collection/claims/numerical_claims.jsonl

Output:
  paper_collection/synthetic_errors/corrupted_claims.jsonl
  paper_collection/synthetic_errors/labels.jsonl
"""

from __future__ import annotations

import argparse
import json
import re
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from pathlib import Path


DEFAULT_INPUT = Path("paper_collection/claims/numerical_claims.jsonl")
DEFAULT_OUTPUT_DIR = Path("paper_collection/synthetic_errors")


def parse_decimal(value: str) -> Decimal | None:
    cleaned = value.strip().replace("%", "").replace("percent", "")
    cleaned = cleaned.replace(",", ".")
    cleaned = re.sub(r"[^0-9+\-.]", "", cleaned)
    if not cleaned or cleaned in {"+", "-", ".", "+.", "-."}:
        return None
    try:
        return Decimal(cleaned)
    except InvalidOperation:
        return None


def format_like(original: str, value: Decimal) -> str:
    has_percent = "%" in original
    uses_comma = "," in original and "." not in original
    decimal_places = 0
    match = re.search(r"[\.,](\d+)", original)
    if match:
        decimal_places = len(match.group(1))

    quant = Decimal("1") if decimal_places == 0 else Decimal("1").scaleb(-decimal_places)
    rounded = value.quantize(quant, rounding=ROUND_HALF_UP)
    text = f"{rounded:f}"
    if decimal_places == 0:
        text = text.split(".")[0]
    if uses_comma:
        text = text.replace(".", ",")
    if has_percent:
        text += "%"
    return text


def choose_value(values: list[str], claim_text: str) -> str | None:
    scored: list[tuple[int, str]] = []
    lowered = claim_text.lower()
    for value in values:
        parsed = parse_decimal(value)
        if parsed is None:
            continue
        score = 0
        if "%" in value:
            score += 4
        if parsed.copy_abs() < Decimal("1") and any(k in lowered for k in ["accuracy", "f1", "auc", "score"]):
            score += 3
        if any(k in lowered for k in ["p =", "p=", "p-value", "p value"]):
            score += 2
        if parsed.copy_abs() > Decimal("20"):
            score += 1
        scored.append((score, value))

    if not scored:
        return None
    scored.sort(reverse=True)
    return scored[0][1]


def is_integerish(value: str) -> bool:
    if "." in value:
        return False
    if "," in value and len(value.split(",")[-1]) != 3:
        return False
    return bool(re.fullmatch(r"[-+]?\d+", value.replace(",", "").replace("%", "").strip()))


def inject_value(original: str, claim_text: str) -> tuple[str, str] | None:
    parsed = parse_decimal(original)
    if parsed is None:
        return None

    lowered = claim_text.lower()
    error_type = "metric_value_mismatch"

    original_is_percentage = bool(re.search(rf"{re.escape(original)}\s*\\?%", claim_text))

    if "p =" in lowered or "p=" in lowered or "p-value" in lowered or "p value" in lowered:
        error_type = "statistical_significance_mismatch"
        modified = Decimal("0.0800") if parsed < Decimal("0.05") else Decimal("0.0100")
    elif not original_is_percentage and is_integerish(original) and (
        "fold" in lowered or "sample" in lowered or "dataset" in lowered
    ):
        error_type = "sample_or_protocol_count_mismatch"
        modified = parsed + Decimal("1")
    elif "%" in original or original_is_percentage:
        modified = parsed + Decimal("5")
    elif Decimal("0") <= parsed <= Decimal("1"):
        modified = parsed + Decimal("0.05")
        if modified > Decimal("1"):
            modified = parsed - Decimal("0.05")
    else:
        modified = parsed * Decimal("1.15")

    modified_text_value = format_like(original, modified)
    if modified_text_value == original:
        modified_text_value = format_like(original, modified + Decimal("1"))
    return modified_text_value, error_type


def replace_first_value(text: str, original: str, modified: str) -> str:
    return text.replace(original, modified, 1)


def load_claims(path: Path) -> list[dict]:
    with path.open("r", encoding="utf-8") as file:
        return [json.loads(line) for line in file if line.strip()]


def inject_claims(claims: list[dict], limit_per_paper: int) -> tuple[list[dict], list[dict]]:
    counts: dict[str, int] = {}
    corrupted_rows: list[dict] = []
    label_rows: list[dict] = []

    for claim in claims:
        paper_id = claim["paper_id"]
        if counts.get(paper_id, 0) >= limit_per_paper:
            continue

        original_value = choose_value(claim.get("values", []), claim["claim_text"])
        if original_value is None:
            continue
        injected = inject_value(original_value, claim["claim_text"])
        if injected is None:
            continue

        modified_value, error_type = injected
        modified_text = replace_first_value(claim["claim_text"], original_value, modified_value)
        if modified_text == claim["claim_text"]:
            continue

        error_id = f"{claim['claim_id']}_err"
        corrupted_rows.append(
            {
                "error_id": error_id,
                "claim_id": claim["claim_id"],
                "paper_id": paper_id,
                "section_id": claim["section_id"],
                "section_title": claim["section_title"],
                "original_text": claim["claim_text"],
                "modified_text": modified_text,
                "source": claim["source"],
            }
        )
        label_rows.append(
            {
                "error_id": error_id,
                "claim_id": claim["claim_id"],
                "paper_id": paper_id,
                "section_id": claim["section_id"],
                "section_title": claim["section_title"],
                "error_type": error_type,
                "original_value": original_value,
                "modified_value": modified_value,
                "label": "inconsistent",
                "injection_rule": "deterministic_numeric_perturbation_v1",
            }
        )
        counts[paper_id] = counts.get(paper_id, 0) + 1

    return corrupted_rows, label_rows


def write_jsonl(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as file:
        for row in rows:
            file.write(json.dumps(row, ensure_ascii=False) + "\n")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Inject synthetic numerical errors into claims.")
    parser.add_argument("--input", type=Path, default=DEFAULT_INPUT)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--limit-per-paper", type=int, default=5)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    claims = load_claims(args.input)
    corrupted_rows, label_rows = inject_claims(claims, args.limit_per_paper)
    corrupted_path = args.output_dir / "corrupted_claims.jsonl"
    labels_path = args.output_dir / "labels.jsonl"
    write_jsonl(corrupted_path, corrupted_rows)
    write_jsonl(labels_path, label_rows)
    print(f"Wrote {len(corrupted_rows)} corrupted claims to {corrupted_path}")
    print(f"Wrote {len(label_rows)} labels to {labels_path}")


if __name__ == "__main__":
    main()
