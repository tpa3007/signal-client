"""Small Polymarket data-api client for client-mode audits."""
from __future__ import annotations

import json
import urllib.parse
import urllib.request


BASE_DATA = "https://data-api.polymarket.com"
HEADERS = {"User-Agent": "Signal-Client/0.1"}


def fetch_positions(wallet: str, *, timeout: int = 20) -> list[dict]:
    query = urllib.parse.urlencode({"user": wallet})
    req = urllib.request.Request(f"{BASE_DATA}/positions?{query}", headers=HEADERS)
    with urllib.request.urlopen(req, timeout=timeout) as response:
        data = json.loads(response.read().decode("utf-8"))
    return data if isinstance(data, list) else []


def post_json(url: str, payload: dict, *, secret: str, timeout: int = 20) -> dict:
    body = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=body,
        method="POST",
        headers={
            "Content-Type": "application/json",
            "User-Agent": HEADERS["User-Agent"],
            "X-Signal-Client-Secret": secret,
        },
    )
    with urllib.request.urlopen(req, timeout=timeout) as response:
        raw = response.read().decode("utf-8")
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return {"ok": True, "raw": raw}
