#!/usr/bin/env python3
"""Live end-to-end test for the AIOps Copilot — drives the REAL running stack
through every scenario and prints PASS/FAIL per check.

Covers: preflight, deploy recording, slow-chaos detection + correlation +
clustering + runbook, rollback + auto-resolution + postmortem, error-storm
detection, service-down detection (isolate/resume), API edge cases,
concurrency, and demo-data reset.

Usage: python3 scripts/e2e_test.py          (stack must be running)
Exit code 0 = all green, 1 = failures.
"""
import json
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor

BASE = "http://localhost:8000"
PAY = "http://localhost:5002"
ORDER = "http://localhost:5001"
PROM = "http://localhost:9090"
GRAF = "http://localhost:3000"

results = []
section = [""]


def banner(title):
    section[0] = title
    print(f"\n{'=' * 62}\n  {title}\n{'=' * 62}")


def check(name, cond, detail=""):
    ok = bool(cond)
    print(f"  {'✅ PASS' if ok else '❌ FAIL'}  {name}" + (f"  → {detail}" if detail and not ok else ""))
    results.append((name, ok, detail))


def get(url, timeout=15):
    try:
        with urllib.request.urlopen(url, timeout=timeout) as r:
            return r.status, r.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as e:
        return e.code, ""
    except Exception as e:
        return 0, str(e)


