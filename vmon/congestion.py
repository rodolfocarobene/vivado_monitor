"""Congestion summary of place_design / route_design (see [congestion] in flows.toml)."""

SOURCES = (("placer", "placement"), ("router_initial", "initial routing"), ("router_final", "final routing"))
SLOTS = ("global", "long", "short")


def _levels(raw):
    """(level, source label, direction, slot) of every value in the raw tables."""
    for source, label in SOURCES:
        for direction, row in raw.get(source, {}).items():
            for slot in SLOTS:
                if row.get(slot) is not None:
                    yield row[slot], label, direction, slot
            if row.get("level") is not None:
                yield row["level"], label, direction, "global"


def summarize(raw, cfg):
    """Node.congestion for a step, or None when its log has no congestion table."""
    if not raw:
        return None
    worst = max(_levels(raw), default=None)
    top = worst[0] if worst else 0
    settings = cfg.congestion
    level = "crit" if top >= settings.crit_level else "warn" if top >= settings.warn_level else "ok"
    return {**{k: v for k, v in raw.items() if v}, "max_level": top, "level": level,
            "warn_level": settings.warn_level, "crit_level": settings.crit_level}


def worst(congestion):
    """(level, source label, direction, slot) of the worst value of a Node.congestion, or None."""
    return max(_levels(congestion), default=None) if congestion else None


def alert_message(congestion, cfg):
    """Warning text when the worst level reaches warn_level, else None."""
    if not congestion or not cfg.congestion.alert or congestion["level"] == "ok":
        return None
    level, label, direction, slot = worst(congestion)
    return ("Congestion level %d during %s (%s %s, threshold %d): may impact timing closure"
            % (level, label, direction, slot, cfg.congestion.warn_level))
