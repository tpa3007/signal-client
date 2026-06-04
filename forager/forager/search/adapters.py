"""Search adapters for Forager.

The service depends on this small interface so tests can use deterministic
results while production can use real providers such as Tavily or Brave.
"""
from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass, field
from typing import Protocol
from urllib.parse import urlencode
from urllib.request import Request, urlopen


@dataclass(frozen=True)
class SearchResult:
    url: str
    title: str | None = None
    snippet: str | None = None
    published_at: str | None = None
    source_name: str = "unknown"
    raw: dict = field(default_factory=dict)


class SearchAdapter(Protocol):
    source_name: str

    def search(self, query: str, *, count: int) -> list[SearchResult]:
        ...


class NullSearchAdapter:
    source_name = "null"

    def search(self, query: str, *, count: int) -> list[SearchResult]:
        raise RuntimeError(
            "No search adapter configured. Set TAVILY_API_KEY, BRAVE_SEARCH_API_KEY, or inject a SearchAdapter."
        )


class StaticSearchAdapter:
    source_name = "static"

    def __init__(self, results_by_query: dict[str, list[SearchResult]] | None = None, default_results: list[SearchResult] | None = None) -> None:
        self.results_by_query = results_by_query or {}
        self.default_results = default_results or []

    def search(self, query: str, *, count: int) -> list[SearchResult]:
        return list(self.results_by_query.get(query, self.default_results))[:count]


class CompositeSearchAdapter:
    """Search through multiple adapters and keep working when one provider fails."""

    source_name = "composite"

    def __init__(self, adapters: list[SearchAdapter]) -> None:
        self.adapters = adapters

    def search(self, query: str, *, count: int) -> list[SearchResult]:
        seen: set[str] = set()
        results: list[SearchResult] = []
        for adapter in self.adapters:
            if len(results) >= count:
                break
            try:
                adapter_results = adapter.search(query, count=max(1, count - len(results)))
            except Exception:
                continue
            for result in adapter_results:
                if not result.url or result.url in seen:
                    continue
                seen.add(result.url)
                results.append(result)
                if len(results) >= count:
                    break
        return results


class TavilySearchAdapter:
    source_name = "tavily"

    def __init__(self, api_key: str, endpoint: str = "https://api.tavily.com/search") -> None:
        self.api_key = api_key
        self.endpoint = endpoint

    def search(self, query: str, *, count: int) -> list[SearchResult]:
        payload = json.dumps(
            {
                "query": query,
                "search_depth": "basic",
                "max_results": max(1, min(count, 20)),
                "include_answer": False,
                "include_raw_content": False,
            }
        ).encode("utf-8")
        request = Request(
            self.endpoint,
            data=payload,
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
                "User-Agent": "Signal-Forager/1.0",
            },
            method="POST",
        )
        with urlopen(request, timeout=25) as response:
            data = response.read().decode("utf-8")
        response_payload = json.loads(data)
        results: list[SearchResult] = []
        for item in response_payload.get("results", []):
            results.append(
                SearchResult(
                    url=item.get("url") or "",
                    title=item.get("title"),
                    snippet=item.get("content"),
                    published_at=item.get("published_date"),
                    source_name=self.source_name,
                    raw=item,
                )
            )
        return [result for result in results if result.url]


class RotatingTavilySearchAdapter:
    """TavilySearchAdapter with automatic key rotation on quota exhaustion.

    Tavily's free tier has a monthly credit cap; when a key returns HTTP 429/432
    or a usage-limit error, that key is marked exhausted and we rotate to the
    next. State persists to .tavily_key_state.json next to forager.db and resets
    each calendar month. Configure via TAVILY_API_KEY, TAVILY_API_KEY_2, …
    """

    source_name = "tavily"
    _ENDPOINT = "https://api.tavily.com/search"

    def __init__(self, api_keys: list[str], endpoint: str = _ENDPOINT) -> None:
        self._keys = [k.strip() for k in api_keys if k.strip()]
        self._endpoint = endpoint
        self._exhausted: set[int] = set()
        self._state_file = self._resolve_state_path()
        self._load_state()

    @staticmethod
    def _resolve_state_path() -> str:
        db_path = os.getenv("FORAGER_DB_PATH", "").strip()
        if db_path:
            return os.path.join(os.path.dirname(db_path), ".tavily_key_state.json")
        here = os.path.dirname(os.path.abspath(__file__))
        return os.path.normpath(os.path.join(here, "..", "..", "..", "bot", ".tavily_key_state.json"))

    def _load_state(self) -> None:
        from datetime import datetime as _dt  # noqa: PLC0415
        current_month = _dt.now().strftime("%Y-%m")
        try:
            if os.path.exists(self._state_file):
                with open(self._state_file, encoding="utf-8") as fh:
                    state = json.load(fh)
                if state.get("month") == current_month:
                    self._exhausted = set(state.get("exhausted", []))
                    if self._exhausted:
                        active = [i + 1 for i in range(len(self._keys)) if i not in self._exhausted]
                        print(f"  [Tavily] Restored key state: exhausted={sorted(self._exhausted)} "
                              f"active={active} (month {current_month})")
                    return
        except Exception:  # noqa: BLE001
            pass
        self._exhausted = set()

    def _save_state(self) -> None:
        from datetime import datetime as _dt  # noqa: PLC0415
        try:
            data = {"month": _dt.now().strftime("%Y-%m"),
                    "exhausted": sorted(self._exhausted), "keys_count": len(self._keys)}
            os.makedirs(os.path.dirname(self._state_file) or ".", exist_ok=True)
            with open(self._state_file, "w", encoding="utf-8") as fh:
                json.dump(data, fh, indent=2)
        except Exception:  # noqa: BLE001
            pass

    def search(self, query: str, *, count: int) -> list[SearchResult]:
        for i, key in enumerate(self._keys):
            if i in self._exhausted:
                continue
            try:
                return TavilySearchAdapter(key, self._endpoint).search(query, count=count)
            except Exception as exc:  # noqa: BLE001
                if self._is_quota_error(exc):
                    self._exhausted.add(i)
                    self._save_state()
                    remaining = [j + 1 for j in range(len(self._keys)) if j not in self._exhausted]
                    print(f"  [Tavily] Key {i + 1} quota exhausted, rotating. Remaining: {remaining}")
                    continue
                raise
        raise RuntimeError(
            f"All {len(self._keys)} Tavily API key(s) exhausted this month. "
            "Add TAVILY_API_KEY_2, _3, … or wait for monthly reset."
        )

    @staticmethod
    def _is_quota_error(exc: Exception) -> bool:
        msg = str(exc).lower()
        return any(s in msg for s in ("429", "432", "402", "quota", "rate limit",
                                       "too many requests", "usage limit", "credit",
                                       "plan limit", "unauthorized", "401"))


