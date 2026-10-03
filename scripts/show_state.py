#!/usr/bin/env python3
"""Pretty-print the copilot state (used by demo.sh and verification)."""
import json
import sys
import urllib.request

state = json.load(urllib.request.urlopen("http://localhost:8000/api/state", timeout=10))

print("AI mode:", state["ai_mode"])
print("open incidents:", len(state["open_incidents"]))
for inc in state["open_incidents"]:
    print(f"\nINCIDENT #{inc['id']}: {inc['service']} {inc['kind']} = "
          f"{inc['detected_value']:.2f} (threshold {inc['threshold']})")
    print("  root cause :", inc["root_cause"])
    print("  confidence :", str(inc["confidence"]) + "% | engine:", inc["ai_engine"])
    corr = inc.get("correlated_deploy") or {}
    print("  correlation:", corr.get("explanation", "none"))
    ce = inc.get("cost_estimate") or {}
    print("  cost       : ${}/hr | 24h: ${}".format(ce.get("per_hour_usd"), ce.get("projected_24h_usd")))
    print("  blast      :", inc["blast_radius"])
    print("  path (DFS) :", inc["root_cause_path"])
    for step in inc.get("runbook") or []:
        tag = f" [auto: {step['action']}]" if step.get("action") else ""
        print(f"  runbook    : - {step['step'][:70]}{tag}")

print("\nclusters:", [(c["label"], c["incident_ids"]) for c in state["clusters"]])
plan = state["plan"]
print("plan covered: ${} of ${}".format(plan["covered_usd"], plan["total_at_risk_usd"]))
for item in plan["plan"]:
    print(f"  - #{item['incident_id']} {item['service']} {item['kind']}: "
          f"${item['value_usd']}/{item['weight_min']}min -> ${item['ratio_usd_per_min']}/min = {item['take']}")

if len(sys.argv) > 1 and sys.argv[1] == "--resolved":
    for inc in state["incidents"]:
        if inc["status"] == "resolved":
            print(f"\nRESOLVED #{inc['id']}: {inc['resolution']}")
            pm = (inc.get("postmortem") or "")[:300].replace("\n", " | ")
            print("  postmortem:", pm + "…")
