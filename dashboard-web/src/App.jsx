import React, { useEffect, useMemo, useState } from "react";
import { usePolymarketPrices } from "./usePolymarketPrices.js";

const EMPTY_DATA = {
  summary: {},
  signals: [],
  workflowRuns: [],
  modelEvolution: [],
};

function CheckIcon() {
  return (
    <svg viewBox="0 0 24 24" aria-hidden="true">
      <path d="m4.5 12.75 6 6 9-13.5" />
    </svg>
  );
}

function WarningIcon() {
  return (
    <svg viewBox="0 0 24 24" aria-hidden="true">
      <path d="M12 9v3m0 4h.01M4 19h16L12 4 4 19Z" />
    </svg>
  );
}

function ExternalLinkIcon() {
  return (
    <svg viewBox="0 0 24 24" aria-hidden="true">
      <path d="M13.5 6H6a2 2 0 0 0-2 2v10a2 2 0 0 0 2 2h10a2 2 0 0 0 2-2v-7.5M9 15 20 4m0 0h-6m6 0v6" />
    </svg>
  );
}

function CpuIcon() {
  return (
    <svg viewBox="0 0 24 24" aria-hidden="true">
      <path d="M9 3v2m6-2v2M9 19v2m6-2v2M5 9H3m2 6H3m18-6h-2m2 6h-2M7 5h10a2 2 0 0 1 2 2v10a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V7a2 2 0 0 1 2-2Zm2 4h6v6H9V9Z" />
    </svg>
  );
}

function BookIcon() {
  return (
    <svg viewBox="0 0 24 24" aria-hidden="true">
      <path d="M12 6.042A8.967 8.967 0 0 0 6 3.75c-1.052 0-2.062.18-3 .512v14.25A8.987 8.987 0 0 1 6 18c2.305 0 4.408.867 6 2.292m0-14.25a8.966 8.966 0 0 1 6-2.292c1.052 0 2.062.18 3 .512v14.25A8.987 8.987 0 0 0 18 18a8.967 8.967 0 0 0-6 2.292m0-14.25v14.25" />
    </svg>
  );
}

function ChartIcon() {
  return (
    <svg viewBox="0 0 24 24" aria-hidden="true">
      <path d="M3 13.125C3 12.504 3.504 12 4.125 12h2.25c.621 0 1.125.504 1.125 1.125v6.75C7.5 20.496 6.996 21 6.375 21h-2.25A1.125 1.125 0 0 1 3 19.875v-6.75ZM9.75 8.625c0-.621.504-1.125 1.125-1.125h2.25c.621 0 1.125.504 1.125 1.125v11.25c0 .621-.504 1.125-1.125 1.125h-2.25a1.125 1.125 0 0 1-1.125-1.125V8.625ZM16.5 4.125c0-.621.504-1.125 1.125-1.125h2.25C20.496 3 21 3.504 21 4.125v15.75c0 .621-.504 1.125-1.125 1.125h-2.25a1.125 1.125 0 0 1-1.125-1.125V4.125Z" />
    </svg>
  );
}

function fmtUsd(value, compact = false) {
  const num = Number(value || 0);
  if (compact && Math.abs(num) >= 1000) {
    return `$${(num / 1000).toFixed(num >= 10000 ? 0 : 1)}k`;
  }
  return `$${num.toLocaleString("en-US", { maximumFractionDigits: 2 })}`;
}

function fmtPct(value) {
  const num = Number(value || 0);
  return `${Math.round(num * 100)}%`;
}

function fmtSigned(value) {
  const num = Number(value || 0);
  const sign = num >= 0 ? "+" : "-";
  return `${sign}${fmtUsd(Math.abs(num))}`;
}

function signalTone(signal) {
  if (signal.status === "CLOSED") {
    return signal.review?.outcome === "WON" ? "positive" : "negative";
  }
  if (signal.unrealizedPnl > 0.01) return "positive";
  if (signal.unrealizedPnl < -0.01) return "negative";
  return "neutral";
}

function categoryLabel(category) {
  const map = {
    "Private Markets": "Private Markets",
    Elections: "Выборы",
    Geopolitics: "Геополитика",
    Macro: "Макро",
    AI: "AI",
  };
  return map[category] || category || "General";
}

function recommendationLabel(value) {
  const recommendation = String(value || "HOLD").toUpperCase();
  const map = {
    HOLD: "Hold",
    REVIEW: "Review",
    EXIT: "Exit",
  };
  return map[recommendation] || recommendation;
}

function recommendationTone(value) {
  const recommendation = String(value || "HOLD").toUpperCase();
  if (recommendation === "EXIT") return "exit";
  if (recommendation === "REVIEW") return "review";
  return "hold";
}

function signalRiskScore(signal) {
  const recommendation = String(signal.monitorRecommendation || "HOLD").toUpperCase();
  const recommendationScore = recommendation === "EXIT" ? 100 : recommendation === "REVIEW" ? 70 : 0;
  const pnlScore = signal.unrealizedPnl < 0 ? Math.min(Math.abs(signal.unrealizedPnl) * 4, 40) : 0;
  const expiryScore =
    typeof signal.daysToExpiry === "number" && signal.daysToExpiry <= 3 ? Math.max(0, 30 - signal.daysToExpiry * 6) : 0;
  return recommendationScore + pnlScore + expiryScore;
}

