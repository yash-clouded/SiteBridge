# SiteBridge

**The intelligence layer between field reporting and the schedule system of record.**

Construction field reports arrive as typed notes, voice transcripts, DPR spreadsheets and
PDFs — usually in whatever language the supervisor speaks. SiteBridge turns them into
structured, verified execution events, maps them onto the WBS, scores its own confidence,
routes the uncertain ones to a human, and rolls the approved reality up onto a dashboard.

Nothing is invented: a value the report does not state stays `null`, a rule that cannot be
decided stays `unknown`, and every number on a dashboard can be traced back to the exact
sentence it came from.

```
field note (any language)  ─►  translate  ─►  extract  ─►  retrieve  ─►  verify
        raw_text kept verbatim      │              │             │           │
                                    ▼              ▼             ▼           ▼
                            English rendering   1 event/     WBS top-k    rules +
                            stored beside it    report       candidates   confidence
                                                                     │
                                     approve (PLANNER)  ◄── review queue ◄──┘
                                              │
                                              ▼
                                   actuals on activities ─► roll-up ─► dashboard
```

---

## Stack

| Layer     | Tech                                                        |
| --------- | ----------------------------------------------------------- |
| Frontend  | Next.js 16 (App Router), React 19, Tailwind 4, TypeScript    |
| Backend   | FastAPI, SQLAlchemy 2, Pydantic Settings, PyJWT, bcrypt      |
| Database  | PostgreSQL 16 + `pgvector` (Docker image `pgvector/pgvector:pg16`) |
| AI rungs  | OpenAI-compatible chat + embeddings (NVIDIA endpoints today), heuristic pattern extractor, local hash embeddings |
| Translate | Sarvam (`/text-lid` + `/translate`) — optional, never blocking |

```
SiteBridge/
├── docker-compose.yml      # Postgres 16 + pgvector
├── backend/                # FastAPI app
│   ├── app/
│   │   ├── routers/        # auth, intake, projects, matching, review, rollup, status
│   │   ├── services/       # extraction, heuristic, llm, retrieval, verification,
│   │   │                   # confidence, pipeline, rollup, translate, embeddings, importer
│   │   ├── models.py       # users, projects, wbs, reports, events, candidates, actuals
│   │   ├── schemas.py      # request/response contracts
│   │   └── db.py           # engine + lightweight schema migration (no Alembic)
│   ├── seed.py             # demo project (NPU) + one user per role
│   ├── example.env         # every setting, documented (copy to .env)
│   └── tests/              # 99 pytest tests, all offline
├── frontend/
│   └── src/app/(app)/      # login, submit, queue, dashboard, projects/[id]
└── demo/schedule_sample.csv
```

---

## Prerequisites

