"""Catalog checks against real logs: 7-series fixtures (Vivado 2023.2, xc7a35t / xc7z020), device families,
version fallback. The fixtures are small counter/multiplier builds; write_bitstream fails the IO DRC on purpose."""
import re
import time
import tomllib
from pathlib import Path
from types import SimpleNamespace

import pytest

from conftest import FIXTURES, build_runs, read_lines
from vmon.expected import CatalogSet, normalize
from vmon.logparse import LogParser
from vmon.paths import canon
from vmon.project import LogSource, ProjectSource

SEVEN = FIXTURES / "sevenseries"
CATALOG_FILE = Path(__file__).parent.parent / "vmon" / "catalog" / "vivado_2023.2.toml"
LIVE = SimpleNamespace(pids={1}, launcher=None, kind="log")
STEP_BY_COMMAND = {"link_design": "init_design"}
ALL_FAMILIES = {"7series", "ultrascale", "ultrascale+", "versal"}


def raw_catalog():
    with open(CATALOG_FILE, "rb") as fh:
        return tomllib.load(fh)


# ------------------------------------------------------------------ the catalog file itself
def test_every_pattern_compiles_and_matches_its_example():
    for pattern in raw_catalog()["pattern"]:
        regex = re.compile(pattern["regex"])
        if pattern.get("example"):
            assert regex.search(pattern["example"]), pattern["id"]


def test_regexes_compile_and_families_are_known():
    data = raw_catalog()
    assert {m["family"] for m in data["catalog"]["family_map"]} == ALL_FAMILIES
    for entry in data["catalog"]["family_map"]:
        re.compile(entry["match"])
    for step in data["step"]:
        assert set(step.get("device_families", ALL_FAMILIES)) <= ALL_FAMILIES, step["id"]
        for key in ("tasks", "phases", "sections", "stages"):
            for item in step.get(key, ()):
                if item.get("pattern"):
                    re.compile(item["pattern"])
                assert set(item.get("families", ALL_FAMILIES)) <= ALL_FAMILIES, (step["id"], item["name"])


# ------------------------------------------------------------------ part -> family
@pytest.mark.parametrize("part,family", [
    ("xc7a35tcpg236-1", "7series"), ("xc7z020clg400-1", "7series"), ("xc7k325tffg900-2", "7series"),
    ("xc7vx485tffg1157-1", "7series"), ("xc7s50csga324-1", "7series"),
    ("xczu48dr-ffvg1517-2-e", "ultrascale+"), ("xcvu9p-flga2104-2-i", "ultrascale+"),
    ("xcku5p-ffvb676-2-e", "ultrascale+"), ("xck26-sfvc784-2LV-c", "ultrascale+"),
    ("xcku040-ffva1156-2-e", "ultrascale"), ("xcvu095-ffvc1517-2-e", "ultrascale"),
    ("xcvc1902-vsva2197-2MP-e-S", "versal"), ("xcve2302-sfva784-1LP-e-S", "versal"),
    ("xcvp1202-vsva2785-2MP-e-S", "versal"),
    ("", None), (None, None), ("something-else", None)])
def test_family_of_part(catalogs, part, family):
    assert catalogs.family_of(part, "2023.2") == family


# ------------------------------------------------------------------ names seen in real logs vs the catalog
def flatten(entries, out):
    for entry in entries:
        out.append(entry)
        flatten(entry["children"], out)
    return out


def is_known(label, entries):
    norm = normalize(label)
    plain = re.sub(r"^[\d.]+\s+", "", label)
    return any(norm in (e["norm"], e["alt_norm"]) or (e["regex"] and e["regex"].search(plain)) for e in entries)


def seen_nodes(node):
    for child in node.children:
        if child.kind in ("task", "phase"):
            yield child
        yield from seen_nodes(child)