function formatDays(value) {
  if (typeof value !== "number") return "—";
  if (value < 0) return "expired";
  if (value < 1) return "<1d";
  return `${value.toFixed(value >= 10 ? 0 : 1)}d`;
}

function App() {
  const [data, setData] = useState(EMPTY_DATA);
  const [loading, setLoading] = useState(true);
  const [view, setView] = useState("PORTFOLIO");
  const [statusFilter, setStatusFilter] = useState("ALL");
  const [capitalFilter, setCapitalFilter] = useState("ALL");
  const [search, setSearch] = useState("");
  const [sortMode, setSortMode] = useState("RISK");
  const [selectedId, setSelectedId] = useState(null);
  const [mobileView, setMobileView] = useState("LIST");

  useEffect(() => {
    let alive = true;
    fetch("/data/signal-dashboard.json", { cache: "no-store" })
      .then((res) => res.json())
      .then((payload) => {
        if (!alive) return;
        setData(payload);
        setSelectedId(null);
      })
      .catch(() => {
        if (alive) setData(EMPTY_DATA);
      })
      .finally(() => alive && setLoading(false));
    return () => {
      alive = false;
    };
  }, []);

  const rawSignals = useMemo(() => data.signals || [], [data.signals]);

  const openConditionIds = useMemo(
    () => rawSignals.filter((s) => s.status === "COMMITTED" && s.conditionId).map((s) => s.conditionId),
    [rawSignals]
  );
  const { prices: livePrices, isLive, lastUpdated: liveUpdated } = usePolymarketPrices(openConditionIds);

  useEffect(() => {
    document.documentElement.dataset.theme = "swiss";
  }, []);

  const signals = useMemo(() => {
    if (!Object.keys(livePrices).length) return rawSignals;
    return rawSignals.map((signal) => {
      const live = livePrices[signal.conditionId];
      if (!live || signal.status !== "COMMITTED") return signal;
      const currentYesPrice = live.yesPrice;
      const currentNoPrice = live.noPrice;
      const currentSidePrice = signal.side === "YES" ? currentYesPrice : currentNoPrice;
      const stake = Number(signal.realBetUsd || signal.allocatedCapital || 0);
      const sideEntry = Number(signal.sideEntryPrice || 0);
      const shares = sideEntry > 0 ? stake / sideEntry : 0;
      const unrealizedPnl = Math.round((currentSidePrice - sideEntry) * shares * 100) / 100;
      return {
        ...signal,
        currentYesPrice: Math.round(currentYesPrice * 10000) / 10000,
        currentNoPrice: Math.round(currentNoPrice * 10000) / 10000,
        currentSidePrice: Math.round(currentSidePrice * 10000) / 10000,
        unrealizedPnl,
      };
    });
  }, [rawSignals, livePrices]);

  const filteredSignals = useMemo(() => {
    const query = search.trim().toLowerCase();
    const filtered = signals.filter((signal) => {
      const matchesStatus = statusFilter === "ALL" || signal.status === statusFilter;
      const matchesCapital =
        capitalFilter === "ALL" ||
        (capitalFilter === "REAL" && signal.realMoney) ||
        (capitalFilter === "PAPER" && !signal.realMoney);
      const searchText = [
        signal.title,
        signal.category,
        signal.side,
        signal.status,
        signal.monitorRecommendation,
        signal.monitorReason,
      ]
        .filter(Boolean)
        .join(" ")
        .toLowerCase();
      return matchesStatus && matchesCapital && (!query || searchText.includes(query));
    });
    return filtered.sort((a, b) => {
      if (sortMode === "PNL") return Number(b.unrealizedPnl || 0) - Number(a.unrealizedPnl || 0);
      if (sortMode === "EXPIRY") return Number(a.daysToExpiry ?? 9999) - Number(b.daysToExpiry ?? 9999);
      if (sortMode === "EDGE") return Math.abs(Number(b.edge || 0)) - Math.abs(Number(a.edge || 0));
      if (sortMode === "RECENT") {
        return new Date(b.openedAt || b.createdAt || 0) - new Date(a.openedAt || a.createdAt || 0);
      }
      return signalRiskScore(b) - signalRiskScore(a);
    });
  }, [signals, statusFilter, capitalFilter, search, sortMode]);

  const selectedSignal = useMemo(() => {
    return filteredSignals.find((signal) => signal.id === selectedId) || filteredSignals[0] || signals[0] || null;
  }, [filteredSignals, signals, selectedId]);

  const summary = data.summary || {};
  const openSignals = signals.filter((signal) => signal.status === "COMMITTED");
  const closedSignals = signals.filter((signal) => signal.status === "CLOSED");
  const positiveOpen = openSignals.filter((signal) => signal.unrealizedPnl > 0);
  const liveUnrealizedPnl = useMemo(
    () => openSignals.reduce((sum, s) => sum + Number(s.unrealizedPnl || 0), 0),
    [openSignals]
  );
  const realExposure = Number(summary.realExposure || 0);
  const paperExposure = Number(summary.paperExposure || 0);
  const attentionSignals = useMemo(() => {
    return openSignals
      .filter((signal) => signalRiskScore(signal) > 0 || !signal.gateCheck?.gatePassed)
      .sort((a, b) => signalRiskScore(b) - signalRiskScore(a));
  }, [openSignals]);

  if (loading) {
    return <div className="loading">Загрузка Signal dashboard...</div>;
  }

  return (
    <div className="app-shell">
      <header className="topbar">
        <div className="topbar-inner">
          <button className="brand" onClick={() => setView("PORTFOLIO")}>
            <span>SIGNAL</span>
            <em>Editorial Board</em>
          </button>

          <div className="top-actions">
            <LiveBadge isLive={isLive} lastUpdated={liveUpdated} />
            <nav className="main-nav" aria-label="Главные разделы">
              <button className={view === "PORTFOLIO" ? "active" : ""} onClick={() => setView("PORTFOLIO")}>
                Активные портфели
              </button>
              <button className={view === "DIARY" ? "active" : ""} onClick={() => setView("DIARY")}>
                <BookIcon />
                Дневник
              </button>
              <button className={view === "ANALYTICS" ? "active" : ""} onClick={() => setView("ANALYTICS")}>
                <ChartIcon />
                Аналитика
              </button>
              <button className={view === "MODEL_EVOLUTION" ? "active" : ""} onClick={() => setView("MODEL_EVOLUTION")}>
                <CpuIcon />
                Эволюция
              </button>
            </nav>
          </div>
        </div>
      </header>

      <main className="main">
        {view === "PORTFOLIO" ? (
          <>
            <section className="metric-grid" aria-label="Сводка портфеля">
              <Metric label="Реальный капитал" value={fmtUsd(realExposure, true)} hint="Открытые live позиции" tone="positive" />
              <Metric label="Paper money" value={fmtUsd(paperExposure, true)} hint={`${openSignals.length} открытых сигналов`} />
              <Metric label="Unrealized P&L" value={fmtSigned(liveUnrealizedPnl)} hint={`${positiveOpen.length}/${openSignals.length} в плюс`} tone={liveUnrealizedPnl >= 0 ? "positive" : "negative"} />
              <Metric label="Средний edge" value={`${summary.avgEdge || 0}%`} hint={`${signals.length} сигналов в базе`} tone="gold" />
            </section>

            <AttentionStrip
              signals={attentionSignals.slice(0, 4)}
              onSelect={(signal) => {
                setSelectedId(signal.id);
                setMobileView("DETAIL");
              }}
            />

            <section className="portfolio-grid">
              <aside className={`signal-list ${mobileView === "DETAIL" ? "mobile-hidden" : ""}`}>
                <div className="portfolio-tools">
                  <label className="search-field">
                    Поиск
                    <input value={search} onChange={(event) => setSearch(event.target.value)} placeholder="Kim, Iran, OpenAI..." />
                  </label>
                  <label className="sort-field">
                    Сортировка
                    <select value={sortMode} onChange={(event) => setSortMode(event.target.value)}>
                      <option value="RISK">Risk first</option>
                      <option value="RECENT">Newest</option>
                      <option value="PNL">P&L</option>
                      <option value="EXPIRY">Expiry</option>
                      <option value="EDGE">Edge</option>
                    </select>
                  </label>
                </div>

                <div className="tabs">
                  {[
                    ["ALL", "Все статусы"],
                    ["COMMITTED", "В рынке"],
                    ["CLOSED", "Завершенные"],
                  ].map(([id, label]) => (
                    <button key={id} className={statusFilter === id ? "active" : ""} onClick={() => setStatusFilter(id)}>
                      {label}
                    </button>
                  ))}
                </div>

                <div className="segment">
                  {[
                    ["ALL", "Все сделки"],
                    ["REAL", "Реальный капитал"],
                    ["PAPER", "Paper money"],
                  ].map(([id, label]) => (
                    <button key={id} className={capitalFilter === id ? "active" : ""} onClick={() => setCapitalFilter(id)}>
                      {label}
                    </button>
                  ))}
                </div>

                <div className="list-scroll">
                  {filteredSignals.map((signal) => (
                    <SignalCard
                      key={signal.id}
                      signal={signal}
                      selected={signal.id === selectedSignal?.id}
                      onSelect={() => {
                        setSelectedId(signal.id);
                        setMobileView("DETAIL");
                      }}
                    />
                  ))}
                </div>
              </aside>

              <section className={`detail-pane ${mobileView === "LIST" ? "mobile-hidden" : ""}`}>
                {selectedSignal ? (
                  <SignalDetail signal={selectedSignal} onBack={() => setMobileView("LIST")} />
                ) : (
                  <div className="empty-state">Выберите сигнал для детального разбора.</div>
                )}
              </section>
            </section>
          </>
        ) : view === "DIARY" ? (
          <DiaryView
            diary={data.diary || []}
            onSignalSelect={(id) => { setSelectedId(id); setView("PORTFOLIO"); setStatusFilter("ALL"); }}
          />
        ) : view === "ANALYTICS" ? (
          <AnalyticsView analytics={data.analytics || {}} summary={summary} />
        ) : (
          <ModelEvolution data={data} />
        )}
      </main>

      <footer className="footer">© 2026 Signal Predictive System · SQLite snapshot · {summary.generatedAt?.slice(0, 19) || "local"}</footer>
    </div>
  );
}

