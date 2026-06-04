"""RSS / Atom feed crawler adapter for Forager Phase 6.

Uses only stdlib (urllib + xml.etree.ElementTree) — no external dependencies.
"""
from __future__ import annotations

import xml.etree.ElementTree as ET
from urllib.request import Request, urlopen

from forager.crawl import CrawledDocument, CrawlerAdapter

_ATOM_NS = "http://www.w3.org/2005/Atom"


class RssCrawlerAdapter(CrawlerAdapter):
    """Fetches an RSS 2.0 or Atom feed and returns a single CrawledDocument
    whose content_text is the concatenated item/entry titles + descriptions.
    """

    source_name = "rss"

    def crawl(self, url: str, *, max_chars: int) -> CrawledDocument:
        request = Request(url, headers={"User-Agent": "SignalForager/0.6"})
        with urlopen(request, timeout=20) as response:
            raw = response.read(max_chars * 8)
        xml_text = raw.decode("utf-8", errors="replace")
        title, content = self.parse_feed(xml_text, max_chars)
        return CrawledDocument(url=url, title=title, content_text=content)

    def parse_feed(self, xml_text: str, max_chars: int) -> tuple[str | None, str]:
        """Parse RSS 2.0 or Atom XML and return (feed_title, concatenated items)."""
        try:
            root = ET.fromstring(xml_text)
        except ET.ParseError:
            return None, xml_text[:max_chars]

        # RSS 2.0
        channel = root.find("channel")
        if channel is not None:
            feed_title = (channel.findtext("title") or "").strip() or None
            lines: list[str] = []
            for item in channel.findall("item"):
                t = (item.findtext("title") or "").strip()
                d = _strip_html((item.findtext("description") or "").strip())
                line = f"{t}: {d}" if t and d else t or d
                if line:
                    lines.append(line)
            return feed_title, "\n".join(lines)[:max_chars]

        # Atom
        feed_title_el = root.find(f"{{{_ATOM_NS}}}title")
        feed_title = (feed_title_el.text or "").strip() or None if feed_title_el is not None else None
        lines = []
        for entry in root.findall(f"{{{_ATOM_NS}}}entry"):
            t_el = entry.find(f"{{{_ATOM_NS}}}title")
            s_el = entry.find(f"{{{_ATOM_NS}}}summary")
            c_el = entry.find(f"{{{_ATOM_NS}}}content")
            t = (t_el.text or "").strip() if t_el is not None else ""
            body_el = s_el if s_el is not None else c_el
            d = _strip_html((body_el.text or "").strip() if body_el is not None else "")
            line = f"{t}: {d}" if t and d else t or d
            if line:
                lines.append(line)
        return feed_title, "\n".join(lines)[:max_chars]


def _strip_html(text: str) -> str:
    import re
    return re.sub(r"<[^>]+>", " ", text).strip()
