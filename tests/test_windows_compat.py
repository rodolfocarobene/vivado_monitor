"""Windows robustness that can be checked anywhere: data dirs, path contract, CRLF files, replacement detection."""
import os
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest
from conftest import FIXTURES, redirect_profile
from test_logparse import dump
from test_v6 import feed, route_step, step_of
from vmon import discovery, failure, info, paths, procinfo, timing_paths
from vmon.logparse import LogParser
from vmon.logtail import LogTail, file_identity
from vmon.project import fw_id
from vmon.resume import scan_session

QICK = FIXTURES / "qick"
CRASH = FIXTURES / "crash"


def windows(monkeypatch):
    monkeypatch.setattr(sys, "platform", "win32")


def posix(monkeypatch):
    monkeypatch.setattr(sys, "platform", "linux")


# ---------------------------------------------------------------- data directories
def test_data_dirs_follow_the_isolated_profile_on_linux(monkeypatch):
    monkeypatch.setattr(sys, "platform", "linux")
    home = Path.home()
    assert paths.cache_dir() == home / ".cache" / "vmon" and paths.config_dir() == home / ".config" / "vmon"


def test_data_dirs_on_windows_use_localappdata_and_appdata(tmp_path, monkeypatch):
    windows(monkeypatch)
    home = Path(os.environ["USERPROFILE"])
    assert paths.cache_dir() == Path(os.environ["LOCALAPPDATA"]) / "vmon"
    assert paths.config_dir() == Path(os.environ["APPDATA"]) / "vmon"
    assert str(paths.cache_dir()).startswith(str(home)) and str(paths.config_dir()).startswith(str(home))   # inside the tmp profile
    monkeypatch.delenv("LOCALAPPDATA")
    monkeypatch.delenv("APPDATA")
    assert paths.cache_dir() == home / "AppData" / "Local" / "vmon"
    assert paths.config_dir() == home / "AppData" / "Roaming" / "vmon"


def test_isolation_redirects_every_profile_variable(tmp_path):
    session_home = Path(os.environ["HOME"])
    for name in ("USERPROFILE", "LOCALAPPDATA", "APPDATA", "XDG_CACHE_HOME", "XDG_CONFIG_HOME"):
        assert Path(os.environ[name]).is_relative_to(session_home), name
    assert Path.home() == session_home and not (session_home / "vmon").exists()
    real = Path(os.path.expanduser("~"))
    assert real == session_home                                  # expanduser agrees on POSIX and Windows


def test_stores_land_in_the_tmp_profile(cfg):
    from vmon.attempts import AttemptStore
    from vmon.monitor import Monitor
    monitor = Monitor(cfg)
    assert monitor.recent_file == paths.cache_dir() / "recent.json"
    assert AttemptStore(None, "x").path == paths.cache_dir() / "attempts" / "x.json"
    assert Path.home() in monitor.recent_file.parents


def test_redirect_profile_helper_is_complete(tmp_path, monkeypatch):
    redirect_profile(monkeypatch, tmp_path / "p")
    assert Path.home() == tmp_path / "p" and os.environ["LOCALAPPDATA"] == str(tmp_path / "p" / "AppData" / "Local")


# ---------------------------------------------------------------- path contract
def test_runs_location_keeps_the_input_syntax_on_every_os(monkeypatch):
    for platform in ("linux", "win32"):
        monkeypatch.setattr(sys, "platform", platform)
        assert discovery.runs_location("/x/foo.runs/impl_1") == ("/x/foo.runs", "impl_1")
        assert discovery.runs_location("C:\\x\\foo.runs\\impl_1") == ("C:\\x\\foo.runs", "impl_1")
        assert discovery.runs_location("C:/x/foo.runs/impl_1") == ("C:\\x\\foo.runs", "impl_1")
        assert discovery.runs_location("/x/foo") is None


def test_canon_and_path_key(monkeypatch):
    posix(monkeypatch)
    assert paths.canon("C:/a/b") == "C:/a/b" and paths.path_key("C:\\A") == "C:\\A"          # untouched off Windows
    windows(monkeypatch)
    assert paths.canon("c:/a//b/../c/") == "C:\\a\\c" and paths.canon("\\\\srv\\sh\\x") == "\\\\srv\\sh\\x"
    assert paths.path_key("C:/Work/P.runs") == paths.path_key("c:\\work\\p.RUNS\\")
    assert paths.same_path("C:/a/b", "c:\\A\\B") and not paths.same_path("C:/a", "C:/b")


