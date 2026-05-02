from pathlib import Path
from typing import List, Dict, Any

from .parser import parse_sections
from .llm import extract_numbers


def analyze_file(filepath: Path) -> Dict[str, Any]:
    """Analyze a single file for quantitative inconsistencies."""
    content = filepath.read_text(encoding='utf-8', errors='ignore')
    sections = parse_sections(content)

    results = []
    for i, section in enumerate(sections, 1):
        orig_numbers = extract_numbers(section['original'])
        mod_numbers = extract_numbers(section['modified'])

        results.append({
            'section': i,
            'original_numbers': orig_numbers,
            'modified_numbers': mod_numbers,
            'has_difference': orig_numbers != mod_numbers
        })

    return {
        'filename': filepath.name,
        'sections': results,
        'total_differences': sum(1 for r in results if r['has_difference'])
    }


def analyze_dataset(directory: Path, limit: int = None) -> List[Dict[str, Any]]:
    """Analyze multiple files in a directory."""
    files = sorted(directory.glob("*.txt"))
    if limit:
        files = files[:limit]

    return [analyze_file(f) for f in files]