class BraveSearchAdapter:
    source_name = "brave"

    def __init__(self, api_key: str, endpoint: str = "https://api.search.brave.com/res/v1/web/search") -> None:
        self.api_key = api_key
        self.endpoint = endpoint

    def search(self, query: str, *, count: int) -> list[SearchResult]:
        params = urlencode({
            "q": query,
            "count": max(1, min(count, 20)),
            "extra_snippets": 1,       # up to 5 additional text snippets per result
            "text_decorations": 0,     # no bold markers in snippets
        })
        request = Request(
            f"{self.endpoint}?{params}",
            headers={
                "Accept": "application/json",
                "X-Subscription-Token": self.api_key,
                "User-Agent": "Signal-Forager/1.0",
            },
        )
        with urlopen(request, timeout=20) as response:
            payload = json.loads(response.read().decode("utf-8"))
        web_results = payload.get("web", {}).get("results", [])
        results: list[SearchResult] = []
        for item in web_results:
            # Combine description + extra_snippets into one rich snippet for
            # better claim extraction on paywalled / JS-only pages.
            desc = item.get("description") or ""
            extras = item.get("extra_snippets") or []
            if extras:
                combined = desc + " ... " + " ... ".join(extras[:3]) if desc else " ... ".join(extras[:3])
            else:
                combined = desc
            results.append(
                SearchResult(
                    url=item.get("url") or "",
                    title=item.get("title"),
                    snippet=combined.strip() or None,
                    published_at=item.get("age"),
                    source_name=self.source_name,
                    raw=item,
                )
            )
        return [result for result in results if result.url]


class RotatingBraveSearchAdapter:
    """BraveSearchAdapter with automatic key rotation on monthly quota exhaustion.

    When a key returns HTTP 429 (Too Many Requests) or 402 (Payment Required /
    quota exceeded), marks that key as exhausted for the current calendar month
    and rotates to the next available key.

    State is persisted to .brave_key_state.json (next to forager.db) so the
    exhaustion survives process restarts within the same month.  At the start
    of a new calendar month all keys are automatically treated as fresh again.

    Usage (auto-configured via BRAVE_SEARCH_API_KEY + BRAVE_SEARCH_API_KEY_2 env):
        adapter = RotatingBraveSearchAdapter(api_keys=[key1, key2])
    """

    source_name = "brave"
    _BRAVE_ENDPOINT = "https://api.search.brave.com/res/v1/web/search"

    def __init__(self, api_keys: list[str], endpoint: str = _BRAVE_ENDPOINT) -> None:
        self._keys = [k.strip() for k in api_keys if k.strip()]
        self._endpoint = endpoint
        self._exhausted: set[int] = set()
        self._state_file = self._resolve_state_path()
        self._load_state()

    # ── State persistence ──────────────────────────────────────────────────

    @staticmethod
    def _resolve_state_path() -> str:
        """Resolve state file path.  Stored next to FORAGER_DB_PATH when set,
        otherwise 3 levels up from this file into Signal/bot/."""
        db_path = os.getenv("FORAGER_DB_PATH", "").strip()
        if db_path:
            return os.path.join(os.path.dirname(db_path), ".brave_key_state.json")
        # Fallback: C:\Signal\forager\forager\search\ → C:\Signal\bot\
        here = os.path.dirname(os.path.abspath(__file__))
        return os.path.normpath(os.path.join(here, "..", "..", "..", "bot", ".brave_key_state.json"))

    def _load_state(self) -> None:
        """Load persisted exhaustion state; auto-reset at the start of each month."""
        from datetime import datetime as _dt  # noqa: PLC0415
        current_month = _dt.now().strftime("%Y-%m")
        try:
            if os.path.exists(self._state_file):
                with open(self._state_file, encoding="utf-8") as fh:
                    state = json.load(fh)
                if state.get("month") == current_month:
                    self._exhausted = set(state.get("exhausted", []))
                    if self._exhausted:
                        active = [i + 1 for i in range(len(self._keys)) if i not in self._exhausted]
                        print(f"  [Brave] Restored key state: exhausted={sorted(self._exhausted)} "
                              f"active={active} (month {current_month})")
                    return
        except Exception:  # noqa: BLE001
            pass
        self._exhausted = set()

    def _save_state(self) -> None:
        """Persist exhaustion state to survive restarts within the month."""
        from datetime import datetime as _dt  # noqa: PLC0415
        try:
            data = {
                "month": _dt.now().strftime("%Y-%m"),
                "exhausted": sorted(self._exhausted),
                "keys_count": len(self._keys),
            }
            os.makedirs(os.path.dirname(self._state_file) or ".", exist_ok=True)
            with open(self._state_file, "w", encoding="utf-8") as fh:
                json.dump(data, fh, indent=2)
        except Exception:  # noqa: BLE001
            pass

    # ── Search ────────────────────────────────────────────────────────────

    def search(self, query: str, *, count: int) -> list[SearchResult]:
        for i, key in enumerate(self._keys):
            if i in self._exhausted:
                continue
            try:
                results = BraveSearchAdapter(key, self._endpoint).search(query, count=count)
                return results
            except Exception as exc:  # noqa: BLE001
                if self._is_quota_error(exc):
                    self._exhausted.add(i)
                    self._save_state()
                    remaining = [j + 1 for j in range(len(self._keys)) if j not in self._exhausted]
                    print(f"  [Brave] Key {i + 1} quota exhausted, rotating. "
                          f"Remaining keys: {remaining}")
                    continue
                raise
        raise RuntimeError(
            f"All {len(self._keys)} Brave API key(s) exhausted for this month. "
            "Add more keys to BRAVE_SEARCH_API_KEY_3, etc. or wait for monthly reset."
        )

    @staticmethod
    def _is_quota_error(exc: Exception) -> bool:
        """Return True if the exception signals quota / rate-limit exhaustion."""
        msg = str(exc)
        # urllib raises HTTPError; code is in the message as "HTTP Error 429: ..."
        return (
            "429" in msg
            or "402" in msg
            or "quota" in msg.lower()
            or "rate limit" in msg.lower()
            or "too many requests" in msg.lower()
            or "plan limit" in msg.lower()
            or "subscription" in msg.lower()
        )