def test_firmware_id_is_stable_across_spellings_on_windows(monkeypatch):
    posix(monkeypatch)
    assert fw_id("/a/p.runs") != fw_id("/A/p.runs")                                          # POSIX is case-sensitive
    windows(monkeypatch)
    assert fw_id("C:/w/P.runs") == fw_id("c:\\W\\p.RUNS")


def test_path_helpers_accept_both_separators_off_windows():
    assert paths.is_abs("C:/x/y.xpr") and paths.is_abs("C:\\x") and not paths.is_abs("x\\y")
    assert paths.dirname("C:\\x\\y.xpr") == "C:\\x" and paths.normpath("C:/a/./b/../c") == "C:\\a\\c"
    assert paths.split_name("C:\\x\\y\\main_physopt.dcp") == paths.split_name("C:/x/y/main_physopt.dcp") == "main_physopt.dcp"
    assert paths.basename("C:\\x\\p.runs") == "p.runs" and paths.basename("/x/p.runs") == "p.runs"


def test_discovery_groups_windows_spellings_together(cfg, monkeypatch):
    windows(monkeypatch)
    procs = [
        {"pid": 10, "ppid": 1, "cwd": "c:/w/p/p.runs/impl_1", "args": ["vivado.exe", "-log", "c:/w/p/p.runs/impl_1/top.vdi"]},
        {"pid": 11, "ppid": 1, "cwd": "C:\\W\\p\\p.runs\\synth_1", "args": ["vivado.exe", "-log", "runme.log"]},
    ]

    class Backend(procinfo.NullBackend):
        def vivado_processes(self):
            return procs

        def process_table(self):
            return {10: 1, 11: 1}

    procinfo.set_backend(Backend())
    try:
        groups = discovery.Discovery(cfg).discover()
    finally:
        procinfo.set_backend(None)
    assert len(groups) == 1 and groups[0].path == "C:\\w\\p\\p.runs" and groups[0].name == "p"
    assert groups[0].pids == {10, 11} and set(groups[0].run_pids) == {"impl_1", "synth_1"}


def test_run_worker_compares_case_insensitively_on_windows(monkeypatch):
    proc = {"args": ["vivado.exe", "-log", "c:/W/P/p.runs/impl_1/top.vdi"], "cwd": "C:\\w\\p\\p.runs\\impl_1"}
    posix(monkeypatch)
    assert not discovery.is_run_worker(proc, "C:\\w\\p\\p.runs\\impl_1")                     # exact compare off Windows
    windows(monkeypatch)
    assert discovery.is_run_worker(proc, "C:\\w\\p\\p.runs\\impl_1")


def test_project_from_log_reads_windows_open_project(cfg, tmp_path, monkeypatch):
    log = tmp_path / "vivado.log"
    log.write_bytes(b"INFO: x\r\nopen_project C:/work/proj/x.xpr\r\nopen_project {C:\\work\\x\\top.xpr}\r\n")
    found = discovery.Discovery(cfg)._project_from_log(str(log), None)
    assert paths.basename(found) == "top.runs" and paths.dirname(found).lower().endswith("x")


# ---------------------------------------------------------------- CRLF
def variants(src, tmp_path):
    """The fixture as LF and as CRLF (whatever git checked out), written fresh so they differ only in line endings."""
    data = Path(src).read_bytes().replace(b"\r\n", b"\n")
    lf, crlf = tmp_path / "lf" / Path(src).name, tmp_path / "crlf" / Path(src).name
    for path, content in ((lf, data), (crlf, data.replace(b"\n", b"\r\n"))):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)
    assert b"\r\n" in crlf.read_bytes() and b"\r" not in lf.read_bytes()
    return lf, crlf


def tailed(path):
    return LogTail(path).poll()[0]


@pytest.mark.parametrize("fixture", [FIXTURES / "lockin" / "main_wrapper.vdi", QICK / "d_1_wrapper.vdi",
                                     QICK / "congestion.vdi", QICK / "route_iterations.vdi"])
def test_vdi_crlf_parses_identically(cfg, tmp_path, fixture):
    lf, crlf = variants(fixture, tmp_path)
    lines_lf, lines_crlf = tailed(lf), tailed(crlf)
    assert lines_crlf == lines_lf and not any("\r" in line for line in lines_crlf)
    a, b = LogParser(cfg), LogParser(cfg)
    a.feed(lines_lf)
    b.feed(lines_crlf)
    assert dump(b.root) == dump(a.root) and b.messages == a.messages and b.version == a.version


