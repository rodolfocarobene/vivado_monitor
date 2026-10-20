"""Alert rules: things not going as expected, so a run can be stopped early.

Thresholds come from [alerts] in flows.toml. Stale reports (from an older launch) never alert.
"""


def _alert(level, code, message, node_id):
    return {"level": level, "code": code, "message": message, "node_id": node_id}


def timing_alerts(node, step_id):
    out = []
    timing = node.timing
    if timing and node.status in ("running", "done", "failed", "stopped"):
        where = "after %s" % node.label if node.status == "done" else "during %s (%s)" % (node.label, timing.label)
        for name, value in (("WNS", timing.wns), ("WHS", timing.whs)):
            if value is None or value >= 0:
                continue
            origin = timing.carried.get(name.lower())
            if origin:
                out.append(_alert("warning", "timing_fail", "%s %.3f ns %s (from %s)"
                                  % (name, value, where, origin["label"]), node.id))
                continue
            if timing.final:
                out.append(_alert("error", "timing_fail", "%s %.3f ns %s (final)" % (name, value, where), node.id))
                continue
            word = "intermediate" if "intermediate" in timing.stage.lower() else "estimated"
            note = "%s value during %s, not final" % (word, node.label)
            if name == "WHS" and step_id in ("route_design", "place_design", "phys_opt_design"):
                note += " (hold fixing usually comes later in route)"
            out.append(_alert("warning", "timing_fail", "%s %.3f ns - %s" % (name, value, note), node.id))
    return out


def node_alerts(node, step_id, cfg, stall_age=None, alive=True):
    """Alerts for a step or run node (not for phases)."""
    settings = cfg.alerts
    out = []
    nid = node.id
    errors, critical = node.counts[3], node.counts[2]
    if node.status == "failed":
        out.append(_alert("error", "step_failed", "%s failed" % node.label, nid))
    if node.status == "stopped":
        out.append(_alert("error", "process_gone", "Vivado process gone during %s" % node.label, nid))
    if errors:
        out.append(_alert("error", "error", "%d ERROR message(s) in %s" % (errors, node.label), nid))
    if critical:
        out.append(_alert("warning", "critical_warning",
                          "%d critical warning(s) in %s" % (critical, node.label), nid))
    out.extend(timing_alerts(node, step_id))
    for report in node.reports:
        if not report["stale"]:
            for alert in report["alerts"]:
                out.append(_alert(alert["level"], alert["code"],
                                  "%s: %s" % (report["name"], alert["message"]), nid))
    minutes = settings.get("stall_minutes", 20)
    if node.status == "running" and alive and stall_age is not None and stall_age > minutes * 60:
        out.append(_alert("warning", "stalled",
                          "%s: no log output for %d min" % (node.label, stall_age // 60), nid))
    return out


def collect(nodes):
    """All alerts in a node forest, depth first."""
    out = []
    for node in nodes:
        out.extend(node.alerts)
        out.extend(collect(node.children))
    return out


def health(alerts):
    if any(a["level"] == "error" for a in alerts):
        return "error"
    return "warning" if alerts else "ok"