class WikipediaSearchAdapter:
    """Small no-key fallback for entity discovery, not a full web search engine."""

    source_name = "wikipedia"

    def __init__(self, endpoint: str = "https://en.wikipedia.org/w/api.php") -> None:
        self.endpoint = endpoint

    def search(self, query: str, *, count: int) -> list[SearchResult]:
        results: list[SearchResult] = []
        seen: set[str] = set()
        for variant in _query_variants(query):
            if len(results) >= count:
                break
            params = urlencode(
                {
                    "action": "opensearch",
                    "search": variant,
                    "limit": max(1, min(count - len(results), 10)),
                    "namespace": 0,
                    "format": "json",
                }
            )
            request = Request(f"{self.endpoint}?{params}", headers={"User-Agent": "Signal-Forager/1.0"})
            with urlopen(request, timeout=10) as response:
                payload = json.loads(response.read().decode("utf-8"))
            titles = payload[1] if len(payload) > 1 else []
            snippets = payload[2] if len(payload) > 2 else []
            urls = payload[3] if len(payload) > 3 else []
            for index, url in enumerate(urls):
                if not url or url in seen:
                    continue
                seen.add(url)
                results.append(
                    SearchResult(
                        url=url,
                        title=titles[index] if index < len(titles) else None,
                        snippet=snippets[index] if index < len(snippets) else None,
                        source_name=self.source_name,
                        raw={"query": variant},
                    )
                )
                if len(results) >= count:
                    break
        return results


class GdeltSearchAdapter:
    """No-key news fallback through the public GDELT Doc API.

    GDELT artlist returns: url, title, seendate, domain, language, sourcecountry.
    No article body is available — we build the richest snippet we can from metadata.
    Snippet format: "<title> | <domain> | <date>" for claim extraction usefulness.
    """

    source_name = "gdelt"

    def __init__(self, endpoint: str = "https://api.gdeltproject.org/api/v2/doc/doc") -> None:
        self.endpoint = endpoint

    @staticmethod
    def _format_date(seendate: str) -> str:
        """Convert GDELT seendate (YYYYMMDDTHHMMSSZ) to readable YYYY-MM-DD."""
        if not seendate or len(seendate) < 8:
            return seendate or ""
        try:
            return f"{seendate[:4]}-{seendate[4:6]}-{seendate[6:8]}"
        except Exception:  # noqa: BLE001
            return seendate[:10]

    def search(self, query: str, *, count: int) -> list[SearchResult]:
        results: list[SearchResult] = []
        seen: set[str] = set()
        # Use up to 2 query variants; GDELT supports near: operator but plain text works well
        for variant in _query_variants(query)[:2]:
            if len(results) >= count:
                break
            try:
                params = urlencode(
                    {
                        "query": variant,
                        "mode": "artlist",
                        "format": "json",
                        "maxrecords": max(1, min(count - len(results), 25)),
                        "timespan": "14d",    # 14 days: fresher than 30d for breaking news
                        "sort": "datedesc",
                    }
                )
                request = Request(
                    f"{self.endpoint}?{params}",
                    headers={"User-Agent": "Signal-Forager/1.0"},
                )
                with urlopen(request, timeout=15) as response:
                    payload = json.loads(response.read().decode("utf-8"))
            except Exception:  # noqa: BLE001
                continue
            for item in payload.get("articles", []):
                url = item.get("url") or ""
                if not url or url in seen:
                    continue
                seen.add(url)
                title = item.get("title") or ""
                domain = item.get("domain") or ""
                seendate = item.get("seendate") or ""
                date_str = self._format_date(seendate)
                lang = item.get("language") or ""
                country = item.get("sourcecountry") or ""
                # Build the richest possible snippet from GDELT metadata
                # Title is the most useful field — it's what the article actually says
                parts = [p for p in [title, domain, date_str] if p]
                if lang and lang.upper() not in ("ENGLISH", "ENG"):
                    parts.append(f"[{lang}/{country}]")
                snippet = " | ".join(parts) if parts else None
                results.append(
                    SearchResult(
                        url=url,
                        title=title or None,
                        snippet=snippet,
                        published_at=date_str or None,
                        source_name=self.source_name,
                        raw=item,
                    )
                )
                if len(results) >= count:
                    break
        return results


