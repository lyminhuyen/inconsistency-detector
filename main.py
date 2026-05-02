#!/usr/bin/env python3
"""Analyze quantitative inconsistencies in FLAWS dataset."""

from pathlib import Path
from src.analyzer import analyze_dataset


def print_results(results):
    """Print analysis results."""
    print("=" * 70)
    print("QUANTITATIVE ANALYSIS - FLAWS DATASET")
    print("=" * 70)

    for result in results:
        print(f"\n{result['filename']}")
        print("-" * 70)

        for section in result['sections']:
            print(f"\n  [Section {section['section']}]")
            print(f"  Original: {section['original_numbers'][:200]}")
            print(f"  Modified: {section['modified_numbers'][:200]}")

            if section['has_difference']:
                print("  >> DIFFERENCE DETECTED")
            else:
                print("  >> No difference")


def main():
    inserted_error_dir = Path("ALL_OPENAI/inserted_error")
    results = analyze_dataset(inserted_error_dir, limit=5)
    print_results(results)


if __name__ == "__main__":
    main()
