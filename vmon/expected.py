"""Catalog of expected sub-steps per flow step (vmon/catalog/vivado_<version>.toml).

The catalog (schema in vmon/catalog/README.md) is merged into the parsed tree so phases that
have not happened yet show up as pending placeholders (expected=True). Seen nodes are matched
to catalog entries by NAME (numbers vary), and gain description/optional/weight. If no catalog
is available nothing is added and nothing else changes.
"""
import re
import tomllib
from pathlib import Path

from .logparse import slug
from .model import Node
from .paths import config_dir


def catalog_dirs():
    return (Path(__file__).parent / "catalog", config_dir() / "catalog")


_LEADING = re.compile(r"^[\d.]+\s+")
_REAL_NUMBER = re.compile(r"^\d+(\.\d+)*$")


def normalize(name):
    name = _LEADING.sub("", name.strip().lower())
    name = re.sub(r"\s+task$", "", name)
    return re.sub(r"\s+", " ", name)


def _families(value):
    return frozenset(value) if isinstance(value, list) and value else None


def _applies(families, family):
    """No restriction, or the family is unknown: the entry applies (unknown family = behave as before)."""
    return families is None or family is None or family in families


def _entry(item, kind):
    pattern = item.get("pattern")
    try:
        regex = re.compile(pattern, re.I) if pattern else None
    except re.error:
        regex = None
    return {"name": item["name"], "norm": normalize(item.get("finish_name") or item["name"]),
            "alt_norm": normalize(item["name"]), "kind": kind, "parent": item.get("parent"),
            "optional": bool(item.get("optional", False)), "description": item.get("desc") or item.get("description"),
            "weight": item.get("weight"), "regex": regex, "repeat": bool(item.get("repeat")),
            "families": _families(item.get("families")), "children": []}


def _tree(items, kind):
    """Nest a flat list on its `parent` names, keeping order."""
    nodes = [_entry(i, kind) for i in items if isinstance(i, dict) and i.get("name") and not i.get("disabled")]
    top = []
    for node in nodes:
        parent = next((p for p in nodes if p is not node and p["name"] == node["parent"]), None) \
            if node["parent"] else None
        (parent["children"] if parent else top).append(node)
    return top


class StepCatalog:
    def __init__(self, spec):
        self.weight = spec.get("weight")
        self.families = _families(spec.get("device_families"))
        self.dynamic = spec.get("plan_mode") == "dynamic"
        tasks = _tree(spec.get("tasks") or [], "task")
        phases = _tree(spec.get("phases") or [], "phase")
        sections = _tree(spec.get("sections") or [], "phase")
        stages = _tree(spec.get("stages") or [], "phase")
        self.stages = [(i["name"], re.compile(i["match"])) for i in spec.get("stages") or ()
                       if isinstance(i, dict) and i.get("match") and not i.get("disabled")]
        self.command = spec.get("command")
        self.label = spec.get("label")
        self.run = spec.get("run", "impl")
        self.cached_marker = re.compile(spec["cached_marker"]) if spec.get("cached_marker") else None
        if tasks and phases:
            container = next((t for t in tasks if "phase" in (t["description"] or "").lower()), tasks[0])
            container["children"] = phases + container["children"]
            self.tree = tasks
        else:
            self.tree = tasks or phases or sections or stages


class Catalog:
    def __init__(self, data):
        self.version = (data.get("catalog") or {}).get("vivado")
        self.family_map = []
        for item in (data.get("catalog") or {}).get("family_map") or ():
            try:
                self.family_map.append((re.compile(item["match"], re.I), item["family"]))
            except (KeyError, TypeError, re.error):
                continue
        self.steps = {}
        for spec in data.get("step") or ():
            if isinstance(spec, dict) and spec.get("id") and not spec.get("disabled"):
                self.steps[spec["id"]] = StepCatalog(spec)


def _version_key(text):
    try:
        return tuple(int(p) for p in text.split("."))
    except (ValueError, AttributeError):
        return ()