class OfficialSeedSearchAdapter:
    """Deterministic seeds for official/primary-source paths when no search key exists."""

    source_name = "official_seed"

    def search(self, query: str, *, count: int) -> list[SearchResult]:
        q = query.lower()
        seeds: list[SearchResult] = []
        if any(token in q for token in ["orikhiv", "zaporizh", "deepstate", "isw", "russia enter"]):
            seeds.extend(
                [
                    self._seed("https://storymaps.arcgis.com/stories/36a7f6a6f5a9448496de641cf64bd375", "ISW interactive Ukraine map", "Official research map seed for Ukraine control/geolocation checks."),
                    self._seed("https://deepstatemap.live/en", "DeepStateMap Ukraine", "Local-language/open-source map seed for Orikhiv control claims."),
                ]
            )
        if any(token in q for token in ["wisconsin", "mandela", "barnes", "governor primary"]):
            seeds.extend(
                [
                    self._seed("https://elections.wi.gov/", "Wisconsin Elections Commission", "Official Wisconsin election administration seed."),
                    self._seed("https://wisdems.org/", "Democratic Party of Wisconsin", "Party infrastructure seed for Wisconsin Democratic primary research."),
                ]
            )
        if any(token in q for token in ["romania", "predoiu", "prime minister", "catalin", "cătălin"]):
            seeds.extend(
                [
                    self._seed("https://www.presidency.ro/", "Romanian Presidency", "Official appointment/consultation source seed."),
                    self._seed("https://gov.ro/", "Government of Romania", "Official Romanian government source seed."),
                    self._seed("https://www.cdep.ro/", "Chamber of Deputies Romania", "Parliamentary source seed for Romanian coalition checks."),
                ]
            )
        if any(token in q for token in ["saudi", "riyadh", "us military aircraft", "aircraft ban"]):
            seeds.extend(
                [
                    self._seed("https://www.spa.gov.sa/en", "Saudi Press Agency", "Official Saudi state news source seed."),
                    self._seed("https://www.mod.gov.sa/", "Saudi Ministry of Defense", "Official Saudi defense source seed."),
                    self._seed("https://www.centcom.mil/", "U.S. Central Command", "Official U.S. regional military source seed."),
                ]
            )
        if any(token in q for token in ["house member", "congress", "iran", "us house"]):
            seeds.extend(
                [
                    self._seed("https://www.house.gov/", "U.S. House of Representatives", "Official House source seed for member/travel checks."),
                    self._seed("https://www.congress.gov/", "Congress.gov", "Official legislative activity source seed."),
                    self._seed("https://travel.state.gov/content/travel/en/international-travel/International-Travel-Country-Information-Pages/Iran.html", "U.S. State Department Iran travel advisory", "Official U.S. Iran travel/security context seed."),
                ]
            )

        # ── Central bank / monetary policy ─────────────────────────────────────
        if any(token in q for token in ["rba", "reserve bank australia", "cash rate", "australia interest"]):
            seeds.extend([
                self._seed("https://www.rba.gov.au/monetary-policy/", "Reserve Bank of Australia — Monetary Policy", "Official RBA monetary policy statements, cash rate decisions, and meeting dates."),
                self._seed("https://www.rba.gov.au/monetary-policy/rba-board-minutes/", "RBA Board Minutes", "Official meeting minutes for recent RBA board decisions."),
                self._seed("https://www.abs.gov.au/statistics/economy/price-indexes-and-inflation/consumer-price-index-australia", "ABS CPI Australia", "Official Australian Bureau of Statistics CPI data — RBA inflation target."),
            ])
        if any(token in q for token in ["federal reserve", "fed funds", "fomc", "us interest rate", "fed rate"]):
            seeds.extend([
                self._seed("https://www.federalreserve.gov/monetarypolicy/openmarket.htm", "Federal Reserve — Open Market Operations", "Official FOMC decisions and target rate range."),
                self._seed("https://www.federalreserve.gov/releases/h15/", "Fed H.15 Selected Interest Rates", "Official Federal Reserve interest rate data."),
                self._seed("https://www.cmegroup.com/markets/interest-rates/cme-fedwatch-tool.html", "CME FedWatch Tool", "Market-implied probabilities for future FOMC rate decisions."),
            ])
        if any(token in q for token in ["ecb", "european central bank", "euro interest rate"]):
            seeds.extend([
                self._seed("https://www.ecb.europa.eu/press/pr/date/", "ECB Press Releases", "Official European Central Bank monetary policy announcements."),
                self._seed("https://www.ecb.europa.eu/stats/policy_and_exchange_rates/key_ecb_interest_rates/html/index.en.html", "ECB Key Interest Rates", "Official ECB deposit facility and MRO rates."),
            ])
        if any(token in q for token in ["bank of england", "boe", "uk interest rate", "mpc decision"]):
            seeds.extend([
                self._seed("https://www.bankofengland.co.uk/monetary-policy", "Bank of England — Monetary Policy", "Official BoE MPC decisions, minutes, and rate history."),
            ])

        # ── Minnesota / US Senate 2026 ─────────────────────────────────────────
        if any(token in q for token in ["minnesota", "flanagan", "minnesota senate", "mn senate", "dfl"]):
            seeds.extend([
                self._seed("https://www.dfl.org/", "DFL — Democratic-Farmer-Labor Party of Minnesota", "Official MN DFL party news, endorsements, and primary calendar."),
                self._seed("https://www.sos.state.mn.us/elections-voting/", "Minnesota Secretary of State — Elections", "Official MN election administration, filing deadlines, primary dates."),
            ])

        # ── Middle East / Israel-Gaza ──────────────────────────────────────────
        if any(token in q for token in ["israel", "gaza", "hamas", "ceasefire", "idf", "rafah"]):
            seeds.extend([
                self._seed("https://www.idf.il/en/", "Israel Defense Forces", "Official IDF press releases and operational announcements."),
                self._seed("https://www.timesofisrael.com/", "Times of Israel", "Real-time Israeli news coverage of conflict developments."),
                self._seed("https://www.ochaopt.org/", "OCHA oPt — UN humanitarian updates", "UN humanitarian coordination for occupied Palestinian territory."),
            ])

        # ── Colombia / Petro ──────────────────────────────────────────────────
        if any(token in q for token in ["colombia", "bogota", "petro", "colombian"]):
            seeds.extend([
                self._seed("https://www.cancilleria.gov.co/", "Colombian Ministry of Foreign Affairs", "Official Colombian foreign affairs announcements."),
                self._seed("https://id.presidencia.gov.co/", "Colombian Presidency", "Official Colombian presidential announcements and decrees."),
            ])

        # ── Indonesia / Prabowo ───────────────────────────────────────────────
        if any(token in q for token in ["indonesia", "jakarta", "prabowo", "indonesian"]):
            seeds.extend([
                self._seed("https://www.presidenri.go.id/en/", "Indonesian Presidency", "Official Indonesian presidential statements."),
                self._seed("https://kemlu.go.id/portal/en", "Indonesian Ministry of Foreign Affairs", "Official Indonesian foreign policy and diplomatic news."),
            ])

        # ── India / Modi ──────────────────────────────────────────────────────
        if any(token in q for token in ["india", "modi", "delhi", "bjp", "pakistan", "kashmir"]):
            seeds.extend([
                self._seed("https://www.pmindia.gov.in/en/", "Prime Minister of India", "Official PMO India statements and press releases."),
                self._seed("https://mea.gov.in/", "Indian Ministry of External Affairs", "Official Indian diplomatic and foreign policy statements."),
            ])

        # ── Iran nuclear / deal ───────────────────────────────────────────────
        if any(token in q for token in ["iran nuclear", "jcpoa", "enrichment", "iaea iran", "rubio iran", "us iran deal"]):
            seeds.extend([
                self._seed("https://www.iaea.org/newscenter/news", "IAEA Newsroom", "Official IAEA nuclear safeguards and Iran monitoring news."),
                self._seed("https://www.state.gov/bureaus-offices/under-secretary-for-arms-control-and-international-security/", "U.S. State Dept — Arms Control", "Official U.S. arms control and Iran nuclear policy statements."),
                self._seed("https://en.irna.ir/", "IRNA — Islamic Republic News Agency", "Iran's official state news agency for diplomatic announcements."),
            ])

        # ── North Korea / nuclear / DPRK ──────────────────────────────────────
        if any(token in q for token in ["north korea", "dprk", "kim jong", "nuclear test", "missile launch"]):
            seeds.extend([
                self._seed("https://38north.org/", "38 North — North Korea analysis", "Expert analysis of North Korean satellite, nuclear, and missile activity."),
                self._seed("https://www.nti.org/countries/north-korea/", "NTI — North Korea nuclear", "Nuclear Threat Initiative tracking of DPRK weapons program."),
            ])

        # ── Taiwan / China military ────────────────────────────────────────────
        if any(token in q for token in ["taiwan", "pla", "strait", "china invasion", "taiwan strait"]):
            seeds.extend([
                self._seed("https://www.mnd.gov.tw/english/", "Taiwan Ministry of National Defense", "Official Taiwan MND PLA incursion reports and press releases."),
                self._seed("https://www.globalsecurity.org/military/world/china/", "GlobalSecurity — China military", "China military capabilities and Taiwan Strait analysis."),
            ])

        return _dedupe_results(seeds)[:count]

    def _seed(self, url: str, title: str, snippet: str) -> SearchResult:
        return SearchResult(url=url, title=title, snippet=snippet, source_name=self.source_name, raw={"seed": True})


