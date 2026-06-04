# Forager

Forager is the cognitive foraging layer upstream of Signal.

It does not decide trades. It does not emit Signal positions. It searches for weak signals, contradictions, anomalous entities, unresolved threads, and research packets that Signal can later judge.

```text
Forager discovers.
Signal decides.
```

## Phase 0

Implemented:

- research threads;
- deterministic query mutation across non-obvious research lenses;
- source registration;
- source weirdness scoring;
- anomaly creation for unusual sources;
- hypothesis registration;
- research packet creation for Signal handoff;
- FastAPI skeleton;
- core tests.

## Phase 1

Implemented:

- `source_raw_items` as a layer before promoted sources;
- search adapter interface;
- Brave Search adapter via `BRAVE_SEARCH_API_KEY`;
- deterministic static adapter for tests;
- search burst workflow;
- SQLite persistence store;
- Signal bridge packet export;
- API endpoints for search burst and bridge.

## Phase 2

Implemented:

- crawler adapter interface;
- simple HTTP crawler;
- deterministic static crawler for tests;
- document persistence;
- rule-based claim extraction;
- rule-based entity and mention extraction;
- document-level anomaly creation;
- bridge blocker for uncrawled packets.

## Phase 3

Implemented:

- entity relation graph from document co-mentions;
- claim relation graph from shared topic language and contradiction stance;
- graph expansion queries from extracted entities;
- local-language research profile;
- SQLite persistence for graph relations and language profiles;
- API endpoints for graph expansion and local-language profiling.

## Phase 4

Implemented:

- recursive graph search with bounded query budget;
- graph expansion queries can now feed new search bursts;
- translation queue for non-English documents;
- SQLite persistence for translation queue;
- API endpoints for recursive graph search and translation queue.

The current chain is:

```text
search result -> source_raw_item -> promoted source -> crawled document -> claims/entities/mentions -> graph relations -> recursive search -> translation queue -> anomalies -> packet -> Signal validation
```

## Run Tests

```bash
pytest -q forager
```

## API

In-memory mode:

```bash
uvicorn apps.api.main:app --app-dir forager
```

SQLite mode:

```bash
set FORAGER_DB_PATH=C:\Signal\data\forager.sqlite3
uvicorn apps.api.main:app --app-dir forager
```

Live search mode:

```bash
set TAVILY_API_KEY=your_key_here
set BRAVE_SEARCH_API_KEY=optional_second_key
set FORAGER_DB_PATH=C:\Signal\data\forager.sqlite3
uvicorn apps.api.main:app --app-dir forager
```

Forager searches through a composite adapter: Tavily, Brave, deterministic official-source seeds, Wikipedia, then GDELT. If paid keys are missing, it still keeps a degraded no-key discovery path instead of falling into a null adapter.

Endpoints:

- `GET /health`
- `POST /research/start`
- `POST /threads/{thread_id}/search-burst`
- `POST /threads/{thread_id}/crawl-sources`
- `POST /threads/{thread_id}/expand-graph`
- `POST /threads/{thread_id}/recursive-graph-search`
- `POST /threads/{thread_id}/local-language-profile`
- `POST /threads/{thread_id}/translation-queue`
- `GET /threads/{thread_id}`
- `POST /threads/{thread_id}/sources`
- `POST /threads/{thread_id}/hypotheses`
- `POST /threads/{thread_id}/packet`
- `GET /threads/{thread_id}/signal-bridge`
- `GET /signal/markets/{market_id}/latest-packet`

## Next Phase

- actual translation execution and translated document extraction;
- richer crawler adapter: Firecrawl or Playwright;
- PDF extraction;
- evidence draft layer;
- contradiction cluster scoring;
- graph dashboard;
- swarm orchestration.