class CatalogSet:
    def __init__(self, directories=None):
        directories = catalog_dirs() if directories is None else directories
        self.catalogs = {}
        for directory in directories:
            if not directory.is_dir():
                continue
            for path in sorted(directory.glob("vivado_*.toml")):
                try:
                    with open(path, "rb") as fh:
                        self.catalogs[path.stem[len("vivado_"):]] = Catalog(tomllib.load(fh))
                except (OSError, tomllib.TOMLDecodeError):
                    continue

    def family_of(self, part, version=None):
        """Device family ("7series", "ultrascale+", ...) for a part name, None when unknown."""
        if not part:
            return None
        catalogs = [self.get(version)] + list(self.catalogs.values())
        for catalog in catalogs:
            for regex, family in (catalog.family_map if catalog else ()):
                if regex.match(part):
                    return family
        return None

    def step_applies(self, step_id, family, version=None):
        catalog = self.get(version)
        entry = catalog.steps.get(step_id) if catalog else None
        return entry is None or _applies(entry.families, family)

    def version_used(self, version):
        """Version of the catalog file `get(version)` falls back to (None without a catalog)."""
        catalog = self.get(version)
        return catalog.version if catalog else None

    def stage_matchers(self, version):
        catalog = self.get(version)
        out = {}
        if catalog:
            for entry in catalog.steps.values():
                if entry.stages and entry.command:
                    out.setdefault(entry.command, []).extend(entry.stages)
        return out

    def apply_to_config(self, cfg):
        """Catalog is the source for steps: labels, commands, flow; flows.toml keeps the rest."""
        from .config import StepDef
        catalog = self.get(None)
        if not catalog:
            return
        for index, (step_id, entry) in enumerate(catalog.steps.items()):
            existing = cfg.steps.get(step_id)
            order = existing.order if existing else index * 10 + 5
            commands = set(existing.commands) if existing else set()
            if entry.command:
                commands.add(entry.command)
            cfg.steps[step_id] = StepDef(step_id, {
                "label": entry.label or (existing.label if existing else step_id),
                "flow": entry.run or "impl", "order": order, "commands": sorted(commands)})
        cfg.steps = dict(sorted(cfg.steps.items(), key=lambda kv: (kv[1].order, kv[0])))
        cfg.step_order = list(cfg.steps)
        cfg.step_commands = {c for s in cfg.steps.values() for c in s.commands}

    def is_cached_ip(self, step_id, messages, version=None):
        catalog = self.get(version)
        entry = catalog.steps.get(step_id) if catalog else None
        if not entry or entry.cached_marker is None:
            return False
        return any(m[2] and "IP_Flow" in m[2] and entry.cached_marker.search("INFO: [%s] %s" % (m[2], m[3]))
                   for m in messages[:3000])

    def get(self, version):
        """Exact version, else the closest older one, else the oldest available."""
        if not self.catalogs:
            return None
        if version in self.catalogs:
            return self.catalogs[version]
        want = _version_key(version or "")
        older = sorted((v for v in self.catalogs if _version_key(v) <= want), key=_version_key)
        pick = older[-1] if older and want else sorted(self.catalogs, key=_version_key)[0]
        return self.catalogs[pick]

    # ------------------------------------------------------------------ merging
    def merge(self, step_id, node, status, version=None, annotate_only=False, family=None):
        catalog = self.get(version)
        entry = catalog.steps.get(step_id) if catalog else None
        if not entry:
            return node.children
        seen_names = set()
        _collect_names(node.children, seen_names)
        return self._merge_level(node.children, entry.tree, node.id, status,
                                 entry.dynamic or annotate_only, seen_names, family=family)

    def _merge_level(self, seen, expected, parent_id, status, dynamic, seen_names, parent_number=None,
                     family=None):
        finished = status in ("done", "failed", "stopped", "skipped")
        pool = list(seen)
        out = []
        last = 0                      # last seen sibling number (final component) for prediction
        for spec in expected:
            matches = [n for n in pool if _matches(n, spec)]
            if matches:
                taken = matches if spec["repeat"] or spec["regex"] else matches[:1]
                for match in taken:
                    while pool and pool[0] is not match:       # keep unmatched log-order nodes in place
                        out.append(pool.pop(0))
                    pool.pop(0)
                    _annotate(match, spec)
                    if match.number and not match.number_predicted:
                        last = int(match.number.rsplit(".", 1)[-1])
                    if spec["children"]:
                        match.children = self._merge_level(match.children, spec["children"], match.id,
                                                           match.status, dynamic, seen_names, match.number,
                                                           family)
                    out.append(match)
                continue
            if dynamic or (spec["optional"] and finished) or not _applies(spec["families"], family):
                continue
            if spec["kind"] == "task" and spec["norm"] in seen_names:   # task seen deeper in the tree
                continue
            placeholder = Node(id="%s/x-%s" % (parent_id, slug(spec["name"])), label=spec["name"],
                               kind=spec["kind"], status="skipped" if finished else "pending",
                               expected=True, optional=spec["optional"], description=spec["description"])
            if spec["weight"]:
                placeholder.estimate = {"weight": float(spec["weight"])}
            if spec["kind"] == "phase" and not spec["optional"] and not finished:
                last += 1
                placeholder.number = "%s.%d" % (parent_number, last) if parent_number else str(last)
                placeholder.number_predicted = True
                placeholder.label = "%s %s" % (placeholder.number, spec["name"])
            if spec["children"]:
                placeholder.children = self._merge_level([], spec["children"], placeholder.id,
                                                         placeholder.status, dynamic, seen_names,
                                                         placeholder.number, family)
            out.append(placeholder)
        out.extend(pool)
        return out

    # ------------------------------------------------------------------ progress estimate
    def progress(self, flows, version=None):
        if not flows:
            return None
        catalog = self.get(version)
        total = done = 0.0
        impl_total = sum(((catalog.steps.get(n.id.rsplit("/", 1)[-1]).weight if catalog and
                           catalog.steps.get(n.id.rsplit("/", 1)[-1]) else None) or 1.0)
                         for n in flows[-1].stages if n.kind == "step")
        for stage in flows[-1].stages:
            node = stage
            if stage.kind == "group":
                runs = [c for c in stage.children if c.kind == "run"]
                if not runs:
                    continue
                node, step_id = runs[-1], "synth_design"
            else:
                step_id = node.id.rsplit("/", 1)[-1]
            entry = catalog.steps.get(step_id) if catalog else None
            weight = (entry.weight if entry else None) or 1.0
            if step_id == "synth_design" and impl_total:
                weight = min(weight, 0.25 * impl_total)      # synth is weighted 100 in its own run
            total += weight
            done += weight * _step_fraction(node)
        return round(done / total, 3) if total else None


