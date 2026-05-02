import re
from typing import List, Dict


def parse_sections(content: str) -> List[Dict[str, str]]:
    """Parse original_text and modified_text sections from file content."""
    pattern = r':original_text:\s*(.*?):modified_text:\s*(.*?)(?=:original_text:|:explanation:|$)'
    matches = re.findall(pattern, content, re.DOTALL)
    return [
        {'original': orig.strip(), 'modified': mod.strip()}
        for orig, mod in matches
    ]
