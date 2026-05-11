#!/usr/bin/env python3
"""
Search arXiv for ML/AI papers that are good candidates for numerical
inconsistency experiments.

Output:
  papers/metadata/arxiv_candidates.jsonl
  papers/metadata/arxiv_candidates_summary.txt
"""

from __future__ import annotations

import argparse
import json
import re
import time
import urllib.parse
import urllib.request
from urllib.error import HTTPError, URLError
import xml.etree.ElementTree as ET
from dataclasses import asdict, dataclass
from pathlib import Path


ARXIV_API_URL = "https://export.arxiv.org/api/query"
ATOM_NS = "{http://www.w3.org/2005/Atom}"
ARXIV_NS = "{http://arxiv.org/schemas/atom}"

DEFAULT_QUERIES = [
    'cat:cs.LG AND all:"ablation study"',
    'cat:cs.CL AND all:"F1" AND all:"ablation study"',
    'cat:cs.CV AND all:"mAP" AND all:"ablation study"',
    'cat:cs.AI AND all:"accuracy" AND all:"experiments"',
    'cat:cs.LG AND all:"AUC" AND all:"results"',
]

NUMERIC_KEYWORDS = [
    "accuracy",
    "f1",
    "auc",
    "bleu",
    "rouge",
    "map",
    "precision",
    "recall",
    "ablation",
    "results",
    "experiments",
    "table",
    "p-value",
    "significant",
]


@dataclass
class Paper:
    arxiv_id: str
    title: str
    authors: list[str]
    published: str
    updated: str
    summary: str
    categories: list[str]
    primary_category: str
    pdf_url: str
    abs_url: str
    source_url: str
    matched_query: str
    candidate_score: int
    matched_keywords: list[str]


def normalize_space(text: str | None) -> str:
    return re.sub(r"\s+", " ", text or "").strip()


def extract_arxiv_id(entry_id: str) -> str:
    return entry_id.rstrip("/").split("/")[-1]


def score_candidate(title: str, summary: str) -> tuple[int, list[str]]:
    haystack = f"{title} {summary}".lower()
    matched = [keyword for keyword in NUMERIC_KEYWORDS if keyword in haystack]
    score = len(matched)

    if re.search(r"\b\d+(\.\d+)?\s*%", haystack):
        score += 3
        matched.append("percentage_pattern")
    if re.search(r"\b(table|tab\.)\s+\d+", haystack):
        score += 2
        matched.append("table_reference_pattern")
    if "ablation" in haystack:
        score += 2
    if "experiments" in haystack or "results" in haystack:
        score += 1

    return score, sorted(set(matched))


def build_query_url(query: str, start: int, max_results: int) -> str:
    params = {
        "search_query": query,
        "start": str(start),
        "max_results": str(max_results),
        "sortBy": "submittedDate",
        "sortOrder": "descending",
    }
    return f"{ARXIV_API_URL}?{urllib.parse.urlencode(params)}"


def fetch_feed(
    query: str,
    start: int,
    max_results: int,
    timeout: int,
    retries: int,
    retry_delay_seconds: float,
) -> ET.Element:
    url = build_query_url(query, start, max_results)
    request = urllib.request.Request(
        url,
        headers={"User-Agent": "master-nctq-arxiv-search/0.1 (research dataset collection)"},
    )

    for attempt in range(retries + 1):
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                return ET.fromstring(response.read())
        except HTTPError as error:
            if error.code != 429 or attempt == retries:
                raise
            wait_seconds = retry_delay_seconds * (attempt + 1)
            print(f"Rate limited by arXiv; retrying in {wait_seconds:.1f}s...")
            time.sleep(wait_seconds)
        except URLError:
            if attempt == retries:
                raise
            wait_seconds = retry_delay_seconds * (attempt + 1)
            print(f"Network error; retrying in {wait_seconds:.1f}s...")
            time.sleep(wait_seconds)

    raise RuntimeError("Unexpected arXiv fetch failure")


def parse_entry(entry: ET.Element, matched_query: str) -> Paper:
    entry_id = normalize_space(entry.findtext(f"{ATOM_NS}id"))
    arxiv_id = extract_arxiv_id(entry_id)
    title = normalize_space(entry.findtext(f"{ATOM_NS}title"))
    summary = normalize_space(entry.findtext(f"{ATOM_NS}summary"))
    authors = [
        normalize_space(author.findtext(f"{ATOM_NS}name"))
        for author in entry.findall(f"{ATOM_NS}author")
    ]
    categories = [
        category.attrib.get("term", "")
        for category in entry.findall(f"{ATOM_NS}category")
        if category.attrib.get("term")
    ]
    primary_category_el = entry.find(f"{ARXIV_NS}primary_category")
    primary_category = ""
    if primary_category_el is not None:
        primary_category = primary_category_el.attrib.get("term", "")

    pdf_url = ""
    abs_url = entry_id
    for link in entry.findall(f"{ATOM_NS}link"):
        title_attr = link.attrib.get("title", "")
        type_attr = link.attrib.get("type", "")
        href = link.attrib.get("href", "")
        if title_attr == "pdf" or type_attr == "application/pdf":
            pdf_url = href
        elif link.attrib.get("rel") == "alternate":
            abs_url = href

    base_id = arxiv_id.split("v")[0]
    source_url = f"https://arxiv.org/e-print/{base_id}"
    score, matched_keywords = score_candidate(title, summary)

    return Paper(
        arxiv_id=arxiv_id,
        title=title,
        authors=authors,
        published=normalize_space(entry.findtext(f"{ATOM_NS}published")),
        updated=normalize_space(entry.findtext(f"{ATOM_NS}updated")),
        summary=summary,
        categories=categories,
        primary_category=primary_category,
        pdf_url=pdf_url or f"https://arxiv.org/pdf/{arxiv_id}",
        abs_url=abs_url,
        source_url=source_url,
        matched_query=matched_query,
        candidate_score=score,
        matched_keywords=matched_keywords,
    )


