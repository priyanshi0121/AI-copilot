"""Alert-fatigue reducer: group duplicate/related alerts into incident clusters.

Two open alerts belong to the same cluster when their services are connected
in the dependency graph (BFS connectivity check) AND they started close
together in time — one human response instead of five pager pings."""
from datetime import datetime, timezone

from .dependency_graph import are_connected

WINDOW_MIN = 10


def _parse(ts: str) -> datetime:
    dt = datetime.fromisoformat(ts)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def cluster_incidents(incidents: list, window_min: int = WINDOW_MIN) -> list:
    open_incidents = [i for i in incidents if i["status"] in ("open", "acknowledged")]
    clusters = []

    for incident in open_incidents:
        placed = False
        for cluster in clusters:
            member = cluster["incidents"][0]
            time_close = abs((_parse(incident["started_at"]) - _parse(member["started_at"])).total_seconds()) <= window_min * 60
            if time_close and are_connected(incident["service"], member["service"]):
                cluster["incidents"].append(incident)
                placed = True
                break
        if not placed:
            clusters.append({"incidents": [incident]})

    result = []
    for cluster in clusters:
        services = sorted({i["service"] for i in cluster["incidents"]})
        primary = max(cluster["incidents"], key=lambda i: (i.get("priority_score") or 0))
        label = f"{primary['service']} (+{len(cluster['incidents']) - 1} related)" if len(cluster["incidents"]) > 1 else primary["service"]
        result.append(
            {
                "label": label,
                "services": services,
                "incident_ids": [i["id"] for i in cluster["incidents"]],
                "size": len(cluster["incidents"]),
            }
        )
    return result
