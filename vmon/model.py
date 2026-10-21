"""Output dataclasses; to_dict() produces the JSON contract described in SPEC.md."""
from dataclasses import dataclass, field


def counts_dict(counts):
    """counts: [info, warning, critical, error] -> contract dict."""
    return {"error": counts[3], "critical": counts[2], "warning": counts[1], "info": counts[0]}


def compute_met(wns, tns, whs, ths=None):
    if wns is None:
        return None
    return bool(wns >= 0 and (tns is None or tns >= 0) and (whs is None or whs >= 0)
                and (ths is None or ths >= 0))


@dataclass
class Timing:
    wns: float | None = None
    tns: float | None = None
    whs: float | None = None
    ths: float | None = None
    tns_fail: int | None = None
    ths_fail: int | None = None
    met: bool | None = None
    source: str = "log"
    label: str = ""
    history: list = field(default_factory=list)
    wpws: float | None = None
    clocks: list = field(default_factory=list)
    final: bool = False
    stage: str = ""
    carried: dict = field(default_factory=dict)
    report: str | None = None
    path_counts: dict | None = None
    paths: list = field(default_factory=list)

    def to_dict(self):
        return {"wns": self.wns, "tns": self.tns, "whs": self.whs, "ths": self.ths,
                "tns_fail": self.tns_fail, "ths_fail": self.ths_fail, "met": self.met,
                "source": self.source, "label": self.label, "history": self.history,
                "wpws": self.wpws, "clocks": self.clocks, "final": self.final, "stage": self.stage,
                "carried": self.carried, "report": self.report, "path_counts": self.path_counts,
                "paths": self.paths}


@dataclass
class Node:
    id: str
    label: str
    kind: str
    status: str = "pending"
    started_at: float | None = None
    ended_at: float | None = None
    elapsed_s: float | None = None
    peak_mem_mb: float | None = None
    counts: list = field(default_factory=lambda: [0, 0, 0, 0])
    timing: Timing | None = None
    run: str | None = None
    log: str | None = None
    line_start: int | None = None
    line_end: int | None = None
    progress: dict | None = None
    children: list = field(default_factory=list)
    expected: bool = False
    optional: bool = False
    description: str | None = None
    estimate: dict | None = None
    reports: list = field(default_factory=list)
    alerts: list = field(default_factory=list)
    doc_url: str | None = None
    number: str | None = None
    number_predicted: bool = False
    failure: dict | None = None
    attempts: list = field(default_factory=list)
    log_missing: bool = False
    convergence: dict | None = None
    congestion: dict | None = None

    def to_dict(self):
        return {
            "id": self.id, "label": self.label, "kind": self.kind, "status": self.status,
            "started_at": self.started_at, "ended_at": self.ended_at, "elapsed_s": self.elapsed_s,
            "peak_mem_mb": self.peak_mem_mb, "counts": counts_dict(self.counts),
            "timing": self.timing.to_dict() if self.timing else None,
            "run": self.run, "log": self.log, "line_start": self.line_start,
            "line_end": self.line_end, "progress": self.progress,
            "expected": self.expected, "optional": self.optional, "description": self.description,
            "estimate": self.estimate, "reports": self.reports, "alerts": self.alerts,
            "doc_url": self.doc_url, "number": self.number, "number_predicted": self.number_predicted,
            "failure": self.failure, "attempts": self.attempts, "log_missing": self.log_missing,
            "convergence": self.convergence, "congestion": self.congestion,
            "children": [c.to_dict() for c in self.children],
        }


@dataclass
class Flow:
    id: str
    label: str
    stages: list = field(default_factory=list)

    def to_dict(self):
        return {"id": self.id, "label": self.label, "stages": [s.to_dict() for s in self.stages]}


@dataclass
class Firmware:
    id: str
    name: str
    kind: str
    path: str
    status: str = "idle"
    live: bool = False
    pids: list = field(default_factory=list)
    launcher: dict | None = None
    started_at: float | None = None
    updated_at: float | None = None
    elapsed_s: float | None = None
    current: dict | None = None
    counts: list = field(default_factory=lambda: [0, 0, 0, 0])
    timing: Timing | None = None
    flows: list = field(default_factory=list)
    health: str = "ok"
    alerts: list = field(default_factory=list)
    progress_estimate: float | None = None
    vivado_version: str | None = None
    resources: dict | None = None
    utilization: dict | None = None
    top_messages: list = field(default_factory=list)
    events: list = field(default_factory=list)
    eta: dict | None = None
    info: dict | None = None
    attempt: dict | None = None
    clock_history: dict | None = None
    host: str | None = None      # set only by the aggregating vmon, for firmwares of a remote

    def to_dict(self):
        return {
            "id": self.id, "name": self.name, "kind": self.kind, "path": self.path,
            "status": self.status, "live": self.live, "pids": self.pids, "launcher": self.launcher,
            "started_at": self.started_at, "updated_at": self.updated_at, "elapsed_s": self.elapsed_s,
            "current": self.current, "counts": counts_dict(self.counts),
            "timing": self.timing.to_dict() if self.timing else None,
            "health": self.health, "alerts": self.alerts, "progress_estimate": self.progress_estimate,
            "vivado_version": self.vivado_version, "resources": self.resources,
            "utilization": self.utilization, "top_messages": self.top_messages,
            "events": self.events, "eta": self.eta, "info": self.info,
            "attempt": self.attempt, "clock_history": self.clock_history, "host": self.host,
            "flows": [f.to_dict() for f in self.flows],
        }