function AttentionStrip({ signals, onSelect }) {
  if (!signals.length) {
    return (
      <section className="attention-strip calm">
        <div>
          <span>Operator attention</span>
          <strong>Критичных позиций нет</strong>
        </div>
        <p>Открытые сигналы сейчас не требуют немедленного ручного решения по мониторингу.</p>
      </section>
    );
  }

  return (
    <section className="attention-strip">
      <div className="attention-head">
        <div>
          <span>Operator attention</span>
          <strong>Что проверить первым</strong>
        </div>
        <em>{signals.length} priority</em>
      </div>
      <div className="attention-grid">
        {signals.map((signal) => (
          <button className="attention-card" key={signal.id} onClick={() => onSelect(signal)}>
            <MonitorBadge value={signal.monitorRecommendation} />
            <strong>{signal.title}</strong>
            <span>
              {fmtSigned(signal.unrealizedPnl)} · {formatDays(signal.daysToExpiry)} left
            </span>
          </button>
        ))}
      </div>
    </section>
  );
}

function MonitorBadge({ value }) {
  return <span className={`monitor-badge ${recommendationTone(value)}`}>{recommendationLabel(value)}</span>;
}

function Metric({ label, value, hint, tone = "neutral" }) {
  return (
    <div className={`metric ${tone}`}>
      <span>{label}</span>
      <strong>{value}</strong>
      <p>{hint}</p>
    </div>
  );
}

