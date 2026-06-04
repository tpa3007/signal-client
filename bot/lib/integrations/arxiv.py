"""arXiv API client — keyless. Atom XML response, we parse to dicts.

Docs: https://info.arxiv.org/help/api/user-manual.html
Rate: be polite — at most 1 req/3s for heavy use.
"""
from __future__ import annotations

import re
from xml.etree import ElementTree as ET

from lib.integrations import _safe_get

ARXIV_API = "https://export.arxiv.org/api/query"
ATOM_NS = {"a": "http://www.w3.org/2005/Atom"}


async def search_papers(client, query: str, *, max_results: int = 10,
                         sort_by: str = "submittedDate",
                         sort_order: str = "descending") -> dict:
    """Search arXiv for papers.

    Args:
        query: arXiv search syntax. "ti:" for title, "au:" for author,
               "abs:" for abstract, "cat:cs.AI" etc.
               Examples: 'all:"Gemini 3"', 'cat:cs.AI AND ti:reasoning'
        sort_by: relevance | lastUpdatedDate | submittedDate
        sort_order: ascending | descending
    """
    if not query.strip():
        return {"error": "query is required"}
    params = {
        "search_query": query,
        "max_results": max(1, min(50, max_results)),
        "sortBy": sort_by,
        "sortOrder": sort_order,
    }
    r = await _safe_get(client, ARXIV_API, params=params)
    if isinstance(r, dict) and "_error" in r:
        return {"error": r["_error"], "papers": []}
    try:
        root = ET.fromstring(r.text)
    except Exception as e:
        return {"error": f"parse: {e}", "papers": []}
    papers = []
    for entry in root.findall("a:entry", ATOM_NS):
        # Title (collapse whitespace)
        title_el = entry.find("a:title", ATOM_NS)
        title = re.sub(r"\s+", " ", title_el.text.strip()) if title_el is not None and title_el.text else ""
        summary_el = entry.find("a:summary", ATOM_NS)
        summary = re.sub(r"\s+", " ", summary_el.text.strip()) if summary_el is not None and summary_el.text else ""
        published = entry.find("a:published", ATOM_NS)
        updated = entry.find("a:updated", ATOM_NS)
        link = None
        for L in entry.findall("a:link", ATOM_NS):
            if L.get("rel") == "alternate":
                link = L.get("href")
        authors = []
        for au in entry.findall("a:author/a:name", ATOM_NS):
            if au.text:
                authors.append(au.text.strip())
        papers.append({
            "title": title,
            "summary": summary[:500],  # truncate for display
            "authors": authors,
            "published": published.text if published is not None else None,
            "updated": updated.text if updated is not None else None,
            "url": link,
        })
    return {"count": len(papers), "papers": papers, "query": query}