class FREDSearchAdapter:
    """Federal Reserve Economic Data — free official economic data series.

    No key required for search; key required for data retrieval.
    Get a FREE key at: https://fred.stlouisfed.org/docs/api/api_key.html

    Searches FRED series index and returns matching economic indicator links.
    Each result's snippet includes the latest observation value + date,
    making it directly usable as a claim for monetary policy markets.

    Set FRED_API_KEY in .env to enable full data fetch.
    Without a key, falls back to FRED search page links (snippet-only).
    """

    source_name = "fred"
    _FRED_SEARCH = "https://api.stlouisfed.org/fred/series/search"
    _FRED_OBS = "https://api.stlouisfed.org/fred/series/observations"

    # Map query keywords → FRED series IDs for direct lookup
    _KEYWORD_SERIES: dict[str, list[str]] = {
        "rba": ["RBATCTR", "AUSCPIALLQINMEI", "AUSUR"],
        "australia": ["RBATCTR", "AUSCPIALLQINMEI", "AUSUR", "AUSURAMS"],
        "cash rate": ["RBATCTR"],
        "fed funds": ["FEDFUNDS", "DFEDTARU"],
        "federal reserve": ["FEDFUNDS", "DFEDTARU", "DFF"],
        "interest rate": ["FEDFUNDS", "RBATCTR", "IR3TIB01USM156N"],
        "cpi": ["CPIAUCSL", "CPILFESL", "AUSCPIALLQINMEI"],
        "inflation": ["CPIAUCSL", "CPILFESL", "T5YIFR"],
        "unemployment": ["UNRATE", "AUSUR"],
        "gdp": ["GDP", "GDPC1", "A191RL1Q225SBEA"],
        "yield curve": ["T10Y2Y", "T10Y3M", "GS10"],
        "treasury": ["DGS10", "DGS2", "DGS30"],
        "oil": ["DCOILWTICO", "DCOILBRENTEU"],
        "dollar": ["DTWEXBGS", "DTWEXAFEGS"],
        "housing": ["CSUSHPINSA", "HOUST", "MORTGAGE30US"],
        "payroll": ["PAYEMS", "MANEMP"],
    }

    def __init__(self, api_key: str | None = None) -> None:
        self.api_key = api_key or os.getenv("FRED_API_KEY", "").strip()

    def search(self, query: str, *, count: int) -> list[SearchResult]:
        results: list[SearchResult] = []
        q_lower = query.lower()

        # 1. Direct series lookup for known keywords (most precise)
        matched_series: list[str] = []
        for keyword, series_list in self._KEYWORD_SERIES.items():
            if keyword in q_lower:
                matched_series.extend(series_list)

        if matched_series and self.api_key:
            seen_ids: set[str] = set()
            for series_id in matched_series[:count]:
                if series_id in seen_ids:
                    continue
                seen_ids.add(series_id)
                result = self._fetch_latest_observation(series_id)
                if result:
                    results.append(result)
                if len(results) >= count:
                    return results

        # 2. FRED full-text search (API key required)
        if self.api_key and len(results) < count:
            try:
                params = urlencode({
                    "search_text": query[:100],
                    "api_key": self.api_key,
                    "file_type": "json",
                    "limit": max(1, min(count - len(results), 25)),
                    "order_by": "popularity",
                    "sort_order": "desc",
                    "filter_variable": "frequency",
                    "filter_value": "Monthly",
                })
                req = Request(
                    f"{self._FRED_SEARCH}?{params}",
                    headers={"User-Agent": "Signal-Forager/1.0"},
                )
                with urlopen(req, timeout=10) as resp:
                    data = json.loads(resp.read().decode("utf-8"))
                for series in data.get("seriess", [])[:count - len(results)]:
                    sid = series.get("id", "")
                    title = series.get("title", "")
                    notes = (series.get("notes") or "")[:200]
                    url = f"https://fred.stlouisfed.org/series/{sid}"
                    obs_result = self._fetch_latest_observation(sid) if self.api_key else None
                    snippet = obs_result.snippet if obs_result else f"FRED series: {notes}"
                    results.append(SearchResult(
                        url=url,
                        title=f"FRED: {title} ({sid})",
                        snippet=snippet,
                        source_name=self.source_name,
                        raw=series,
                    ))
            except Exception:  # noqa: BLE001
                pass

        # 3. No-key fallback: return direct FRED page links for known series
        if not results:
            for series_id in (matched_series or ["FEDFUNDS"])[:count]:
                results.append(SearchResult(
                    url=f"https://fred.stlouisfed.org/series/{series_id}",
                    title=f"FRED Economic Data: {series_id}",
                    snippet=f"Federal Reserve Economic Data series {series_id}. Set FRED_API_KEY for live values.",
                    source_name=self.source_name,
                    raw={"series_id": series_id},
                ))

        return results[:count]

    def _fetch_latest_observation(self, series_id: str) -> SearchResult | None:
        """Fetch the most recent observation for a FRED series."""
        if not self.api_key:
            return None
        try:
            params = urlencode({
                "series_id": series_id,
                "api_key": self.api_key,
                "file_type": "json",
                "sort_order": "desc",
                "limit": 3,
                "observation_start": "2024-01-01",
            })
            req = Request(
                f"{self._FRED_OBS}?{params}",
                headers={"User-Agent": "Signal-Forager/1.0"},
            )
            with urlopen(req, timeout=10) as resp:
                data = json.loads(resp.read().decode("utf-8"))
            obs = data.get("observations", [])
            if not obs:
                return None
            latest = obs[0]
            val = latest.get("value", ".")
            date = latest.get("date", "")
            # Build previous observations for trend context
            trend = ""
            if len(obs) >= 2:
                prev = obs[1].get("value", ".")
                try:
                    delta = float(val) - float(prev)
                    trend = f" (prev: {prev}, chg {delta:+.2f})"
                except ValueError:
                    trend = f" (prev: {prev})"
            snippet = f"FRED {series_id}: latest value = {val} as of {date}{trend}"
            return SearchResult(
                url=f"https://fred.stlouisfed.org/series/{series_id}",
                title=f"FRED {series_id} — Latest: {val} ({date})",
                snippet=snippet,
                published_at=date,
                source_name=self.source_name,
                raw={"series_id": series_id, "observations": obs},
            )
        except Exception:  # noqa: BLE001
            return None