* Docker (Postgres only — nothing else is containerised)
* [uv](https://docs.astral.sh/uv/) for the Python backend
* Node 20+ for the frontend
* An OpenAI-compatible chat API key (NVIDIA, OpenAI, …) — *optional*, the heuristic rung works without one
* A Sarvam API key — *optional*, only for multilingual intake

---

## Setup (first run)

```bash
# 1. database (Postgres 16 + pgvector)
docker compose up -d

# 2. backend config — copy the template ONLY if .env does not exist yet
cd backend
[ -f .env ] || cp example.env .env   # never overwrite an existing .env
#    put your keys in .env: LLM_API_KEY, EMBEDDING_* (if used), SARVAM_API_KEY
#    ⚠ `cp example.env .env` on a file that already has your keys silently
#    resets them: extraction drops to the "Pattern (no LLM)" rung and
#    translation reports "SARVAM_API_KEY is not set".

# 3. install + create schema + seed the demo project (NPU) and demo users
uv sync
uv run python seed.py

# 4. frontend deps
cd ../frontend && npm install
```

### Demo accounts (role-based; password `demo1234`)

| Role     | Email                       | Lands on  | Can do                                    |
| -------- | --------------------------- | --------- | ----------------------------------------- |
| FIELD    | `field@sitebridge.dev`      | `/submit` | submit reports, read own outcomes         |
| PLANNER  | `planner@sitebridge.dev`    | `/queue`  | review, approve, reject, re-embed         |
| PM       | `pm@sitebridge.dev`         | `/dashboard` | read-only roll-up, KPIs, WBS coverage  |

> Roles grant functions, never WBS levels. Test users use `*@test.local` with password
> `test-pass-123` and are cleaned up after every test run.

---

## Run it

**Backend** (port 8000) — from `backend/`:

```bash
uv run uvicorn app.main:app --port 8000
```

**Frontend** (port 3000) — from `frontend/`:

```bash
npm run dev
```

Open <http://localhost:3000> and sign in with any demo account.
API docs: <http://localhost:8000/docs> · runtime state: `GET /api/status`.

---

## What to test (use cases)

Each case below is a self-contained story you can walk in the browser (or with `curl`).

### 1. Typed report → extraction → review → approval → dashboard (the happy path)

1. Sign in as **FIELD** → `/submit`, pick project `NPU`, type something explicit:
   `Area B cable tray installation is 60 percent complete.`
2. In **My submissions** the row shows `Extraction = <model>` and `Outcome = Awaiting review`.
3. Sign in as **PLANNER** → `/queue`: the report is there with a top candidate, a confidence
   band and rule results (`pass` / `fail` / `unknown`).
4. Expand it: extracted fields (progress 60, discipline, location), the raw evidence, and
   `Extracted by` (model name or `Pattern match (no LLM)`).
5. **Approve** the top candidate → the row flips to `Approved`.
6. Sign in as **PM** → `/dashboard`: KPIs, coverage, approvals-per-day and the WBS tab now
   include this report; the activity shows **reported** progress.

### 2. Multilingual intake (Sarvam)

1. FIELD → `/submit`, **Language = Auto-detect**, paste Hindi:
   `एरिया बी में केबल ट्रे इंस्टॉलेशन 60 प्रतिशत पूर्ण है।`
2. The history row shows `hi → en`; open the queue entry: **Input (translated)** shows the
   English text extraction read, **Raw evidence** below keeps the Hindi verbatim.
3. Repeat with **Language = Tamil** and a Tamil sentence → `ta → en`.
4. Submit English text → chip reads `en · English`, nothing is translated (`skipped`).
5. Unset `SARVAM_API_KEY` and restart → chips show `—`, `GET /api/status` degrades with
   *“SARVAM_API_KEY is not set — reports are extracted as submitted”*. Submissions still work.

### 3. File intake with evidence pointers

1. FIELD → **Upload file** tab: a `.csv`/`.xlsx` DPR, a `.txt`, or a text-based `.pdf`.
2. The **Evidence** column reads `sheet · rows 1–14`, `pages 1–3` or `512 chars` — the
   pointer that ties every downstream number back to its origin.

### 4. Confidence and rules

1. PLANNER → `/queue`: compare bands — `high` ≥ 0.75, `medium` ≥ 0.5, below that `low`
   (labelled `Needs manual mapping`).
2. Final score = `0.6 × retrieval + 0.4 × rules`; rules that cannot be decided (`unknown`)
   are excluded instead of counting as failures.
3. Submit a deliberately vague report (`Work continued.`) → no rules can be decided, so the
   score falls back to retrieval alone and the queue sends it to manual mapping.

### 5. Roles and permissions

| Try                                           | Expect                          |
| --------------------------------------------- | ------------------------------- |
| FIELD opens `/queue` (or calls `GET /api/queue`) | sidebar hides it; API answers **403** |
| FIELD opens `/dashboard`                      | page says it is the PM’s screen  |
| FIELD reads `GET /api/reports`                | only their own submissions       |
| FIELD calls `POST /api/reports/{id}/approve`  | **403** (PLANNER-only)           |
| PM opens `/queue`                             | read-only — no approve/reject buttons |
| A report id that does not exist               | **404**                          |

### 6. The fallback ladder (Phases 11)

1. `GET /api/status` — `llm`, `embeddings`, `extraction`, `translation`, plus `degraded[]`.
2. Remove `LLM_API_KEY` (or point `LLM_BASE_URL` at nothing) → new reports extract with the
   **heuristic** rung: history shows `Pattern (no LLM)`, event `model = heuristic-v1`.
3. Add `LLM_FALLBACK_BASE_URL` (e.g. `http://localhost:11434/v1`) → the ladder becomes
   primary → fallback, and status reports both rungs.
4. Clear the embedding key → embeddings drop to local hash vectors and status warns
   *“lexical, not semantic”* — you never silently mix two vector spaces.

### 7. Rejection and reopening

1. PLANNER rejects a candidate → it becomes `Rejected`, and that report’s actuals are
   cleared (never another report’s).
2. **Reopen** → back to `PENDING` with actuals cleared only where they came from this report.
3. One approved candidate per event, ever — approving a second one is rejected with **409**.

### 8. Schedule roll-up honesty

* An activity with **no** approved report is **not reported**, not `0%`.
* Average progress averages only the activities that actually state progress.
* `by_wbs` groups by the first level under the project root, so a WBS segment never shows a
  misleading `0.0`.

---

## Configuration (`backend/example.env`)

Copy to `backend/.env`. **Never commit `.env` — it is gitignored and holds real keys.**

| Setting | Default | Meaning |
| --- | --- | --- |
| `DATABASE_URL` | `postgresql+psycopg://sitebridge:sitebridge@localhost:5432/sitebridge` | Postgres + pgvector |
| `JWT_SECRET` / `JWT_ALGORITHM` / `JWT_EXPIRE_MINUTES` | dev value / HS256 / 720 | auth |
| `LLM_BASE_URL`, `LLM_API_KEY`, `LLM_MODEL` | — / — / — | primary chat rung |
| `LLM_FALLBACK_BASE_URL`, `LLM_FALLBACK_API_KEY`, `LLM_FALLBACK_MODEL` | unset | second rung, tried only when the first fails |
| `LLM_JSON_MODE`, `LLM_TEMPERATURE`, `LLM_TIMEOUT_SECONDS` | true / 0 / 60 | chat call behaviour |
| `EXTRACTION_FALLBACK` | `heuristic` | what runs when no endpoint answers: `heuristic` \| `off` |
| `AUTO_EXTRACT_ON_INTAKE` | `true` | extract immediately on submission |
| `EMBEDDING_PROVIDER` | `local` | `local` \| `openai` \| `auto` |
| `EMBEDDING_MODEL` / `EMBEDDING_DIM` / `EMBEDDING_INPUT_TYPE` | — | must match your provider |
| `EMBEDDING_FALLBACK_LOCAL` | `true` | fall back only while the index is still local |
| `RETRIEVAL_TOP_K` | `5` | candidates considered |
| `SARVAM_API_KEY` | *(empty)* | Sarvam subscription key — empty disables translation |
| `SARVAM_TRANSLATE_MODEL` | `sarvam-translate:v1` | `sarvam-translate:v1` (23 languages) \| `mayura:v1` (11) |
| `SARVAM_TARGET_LANGUAGE` | `en-IN` | language the pipeline always reads |
| `TRANSLATE_ON_INTAKE` | `true` | detect/translate before extraction |
| `TRANSLATE_TIMEOUT_SECONDS` | `30` | per HTTP call |

Schema changes are applied automatically at startup (`_add_missing_columns` in
`backend/app/db.py`) — no Alembic. Adding a column to a model is enough.

---

## Tests

```bash
cd backend && uv run pytest -q     # 99 tests, ~2 min, fully offline
cd frontend && npx tsc --noEmit && npm run lint && npm run build
```

The suite clears every API key (autouse `_offline` fixture), so it never calls a live
endpoint; translation tests stub `translate._post`, extraction tests stub
`extraction.chat_json`. Test data uses `*@test.local` users and `TEST*` project codes and is
removed after each test.

---

## API map (most-used)

| Method & path | Who | Purpose |
| --- | --- | --- |
| `POST /api/auth/login` | anyone | JWT for a role |
| `POST /api/reports/text` | FIELD | typed / voice / DPR note (`language` optional) |
| `POST /api/reports/file` | FIELD | PDF / Excel / txt with evidence pointer |
| `GET /api/reports` | any | FIELD: own reports; others: all (Phase 10 outcomes) |
| `POST /api/reports/{id}/process` | FIELD/PLANNER | run (or re-run) extraction |
| `GET /api/queue` | PLANNER, PM | work list: report + top candidate + band |
| `GET /api/reports/{id}/match` | PLANNER, PM | full detail: candidates, rules, confidence |
| `POST /api/reports/{id}/approve` \| `/reject` \| `/reopen` | PLANNER | decision (409 on a second approval) |
| `GET /api/projects/{id}/rollup` | any | coverage, avg progress, WBS segments, series |
| `GET /api/projects/{id}/wbs` | any | WBS tree |
| `POST /api/projects/{id}/embed?force=` | PLANNER | rebuild the vector index |
| `GET /api/status` | any | resolved modes + `degraded[]` (never keys) |

---

## Start here (copy/paste)

```bash
# one-time
docker compose up -d
cd backend && [ -f .env ] || cp example.env .env   # keep existing .env if present
cd backend && uv sync && uv run python seed.py && cd ..
cd frontend && npm install && cd ..

# terminal 1 — API on :8000
cd backend && uv run uvicorn app.main:app --port 8000

# terminal 2 — app on :3000
cd frontend && npm run dev
```

Then open <http://localhost:3000> and sign in as `field@sitebridge.dev` / `demo1234`
(or `planner@…` / `pm@…`).

**First five minutes:** submit a typed report as FIELD → review it in `/queue` as PLANNER →
approve → open `/dashboard` as PM → repeat the same report in Hindi with
**Language = Auto-detect** and watch the `hi → en` chip and the *Input (translated)* panel.
