"""A launcher (`vivado -source build.tcl`) tied to its project from its log, before any run starts."""
from vmon.discovery import Discovery, Group
from vmon.monitor import Monitor

# Shape of a project-generating script as Vivado echoes it into vivado.log ("# " = executed line, "## " = comment).
ECHOED = """\
# set origin_dir [file normalize "."]
# set _xil_proj_name_ "top"
# if {[file exists "$origin_dir/top/top.xpr"]} {
# open_project "$origin_dir/top/top.xpr"
# } else {
# create_project ${_xil_proj_name_} ./${_xil_proj_name_} -part xczu49dr-ffvf1760-2-e
## create_project project_1 myproj -part xczu49dr-ffvf1760-2-e
# }
"""


def projects(cfg, text, cwd="/w"):
    return [runs for _, runs in Discovery(cfg)._projects_in(text, cwd)]


def test_echoed_script_resolves_the_project(cfg):
    assert set(projects(cfg, ECHOED)) == {"/w/top/top.runs"}


def test_variables_and_forms(cfg):
    assert projects(cfg, "set d [pwd]\nopen_project $d/a/b.xpr\n") == ["/w/a/b.runs"]
    assert projects(cfg, "create_project -force p1 /abs/dir -part xc\n") == ["/abs/dir/p1.runs"]
    assert projects(cfg, "create_project p2\n") == ["/w/p2.runs"]                      # dir defaults to cwd
    assert projects(cfg, "open_project {/p/a b/c.xpr}\n") == ["/p/a b/c.runs"]


def test_unresolved_or_in_memory_is_ignored(cfg):
    """The old rule turned `open_project "$origin_dir/..."` into a bogus .../$origin_dir/... project."""
    assert projects(cfg, '# open_project "$origin_dir/top/top.xpr"\n') == []
    assert projects(cfg, "create_project $name ./x\n") == []
    assert projects(cfg, "create_project -in_memory -part xc\n") == []
    assert projects(cfg, "## create_project project_1 myproj\n") == []                # a script comment


def test_last_project_wins_and_live_log(cfg, tmp_path):
    log = tmp_path / "vivado.log"
    log.write_text("open_project /p/old.xpr\n" + ECHOED)
    assert Discovery(cfg)._project_from_log(str(log), "/w") == "/w/top/top.runs"


def make_monitor(tmp_path, cfg):
    monitor = Monitor(cfg, recent_file=tmp_path / "cache" / "recent.json", rules_file=tmp_path / "rules.json")
    monitor.discovery.discover = lambda: []
    return monitor


def test_launcher_log_seen_alone_is_absorbed_by_its_project(cfg, tmp_path):
    log = tmp_path / "vivado.log"
    log.write_text(ECHOED)
    runs = tmp_path / "top" / "top.runs"                   # not created yet: the project is still being generated
    monitor = make_monitor(tmp_path, cfg)
    log_id = monitor._watch("log", str(log))                # what discovery produced before the project was known
    group = Group("project", str(runs), "top")
    group.launcher = {"pid": 1, "log": str(log), "script": "proj.tcl"}
    monitor.discovery.discover = lambda: [group]
    monitor.tick()
    assert log_id not in monitor.firmwares and log_id not in monitor.watched
    assert [fw.name for fw in monitor.firmwares.values()] == ["top"]
    assert "vivado.log" not in (tmp_path / "cache" / "recent.json").read_text()


def test_a_standalone_log_is_kept(cfg, tmp_path):
    log = tmp_path / "other.log"
    log.write_text("plain\n")
    monitor = make_monitor(tmp_path, cfg)
    log_id = monitor._watch("log", str(log))
    monitor.tick()
    assert log_id in monitor.firmwares


def discover_with(cfg, procs, parent_of):
    from vmon import procinfo

    class Backend(procinfo.NullBackend):
        def vivado_processes(self):
            return procs

        def process_table(self):
            return parent_of
    procinfo.set_backend(Backend())
    try:
        return Discovery(cfg).discover()
    finally:
        procinfo.set_backend(None)


def test_debug_core_helpers_are_part_of_their_run(cfg, tmp_path):
    """Debug-core generation spawns Vivados under impl_1/.Xil (and a nested prj_ip.runs): not resumes, not builds."""
    impl = tmp_path / "top.runs" / "impl_1"
    impl.mkdir(parents=True)
    xil = impl / ".Xil" / "Vivado-20-host" / "dc_drv.0" / "dc"
    procs = [
        {"pid": 20, "args": ["vivado", "-log", "top.vdi", "-mode", "batch"], "cwd": str(impl)},
        {"pid": 30, "args": ["vivado", "-mode", "batch", "-source", "debug_ip_core.tcl"], "cwd": str(xil)},
        {"pid": 40, "args": ["vivado", "-mode", "batch", "-source", "dbg_hub.tcl"],
         "cwd": str(xil / "prj_ip.runs" / "dbg")},
        {"pid": 50, "args": ["vivado", "-mode", "batch"], "cwd": str(impl)},   # a non-scratch child in the run dir
    ]
    groups = discover_with(cfg, procs, {20: 1, 25: 20, 30: 25, 40: 30, 50: 20})
    assert len(groups) == 1
    group = groups[0]
    assert group.resumes == [] and group.pids == {20, 30, 40, 50} and group.run_pids == {"impl_1": {20}}


def test_a_launchers_vivado_child_is_not_a_build(cfg, tmp_path):
    (tmp_path / "vivado.log").write_text("plain\n")
    procs = [{"pid": 10, "args": ["vivado", "-mode", "batch", "-source", "b.tcl"], "cwd": str(tmp_path)},
             {"pid": 11, "args": ["vivado", "-mode", "batch"], "cwd": str(tmp_path)}]
    groups = discover_with(cfg, procs, {10: 1, 11: 10})
    assert [(g.kind, g.pids) for g in groups] == [("log", {10, 11})]