class MetaculusSearchAdapter:
    """Metaculus community forecasts — requires free API token as of 2025.

    Returns community probability estimates as search results.
    Invaluable for calibration: if Metaculus at 15% and Polymarket at 20%,
    that's meaningful convergence signal.

    Get a free token at: https://www.metaculus.com/accounts/profile/
    Set METACULUS_API_TOKEN in .env

    API docs: https://www.metaculus.com/api/
    """

    source_name = "metaculus"
    # v4 API (current, requires auth)
    _ENDPOINT_V4 = "https://www.metaculus.com/api/posts/"
    # v2 API (legacy, may still work for some endpoints)
    _ENDPOINT_V2 = "https://www.metaculus.com/api2/questions/"

    def __init__(self, api_token: str | None = None) -> None:
        self.api_token = (
            api_token
            or os.getenv("METACULUS_API_TOKEN", "")
            or os.getenv("METACULUS_TOKEN", "")
        ).strip()

    def _headers(self) -> dict:
        h: dict = {"Accept": "application/json", "User-Agent": "Signal-Forager/1.0"}
        if self.api_token:
            h["Authorization"] = f"Token {self.api_token}"
        return h

    def search(self, query: str, *, count: int) -> list[SearchResult]:
        results: list[SearchResult] = []
        seen: set[str] = set()
        for variant in _query_variants(query)[:2]:
            if len(results) >= count:
                break
            try:
                # Try v4 API first (current)
                params = urlencode({
                    "search": variant[:100],
                    "limit": max(1, min(count - len(results), 20)),
                    "order_by": "-activity",
                    "forecast_type": "binary",
                    "statuses": "open",
                })
                req = Request(
                    f"{self._ENDPOINT_V4}?{params}",
                    headers=self._headers(),
                )
                with urlopen(req, timeout=12) as resp:
                    data = json.loads(resp.read().decode("utf-8"))
                # v4 returns {"results": [...]} or {"items": [...]}
                items = data.get("results") or data.get("items") or []
                for q in items:
                    # v4 nests question inside "question" key or uses top-level fields
                    qdata = q.get("question") or q
                    qid = qdata.get("id") or q.get("id", "")
                    url = f"https://www.metaculus.com/questions/{qid}/"
                    if not url or url in seen:
                        continue
                    seen.add(url)
                    title = qdata.get("title") or q.get("title", "")
                    # Community probability — v4 uses aggregations.recency_weighted
                    prob = None
                    aggs = qdata.get("aggregations") or {}
                    rw = aggs.get("recency_weighted") or {}
                    if rw:
                        latest = rw.get("latest") or {}
                        prob = latest.get("centers", [None])[0] if latest.get("centers") else None
                    if prob is None:
                        # v2 fallback field
                        cp = qdata.get("community_prediction", {})
                        if isinstance(cp, dict):
                            prob = (cp.get("full") or {}).get("q2")
                        elif isinstance(cp, float):
                            prob = cp
                    close_date = (qdata.get("scheduled_close_time") or qdata.get("close_time") or "")[:10]
                    nr_forecasters = qdata.get("nr_forecasters") or qdata.get("number_of_forecasters") or "?"
                    if prob is not None:
                        prob_pct = f"{prob * 100:.0f}%" if prob <= 1.0 else f"{prob:.0f}%"
                        snippet = (
                            f"Metaculus community: {prob_pct} probability | "
                            f"Closes: {close_date} | "
                            f"Forecasters: {nr_forecasters}"
                        )
                    else:
                        snippet = f"Metaculus question | Closes: {close_date} | {nr_forecasters} forecasters"
                    results.append(SearchResult(
                        url=url,
                        title=f"[Metaculus] {title}",
                        snippet=snippet,
                        published_at=close_date or None,
                        source_name=self.source_name,
                        raw=q,
                    ))
                    if len(results) >= count:
                        break
            except Exception:  # noqa: BLE001
                continue
        return results


