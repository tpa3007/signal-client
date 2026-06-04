import { useEffect, useState } from "react";

const GAMMA = "https://gamma-api.polymarket.com/markets";
const INTERVAL = 60_000;

async function fetchMarketPrice(conditionId) {
  // NOTE: the correct Gamma param is `condition_ids` (plural). The singular
  // form is silently ignored and returns a default market list — that bug
  // previously made every position show a ~0.51 placeholder price.
  const res = await fetch(`${GAMMA}?condition_ids=${encodeURIComponent(conditionId)}`);
  if (!res.ok) return null;
  const data = await res.json();
  const market = Array.isArray(data) ? data[0] : null;
  if (!market) return null;

  // Validate the API returned the exact market we asked for, and that it is
  // still tradable. Otherwise the live price is meaningless.
  const returnedId = market.conditionId || market.condition_id;
  if (returnedId && returnedId.toLowerCase() !== conditionId.toLowerCase()) return null;
  if (market.closed === true) return null;

  const op = market.outcomePrices;
  if (op) {
    try {
      const prices = typeof op === "string" ? JSON.parse(op) : op;
      const yesPrice = parseFloat(prices[0]);
      const noPrice = prices.length > 1 ? parseFloat(prices[1]) : 1 - yesPrice;
      if (!Number.isNaN(yesPrice) && yesPrice > 0) {
        return {
          yesPrice,
          noPrice,
          volume: market.volumeNum || 0,
          liquidity: market.liquidityNum || 0,
        };
      }
    } catch {
      // fall through to bestBid
    }
  }

  const bid = parseFloat(market.bestBid || 0);
  if (bid > 0) {
    return { yesPrice: bid, noPrice: 1 - bid, volume: market.volumeNum || 0 };
  }
  return null;
}

export function usePolymarketPrices(conditionIds) {
  const [prices, setPrices] = useState({});
  const [isLive, setIsLive] = useState(false);
  const [lastUpdated, setLastUpdated] = useState(null);

  // stable key so effect only re-runs when the actual IDs change
  const idsKey = conditionIds.slice().sort().join(",");

  useEffect(() => {
    if (!conditionIds.length) return;
    let alive = true;

    async function refresh() {
      try {
        const entries = await Promise.all(
          conditionIds.map(async (cid) => [cid, await fetchMarketPrice(cid)])
        );
        if (!alive) return;
        const map = {};
        let hits = 0;
        for (const [cid, price] of entries) {
          if (price) {
            map[cid] = price;
            hits++;
          }
        }
        setPrices(map);
        setIsLive(hits > 0);
        setLastUpdated(new Date());
      } catch {
        if (alive) setIsLive(false);
      }
    }

    refresh();
    const timer = setInterval(refresh, INTERVAL);
    return () => {
      alive = false;
      clearInterval(timer);
    };
  }, [idsKey]); // eslint-disable-line react-hooks/exhaustive-deps

  return { prices, isLive, lastUpdated };
}