def search_arxiv(
    queries: list[str],
    per_query: int,
    batch_size: int,
    delay_seconds: float,
    timeout: int,
    retries: int,
    retry_delay_seconds: float,
) -> list[Paper]:
    papers_by_id: dict[str, Paper] = {}

    for query in queries:
        fetched = 0
        while fetched < per_query:
            current_batch = min(batch_size, per_query - fetched)
            feed = fetch_feed(
                query=query,
                start=fetched,
                max_results=current_batch,
                timeout=timeout,
                retries=retries,
                retry_delay_seconds=retry_delay_seconds,
            )
            entries = feed.findall(f"{ATOM_NS}entry")
            if not entries:
                break

            for entry in entries:
                paper = parse_entry(entry, query)
                existing = papers_by_id.get(paper.arxiv_id)
                if existing is None or paper.candidate_score > existing.candidate_score:
                    papers_by_id[paper.arxiv_id] = paper

            fetched += len(entries)
            if len(entries) < current_batch:
                break
            time.sleep(delay_seconds)

    return sorted(
        papers_by_id.values(),
        key=lambda paper: (paper.candidate_score, paper.published),
        reverse=True,
    )


def write_outputs(papers: list[Paper], output_dir: Path, limit: int) -> tuple[Path, Path]:
    output_dir.mkdir(parents=True, exist_ok=True)
    jsonl_path = output_dir / "arxiv_candidates.jsonl"
    summary_path = output_dir / "arxiv_candidates_summary.txt"

    selected = papers[:limit]
    with jsonl_path.open("w", encoding="utf-8") as file:
        for paper in selected:
            file.write(json.dumps(asdict(paper), ensure_ascii=False) + "\n")

    with summary_path.open("w", encoding="utf-8") as file:
        file.write("arXiv candidate papers for synthetic numerical inconsistency dataset\n")
        file.write(f"Total selected: {len(selected)}\n\n")
        for index, paper in enumerate(selected, start=1):
            authors = ", ".join(paper.authors[:3])
            if len(paper.authors) > 3:
                authors += ", et al."
            file.write(f"{index}. {paper.arxiv_id} | score={paper.candidate_score}\n")
            file.write(f"   Title: {paper.title}\n")
            file.write(f"   Authors: {authors}\n")
            file.write(f"   Category: {paper.primary_category or ', '.join(paper.categories[:3])}\n")
            file.write(f"   Keywords: {', '.join(paper.matched_keywords)}\n")
            file.write(f"   PDF: {paper.pdf_url}\n")
            file.write(f"   Source: {paper.source_url}\n\n")

    return jsonl_path, summary_path


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Search arXiv for candidate ML/AI papers with numerical results."
    )
    parser.add_argument(
        "--query",
        action="append",
        dest="queries",
        help="arXiv query. Can be passed multiple times. Defaults to ML/AI numerical-result queries.",
    )
    parser.add_argument("--per-query", type=int, default=20)
    parser.add_argument("--batch-size", type=int, default=10)
    parser.add_argument("--limit", type=int, default=50)
    parser.add_argument("--delay-seconds", type=float, default=3.0)
    parser.add_argument("--retries", type=int, default=3)
    parser.add_argument("--retry-delay-seconds", type=float, default=10.0)
    parser.add_argument("--timeout", type=int, default=30)
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("papers/metadata"),
        help="Output directory, relative to current working directory if not absolute.",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    queries = args.queries or DEFAULT_QUERIES
    papers = search_arxiv(
        queries=queries,
        per_query=args.per_query,
        batch_size=args.batch_size,
        delay_seconds=args.delay_seconds,
        timeout=args.timeout,
        retries=args.retries,
        retry_delay_seconds=args.retry_delay_seconds,
    )
    jsonl_path, summary_path = write_outputs(papers, args.output_dir, args.limit)
    print(f"Wrote {min(len(papers), args.limit)} papers to {jsonl_path}")
    print(f"Wrote summary to {summary_path}")


if __name__ == "__main__":
    main()