def _collect_names(nodes, out):
    for node in nodes:
        out.add(normalize(node.label))
        _collect_names(node.children, out)


def _matches(node, spec):
    norm = normalize(node.label)
    if norm == spec["norm"] or norm == spec["alt_norm"]:
        return True
    return bool(spec["regex"] and spec["regex"].search(_LEADING.sub("", node.label)))


def _annotate(node, spec):
    node.description = node.description or spec["description"]
    node.optional = spec["optional"]
    if spec["weight"]:
        node.estimate = {"weight": float(spec["weight"])}


def _step_fraction(node):
    if node.status in ("done", "skipped"):
        return 1.0
    if node.status not in ("running", "stopped", "failed"):
        return 0.0
    weighted = _weighted(node.children)
    if not weighted:
        return 0.5 if node.status == "running" else 0.0
    total = sum(c.estimate["weight"] for c in weighted)
    got = sum(c.estimate["weight"] * (1.0 if c.status == "done" else 0.5 if c.status == "running" else 0.0)
              for c in weighted)
    return got / total if total else 0.0


def _weighted(children):
    """Weighted nodes at the first level that has any (steps often hide phases under a task)."""
    direct = [c for c in children if c.estimate]
    if direct:
        return direct
    for child in children:
        found = _weighted(child.children)
        if found:
            return found
    return []
