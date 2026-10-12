# Deploying the AIOps Copilot to Render

This deploys the project to [Render](https://render.com) as **one all-in-one web
service** and gives you a public URL you can share. The full 6-container
`docker-compose.yml` stack stays the local deployment.

---

## 1. Why one service instead of six?

Render is a different kind of platform from Docker Compose, and four of its
constraints decide the design:

| Constraint | Consequence |
|---|---|
| Render does not run `docker-compose.yml` | Every component would have to become its own Render service. |
| Containers get **no Docker socket** | `restart` / `isolate` / `resume` talk to the Docker daemon — impossible there. |
| The **free plan has only web services** | No private services, no background workers, no persistent disks. |
| Free web services **cannot receive private-network traffic** | Six free services could not talk to each other internally — they would have to use public URLs. |

The last two are fatal for a six-service deployment: the services could not reach
each other privately, and the copilot's 10-second detector loop would keep them
all awake until the 750 instance-hour monthly cap was exceeded.

So the Blueprint bundles **Prometheus + order-service + payment-service + a
traffic generator + the copilot into one container**
(`deploy/allinone/Dockerfile`), all talking over `localhost` behind a single
public port. One service, one URL, no cross-service networking.

---

## 2. What works on the hosted link, and what doesn't

Be upfront about this if you present the hosted URL — it is a real trade-off, not
a bug.

| Capability | Hosted (Render) | Local Compose |
|---|---|---|
| Detection loop, thresholds, auto-resolve | ✅ | ✅ |
| Root-cause path (DFS), blast radius (BFS) | ✅ | ✅ |
| Deploy correlation, confidence scoring | ✅ | ✅ |
| Cost model, knapsack response plan, clustering | ✅ | ✅ |
| Runbooks, postmortems, timeline | ✅ | ✅ |
| Chaos injection (the demo input) | ✅ | ✅ |
| Prometheus query UI (`/prometheus/graph`) | ✅ via proxy | ✅ port 9090 |
| **Rollback** | ✅ (clears chaos flags over HTTP) | ✅ clear + restart |
| **Restart / Isolate / Resume** | ❌ no Docker socket | ✅ |
| Grafana dashboards | ❌ (image too heavy for a free 512 MB instance) | ✅ port 3000 |

In hosted mode the dashboard shows a small **`hosted actions: rollback only`**
chip, and the Restart / Isolate buttons are visibly disabled with an explanation
rather than failing silently.

---

## 3. Before you deploy

The code must be on GitHub — it already is:

```
https://github.com/priyanshi0121/AI-copilot
```

You need a Render account (free, sign in with GitHub). Nothing else.

---

## 4. Deploy (about 5 minutes)

1. Go to <https://dashboard.render.com> and sign in with GitHub.
2. Click **New +** → **Blueprint**.
3. Choose the **`priyanshi0121/AI-copilot`** repository → **Connect**.
4. Render reads `render.yaml` and shows one service, `aiops-copilot`. Confirm:
   - **Instance type / plan:** Free
   - **Dockerfile path:** `./deploy/allinone/Dockerfile`
   - **Health check path:** `/health`
5. Click **Apply** / **Create Resources**.
6. Wait for the first build (a few minutes — it installs Python deps and copies
   the Prometheus binary).
7. When the status is **Live**, open the URL Render shows you, for example
   `https://aiops-copilot.onrender.com`.

> If Render rejects `plan: free` from the Blueprint, delete the `plan:` line from
> `render.yaml` and select **Free** in the dashboard instead. Do this before
> applying — otherwise it may pick a paid instance type.

---

## 5. Optional: turn on real AI reasoning

With no API key the copilot runs its **deterministic rule-based engine**, which
is fully functional — every diagnosis, runbook and postmortem still works. The
header will say `AI rule-based mode — add key in .env`.

To use real model reasoning instead:

1. Render dashboard → your service → **Environment**.
2. Set `ANTHROPIC_API_KEY` to your key (it is marked `sync: false` in the
   Blueprint precisely so it is never committed to the repo).
3. Save — Render redeploys automatically. The header chip changes to
   `AI key configured`.

---

## 6. Demoing the hosted link

Free services sleep after ~15 minutes without public traffic and take about a
minute to wake, so **wake it up before you present**:

```bash
curl -s https://YOUR-URL.onrender.com/health
# {"detector_running":true,"status":"ok"}
```

Then walk through it exactly like the local demo:

1. Open the URL — services, latency sparklines with the 0.5 s threshold, and the
   seeded deploy history are visible.
2. **Run a PromQL query**: click *Prometheus query UI* in the footer (proxied at
   `/prometheus/graph`). The five queries are in
   [`monitoring/prometheus-queries.md`](monitoring/prometheus-queries.md).
3. Click **🐢 Inject slowness** on payment-service. Wait ~30–40 s.
4. An incident appears with severity, confidence, root cause (blamed on the
   correlated deploy), the DFS path, BFS blast radius, cost estimate and a
   4-step runbook — and order-service goes slow too, because it calls payment.
5. Click **⏪ Rollback** — chaos flags clear over HTTP and the incident resolves
   into a postmortem. Point out the honest note: restart needs the Docker socket,
   which only exists locally.

---

## 7. Free-tier behaviour to expect

- **Sleep / wake:** no public traffic for ~15 min → it sleeps and consumes no
  instance-hours; the next request wakes it in ~1 minute.
- **Instance hours:** a workspace gets 750/month. One service that sleeps when
  idle stays well inside that.
- **Ephemeral filesystem:** no persistent disk on free, so
  `data/incidents.json` and `data/deploys.json` reset when the container
  restarts. Deploys re-seed themselves on first read; incidents start empty.
- **Compute:** free instances are 512 MB / fractional CPU, so the UI can feel
  slow under load. Bumping the service to a paid instance (≈$7/month) makes it
  consistently responsive and removes the sleep.

---

## 8. Want the full stack hosted instead?

If you need the Docker-backed actions, Grafana, and no spin-down, the options are:

- **Paid Render plans** — separate services with real private networking and
  always-on instances (roughly $7 per service per month). Ask and this can be
  added as a second Blueprint alongside the all-in-one one.
- **A single small VM** (DigitalOcean, Hetzner, …) running the existing
  `docker-compose.yml` unchanged. Everything works, including the sandboxed
  Docker actions, because there is a real Docker daemon.
- **Local + a tunnel** for a temporary public link to the fully working local
  stack: `cloudflared tunnel --url http://localhost:8000`.

---

## 9. Troubleshooting

| Symptom | Cause / fix |
|---|---|
| Deploy fails: "no open ports detected" | The copilot must listen on `$PORT`. It reads `PORT` (default 8000) in `dashboard/app.py`; internal services are pinned to 5001/5002 in `deploy/allinone/supervisord.conf`. |
| Health check failing at `/health` | Give the container longer: Prometheus and both services start in parallel, and the copilot's detector needs a few seconds. |
| Dashboard loads but shows `waiting for data…` | Prometheus needs ~10–20 s to accumulate samples for the `rate()` queries. Refresh. |
| Everything shows `unknown` / no incidents | The traffic generator may not have produced data yet. Check the service's **Logs** tab in Render for the `loadgen`, `order-service` and `payment-service` programs. |
| 502 from `/prometheus/graph` | The proxy could not reach Prometheus at `PROMETHEUS_URL`. Confirm the env var is `http://127.0.0.1:9090/prometheus`. |
| First visit is very slow | The free instance was asleep and is cold-starting (~1 minute). |