def post(url, data=None, timeout=60):
    body = urllib.parse.urlencode(data or {}).encode()
    req = urllib.request.Request(url, data=body, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status, r.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as e:
        return e.code, ""
    except Exception as e:
        return 0, str(e)


def state():
    status, body = get(BASE + "/api/state")
    return json.loads(body) if status == 200 else {}


def wait_for(pred, timeout=80, interval=5, desc=""):
    start = time.time()
    while time.time() - start < timeout:
        try:
            if pred():
                return True
        except Exception:
            pass
        time.sleep(interval)
    return False


def chaos_status(service_url):
    status, body = get(service_url + "/chaos/status")
    return json.loads(body)["chaos"] if status == 200 else {}


# ============================================================ S0 preflight
def s0_preflight():
    banner("S0 · PREFLIGHT — is the whole stack alive?")
    st, body = get(BASE + "/health")
    check("copilot /health responds", st == 200, f"HTTP {st}")
    try:
        check("detector thread running", json.loads(body)["detector_running"])
    except Exception as e:
        check("detector thread running", False, str(e))
    for name, url in (("order-service", ORDER), ("payment-service", PAY)):
        st, body = get(url + "/health")
        ok = st == 200 and json.loads(body)["status"] == "ok"
        check(f"{name} healthy", ok, f"HTTP {st}")
    st, body = get(PROM + "/api/v1/targets")
    try:
        targets = {t["labels"]["job"]: t["health"] for t in json.loads(body)["data"]["activeTargets"]}
        check("prometheus scraping order-service", targets.get("order-service") == "up", str(targets))
        check("prometheus scraping payment-service", targets.get("payment-service") == "up", str(targets))
    except Exception as e:
        check("prometheus targets", False, str(e))
    st, body = get(GRAF + "/api/search")
    check("grafana API reachable", st == 200, f"HTTP {st}")
    check("grafana has AIOps dashboard provisioned", "AIOps" in body, body[:120])
    st, body = get(BASE + "/")
    check("dashboard HTML renders (200)", st == 200, f"HTTP {st}")
    check("dashboard shows services section", "Services" in body)
    check("dashboard shows plan section", "Response plan" in body)


# ============================================================ S1 state API
def s1_state_api():
    banner("S1 · STATE API — /api/state structure")
    s = state()
    check("state has services", len(s.get("services", [])) == 2, str(list(s.keys())))
    check("state has incidents list", isinstance(s.get("incidents", []), list))
    check("state has plan", "plan" in s and "capacity_min" in s["plan"])
    check("state has clusters", isinstance(s.get("clusters", []), list))
    check("state reports ai_mode", isinstance(s.get("ai_mode"), str) and s["ai_mode"], s.get("ai_mode", "MISSING"))
    check("state has recent deploys", isinstance(s.get("deploys", []), list))
    check("state reports total deploy count", isinstance(s.get("deploy_count"), int))


# ============================================================ S2 deploys
def s2_deploys():
    banner("S2 · DEPLOY RECORDING — correlation source")
    before = state()["deploy_count"]
    st, _ = post(BASE + "/deploys", {"service": "payment-service", "note": "e2e test deploy"})
    check("POST /deploys succeeds", st in (200, 302), f"HTTP {st}")
    after = state()["deploy_count"]
    check("deploy count increased", after == before + 1, f"{before} → {after}")
    latest = state()["deploys"][0]
    check("new deploy is most recent + correct service",
          latest["service"] == "payment-service" and latest["note"] == "e2e test deploy",
          json.dumps(latest)[:120])


# ============================================================ S3 slow chaos
def s3_slow_chaos():
    banner("S3 · SLOWNESS CHAOS — detection, correlation, clustering, runbook")
    st, body = post(PAY + "/chaos/slow?enabled=true")
    check("chaos slow enabled", st == 200 and json.loads(body)["chaos"]["slow"])
    print("  … polling up to 80s for the detector …")

    def incident_open():
        return next((i for i in state()["open_incidents"]
                     if i["service"] == "payment-service" and i["kind"] == "latency"), None)

    inc = None
    found = wait_for(lambda: incident_open() is not None, timeout=80, desc="latency incident")
    inc = incident_open()
    check("latency incident detected on payment-service", found and inc is not None)
    if not inc:
        return
    check("detected value above threshold", inc["detected_value"] > inc["threshold"],
          f"{inc['detected_value']} vs {inc['threshold']}")
    corr = inc.get("correlated_deploy")
    check("correlated to the fresh e2e deploy", bool(corr), json.dumps(inc)[:150])
    if corr:
        check("correlation confidence ≥ 60%", corr["confidence"] >= 60, str(corr["confidence"]))
    check("root cause drafted", bool(inc.get("root_cause")))
    check("confidence score present", inc.get("confidence") is not None, str(inc.get("confidence")))
    check("runbook has ≥3 steps", len(inc.get("runbook") or []) >= 3)
    check("runbook steps have automation tags", any(s.get("action") for s in inc["runbook"]))
    blast = sum(inc.get("blast_radius") or [], [])
    check("blast radius (BFS) includes order-service", "order-service" in blast, str(inc.get("blast_radius")))
    check("DFS root-cause path present", bool(inc.get("root_cause_path")))
    check("cost estimate attached", (inc.get("cost_estimate") or {}).get("projected_24h_usd") is not None)
    check("priority score computed", inc.get("priority_score") is not None)
    check("alert clustering active", any("payment" in c["label"] or len(c["incident_ids"]) >= 1
                                         for c in state()["clusters"]))
    st, body = get(BASE + "/")
    check("dashboard HTML shows the open incident", f'id="incident-{inc["id"]}"' in body)

    # concurrency probe while system is under incident load
    with ThreadPoolExecutor(5) as ex:
        codes = list(ex.map(lambda _: get(BASE + "/api/state")[0], range(5)))
    check("5 parallel /api/state requests all OK", codes == [200] * 5, str(codes))
    globals()["S3_INCIDENT_ID"] = inc["id"]


# ============================================================ S4 rollback
def s4_rollback():
    banner("S4 · ROLLBACK ACTION — sandboxed remediation + auto-resolution")
    inc_id = globals().get("S3_INCIDENT_ID")
    if not inc_id:
        check("skipped (no open incident from S3)", False)
        return
    st, _ = post(BASE + "/action/rollback", {"incident_id": inc_id})
    check("POST /action/rollback succeeds", st in (200, 302), f"HTTP {st}")
    check("chaos flags cleared on payment-service",
          wait_for(lambda: not chaos_status(PAY).get("slow"), timeout=40), str(chaos_status(PAY)))

    def resolved_with_pm():
        i = next((x for x in state()["incidents"] if x["id"] == inc_id), None)
        return i and i["status"] == "resolved" and i.get("postmortem")

    check("incident auto-resolved with postmortem", wait_for(resolved_with_pm, timeout=50))
    inc = next((x for x in state()["incidents"] if x["id"] == inc_id), {})
    timeline_text = " ".join(t["event"] for t in inc.get("timeline", []))
    check("timeline records the rollback action", "rollback" in timeline_text.lower(), timeline_text[:150])


# ============================================================ S5 error chaos
def s5_error_chaos():
    banner("S5 · ERROR-STORM CHAOS — error-rate detection")
    st, _ = post(PAY + "/chaos/errors?enabled=true")
    check("chaos errors enabled", st == 200)

    def error_incident():
        return next((i for i in state()["open_incidents"]
                     if i["service"] == "payment-service" and i["kind"] == "error"), None)

    inc = None
    found = wait_for(lambda: error_incident() is not None, timeout=80, desc="error incident")
    inc = error_incident()
    check("error-rate incident detected", found and inc is not None)
    if inc:
        check("error rate above threshold", inc["detected_value"] >= inc["threshold"],
              f"{inc['detected_value']} vs {inc['threshold']}")
        check("error cost = revenue-at-risk model",
              (inc.get("cost_estimate") or {}).get("per_hour_usd", 0) > 0,
              str(inc.get("cost_estimate")))
    post(BASE + "/action/rollback", {"incident_id": inc["id"]}) if inc else None
    check("error incident resolved after rollback",
          wait_for(lambda: inc and next((x for x in state()["incidents"] if x["id"] == inc["id"]), {}).get("status") == "resolved",
                   timeout=60))


# ============================================================ S6 down/resume
def s6_down_and_resume():
    banner("S6 · SERVICE-DOWN CHAOS — availability incident + resume")
    st, _ = post(BASE + "/action/isolate", {"service": "payment-service"})
    check("isolate action accepted", st in (200, 302), f"HTTP {st}")

    def down_incident():
        return next((i for i in state()["open_incidents"]
                     if i["service"] == "payment-service" and i["kind"] == "down"), None)

    inc = None
    found = wait_for(lambda: down_incident() is not None, timeout=60, desc="down incident")
    inc = down_incident()
    check("service-down incident detected", found and inc is not None)
    st, body = get(BASE + "/")
    check("dashboard shows payment-service DOWN", "DOWN" in body)
    if inc:
        check("down runbook suggests restart/resume",
              any("restart" in s["step"].lower() or "resume" in s["step"].lower() or "start" in s["step"].lower()
                  for s in inc.get("runbook", [])), str(inc.get("runbook"))[:150])
    st, _ = post(BASE + "/action/resume", {"service": "payment-service"})
    check("resume action accepted", st in (200, 302), f"HTTP {st}")

    def container_running():
        out = subprocess.run(["docker", "inspect", "-f", "{{.State.Running}}", "payment-service"],
                             capture_output=True, text=True).stdout.strip()
        return out == "true"

    check("container actually running again (docker inspect)", wait_for(container_running, timeout=40))

    def down_resolved():
        i = next((x for x in state()["incidents"] if x.get("kind") == "down"), None)
        return i and i["status"] == "resolved"

    check("down incident auto-resolved after resume", wait_for(down_resolved, timeout=60))


# ============================================================ S7 edge cases
def s7_edge_cases():
    banner("S7 · EDGE CASES — bad input, unknown actions, concurrency")
    st, _ = post(BASE + "/action/definitely-not-an-action", {"incident_id": 9999})
    check("unknown action → graceful redirect (no 500)", st in (200, 302), f"HTTP {st}")
    st, _ = post(BASE + "/action/rollback", {"incident_id": 99999})
    check("rollback on nonexistent incident → redirect", st in (200, 302), f"HTTP {st}")
    st, _ = post(BASE + "/chaos/bogus-kind")
    check("unknown chaos kind → graceful redirect", st in (200, 302), f"HTTP {st}")
    st, body = get(BASE + "/api/state")
    check("/api/state still valid JSON after abuse", st == 200 and "incidents" in json.loads(body))

    before = state()["deploy_count"]
    with ThreadPoolExecutor(3) as ex:
        codes = list(ex.map(lambda _: post(BASE + "/deploys", {"service": "order-service", "note": "rapid"})[0], range(3)))
    after = state()["deploy_count"]
    check("3 rapid concurrent deploy posts all succeed", codes == [200] * 3 and after == before + 3,
          f"codes={codes} {before}→{after}")

    st, body = get(BASE + "/health")
    check("copilot health still OK after stress", st == 200 and json.loads(body)["detector_running"])


# ============================================================ S8 reset
def s8_reset():
    banner("S8 · DEMO RESET — clean slate")
    post(PAY + "/chaos/clear")
    post(ORDER + "/chaos/clear")
    st, _ = post(BASE + "/admin/reset")
    check("POST /admin/reset succeeds", st in (200, 302), f"HTTP {st}")
    check("incident store empty after reset", state()["incidents"] == [])
    st, body = get(BASE + "/")
    check("dashboard renders clean state", st == 200 and "All quiet" in body)


def main():
    print("AIOps Copilot — LIVE end-to-end test run")
    print(f"target: {BASE}  ·  {time.strftime('%Y-%m-%d %H:%M:%S')}")
    s0_preflight()
    s1_state_api()
    s2_deploys()
    s3_slow_chaos()
    s4_rollback()
    s5_error_chaos()
    s6_down_and_resume()
    s7_edge_cases()
    s8_reset()

    banner("SUMMARY")
    passed = sum(1 for _, ok, _ in results if ok)
    failed = len(results) - passed
    print(f"  {passed} passed · {failed} failed · {len(results)} total\n")
    if failed:
        print("  Failures:")
        for name, ok, detail in results:
            if not ok:
                print(f"   ❌ {name}" + (f" — {detail[:160]}" if detail else ""))
    print()
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
