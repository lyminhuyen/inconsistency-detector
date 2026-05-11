#!/usr/bin/env python3
"""
Parse downloaded arXiv LaTeX source archives into lightweight JSON.

This is an MVP parser for the thesis dataset pipeline. It prefers LaTeX source
over PDF because source preserves sections, tables, equations, and text better
than raw PDF coordinates.

Input:
  paper_collection/source/*.tar.gz
  paper_collection/metadata/arxiv_candidates.jsonl

Output:
  paper_collection/parsed_json/<arxiv_id>.json
"""

from __future__ import annotations

import argparse
import json
import re
import tarfile
from dataclasses import asdict, dataclass
from pathlib import Path


DEFAULT_METADATA = Path("paper_collection/metadata/arxiv_candidates.jsonl")
DEFAULT_SOURCE_DIR = Path("paper_collection/source")
DEFAULT_OUTPUT_DIR = Path("paper_collection/parsed_json")

SECTION_RE = re.compile(
    r"\\(?P<level>section|subsection|subsubsection)\*?\{(?P<title>[^{}]+)\}",
    re.IGNORECASE,
)
BEGIN_DOC_RE = re.compile(r"\\begin\{document\}", re.IGNORECASE)
END_DOC_RE = re.compile(r"\\end\{document\}", re.IGNORECASE)
TABLE_RE = re.compile(
    r"\\begin\{table\*?\}(?P<body>.*?)\\end\{table\*?\}",
    re.IGNORECASE | re.DOTALL,
)
EQUATION_RE = re.compile(
    r"(\\begin\{(?:equation|align|gather|multline)\*?\}.*?\\end\{(?:equation|align|gather|multline)\*?\})",
    re.IGNORECASE | re.DOTALL,
)
CAPTION_RE = re.compile(r"\\caption(?:\[[^\]]*\])?\{(?P<caption>.*?)\}", re.DOTALL)
LABEL_RE = re.compile(r"\\label\{(?P<label>.*?)\}", re.DOTALL)
NUMBER_RE = re.compile(
    r"(?<![A-Za-z])[-+]?(?:\d+[\.,]\d+|\d{1,3}(?:,\d{3})+|\d+)(?:\s?%|\s?percent|\s?pp|\s?ms|\s?sec|\s?x)?",
    re.IGNORECASE,
)
RESULTS_NAMES = {
    "result",
    "results",
    "experiment",
    "experiments",
    "experimental results",
    "evaluation",
    "evaluation results",
    "empirical results",
    "ablation",
    "ablation study",
}


@dataclass
class NumberMention:
    value: str
    context: str


@dataclass
class Paragraph:
    paragraph_id: str
    text: str
    numbers: list[NumberMention]


@dataclass
class TableBlock:
    table_id: str
    caption: str
    label: str
    raw_latex: str
    numbers: list[str]


@dataclass
class EquationBlock:
    equation_id: str
    raw_latex: str
    numbers: list[str]


@dataclass
class Section:
    section_id: str
    level: str
    title: str
    is_results_like: bool
    paragraphs: list[Paragraph]
    tables: list[TableBlock]
    equations: list[EquationBlock]


def safe_id(arxiv_id: str) -> str:
    return arxiv_id.replace("/", "_")


def load_metadata(path: Path) -> dict[str, dict]:
    rows: dict[str, dict] = {}
    if not path.exists():
        return rows
    with path.open("r", encoding="utf-8") as file:
        for line in file:
            if line.strip():
                row = json.loads(line)
                rows[row["arxiv_id"]] = row
    return rows


def read_tex_members(archive_path: Path) -> dict[str, str]:
    tex_files: dict[str, str] = {}
    with tarfile.open(archive_path, "r:*") as archive:
        for member in archive.getmembers():
            if not member.isfile() or not member.name.lower().endswith(".tex"):
                continue
            extracted = archive.extractfile(member)
            if extracted is None:
                continue
            raw = extracted.read()
            text = raw.decode("utf-8", errors="replace")
            tex_files[member.name] = text
    return tex_files