def test_convergence_and_congestion_from_a_crlf_log(cfg, tmp_path):
    lf, crlf = variants(QICK / "route_iterations.vdi", tmp_path)
    assert route_step(feed(tailed(crlf), cfg)).iters == route_step(feed(tailed(lf), cfg)).iters
    lf, crlf = variants(QICK / "congestion.vdi", tmp_path / "c")
    assert step_of(feed(tailed(crlf), cfg), "place_design").congestion == step_of(feed(tailed(lf), cfg), "place_design").congestion
    assert step_of(feed(tailed(crlf), cfg), "route_design").congestion == step_of(feed(tailed(lf), cfg), "route_design").congestion


def test_tail_with_the_crlf_split_across_reads(tmp_path):
    lf, crlf = variants(QICK / "d_1_wrapper.vdi", tmp_path)
    expected, data = tailed(lf), crlf.read_bytes()
    cuts = [i for i in range(1, len(data)) if data[i - 1:i + 1] == b"\r\n"][:40]     # between \r and \n
    cuts += [i for i in range(1, len(data), 997)]                                    # and mid-line
    live = tmp_path / "live.vdi"
    for cut in sorted(set(cuts))[:60]:
        live.write_bytes(b"")
        tail, got, pos = LogTail(live), [], 0
        for end in (cut, len(data)):
            with open(live, "ab") as fh:
                fh.write(data[pos:end])
            pos = end
            got += tail.poll()[0]
        assert got == expected, cut
        assert tail.offset == len(data) and tail.line_count == len(expected)


def test_tail_offsets_are_bytes_so_ranges_read_back_exactly(tmp_path):
    rows = ["INFO: [Common 17-1] row %d" % i for i in range(2600)]
    path = tmp_path / "big.log"
    path.write_bytes(("\r\n".join(rows) + "\r\n").encode())
    tail = LogTail(path)
    assert tail.poll()[0] == rows
    for start, end in ((1, 3), (999, 1002), (1000, 2001), (2001, 2005), (2599, 2600)):
        assert tail.read_range(start, end) == rows[start - 1:end]


def test_tail_detects_replacement_without_inode(tmp_path, monkeypatch):
    path = tmp_path / "x.log"
    path.write_bytes(b"one\r\ntwo\r\n")
    tail = LogTail(path)
    real_stat = os.stat
    monkeypatch.setattr("vmon.logtail.os.stat", lambda p: _fake_ino(real_stat(p), 0))
    assert tail.poll()[0] == ["one", "two"]
    path.write_bytes(b"1\r\n")                                                  # replaced by a smaller file
    lines, reset = tail.poll()
    assert reset and lines == ["1"]


def _fake_ino(st, ino):
    return SimpleNamespace(st_ino=ino, st_size=st.st_size, st_mtime=st.st_mtime, st_ctime_ns=st.st_ctime_ns)


def test_file_identity_fallbacks(monkeypatch):
    st = lambda **kw: SimpleNamespace(**{"st_ino": 0, "st_ctime_ns": 5, **kw})
    assert file_identity(st(st_ino=7)) == 7
    assert file_identity(st(st_birthtime=1.5)) == "born:1.5"
    assert file_identity(st()) == 0                                              # no inode, not Windows: size shrink only
    windows(monkeypatch)
    assert file_identity(st()) == "born:5"


def test_tail_tolerates_a_locked_file(tmp_path, monkeypatch):
    path = tmp_path / "locked.log"
    path.write_bytes(b"a\r\nb\r\n")
    tail = LogTail(path)
    real_open = open
    monkeypatch.setattr("builtins.open", lambda *a, **k: (_ for _ in ()).throw(PermissionError("locked")))
    assert tail.poll() == ([], False)
    monkeypatch.setattr("builtins.open", real_open)
    assert tail.poll()[0] == ["a", "b"]                                           # picked up on the next poll