function SignalCard({ signal, selected, onSelect }) {
  const tone = signalTone(signal);
  const isClosed = signal.status === "CLOSED";
  return (
    <button className={`signal-card ${selected ? "selected" : ""}`} onClick={onSelect}>
      <div className="card-head">
        <span className="category">{categoryLabel(signal.category)}</span>
        <MonitorBadge value={signal.monitorRecommendation} />
        <span className={`capital-badge ${signal.realMoney ? "real" : "paper"}`}>
          {signal.realMoney ? "Real" : "Paper"}
        </span>
        <span className={`status-badge ${signal.status.toLowerCase()}`}>
          {signal.status === "COMMITTED" ? "Active" : signal.status === "DRAFT" ? "Draft" : "Closed"}
        </span>
      </div>
      <h3>{signal.title}</h3>
      <p className="card-note">
        {recommendationLabel(signal.monitorRecommendation)} · {formatDays(signal.daysToExpiry)} left
      </p>
      <div className="card-stats">
        <div>
          <span>Entry</span>
          <strong>{fmtPct(signal.sideEntryPrice)}</strong>
        </div>
        <div>
          <span>Now</span>
          <strong>{signal.currentSidePrice ? fmtPct(signal.currentSidePrice) : "—"}</strong>
        </div>
        <div className={tone}>
          <span>{isClosed ? "Result" : "P&L"}</span>
          <strong>{isClosed ? signal.review?.outcome || "—" : fmtSigned(signal.unrealizedPnl)}</strong>
        </div>
      </div>
    </button>
  );
}