class ManifoldMarketsAdapter:
    """Manifold Markets prediction market — free public API, no key needed.

    Returns market probabilities and activity as search results.
    Manifold is a play-money market but has shown strong calibration on
    news events (often leads Polymarket by hours on breaking news).

    API docs: https://docs.manifold.markets/api
    """

    source_name = "manifold"
    _ENDPOINT = "https://api.manifold.markets/v0/search-markets"

    def search(self, query: str, *, count: int) -> list[SearchResult]:
        results: list[SearchResult] = []
        seen: set[str] = set()
        try:
            params = urlencode({
                "term": query[:100],
                "limit": max(1, min(count, 20)),
                "filter": "open",
                "sort": "liquidity",
                "contractType": "BINARY",
            })
            req = Request(
                f"{self._ENDPOINT}?{params}",
                headers={
                    "User-Agent": "Signal-Forager/1.0",
                    "Accept": "application/json",
                },
            )
            with urlopen(req, timeout=12) as resp:
                markets = json.loads(resp.read().decode("utf-8"))
            for m in markets[:count]:
                url = m.get("url") or ""
                if not url or url in seen:
                    continue
                seen.add(url)
                prob = m.get("probability")
                close_time = m.get("closeTime")
                close_str = ""
                if close_time:
                    try:
                        from datetime import datetime as _dt  # noqa: PLC0415
                        close_str = _dt.fromtimestamp(close_time / 1000).strftime("%Y-%m-%d")
                    except Exception:  # noqa: BLE001
                        close_str = str(close_time)[:10]
                volume = m.get("volume", 0)
                if prob is not None:
                    prob_pct = f"{prob * 100:.0f}%"
                    snippet = (
                        f"Manifold probability: {prob_pct} | "
                        f"Volume: M${volume:.0f} | "
                        f"Closes: {close_str}"
                    )
                else:
                    snippet = f"Manifold market | Closes: {close_str}"
                results.append(SearchResult(
                    url=url,
                    title=f"[Manifold] {m.get('question', '')}",
                    snippet=snippet,
                    published_at=close_str or None,
                    source_name=self.source_name,
                    raw=m,
                ))
        except Exception:  # noqa: BLE001
            pass
        return results