def test_reports_crlf_equal_to_lf(report_cache, tmp_path):
    lf, crlf = variants(QICK / "d_1_wrapper_timing_summary_routed.rpt", tmp_path)
    a, b = report_cache.parse(str(lf), "timing"), report_cache.parse(str(crlf), "timing")
    assert b == a and a[0]["wns"] == 0.006
    lf, crlf = variants(QICK / "d_1_wrapper_utilization_placed.rpt", tmp_path / "u")
    a, b = report_cache.parse(str(lf), "utilization"), report_cache.parse(str(crlf), "utilization")
    assert b == a and {r["name"]: r["used"] for r in b[0]["rows"]}["LUT"] == 84081
    for name, parser in (("drc_routed", "drc"), ("route_status", "route_status"), ("power_routed", "power")):
        lf, crlf = variants(QICK / ("d_1_wrapper_%s.rpt" % name), tmp_path / name)
        assert report_cache.parse(str(crlf), parser) == report_cache.parse(str(lf), parser)


def test_timing_paths_crlf_equal_to_lf(tmp_path):
    for name in ("timing_paths_excerpt.rpt", "timing_paths_tables.rpt"):
        lf, crlf = variants(FIXTURES / "paths" / name, tmp_path / name)
        a, b = timing_paths.parse_file(str(lf)), timing_paths.parse_file(str(crlf))
        assert b == a and a["counts"]["total"] > 0


def test_failure_detection_on_a_crlf_runme_log(cfg, tmp_path):
    lf, crlf = variants(CRASH / "route_crash_runme.log", tmp_path)
    a, b = failure.detect([str(lf)], cfg), failure.detect([str(crlf)], cfg)
    assert a and a["reason"].startswith("Segmentation fault")
    assert {k: v for k, v in b.items() if k != "log"} == {k: v for k, v in a.items() if k != "log"}
    hs_lf, hs_crlf = variants(CRASH / "hs_err_pid563188.log", tmp_path / "hs")
    assert failure.read_hs_err(str(hs_crlf), cfg) == failure.read_hs_err(str(hs_lf), cfg)


def test_command_scan_and_resume_session_on_crlf_logs(cfg, tmp_path):
    lf, crlf = variants(QICK / "d_1_wrapper.vdi", tmp_path)
    assert info.InfoReader().scan_log(str(crlf)) == info.InfoReader().scan_log(str(lf))
    lf, crlf = variants(CRASH / "resume.log", tmp_path / "r")
    a, b = scan_session(str(lf), "/w", cfg), scan_session(str(crlf), "/w", cfg)
    assert b == a and a["checkpoint"] and not a["checkpoint"].endswith("\r")


def test_info_text_files_with_crlf(tmp_path):
    lf, crlf = variants(FIXTURES / "info" / "gen_run.xml", tmp_path)
    reader = info.InfoReader()
    assert reader.gen_run(crlf) == reader.gen_run(lf)
    lf, crlf = variants(QICK / "d_1_wrapper.tcl", tmp_path / "t")
    assert reader.jobs_from_tcl(crlf) == reader.jobs_from_tcl(lf)


def test_open_project_regex_on_a_crlf_log(cfg, tmp_path):
    log = tmp_path / "vivado.log"
    log.write_bytes(b"open_project C:/work/x/top.xpr\r\n")
    assert paths.basename(discovery.Discovery(cfg)._project_from_log(str(log), None)) == "top.runs"


# ---------------------------------------------------------------- atomic writes
def test_write_atomic_retries_a_locked_target(tmp_path, monkeypatch):
    target = tmp_path / "sub" / "x.json"
    real, calls = os.replace, []

    def flaky(src, dst):
        calls.append(1)
        if len(calls) < 3:
            raise PermissionError("in use")
        real(src, dst)

    monkeypatch.setattr(paths.os, "replace", flaky)
    monkeypatch.setattr(paths.time, "sleep", lambda s: None)
    paths.write_atomic(target, '{"a": 1}')
    assert len(calls) == 3 and target.read_text() == '{"a": 1}' and not list(target.parent.glob("*.tmp"))
    monkeypatch.setattr(paths.os, "replace", lambda s, d: (_ for _ in ()).throw(PermissionError("locked")))
    with pytest.raises(PermissionError):
        paths.write_atomic(target, "{}")
    assert target.read_text() == '{"a": 1}'                      # the old content survives a failed replace


def test_ssh_argv_uses_the_windows_client(monkeypatch):
    from vmon.remote import ssh_argv
    assert ssh_argv("me@host", 9000)[0] == "ssh"
    windows(monkeypatch)
    argv = ssh_argv("me@host:8800", 9000)
    assert argv[0] == "ssh.exe" and "9000:127.0.0.1:8800" in argv and argv[-2:] == ["--", "me@host"]