function SignalDetail({ signal, onBack }) {
  const tone = signalTone(signal);
  const market = signal.polymarketPrice || 0;
  const model = signal.calculatedProbability || 0;
  const left = Math.min(market, model) * 100;
  const width = Math.abs(model - market) * 100;

  return (
    <article className="detail-card">
      <button className="back-button" onClick={onBack}>← Вернуться к списку</button>
      <header className="detail-header">
        <div>
          <div className="detail-meta">
            <span>{categoryLabel(signal.category)}</span>
            <MonitorBadge value={signal.monitorRecommendation} />
            {signal.marketUrl && (
              <a href={signal.marketUrl} target="_blank" rel="noreferrer">
                Polymarket контракт <ExternalLinkIcon />
              </a>
            )}
          </div>
          <h1>{signal.title}</h1>
          <p>
            Коммит: <strong>{signal.createdAt || "—"}</strong> · ID: {signal.id} · Side: <strong>{signal.side}</strong>
          </p>
        </div>
        <div className="quality">
          <span>Рейтинг качества</span>
          <strong>{signal.qualityScore}</strong>
        </div>
      </header>

      <section className="allocation-box">
        <div>
          <span>Тип сигнала</span>
          <strong>{signal.realMoney ? "Реальный капитал" : "Paper money"}</strong>
          <p>{signal.realMoney ? "Live позиция с реальным риском." : "Позиция записана для калибровки и обучения."}</p>
        </div>
        <div className={`pnl-box ${tone}`}>
          <span>Текущая оценка</span>
          <strong>{fmtSigned(signal.unrealizedPnl)}</strong>
          <p>
            Entry {fmtPct(signal.sideEntryPrice)} → now {signal.currentSidePrice ? fmtPct(signal.currentSidePrice) : "—"}
          </p>
        </div>
      </section>

      <section className="monitor-panel">
        <div>
          <span>Command F / Monitor</span>
          <strong>{recommendationLabel(signal.monitorRecommendation)}</strong>
          <p>{signal.monitorReason || "Свежая мониторинговая причина не записана."}</p>
        </div>
        <div className="monitor-grid">
          <div><span>Expiry</span><strong>{formatDays(signal.daysToExpiry)}</strong></div>
          <div><span>SDV</span><strong>{signal.monitorSdv ?? "—"}</strong></div>
          <div><span>Kill criteria</span><strong>{signal.killCriteriaCovered ?? "—"}/{signal.killCriteriaTotal ?? "—"}</strong></div>
        </div>
      </section>

      <section className="edge-box">
        <h2>Карта отклонений</h2>
        <div className="prob-row">
          <div>
            <span>Рынок</span>
            <strong>{fmtPct(market)}</strong>
          </div>
          <div>
            <span>Модель Signal</span>
            <strong>{fmtPct(model)}</strong>
          </div>
          <div>
            <span>Edge</span>
            <strong>{signal.edge > 0 ? "+" : ""}{signal.edge}%</strong>
          </div>
        </div>
        <div className="edge-scale">
          <span className="edge-fill" style={{ left: `${left}%`, width: `${width}%` }} />
          <span className="dot market" style={{ left: `calc(${market * 100}% - 6px)` }}>Market</span>
          <span className="dot model" style={{ left: `calc(${model * 100}% - 6px)` }}>Model</span>
        </div>
      </section>

      {signal.priceHistory?.length > 1 && (
        <Section title="Путь цены (YES)">
          <Sparkline
            data={signal.priceHistory}
            entryYes={signal.yesEquivalentEntry}
            currentYes={signal.currentYesPrice}
          />
        </Section>
      )}

      {signal.smartMoney && signal.smartMoney.totalUsd > 0 && (
        <Section title="Умные деньги">
          <SmartMoneyPanel sm={signal.smartMoney} side={signal.side} />
        </Section>
      )}

      <Section title="Описание неэффективности">
        <blockquote>{signal.thesis || "Тезис не записан."}</blockquote>
      </Section>

      <Section title="Evidence ledger">
        <div className="evidence-grid">
          {(signal.evidence || []).slice(0, 4).map((item, index) => (
            <div className="evidence-card" key={`${item.source_name}-${index}`}>
              <div>
                <span>{item.source_name || "Evidence"}</span>
                <em>{item.stance || "NEUTRAL"}</em>
              </div>
              <p>{item.claim}</p>
            </div>
          ))}
        </div>
      </Section>

      <Section title="Actor map">
        <div className="actor-grid">
          {(signal.actors || []).slice(0, 4).map((actor, index) => (
            <div className="actor-card" key={`${actor.actor_name}-${index}`}>
              <div>
                <strong>{actor.actor_name}</strong>
                <span>{actor.role || actor.actor_type || "Actor"}</span>
              </div>
              <em>{actor.likely_action || actor.incentives || "monitor"}</em>
            </div>
          ))}
        </div>
      </Section>

      <section className="gate-grid">
        <div>
          <h2>Параметры ордера</h2>
          <dl>
            <div><dt>Капитал</dt><dd>{fmtUsd(signal.allocatedCapital)}</dd></div>
            <div><dt>Направление</dt><dd>{signal.side}</dd></div>
            <div><dt>YES equivalent</dt><dd>{fmtPct(signal.yesEquivalentEntry)}</dd></div>
            <div><dt>Резолюция</dt><dd>{signal.endDate || "—"}</dd></div>
          </dl>
        </div>
        <div>
          <h2>Signal gate</h2>
          <GateRow ok={signal.gateCheck?.liquidityOk} label="Ликвидность" okText="ОК" badText="Низкая" />
          <GateRow ok={signal.gateCheck?.noLineAnomaly} label="Spread / line" okText="Чисто" badText="Риск" />
          <GateRow ok={signal.gateCheck?.riskCleared} label="Риск-лимиты" okText="Одобрено" badText="Ожидает" />
          <div className="decision">{signal.gateCheck?.decision || "unknown"}</div>
        </div>
      </section>

      {signal.diaryEntries?.length > 0 && (
        <Section title="Цепочка рассуждений">
          <ReasoningChain entries={signal.diaryEntries} />
        </Section>
      )}
    </article>
  );
}

function Section({ title, children }) {
  return (
    <section className="detail-section">
      <h2>{title}</h2>
      {children}
    </section>
  );
}

function GateRow({ ok, label, okText, badText }) {
  return (
    <div className="gate-row">
      <span>{label}</span>
      <strong className={ok ? "ok" : "bad"}>
        {ok ? <CheckIcon /> : <WarningIcon />}
        {ok ? okText : badText}
      </strong>
    </div>
  );
}

function ModelEvolution({ data }) {
  return (
    <section className="evolution">
      <div className="evolution-head">
        <span>LOGICAL EVOLUTION</span>
        <h1>Хроника обучения и корректировки модели</h1>
        <p>
          Журнал показывает реальные архитектурные изменения Signal: где мы заменяем слепой автоматизм на
          ручную probability, где починены price-модели, и какие workflows меняли качество сигналов.
        </p>
      </div>

      <div className="evolution-metrics">
        <Metric label="Signals in DB" value={data.summary?.totalSignals || 0} hint="SQLite snapshot" />
        <Metric label="Open positions" value={data.summary?.openSignals || 0} hint="Active ledger" tone="positive" />
        <Metric label="Paper accuracy" value={`${data.summary?.paperAccuracy || 0}%`} hint="Closed paper only" tone="gold" />
      </div>

      <div className="timeline">
        {(data.modelEvolution || []).map((item) => (
          <article className="timeline-item" key={`${item.date}-${item.version}`}>
            <header>
              <div>
                <span>{item.version}</span>
                <em>{item.date}</em>
                <strong className={item.status.toLowerCase()}>{item.status}</strong>
              </div>
              <p>{item.metric}: {item.before} → {item.after}</p>
            </header>
            <h2>{item.title}</h2>
            <p>{item.description}</p>
          </article>
        ))}
      </div>

      <div className="workflow-panel">
        <h2>Последние workflow runs</h2>
        {(data.workflowRuns || []).map((run) => (
          <div className="workflow-row" key={run.id}>
            <span>{run.workflow_name}</span>
            <strong>{run.status}</strong>
            <em>{String(run.started_at || "").slice(0, 16)}</em>
          </div>
        ))}
      </div>
    </section>
  );
}

