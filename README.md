# 🤖 AI DevOps Copilot (AIOps)

**Root-Cause Analysis, Automated Runbooks, and Cost-Aware Incident Response for Modern Cloud Infrastructure**

A portfolio project that builds a small, working version of what enterprise tools like Datadog, PagerDuty, and Dynatrace sell: an AI-assisted system that watches a set of services, detects when something is wrong, figures out *why*, drafts a fix, and can apply that fix in a sandboxed way — while estimating the financial cost of the problem.

---

## Architecture

```
                          ┌──────────────────────────────────────────────┐
                          │                 copilot (this repo's brain)  │
   load ──► order-service │  detector ──► correlation ──► AI diagnosis   │
              │           │      │            (deploys)    (multi-model) │
              ▼           │      ▼                                       │
         payment-service  │  dependency graph (DFS/BFS) · cost model     │
              │           │  fractional knapsack · clustering            │
              ▼           │  sandboxed actions (Docker SDK)              │
        notification-svc  └──────────────┬───────────────────────────────┘
                                         │
   Prometheus ◄── scrape ── services     ▼
        │                          dashboard :8000
        └──► Grafana :3000
```

**Service dependency graph** (used for root-cause / impact analysis):

```
API Gateway
 ├── Auth Service
 └── Order Service
      ├── Payment Service ──► Notification Service
      └── Inventory Service ──► Notification Service
```

## Features

| Feature | Where |
|---|---|
| Detection (latency + error-rate + availability, auto-resolution) | `copilot/detector.py` |
| Alert ↔ deploy correlation with confidence % | `copilot/correlation.py` |
| Root-cause tracing (DFS) / blast radius (BFS) | `copilot/dependency_graph.py` |
| Incident prioritization (Greedy / fractional knapsack) | `copilot/prioritizer.py` |
| Cost-aware recommendations (FinOps) | `copilot/cost.py` |
| Alert-fatigue reducer (cluster connected alerts) | `copilot/clustering.py` |
| Auto-drafted runbooks + one-click safe actions | `copilot/runbook.py`, `copilot/actions.py` |
| Auto-generated postmortems | `copilot/postmortem.py` |
| Chaos testing (runtime fault injection) | `*/chaos/*` endpoints |
| Multi-provider AI (Claude / GLM / OpenAI / Ollama) | `copilot/ai_client.py` |

**Runs without any AI key** — a deterministic rule-based engine drafts diagnoses and runbooks; add a key to `.env` and AI reasoning activates instantly (the active engine is shown on the dashboard).

## Quick start

Prereqs: Docker Desktop, Python 3.

```bash
# 1. (optional but recommended) configure AI — skip for rule-based mode
cp .env.example .env        # then paste an API key for your provider

# 2. start the whole stack
docker compose up --build -d

# 3. open the dashboards
open http://localhost:8000    # AIOps Copilot (incidents, runbooks, actions)
open http://localhost:3000    # Grafana (admin/admin) — auto-provisioned
open http://localhost:9090    # Prometheus
```

## 60-second demo

```bash
./scripts/demo.sh
```

or by hand:

1. Open http://localhost:8000 → **💥 Inject slowness** (chaos on payment-service).
2. Within ~20–30 s the copilot opens an incident: root cause, confidence %, deploy correlation, blast radius, cost impact, and a drafted runbook.
3. Click **⏪ Rollback** on the incident card → chaos cleared, service restarts.
4. Within 2 checks the incident auto-resolves and a **postmortem** is generated.

## AI providers (`AI_PROVIDER` in `.env`)

| Provider | Key source | Default model |
|---|---|---|
| `anthropic` | https://console.anthropic.com | `claude-sonnet-4-5` |
| `zai` | https://z.ai/manage-apikey/apikey-list | `glm-4.6` |
| `openai` | https://platform.openai.com | `gpt-4o-mini` |
| `ollama` | local (`ollama pull llama3.2:3b`) | `llama3.2:3b` |

Model names are all overridable (`ANTHROPIC_MODEL`, `ZAI_MODEL`, …).

## Algorithm applications

