"""Router convergence: trend of the overlap counts per iteration (see [convergence] in flows.toml)."""


def trend(iterations, cfg):
    """"converging" | "stalled" | "diverging" | None from the final overlaps of each iteration."""
    finals = [it["final_overlaps"] for it in iterations if it.get("final_overlaps") is not None]
    if len(finals) < 2:
        return None
    if finals[-1] == 0:
        return "converging"
    settings = cfg.convergence
    recent = finals[-(settings.window + 1):]
    steps = list(zip(recent, recent[1:]))
    if len(recent) < settings.window + 1:
        return "converging" if all(b < a for a, b in steps) else None
    if all(b > a for a, b in steps):
        return "diverging"
    if recent[-1] > recent[0] * (1 - settings.min_improvement_pct / 100.0):
        return "stalled"
    return "converging"


def summarize(iterations, cfg):
    """Node.convergence for a step, or None when the step has no router iterations."""
    if not iterations:
        return None
    items = [dict(it) for it in iterations]
    return {"iterations": items, "trend": trend(items, cfg)}


def alert_message(convergence, cfg):
    """Warning text when the router stalls/diverges long enough, else None."""
    settings = cfg.convergence
    if not settings.alert or convergence is None:
        return None
    state = convergence["trend"]
    items = convergence["iterations"]
    if state not in ("stalled", "diverging") or len(items) < settings.alert_min_iterations:
        return None
    finals = [it["final_overlaps"] for it in items if it.get("final_overlaps") is not None]
    tail = " -> ".join("{:,}".format(v) for v in finals[-(settings.window + 1):])
    return "Router %s: overlaps %s over the last %d iterations (%d so far)" % (
        state, tail, settings.window, len(items))