const DIARY_TYPE_CFG = {
  dossier:        { label: "Форейджер",  cls: "dossier"    },
  monitoring:     { label: "Мониторинг", cls: "monitoring"  },
  signal_created: { label: "Сигнал",     cls: "created"     },
  resolved:       { label: "Завершено",  cls: "resolved"    },
};

function DiaryTypeBadge({ type }) {
  const cfg = DIARY_TYPE_CFG[type] || { label: type, cls: "neutral" };
  return <span className={`diary-type ${cfg.cls}`}>{cfg.label}</span>;
}

function DiaryView({ diary, onSignalSelect }) {
  const [typeFilter, setTypeFilter] = useState("ALL");
  const filterOpts = [
    ["ALL",           "Все"],
    ["dossier",       "Форейджер"],
    ["monitoring",    "Мониторинг"],
    ["signal_created","Сигналы"],
    ["resolved",      "Завершённые"],
  ];
  const filtered = typeFilter === "ALL" ? diary : diary.filter((e) => e.type === typeFilter);

  return (
    <section className="diary-view">
      <div className="diary-head">
        <span>REASONING DIARY</span>
        <h1>Дневник мышления</h1>
        <p>Хронология решений — от гипотезы форейджера до резолюции. Каждая запись — реальный вывод модели или оператора. Кликните на название рынка чтобы открыть позицию.</p>
      </div>
      <div className="diary-filters">
        {filterOpts.map(([id, label]) => (
          <button key={id} className={typeFilter === id ? "active" : ""} onClick={() => setTypeFilter(id)}>
            {label}
          </button>
        ))}
        <span className="diary-count">{filtered.length} записей</span>
      </div>
      <div className="diary-feed">
        {filtered.map((entry, i) => (
          <DiaryEntryCard
            key={`${entry.signalId}-${entry.timestamp}-${i}`}
            entry={entry}
            onSignalSelect={onSignalSelect}
          />
        ))}
        {!filtered.length && <div className="empty-state">Нет записей выбранного типа.</div>}
      </div>
    </section>
  );
}

function DiaryEntryCard({ entry, onSignalSelect }) {
  const [expanded, setExpanded] = useState(false);
  const hasDetail =
    (entry.hypotheses?.length > 0) ||
    (entry.killCriteria?.length > 0) ||
    (entry.scenarios?.length > 0);
  const isResolved = entry.type === "resolved";
  const headingTone = isResolved ? (entry.heading === "WON" ? "positive" : "negative") : "";

  return (
    <article className="diary-card">
      <div className="diary-card-head">
        <time>{entry.date}</time>
        <DiaryTypeBadge type={entry.type} />
        <button className="diary-signal-link" onClick={() => onSignalSelect(entry.signalId)}>
          {entry.signalTitle}
        </button>
      </div>

      <div className="diary-card-body">
        {entry.type === "monitoring" ? (
          <h3 className="diary-heading">
            <span className={`monitor-badge ${entry.heading === "EXIT" ? "exit" : entry.heading === "REVIEW" ? "review" : "hold"}`}>
              {entry.heading}
            </span>
          </h3>
        ) : (
          <h3 className={`diary-heading ${headingTone}`}>{entry.heading}</h3>
        )}
        {entry.body && (
          <p className="diary-body-text">
            {expanded || entry.body.length <= 260 ? entry.body : entry.body.slice(0, 260) + "…"}
          </p>
        )}
      </div>

      {hasDetail && expanded && (
        <div className="diary-detail">
          {entry.hypotheses?.length > 0 && (
            <div className="diary-hyps">
              {entry.hypotheses.map((h, i) => (
                <div key={i} className={`diary-hyp ${(h.direction || "").toLowerCase()}`}>
                  <div>
                    <span>{h.direction}</span>
                    <strong>{h.title}</strong>
                    {h.confidence > 0 && <em>{Math.round(h.confidence * 100)}%</em>}
                  </div>
                  <p>{h.text}</p>
                </div>
              ))}
            </div>
          )}
          {entry.killCriteria?.length > 0 && (
            <div className="diary-kc">
              <h4>Kill criteria</h4>
              {entry.killCriteria.map((kc, i) => (
                <div key={i} className="diary-kc-item">✗ {kc}</div>
              ))}
            </div>
          )}
          {entry.scenarios?.length > 0 && (
            <div className="diary-scenarios">
              <h4>Сценарии</h4>
              {entry.scenarios.map((s, i) => (
                <div key={i} className="diary-scenario-item">{s}</div>
              ))}
            </div>
          )}
        </div>
      )}

      {(hasDetail || entry.body?.length > 260) && (
        <button className="diary-expand" onClick={() => setExpanded((v) => !v)}>
          {expanded ? "Свернуть" : "Развернуть детали"}
        </button>
      )}
    </article>
  );
}