| Task | Algorithm |
|---|---|
| "Why did this happen?" — trace symptom to origin | **DFS** (deepest causal chain) |
| "What else will this affect?" — blast radius | **BFS** (reverse edges, layer by layer) |
| Which incidents to fix first with limited time | **Greedy / fractional knapsack** ($-impact per fix-minute) |
| Safe restart/rollback ordering | **DFS-based topological sort** |
| Grouping related alerts into one response | **BFS connectivity** on the dependency graph |
| Flagging circular service dependencies | **DFS cycle detection** |

## Sandboxed actions

Remediation buttons only ever touch this project's two containers (hard allow-list in `copilot/actions.py`):

- **Restart** — bounce the container (Docker SDK).
- **Rollback** — clear runtime chaos/config flags over HTTP, then restart.
- **Isolate** — stop the container to contain blast radius.
- **Resume** — start an isolated container again.

No production systems, no other containers — safe to run anywhere.

Where there is no Docker socket (the Render bundle), **Restart / Isolate / Resume
are refused with an on-screen explanation** and only **Rollback** acts, clearing
chaos flags over HTTP. The UI marks this as `hosted actions: rollback only` so the
limitation is never hidden.

## Cost model assumptions (tweak in `.env`)

- Latency incidents: sustained slowness ≈ accidental CPU over-provisioning → extra vCPU-hours × `$0.0446/vCPU-hr`.
- Error incidents: failed transactions × `avg order value $42` = revenue-at-risk.
- All numbers are documented demo estimates, not a cloud bill.

## Deploy to Render (public URL)

`docker-compose.yml` stays the full local deployment. For a shareable public URL,
[`render.yaml`](render.yaml) deploys an **all-in-one bundle** — Prometheus, both
services, a traffic generator and the copilot in one container behind a single
port (`deploy/allinone/`), because Render cannot run Compose, gives containers no
Docker socket, and its free plan offers only web services with no private
networking between them.

```bash
# one-time: connect the repo at https://dashboard.render.com → New + → Blueprint
```

What works there: detection, DFS root-cause path, BFS blast radius, deploy
correlation, cost model, knapsack response plan, clustering, runbooks,
postmortems, chaos injection, the proxied Prometheus query UI, and **Rollback**
(clears chaos flags over HTTP). What needs local Docker: **restart / isolate /
resume**, and Grafana — the dashboard labels this honestly in hosted mode.

👉 Full step-by-step guide, including a pre-demo warm-up command and the free-tier
behaviour to expect: **[DEPLOY_RENDER.md](DEPLOY_RENDER.md)**

## Local development (no Docker for the copilot)

```bash
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
# services + monitoring still come from docker compose; then:
python -m dashboard.app           # copilot on :8000, localhost URLs
./venv/bin/python -m pytest tests/ -v
```

## Testing

```bash
./venv/bin/python -m pytest tests/ -v     # 39 unit tests (algorithms, store, actions, hosted mode)
./venv/bin/python scripts/e2e_test.py     # 62 live checks against the running stack
```

## Project layout

```
services/          order-service, payment-service (Flask + Prometheus + chaos endpoints)
monitoring/        prometheus.yml, Grafana auto-provisioning + dashboard
copilot/           detection, correlation, graph algorithms, cost, actions, AI client
dashboard/         Flask UI (incidents, runbooks, chaos triggers, deploy recorder)
data/              incidents.json (runtime), deploys.json (seeded history)
tests/             pytest suite for the algorithm layer
deploy/allinone/   single-container Render bundle (Dockerfile, supervisord, configs)
render.yaml        Render Blueprint for the all-in-one deployment
DEPLOY_RENDER.md   step-by-step hosted deployment guide
scripts/demo.sh    end-to-end chaos → detect → fix demo
scripts/e2e_test.py  62-check live test suite
```

## Roadmap

- Slack / chat-ops notifications
- Real deploy-source integration (GitHub Actions webhook instead of seeded deploys)
- Severity scoring by business criticality
- Kubernetes mode (actions via k8s API instead of Docker SDK)
