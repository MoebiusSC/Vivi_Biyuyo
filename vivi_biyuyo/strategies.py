from .intelligence import Cluster, Guard


def lanes(cluster: Cluster, guard: Guard | None, min_traders=2):
    confirmation = min(1, cluster.unique_traders / 4)
    flow_size = min(1, cluster.total_usd / 20000)
    base = round(
        0.45 * cluster.average_quality
        + 0.30 * confirmation
        + 0.15 * flow_size
        + 0.10 * cluster.max_quality,
        4,
    )
    a = {
        "triggered": cluster.max_quality >= 0.82,
        "score": round(
            0.75 * cluster.max_quality + 0.25 * min(1, cluster.total_usd / 10000), 4
        ),
    }
    b = {"triggered": cluster.unique_traders >= min_traders, "score": base}
    fs = guard.flow_score if guard else 0
    c = {
        "triggered": b["triggered"]
        and guard is not None
        and guard.ratio is not None
        and guard.net is not None
        and guard.ratio >= 1.2
        and guard.net > 0,
        "score": round(0.72 * base + 0.28 * fs, 4),
    }
    ss = guard.safety_score if guard else 0
    d = {
        "triggered": c["triggered"] and bool(guard and guard.passed),
        "score": round(0.62 * base + 0.23 * fs + 0.15 * ss, 4),
    }
    return {"A": a, "B": b, "C": c, "D": d}