function ReasoningChain({ entries }) {
  return (
    <div className="reasoning-chain">
      {entries.map((entry, i) => {
        const isLast = i === entries.length - 1;
        const isResolved = entry.type === "resolved";
        const headingTone = isResolved ? (entry.heading === "WON" ? "positive" : "negative") : "";
        return (
          <div key={i} className={`chain-node ${entry.type}`}>
            {!isLast && <div className="chain-line" />}
            <div className="chain-dot" />
            <div className="chain-content">
              <div className="chain-meta">
                <time>{entry.date}</time>
                <DiaryTypeBadge type={entry.type} />
              </div>
              {entry.type === "monitoring" ? (
                <h4 className="chain-heading">
                  <span className={`monitor-badge ${entry.heading === "EXIT" ? "exit" : entry.heading === "REVIEW" ? "review" : "hold"}`}>
                    {entry.heading}
                  </span>
                </h4>
              ) : (
                <h4 className={`chain-heading ${headingTone}`}>{entry.heading}</h4>
              )}
              {entry.body && (
                <p className="chain-body">{entry.body.length > 300 ? entry.body.slice(0, 300) + "…" : entry.body}</p>
              )}
              {entry.hypotheses?.length > 0 && (
                <div className="chain-hyps">
                  {entry.hypotheses.slice(0, 3).map((h, j) => (
                    <div key={j} className={`chain-hyp-chip ${(h.direction || "").toLowerCase()}`}>
                      <span>{h.direction}</span> {h.title}
                    </div>
                  ))}
                </div>
              )}
              {entry.killCriteria?.length > 0 && (
                <div className="chain-kc-list">
                  {entry.killCriteria.slice(0, 2).map((kc, j) => (
                    <div key={j} className="chain-kc">✗ {kc}</div>
                  ))}
                </div>
              )}
            </div>
          </div>
        );
      })}
    </div>
  );
}

function Sparkline({ data, entryYes, currentYes }) {
  const W = 640;
  const H = 120;
  const PAD = 8;
  const points = data.map((d) => d.p);
  const min = Math.min(...points, entryYes || 1, 0);
  const max = Math.max(...points, entryYes || 0, 1);
  const range = max - min || 1;
  const n = data.length;
  const x = (i) => PAD + (i / (n - 1)) * (W - 2 * PAD);
  const y = (p) => H - PAD - ((p - min) / range) * (H - 2 * PAD);
  const path = data.map((d, i) => `${i === 0 ? "M" : "L"}${x(i).toFixed(1)},${y(d.p).toFixed(1)}`).join(" ");
  const areaPath = `${path} L${x(n - 1).toFixed(1)},${H - PAD} L${x(0).toFixed(1)},${H - PAD} Z`;
  const last = data[n - 1];
  const trend = last.p >= data[0].p;
  const stroke = trend ? "var(--olive)" : "var(--rust)";

  return (
    <div className="sparkline">
      <svg viewBox={`0 0 ${W} ${H}`} preserveAspectRatio="none" className="spark-svg">
        {entryYes != null && (
          <line
            x1={PAD} x2={W - PAD}
            y1={y(entryYes)} y2={y(entryYes)}
            className="spark-entry-line"
            strokeDasharray="4 4"
          />
        )}
        <path d={areaPath} fill={stroke} opacity="0.07" stroke="none" />
        <path d={path} fill="none" stroke={stroke} strokeWidth="2" />
        <circle cx={x(n - 1)} cy={y(last.p)} r="3.5" fill={stroke} />
      </svg>
      <div className="spark-legend">
        <span><em>Старт</em> {fmtPct(data[0].p)}</span>
        {entryYes != null && <span className="entry"><em>Вход (YES-экв.)</em> {fmtPct(entryYes)}</span>}
        <span className={trend ? "positive" : "negative"}><em>Сейчас</em> {fmtPct(currentYes ?? last.p)}</span>
        <span><em>Точек</em> {n} · {data[0].t} → {last.t}</span>
      </div>
    </div>
  );
}

function SmartMoneyPanel({ sm, side }) {
  const yesShare = sm.yesShare != null ? sm.yesShare : 0.5;
  const agrees = sm.agreesWithUs;
  return (
    <div className="smart-money">
      <div className="sm-bar">
        <span className="sm-yes" style={{ width: `${yesShare * 100}%` }}>YES {Math.round(yesShare * 100)}%</span>
        <span className="sm-no" style={{ width: `${(1 - yesShare) * 100}%` }}>NO {Math.round((1 - yesShare) * 100)}%</span>
      </div>
      <div className="sm-stats">
        <div><span>Кошельков</span><strong>{sm.walletCount}</strong></div>
        <div><span>Объём</span><strong>{fmtUsd(sm.totalUsd, true)}</strong></div>
        <div><span>Доминирует</span><strong>{sm.dominantSide}</strong></div>
        <div>
          <span>Timing α</span>
          <strong className={sm.avgTimingAlpha > 0 ? "positive" : sm.avgTimingAlpha < 0 ? "negative" : ""}>
            {sm.avgTimingAlpha != null ? sm.avgTimingAlpha.toFixed(3) : "—"}
          </strong>
        </div>
      </div>
      {agrees != null && (
        <p className={`sm-verdict ${agrees ? "positive" : "negative"}`}>
          {agrees
            ? `Умные деньги на нашей стороне (${side}) — подтверждает тезис.`
            : `Умные деньги против нашей стороны (мы ${side}, они ${sm.dominantSide}) — требует проверки.`}
        </p>
      )}
    </div>
  );
}

