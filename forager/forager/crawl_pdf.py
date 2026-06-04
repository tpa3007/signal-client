"""PDF crawler adapter for Forager Phase 6.

Attempts to extract text using `pypdf` if installed. Falls back to a minimal
byte-level regex heuristic that works for simple single-byte-encoded PDFs.
Neither approach handles complex PDFs reliably; Firecrawl is the recommended
production path for high-quality PDF extraction.
"""
from __future__ import annotations

import io
import re
from urllib.request import Request, urlopen

from forager.crawl import CrawledDocument, CrawlerAdapter

_PDF_FETCH_CAP = 5_000_000  # 5 MB


class PdfCrawlerAdapter(CrawlerAdapter):
    """Downloads a PDF URL and extracts plain text."""

    source_name = "pdf"

    def crawl(self, url: str, *, max_chars: int) -> CrawledDocument:
        request = Request(url, headers={"User-Agent": "SignalForager/0.6"})
        with urlopen(request, timeout=30) as resp:
            raw = resp.read(min(max_chars * 8, _PDF_FETCH_CAP))
        text = self.extract_text(raw, max_chars)
        return CrawledDocument(url=url, title=None, content_text=text)

    def extract_text(self, raw_bytes: bytes, max_chars: int) -> str:
        """Extract text from PDF bytes. Uses pypdf if available, else fallback."""
        try:
            import pypdf  # optional dependency

            reader = pypdf.PdfReader(io.BytesIO(raw_bytes))
            pages = [page.extract_text() or "" for page in reader.pages]
            return "\n".join(pages)[:max_chars]
        except ImportError:
            return self._fallback_extract(raw_bytes, max_chars)

    @staticmethod
    def _fallback_extract(raw_bytes: bytes, max_chars: int) -> str:
        """Minimal regex extraction of text objects from uncompressed PDF streams."""
        text = raw_bytes.decode("latin-1", errors="replace")
        chunks = re.findall(r"BT\s+(.*?)\s+ET", text, re.DOTALL)
        parts: list[str] = []
        for chunk in chunks:
            for match in re.findall(r"\((.*?)\)\s*Tj", chunk):
                clean = re.sub(r"\\n", "\n", match)
                clean = re.sub(r"\\[()\\]", "", clean)
                if clean.strip():
                    parts.append(clean)
        result = " ".join(parts).strip()
        return result[:max_chars] if result else "[PDF: no extractable text found without pypdf]"