@pytest.mark.parametrize("name", ["np_artix7.log", "np_zynq7.log", "proj_artix7/top.vdi", "proj_artix7/top.vds"])
def test_phases_and_tasks_in_fixture_logs_are_in_the_catalog(cfg, catalogs, name):
    parser = LogParser(cfg, catalogs)
    parser.feed(read_lines(SEVEN / name))
    assert parser.version == "2023.2" and parser.part
    catalog = catalogs.get(parser.version)
    unknown = []
    for step in parser.root.children:
        entry = catalog.steps.get(STEP_BY_COMMAND.get(step.label, step.label))
        if entry is not None:
            names = flatten(entry.tree, [])
            unknown += ["%s: %s" % (step.label, n.label) for n in seen_nodes(step) if not is_known(n.label, names)]
    assert not unknown, "names missing from the catalog: %s" % sorted(set(unknown))


def test_family_restrictions_in_the_catalog(catalogs):
    place = catalogs.get("2023.2").steps["place_design"]
    families = {e["name"]: e["families"] for e in flatten(place.tree, [])}
    assert families["Area Swap Optimization"] == {"7series"}
    assert families["Small Shape DP"] == {"ultrascale", "ultrascale+"}
    assert families["Floorplanning"] is None                 # on both: no restriction


# ------------------------------------------------------------------ family filtering of placeholders
def snapshot_with_part(tmp_path, cfg, report_cache, catalogs, part, lines=507, replace=None):
    text = (SEVEN / "np_artix7.log").read_text()
    if part:
        text = text.replace("-part xc7a35tcpg236-1", "-part " + part, 1)
    for old, new in (replace or {}).items():
        text = text.replace(old, new, 1)
    log = tmp_path / "vivado.log"
    log.write_text("\n".join(text.split("\n")[:lines]) + "\n")
    return LogSource(canon(log), cfg, report_cache, catalogs).snapshot(LIVE, now=time.time())


def placeholders(fw, step_id):
    step = next(s for s in fw.flows[0].stages if s.id.endswith("/" + step_id))
    out = set()

    def walk(node):
        for child in node.children:
            if child.expected:
                out.add(re.sub(r"^[\d.]+\s+", "", child.label))
            walk(child)
    walk(step)
    return out


US_ONLY = {"Small Shape DP", "Fast Optimization", "Partition Driven Placement"}


def test_seven_series_firmware_has_no_ultrascale_only_placeholders(tmp_path, cfg, report_cache, catalogs):
    fw = snapshot_with_part(tmp_path, cfg, report_cache, catalogs, None)
    pending = placeholders(fw, "place_design")
    assert not (pending & US_ONLY)
    assert "Post Placement Optimization and Clean-Up" in pending             # the common phases stay
    assert fw.info["family"] == "7series" and "catalog_version" not in fw.info


def test_ultrascale_plus_firmware_keeps_them(tmp_path, cfg, report_cache, catalogs):
    fw = snapshot_with_part(tmp_path, cfg, report_cache, catalogs, "xczu48dr-ffvg1517-2-e")
    pending = placeholders(fw, "place_design")
    assert US_ONLY <= pending and "Area Swap Optimization" not in pending
    assert fw.info["family"] == "ultrascale+"


def test_unknown_family_behaves_as_before(tmp_path, cfg, report_cache, catalogs):
    fw = snapshot_with_part(tmp_path, cfg, report_cache, catalogs, "xcmystery-1")
    pending = placeholders(fw, "place_design")
    assert US_ONLY <= pending and fw.info["family"] is None


def test_route_placeholders_follow_the_family(tmp_path, cfg, report_cache, catalogs):
    seven = placeholders(snapshot_with_part(tmp_path, cfg, report_cache, catalogs, None, lines=640), "route_design")
    plus = placeholders(snapshot_with_part(tmp_path, cfg, report_cache, catalogs, "xczu48dr-ffvg1517-2-e",
                                           lines=640), "route_design")
    assert "Resolve XTalk" not in seven and "Global Clock Net Routing" not in seven
    assert {"Resolve XTalk", "Global Clock Net Routing"} <= plus