function AnalyticsView({ analytics, summary }) {
  const cal = analytics.calibration;
  const brier = analytics.brier;
  const exposure = analytics.exposure || {};
  const catEntries = Object.entries(exposure.byCategory || {});
  const archEntries = Object.entries(exposure.byArchetype || {});
  const maxCat = Math.max(1, ...catEntries.map(([, v]) => v));
  const maxArch = Math.max(1, ...archEntries.map(([, v]) => v));

  return (
    <section className="analytics-view">
      <div className="diary-head">
        <span>PORTFOLIO ANALYTICS</span>
        <h1>Аналитика и калибровка</h1>
        <p>Насколько хорошо модель откалибрована, бьём ли мы рынок по Brier score, и как распределён капитал по категориям и архетипам edge.</p>
      </div>

      <div className="analytics-grid">
        <div className="analytics-panel">
          <h2>Калибровка вероятностей</h2>
          {cal && cal.buckets?.length ? (
            <>
              <div className="calib-chart">
                {cal.buckets.map((b) => (
                  <div className="calib-bar-group" key={b.bucket}>
                    <div className="calib-bars">
                      <div className="calib-bar predicted" style={{ height: `${b.predicted * 100}%` }} title={`Предсказано ${Math.round(b.predicted * 100)}%`} />
                      <div className="calib-bar actual" style={{ height: `${b.actual * 100}%` }} title={`Факт ${Math.round(b.actual * 100)}% (n=${b.count})`} />
                    </div>
                    <span className="calib-label">{Math.round(b.bucket * 100)}%</span>
                  </div>
                ))}
              </div>
              <div className="calib-legend">
                <span><i className="dot-predicted" /> Предсказано</span>
                <span><i className="dot-actual" /> Факт</span>
              </div>
              <p className={`calib-verdict ${cal.wellCalibrated ? "positive" : cal.overconfident ? "negative" : ""}`}>
                {cal.active
                  ? cal.wellCalibrated
                    ? `Хорошо откалибровано (Δ ${cal.averageDelta}). ${cal.resolved} резолюций.`
                    : cal.overconfident
                      ? `Переуверенность: факт ниже прогноза на ${Math.abs(cal.averageDelta)}. ${cal.resolved} резолюций.`
                      : `Недоуверенность (Δ ${cal.averageDelta}). ${cal.resolved} резолюций.`
                  : `Недостаточно данных: ${cal.resolved} резолюций, нужно больше для активной калибровки.`}
              </p>
            </>
          ) : (
            <p className="empty-inline">Нет данных калибровки.</p>
          )}
        </div>

        <div className="analytics-panel">
          <h2>Brier score vs рынок</h2>
          {brier && brier.resolved > 0 ? (
            <div className="brier-stats">
              <div className="brier-big">
                <span>Бьём рынок</span>
                <strong>{brier.beatMarketCount}/{brier.resolved}</strong>
              </div>
              <div className="brier-row">
                <span>Наш средний Brier</span>
                <strong>{brier.ourAvgBrier ?? "—"}</strong>
              </div>
              <div className="brier-row">
                <span>Рынок средний Brier</span>
                <strong>{brier.marketAvgBrier ?? "—"}</strong>
              </div>
              {Object.keys(brier.errorTypes || {}).length > 0 && (
                <div className="brier-errors">
                  <h4>Типы ошибок</h4>
                  {Object.entries(brier.errorTypes).map(([k, v]) => (
                    <div key={k} className="brier-error-item"><span>{k}</span><strong>{v}</strong></div>
                  ))}
                </div>
              )}
              <p className="calib-verdict">Brier ниже = точнее. Меньше рыночного = у нас есть edge.</p>
            </div>
          ) : (
            <p className="empty-inline">Нет резолюций с Brier score.</p>
          )}
        </div>
      </div>

      <div className="analytics-grid">
        <div className="analytics-panel">
          <h2>Экспозиция по категориям</h2>
          <div className="exposure-bars">
            {catEntries.map(([cat, usd]) => (
              <div className="exposure-row" key={cat}>
                <span className="exposure-label">{categoryLabel(cat)}</span>
                <div className="exposure-track">
                  <div className="exposure-fill" style={{ width: `${(usd / maxCat) * 100}%` }} />
                </div>
                <span className="exposure-val">{fmtUsd(usd, true)}</span>
              </div>
            ))}
            {!catEntries.length && <p className="empty-inline">Нет открытых позиций.</p>}
          </div>
        </div>

        <div className="analytics-panel">
          <h2>Экспозиция по архетипам edge</h2>
          <div className="exposure-bars">
            {archEntries.map(([arch, usd]) => (
              <div className="exposure-row" key={arch}>
                <span className="exposure-label">{arch}</span>
                <div className="exposure-track">
                  <div className="exposure-fill gold" style={{ width: `${(usd / maxArch) * 100}%` }} />
                </div>
                <span className="exposure-val">{fmtUsd(usd, true)}</span>
              </div>
            ))}
            {!archEntries.length && <p className="empty-inline">Нет открытых позиций.</p>}
          </div>
        </div>
      </div>
    </section>
  );
}

function LiveBadge({ isLive, lastUpdated }) {
  if (!lastUpdated) return null;
  const time = lastUpdated.toLocaleTimeString("ru-RU", { hour: "2-digit", minute: "2-digit", second: "2-digit" });
  return (
    <span className={`live-badge ${isLive ? "live" : "stale"}`}>
      <span className="live-dot" />
      {isLive ? "LIVE" : "Offline"} {time}
    </span>
  );
}

export default App;