def create_default_search_adapter() -> SearchAdapter:
    """Build the default composite adapter.

    Priority order:
      Brave (rotating) → Tavily → FRED → Metaculus → Manifold → OfficialSeed → Wikipedia → GDELT

    Brave is primary: 2000 free queries/month per key, full web index.
      Supports multiple keys (BRAVE_SEARCH_API_KEY, BRAVE_SEARCH_API_KEY_2, …):
      RotatingBraveSearchAdapter auto-switches on HTTP 429 and persists state
      so the exhaustion survives restarts within the same calendar month.
    Tavily: AI-enriched snippets for paywalled/JS pages, 1000/month free.
    FRED: free economic data — irreplaceable for monetary policy markets.
    Metaculus: community forecasts — calibration signal, no key needed.
    Manifold: play-money but fast-reacting market signal, no key needed.
    OfficialSeed/Wikipedia/GDELT: always available fallbacks.
    """
    adapters: list[SearchAdapter] = []

    # Collect all configured Brave keys (supports arbitrary BRAVE_SEARCH_API_KEY_N)
    brave_keys: list[str] = []
    for suffix in ["", "_2", "_3", "_4", "_5"]:
        k = os.getenv(f"BRAVE_SEARCH_API_KEY{suffix}", "").strip()
        if k and k not in brave_keys:
            brave_keys.append(k)

    # Collect all configured Tavily keys (TAVILY_API_KEY, TAVILY_API_KEY_2..._5)
    tavily_keys: list[str] = []
    for suffix in ["", "_2", "_3", "_4", "_5"]:
        k = os.getenv(f"TAVILY_API_KEY{suffix}", "").strip()
        if k and k not in tavily_keys:
            tavily_keys.append(k)
    if not tavily_keys:
        alt = os.getenv("TAVILY_SEARCH_API_KEY", "").strip()
        if alt:
            tavily_keys.append(alt)

    fred_key = os.getenv("FRED_API_KEY")
    metaculus_token = os.getenv("METACULUS_API_TOKEN") or os.getenv("METACULUS_TOKEN")

    # Tavily FIRST (primary, deepest results), then Brave as failover.
    if len(tavily_keys) > 1:
        print(f"  [Tavily] {len(tavily_keys)} keys configured - RotatingTavilySearchAdapter active")
        adapters.append(RotatingTavilySearchAdapter(api_keys=tavily_keys))
    elif tavily_keys:
        adapters.append(TavilySearchAdapter(api_key=tavily_keys[0]))

    if len(brave_keys) > 1:
        print(f"  [Brave] {len(brave_keys)} keys configured - RotatingBraveSearchAdapter active")
        adapters.append(RotatingBraveSearchAdapter(api_keys=brave_keys))
    elif brave_keys:
        adapters.append(BraveSearchAdapter(api_key=brave_keys[0]))
    # FRED works without a key (returns page links); with key returns live data
    adapters.append(FREDSearchAdapter(api_key=fred_key))
    # Metaculus requires token (free at metaculus.com/accounts/profile/)
    adapters.append(MetaculusSearchAdapter(api_token=metaculus_token))
    adapters.append(ManifoldMarketsAdapter())
    adapters.extend([OfficialSeedSearchAdapter(), WikipediaSearchAdapter(), GdeltSearchAdapter()])
    return CompositeSearchAdapter(adapters)


def _query_variants(query: str) -> list[str]:
    cleaned = re.sub(r"\b(site|filetype|before|after):\S+", " ", query, flags=re.IGNORECASE)
    cleaned = cleaned.replace('"', " ")
    cleaned = re.sub(r"\bOR\b|\bAND\b", " ", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"[^\w\s\-\u0400-\u04ff]", " ", cleaned, flags=re.UNICODE)
    stop = {
        "polymarket",
        "resolution",
        "official",
        "credible",
        "reporting",
        "disconfirming",
        "evidence",
        "contradiction",
        "controversy",
        "dispute",
        "archive",
        "cached",
        "forum",
        "github",
        "repo",
        "commit",
        "issue",
        "changelog",
        "market",
        "prediction",
        "will",
    }
    tokens = [token for token in cleaned.split() if len(token) >= 3 and token.lower() not in stop]
    variants = [" ".join(tokens[:8]), " ".join(tokens[:5]), query.strip()]
    return [variant for variant in dict.fromkeys(v for v in variants if v)]


def _dedupe_results(results: list[SearchResult]) -> list[SearchResult]:
    seen: set[str] = set()
    deduped: list[SearchResult] = []
    for result in results:
        if not result.url or result.url in seen:
            continue
        seen.add(result.url)
        deduped.append(result)
    return deduped