def choose_main_tex(tex_files: dict[str, str]) -> tuple[str, str]:
    if not tex_files:
        raise ValueError("No .tex files found")

    scored = []
    for name, text in tex_files.items():
        score = 0
        if "\\begin{document}" in text:
            score += 10
        if "\\title" in text:
            score += 3
        score += len(SECTION_RE.findall(text))
        score += min(len(text) // 10000, 5)
        scored.append((score, name, text))
    scored.sort(reverse=True)
    _, name, text = scored[0]
    return name, text


def document_body(text: str) -> str:
    begin = BEGIN_DOC_RE.search(text)
    end = END_DOC_RE.search(text)
    if begin:
        text = text[begin.end() :]
    if end:
        text = text[: end.start()]
    return text


def strip_comments(text: str) -> str:
    cleaned_lines = []
    for line in text.splitlines():
        cleaned_lines.append(re.sub(r"(?<!\\)%.*$", "", line))
    return "\n".join(cleaned_lines)


def latex_to_text(text: str) -> str:
    text = re.sub(r"\\(?:cite|citep|citet|ref|autoref|eqref)\*?(?:\[[^\]]*\])?\{[^{}]*\}", "", text)
    text = re.sub(r"\\(?:textbf|emph|textit|underline|texttt)\{([^{}]*)\}", r"\1", text)
    text = re.sub(r"\\[A-Za-z]+\*?(?:\[[^\]]*\])?", " ", text)
    text = re.sub(r"[{}$]", " ", text)
    text = re.sub(r"~", " ", text)
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def extract_caption(raw_latex: str) -> str:
    match = CAPTION_RE.search(raw_latex)
    return latex_to_text(match.group("caption")) if match else ""


def extract_label(raw_latex: str) -> str:
    match = LABEL_RE.search(raw_latex)
    return match.group("label").strip() if match else ""


def find_numbers(text: str) -> list[str]:
    return [match.group(0).strip() for match in NUMBER_RE.finditer(text)]


def sentence_contexts(text: str) -> list[str]:
    candidates = re.split(r"(?<=[.!?])\s+", text)
    return [candidate.strip() for candidate in candidates if candidate.strip()]


def number_mentions(paragraph_text: str) -> list[NumberMention]:
    mentions: list[NumberMention] = []
    for sentence in sentence_contexts(paragraph_text):
        for value in find_numbers(sentence):
            mentions.append(NumberMention(value=value, context=sentence))
    return mentions


def remove_blocks(text: str) -> str:
    text = TABLE_RE.sub(" ", text)
    text = EQUATION_RE.sub(" ", text)
    text = re.sub(r"\\begin\{figure\*?\}.*?\\end\{figure\*?\}", " ", text, flags=re.DOTALL)
    text = re.sub(r"\\begin\{(?:itemize|enumerate)\}(.*?)\\end\{(?:itemize|enumerate)\}", r"\1", text, flags=re.DOTALL)
    return text


def split_paragraphs(section_body: str, section_id: str) -> list[Paragraph]:
    text = remove_blocks(section_body)
    raw_paragraphs = re.split(r"\n\s*\n+", text)
    paragraphs: list[Paragraph] = []

    for raw in raw_paragraphs:
        cleaned = latex_to_text(raw)
        if len(cleaned) < 40:
            continue
        paragraph_id = f"{section_id}_p{len(paragraphs) + 1:03d}"
        paragraphs.append(
            Paragraph(
                paragraph_id=paragraph_id,
                text=cleaned,
                numbers=number_mentions(cleaned),
            )
        )

    return paragraphs


def extract_tables(section_body: str, section_id: str) -> list[TableBlock]:
    tables: list[TableBlock] = []
    for match in TABLE_RE.finditer(section_body):
        raw = match.group(0)
        tables.append(
            TableBlock(
                table_id=f"{section_id}_t{len(tables) + 1:03d}",
                caption=extract_caption(raw),
                label=extract_label(raw),
                raw_latex=raw.strip(),
                numbers=find_numbers(raw),
            )
        )
    return tables


def extract_equations(section_body: str, section_id: str) -> list[EquationBlock]:
    equations: list[EquationBlock] = []
    for match in EQUATION_RE.finditer(section_body):
        raw = match.group(0)
        equations.append(
            EquationBlock(
                equation_id=f"{section_id}_e{len(equations) + 1:03d}",
                raw_latex=raw.strip(),
                numbers=find_numbers(raw),
            )
        )
    return equations


def normalize_title(title: str) -> str:
    return latex_to_text(title).lower()


def is_results_like(title: str) -> bool:
    normalized = normalize_title(title)
    return any(name in normalized for name in RESULTS_NAMES)


def split_sections(text: str) -> list[Section]:
    matches = list(SECTION_RE.finditer(text))
    sections: list[Section] = []

    level_rank = {"section": 1, "subsection": 2, "subsubsection": 3}

    for index, match in enumerate(matches):
        start = match.end()
        end = matches[index + 1].start() if index + 1 < len(matches) else len(text)
        title = latex_to_text(match.group("title"))
        level = match.group("level").lower()
        section_id = f"s{len(sections) + 1:03d}"
        body = text[start:end]
        sections.append(
            Section(
                section_id=section_id,
                level=level,
                title=title,
                is_results_like=is_results_like(title),
                paragraphs=split_paragraphs(body, section_id),
                tables=extract_tables(body, section_id),
                equations=extract_equations(body, section_id),
            )
        )

    active_results_level: int | None = None
    for section in sections:
        rank = level_rank.get(section.level, 1)
        if active_results_level is not None and rank <= active_results_level:
            active_results_level = None
        if section.is_results_like:
            active_results_level = rank
        elif active_results_level is not None and rank > active_results_level:
            section.is_results_like = True

    return sections


def parse_source_archive(archive_path: Path, metadata: dict | None) -> dict:
    tex_files = read_tex_members(archive_path)
    main_tex_name, main_tex = choose_main_tex(tex_files)
    body = document_body(strip_comments(main_tex))
    sections = split_sections(body)
    result_sections = [section.section_id for section in sections if section.is_results_like]

    return {
        "paper_id": archive_path.name.replace(".tar.gz", "").replace(".src", ""),
        "metadata": metadata or {},
        "source_archive": str(archive_path),
        "main_tex": main_tex_name,
        "sections": [asdict(section) for section in sections],
        "result_section_ids": result_sections,
        "stats": {
            "tex_file_count": len(tex_files),
            "section_count": len(sections),
            "result_section_count": len(result_sections),
            "paragraph_count": sum(len(section.paragraphs) for section in sections),
            "table_count": sum(len(section.tables) for section in sections),
            "equation_count": sum(len(section.equations) for section in sections),
            "number_mention_count": sum(
                len(paragraph.numbers)
                for section in sections
                for paragraph in section.paragraphs
            ),
        },
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Parse arXiv LaTeX source archives into JSON.")
    parser.add_argument("--metadata", type=Path, default=DEFAULT_METADATA)
    parser.add_argument("--source-dir", type=Path, default=DEFAULT_SOURCE_DIR)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--limit", type=int, default=None)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    metadata = load_metadata(args.metadata)
    archives = sorted(args.source_dir.glob("*.tar.gz"))
    if args.limit is not None:
        archives = archives[: args.limit]

    args.output_dir.mkdir(parents=True, exist_ok=True)
    for archive_path in archives:
        arxiv_id = archive_path.name.removesuffix(".tar.gz")
        parsed = parse_source_archive(archive_path, metadata.get(arxiv_id))
        output_path = args.output_dir / f"{safe_id(arxiv_id)}.json"
        output_path.write_text(json.dumps(parsed, ensure_ascii=False, indent=2), encoding="utf-8")
        stats = parsed["stats"]
        print(
            f"{arxiv_id}: sections={stats['section_count']}, "
            f"results_like={stats['result_section_count']}, "
            f"tables={stats['table_count']}, numbers={stats['number_mention_count']}"
        )


if __name__ == "__main__":
    main()