def pending_ids(fw):
    return [s.id.split("/")[1] for s in fw.flows[0].stages if s.status == "pending"]


def test_device_image_is_only_planned_for_versal(tmp_path, cfg, report_cache, catalogs):
    seven = pending_ids(snapshot_with_part(tmp_path, cfg, report_cache, catalogs, None))
    versal = pending_ids(snapshot_with_part(tmp_path, cfg, report_cache, catalogs, "xcvc1902-vsva2197-2MP-e-S"))
    assert "write_bitstream" in seven and "write_device_image" not in seven
    assert "write_device_image" in versal and "write_bitstream" not in versal


# ------------------------------------------------------------------ versions
def write_catalog(directory, version):
    (directory / ("vivado_%s.toml" % version)).write_text(
        '[catalog]\nschema = 1\nvivado = "%s"\n[[step]]\nid = "opt_design"\ncommand = "opt_design"\n' % version)


@pytest.mark.parametrize("asked,used", [
    ("2023.2", "2023.2"), ("2024.2", "2023.2"), ("2025.1", "2023.2"), ("2022.2", "2021.2"),
    ("2023.1", "2021.2"), ("2020.1", "2021.2"), ("2021.2", "2021.2"), (None, "2021.2"), ("garbage", "2021.2")])
def test_version_fallback_is_closest_older_else_oldest(tmp_path, asked, used):
    write_catalog(tmp_path, "2021.2")
    write_catalog(tmp_path, "2023.2")
    assert CatalogSet([tmp_path]).version_used(asked) == used


def test_shipped_catalog_serves_newer_and_older_versions(catalogs):
    for version in ("2024.2", "2025.1", "2022.2", "2019.1"):
        assert catalogs.version_used(version) == "2023.2"
        assert "place_design" in catalogs.get(version).steps


def test_no_catalog_means_no_family_and_no_version(tmp_path):
    empty = CatalogSet([tmp_path])
    assert empty.get("2023.2") is None and empty.family_of("xc7a35t") is None
    assert empty.version_used("2023.2") is None and empty.step_applies("write_bitstream", "versal")


def test_info_names_the_fallback_catalog(tmp_path, cfg, report_cache, catalogs):
    fw = snapshot_with_part(tmp_path, cfg, report_cache, catalogs, None, replace={"Vivado v2023.2": "Vivado v2025.1"})
    assert fw.vivado_version == "2025.1" and fw.info["catalog_version"] == "2023.2"


# ------------------------------------------------------------------ project mode (proj_artix7)
def test_project_mode_seven_series_flow(tmp_path, cfg, report_cache, catalogs):
    steps = ["init_design", "opt_design", "place_design", "phys_opt_design", "route_design", "write_bitstream"]
    markers = []
    for step in steps:
        markers += [(step, "begin"), (step, "error" if step == "write_bitstream" else "end")]
    runs = build_runs(tmp_path, "proj", "top", SEVEN / "proj_artix7" / "top.vdi", SEVEN / "proj_artix7" / "top.tcl",
                      SEVEN / "proj_artix7" / "top.vds", markers, vivado_end=True)
    fw = ProjectSource(runs, cfg, report_cache, catalogs).snapshot(None, now=1_010_000.0)
    stages = {s.id: s for s in fw.flows[0].stages}
    assert list(stages) == ["synth"] + ["impl_1/" + s for s in steps]
    assert stages["synth"].status == "done" and stages["impl_1/write_bitstream"].status == "failed"
    assert all(stages["impl_1/" + s].status == "done" for s in steps[:-1])
    for step in ("opt_design", "place_design", "route_design"):
        assert [n for n in stages["impl_1/" + step].children if not n.expected], step
    assert fw.info["family"] == "7series" and fw.info["part"] == "xc7a35tcpg236-1"
    assert fw.vivado_version == "2023.2" and "catalog_version" not in fw.info
