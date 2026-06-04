"""Live wallet portfolio sync — pulls the operator's real Polymarket positions
straight from the public data-api so we never need screenshots again.

Writes dashboard-web/public/data/live-portfolio.json (read by the dashboard) and
prints a reconciled report. Wallet address lives in wallet_config.json.

Usage:  python wallet_sync.py
"""
from __future__ import annotations
import json, os, sys, sqlite3
from datetime import datetime, timezone
import urllib.request

BOT = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(BOT)
CFG = os.path.join(BOT, "wallet_config.json")
OUT = os.path.join(ROOT, "dashboard-web", "public", "data", "live-portfolio.json")
DATA_API = "https://data-api.polymarket.com"


def _get(path, params):
    q = "&".join(f"{k}={v}" for k, v in params.items())
    req = urllib.request.Request(f"{DATA_API}/{path}?{q}", headers={"User-Agent": "Signal-WalletSync/1.0"})
    return json.loads(urllib.request.urlopen(req, timeout=20).read())


def load_wallet() -> str:
    if os.path.exists(CFG):
        return json.load(open(CFG)).get("wallet", "")
    return ""


def sync(wallet: str) -> dict:
    positions = _get("positions", {"user": wallet, "limit": "200"})
    if not isinstance(positions, list):
        positions = []
    value = 0.0
    try:
        v = _get("value", {"user": wallet})
        value = float(v[0]["value"]) if isinstance(v, list) and v else 0.0
    except Exception:
        pass

    rows, unreal = [], 0.0
    for p in positions:
        cv = float(p.get("currentValue") or 0)
        cash = float(p.get("cashPnl") or 0)
        unreal += cash
        rows.append({
            "title": p.get("title"), "outcome": p.get("outcome"),
            "currentValue": round(cv, 2), "cashPnl": round(cash, 2),
            "percentPnl": p.get("percentPnl"),
            "avgPrice": p.get("avgPrice"), "curPrice": p.get("curPrice"),
            "redeemable": p.get("redeemable"), "conditionId": p.get("conditionId"),
            "size": p.get("size"),
        })
    rows.sort(key=lambda r: -r["currentValue"])

    payload = {
        "generatedAt": datetime.now(timezone.utc).isoformat(),
        "wallet": wallet,
        "portfolioValue": round(value, 2),
        "openUnrealizedPnl": round(unreal, 2),
        "positionCount": len([r for r in rows if r["currentValue"] > 0.01]),
        "positions": rows,
    }
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)
    return payload


def reconcile(payload: dict) -> None:
    """Cross-check live wallet vs our DB real-money signals (flag drift)."""
    db = os.path.join(BOT, "bot.db")
    if not os.path.exists(db):
        return
    conn = sqlite3.connect(db); conn.row_factory = sqlite3.Row
    db_open = {r["condition_id"].lower(): r["side"] for r in conn.execute(
        "SELECT condition_id, side FROM signals WHERE real_money=1 AND resolved=0").fetchall()}
    live_cids = {(r["conditionId"] or "").lower() for r in payload["positions"] if r["currentValue"] > 0.01}
    print("\n  Reconciliation vs DB (real-money open):")
    for cid, side in db_open.items():
        tag = "OK on-chain" if cid in live_cids else "NOT on wallet (closed/dust?)"
        print(f"    DB {side:<3} {cid[:14]}  -> {tag}")
    redeemable = [r for r in payload["positions"] if r.get("redeemable")]
    if redeemable:
        print("  Redeemable (resolved, claim on Polymarket):")
        for r in redeemable:
            print(f"    {r['outcome']} ${r['currentValue']} | {(r['title'] or '')[:44]}")


def main():
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    wallet = load_wallet()
    if not wallet:
        print("No wallet configured. Write wallet_config.json: {\"wallet\": \"0x...\"}")
        return
    p = sync(wallet)
    print(f"Portfolio value: ${p['portfolioValue']} | open unrealized PnL: ${p['openUnrealizedPnl']:+.2f} "
          f"| {p['positionCount']} positions")
    for r in p["positions"]:
        if r["currentValue"] > 0.01:
            print(f"  {r['outcome']:>3} ${r['currentValue']:>8.2f} {r['cashPnl']:>+8.2f} | {(r['title'] or '')[:44]}")
    reconcile(p)
    print(f"\nWrote {os.path.relpath(OUT, ROOT)}")


if __name__ == "__main__":
    main()
