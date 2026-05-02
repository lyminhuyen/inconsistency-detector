import re
import json
import urllib.request
from typing import Optional

OLLAMA_URL = 'http://localhost:11434/api/generate'
DEFAULT_MODEL = 'llama3.2'
TIMEOUT = 60


def normalize_output(text: str) -> str:
    """Normalize LLM output for consistent comparison."""
    text = text.strip().rstrip('.')
    text = re.sub(r'^(Here is|The|Extracted|Numbers?:?).*?:\s*', '', text, flags=re.IGNORECASE)
    text = re.sub(r'\s+', ' ', text)
    if text.upper() == 'NONE' or not text:
        return 'NONE'
    return text


def extract_numbers(text: str, model: str = DEFAULT_MODEL) -> str:
    """Extract numbers from text using Ollama LLM."""
    prompt = f"""Extract all numbers (integers, decimals, percentages, values with units like GB, MB, seconds) from this text.
Return ONLY a comma-separated list of numbers with their units. If no numbers, return "NONE".

Text:
{text[:2000]}

Numbers:"""

    try:
        data = json.dumps({
            'model': model,
            'prompt': prompt,
            'stream': False
        }).encode('utf-8')

        req = urllib.request.Request(
            OLLAMA_URL,
            data=data,
            headers={'Content-Type': 'application/json'}
        )

        with urllib.request.urlopen(req, timeout=TIMEOUT) as response:
            result = json.loads(response.read().decode('utf-8'))
            return normalize_output(result.get('response', ''))
    except Exception as e:
        return f"Error: {e}"
