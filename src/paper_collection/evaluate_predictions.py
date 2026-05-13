#!/usr/bin/env python3
"""
Evaluate detector predictions against synthetic labels.

Input:
  paper_collection/synthetic_errors/labels.jsonl
  paper_collection/predictions/baseline_predictions.jsonl

Output:
  paper_collection/evaluation/baseline_evaluation.json
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path


DEFAULT_LABELS = Path("paper_collection/synthetic_errors/labels.jsonl")
DEFAULT_PREDICTIONS = Path("paper_collection/predictions/baseline_predictions.jsonl")
DEFAULT_OUTPUT = Path("paper_collection/evaluation/baseline_evaluation.json")


def load_jsonl(path: Path) -> list[dict]:
    with path.open("r", encoding="utf-8") as file:
        return [json.loads(line) for line in file if line.strip()]


def normalize_value(value: str | None) -> str | None:
    if value is None:
        return None
    return value.strip().lower().replace("percent", "%").replace(" ", "")


def evaluate(labels: list[dict], predictions: list[dict]) -> dict:
    predictions_by_id = {row["error_id"]: row for row in predictions}
    rows = []
    total = len(labels)
    detected = 0
    type_correct = 0
    modified_value_correct = 0
    missing_predictions = 0

    for label in labels:
        prediction = predictions_by_id.get(label["error_id"])
        if prediction is None:
            missing_predictions += 1
            rows.append(
                {
                    "error_id": label["error_id"],
                    "detected_correct": False,
                    "type_correct": False,
                    "modified_value_correct": False,
                    "note": "missing_prediction",
                }
            )
            continue

        detected_correct = bool(prediction["detected"])
        predicted_type = prediction.get("predicted_error_type")
        predicted_modified = normalize_value(prediction.get("predicted_modified_value"))
        gold_modified = normalize_value(label.get("modified_value"))
        current_type_correct = predicted_type == label["error_type"]
        current_modified_correct = predicted_modified == gold_modified

        detected += int(detected_correct)
        type_correct += int(current_type_correct)
        modified_value_correct += int(current_modified_correct)

        rows.append(
            {
                "error_id": label["error_id"],
                "detected_correct": detected_correct,
                "type_correct": current_type_correct,
                "modified_value_correct": current_modified_correct,
                "gold_error_type": label["error_type"],
                "predicted_error_type": predicted_type,
                "gold_modified_value": label["modified_value"],
                "predicted_modified_value": prediction.get("predicted_modified_value"),
            }
        )

    denominator = total or 1
    return {
        "summary": {
            "total_labels": total,
            "total_predictions": len(predictions),
            "missing_predictions": missing_predictions,
            "detection_accuracy": detected / denominator,
            "error_type_accuracy": type_correct / denominator,
            "modified_value_accuracy": modified_value_correct / denominator,
        },
        "rows": rows,
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Evaluate predictions against synthetic labels.")
    parser.add_argument("--labels", type=Path, default=DEFAULT_LABELS)
    parser.add_argument("--predictions", type=Path, default=DEFAULT_PREDICTIONS)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    labels = load_jsonl(args.labels)
    predictions = load_jsonl(args.predictions)
    result = evaluate(labels, predictions)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(result["summary"], ensure_ascii=False, indent=2))
    print(f"Wrote evaluation to {args.output}")


if __name__ == "__main__":
    main()
