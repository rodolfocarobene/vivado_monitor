"""Platform layer: Windows logic through fakes (runs anywhere), the real ctypes layer only on Windows."""
import ctypes
import os
import struct
import sys

import pytest

from vmon import discovery, procinfo, sysstats, winapi
from vmon.procinfo_windows import WindowsBackend, is_vivado_image, memory_to_meminfo

windows_only = pytest.mark.skipif(sys.platform != "win32", reason="exercises the real Win32 API")


# ---------------------------------------------------------------- command line splitting
@pytest.mark.parametrize("line, argv", [
    ('vivado.exe -mode batch -log "C:\\a b\\x.log"', ["vivado.exe", "-mode", "batch", "-log", "C:\\a b\\x.log"]),
    ('"C:\\Program Files\\Xilinx\\vivado.exe" -source x.tcl', ["C:\\Program Files\\Xilinx\\vivado.exe", "-source", "x.tcl"]),
    ('a.exe "x\\\\" y', ["a.exe", "x\\", "y"]),                      # 2 backslashes + quote: one backslash, closes
    ('a.exe "x\\"y"', ["a.exe", 'x"y']),                             # 3 backslashes... odd: literal quote
    ('a.exe "say ""hi"""', ["a.exe", 'say "hi"']),
    ('a.exe C:\\dir\\sub\\ z', ["a.exe", "C:\\dir\\sub\\", "z"]),    # backslashes without quote stay literal
    ('a.exe  \t b', ["a.exe", "b"]),
    ('a.exe ""', ["a.exe", ""]),
    ('"C:\\p\\a.exe"', ["C:\\p\\a.exe"]),
])
def test_split_command_line(line, argv):
    assert winapi.split_command_line(line) == argv


# ---------------------------------------------------------------- PEB parsing
def fake_memory(cmdline, cwd, peb=0x1000, params=0x2000):
    mem = {}
    cmd_raw, cwd_raw = cmdline.encode("utf-16-le"), cwd.encode("utf-16-le")
    block = bytearray(winapi.PARAMS_READ_SIZE)
    struct.pack_into("<HH4xQ", block, winapi.PARAMS_CWD_OFFSET, len(cwd_raw), len(cwd_raw) + 2, 0x3000)
    struct.pack_into("<HH4xQ", block, winapi.PARAMS_CMDLINE_OFFSET, len(cmd_raw), len(cmd_raw) + 2, 0x4000)
    mem[(peb + winapi.PEB_PARAMS_OFFSET, 8)] = struct.pack("<Q", params)
    mem[(params, winapi.PARAMS_READ_SIZE)] = bytes(block)
    mem[(0x3000, len(cwd_raw))] = cwd_raw
    mem[(0x4000, len(cmd_raw))] = cmd_raw
    return lambda address, size: mem.get((address, size)), peb


def test_read_process_params():
    read, peb = fake_memory('vivado.exe -log "x y.log"', "C:\\work\\p\\p.runs\\impl_1\\")
    assert winapi.read_process_params(read, peb) == ('vivado.exe -log "x y.log"', "C:\\work\\p\\p.runs\\impl_1")


def test_read_process_params_unreadable():
    assert winapi.read_process_params(lambda a, s: None, 0x1000) == (None, None)
    read, peb = fake_memory("a", "C:\\")
    partial = lambda address, size: None if address == 0x4000 else read(address, size)
    assert winapi.read_process_params(partial, peb) == (None, "C:\\")


def test_unicode_string_and_helpers():
    raw = struct.pack("<HH4xQ", 6, 8, 0xDEADBEEF)
    assert winapi.unicode_string_at(raw, 0) == (6, 0xDEADBEEF)
    assert winapi.wide_to_str("ab\0cd".encode("utf-16-le")) == "ab"
    assert winapi.strip_trailing_sep("C:\\") == "C:\\" and winapi.strip_trailing_sep("C:\\x\\") == "C:\\x"
    assert winapi.filetime_value(winapi.FILETIME(1, 2)) == (2 << 32) | 1


@pytest.mark.skipif(ctypes.sizeof(ctypes.c_void_p) != 8, reason="x64 layouts")
def test_structure_sizes_x64():
    assert ctypes.sizeof(winapi.PROCESSENTRY32W) == 568
    assert ctypes.sizeof(winapi.PROCESS_BASIC_INFORMATION) == 48
    assert ctypes.sizeof(winapi.MEMORYSTATUSEX) == 64
    assert ctypes.sizeof(winapi.PROCESS_MEMORY_COUNTERS) == 72
    assert winapi.PROCESS_BASIC_INFORMATION.PebBaseAddress.offset == 8
    assert winapi.PROCESS_BASIC_INFORMATION.UniqueProcessId.offset == 32


# ---------------------------------------------------------------- Vivado identification, paths
def test_vivado_image_names():
    assert is_vivado_image("vivado.exe") and is_vivado_image("VIVADO.EXE") and is_vivado_image("Vivado.exe")
    assert not any(is_vivado_image(n) for n in ("vivado.bat", "loader.exe", "cmd.exe", "vivado_lab.exe", "vivado"))


@pytest.mark.parametrize("cwd, expected", [
    ("C:\\work\\proj\\proj.runs\\impl_1", ("C:\\work\\proj\\proj.runs", "impl_1")),
    ("C:\\work\\proj\\proj.runs\\impl_1\\", ("C:\\work\\proj\\proj.runs", "impl_1")),
    ("c:/work/proj/proj.runs/impl_1", ("c:\\work\\proj\\proj.runs", "impl_1")),
    ("C:\\Work\\Proj\\PROJ.RUNS\\synth_1", ("C:\\Work\\Proj\\PROJ.RUNS", "synth_1")),
    ("D:\\a\\x.runs", ("D:\\a\\x.runs", None)),
    ("\\\\server\\share\\x.runs\\impl_1", ("\\\\server\\share\\x.runs", "impl_1")),
    ("C:\\work\\proj", None),
    ("C:\\work\\.runs\\impl_1", None),
])
def test_runs_location_windows_paths(cwd, expected):
    assert discovery.runs_location(cwd) == expected


def test_runs_location_posix_unchanged():
    assert discovery.runs_location("/x/foo.runs/impl_1") == ("/x/foo.runs", "impl_1")
    assert discovery.runs_location("/x/foo") is None


def test_basename_windows_and_posix():
    assert discovery._basename("C:\\w\\foo.runs") == "foo.runs" and discovery._basename("/w/foo.runs") == "foo.runs"


# ---------------------------------------------------------------- fake Windows API
class FakeApi:
    def __init__(self):
        self.entries = [(4, 0, "System"), (100, 4, "cmd.exe"), (200, 100, "vivado.exe"), (300, 200, "VIVADO.EXE"),
                        (400, 4, "notepad.exe")]
        self.params = {200: ('"C:\\Xilinx\\bin\\vivado.exe" -mode batch -log "C:\\w\\p\\p.runs\\impl_1\\a.vdi"',
                             "C:\\w\\p\\p.runs\\impl_1"),
                       300: (None, None)}
        self.cpu = {200: 12.5, 300: 1.0}
        self.rss = {200: 3 * 1024 * 1024, 300: 0}
        self.times = (500, 1000, 600)
        self.status = {"total_phys": 16 << 30, "avail_phys": 6 << 30, "total_pagefile": 24 << 30, "avail_pagefile": 12 << 30}
        self.live = {200}

    def process_entries(self):
        return self.entries

    def command_line_and_cwd(self, pid):
        return self.params.get(pid, (None, None))

    def alive(self, pid):
        return pid in self.live

    def process_cpu_seconds(self, pid):
        return self.cpu.get(pid)

    def working_set_bytes(self, pid):
        return self.rss.get(pid)

    def system_times(self):
        return self.times

    def memory_status(self):
        return self.status


def test_windows_backend_vivado_processes():
    found = WindowsBackend(FakeApi()).vivado_processes()
    assert [p["pid"] for p in found] == [200, 300]
    assert found[0] == {"pid": 200, "ppid": 100, "cwd": "C:\\w\\p\\p.runs\\impl_1",
                        "args": ["C:\\Xilinx\\bin\\vivado.exe", "-mode", "batch", "-log", "C:\\w\\p\\p.runs\\impl_1\\a.vdi"]}
    assert found[1]["args"] == [] and found[1]["cwd"] is None           # access denied: fields skipped


def test_windows_backend_table_liveness_and_resources():
    backend = WindowsBackend(FakeApi())
    assert backend.process_table()[300] == 200 and backend.process_table()[100] == 4
    assert backend.alive(200) and not backend.alive(201) and not backend.alive(None) and not backend.alive(0)
    assert backend.cpu_seconds(200) == 12.5 and backend.cpu_seconds(999) is None
    assert backend.rss_kb(200) == 3 * 1024 * 1024 // 1024 and backend.rss_kb(300) == 0 and backend.rss_kb(999) == 0
    assert backend.load1() is None and backend.cpu_count() >= 1


def test_windows_cpu_percent_from_filetime_deltas():
    api = FakeApi()
    backend = WindowsBackend(api)
    sampler = sysstats.Sampler(backend=backend)
    assert sampler.system()["cpu_pct"] == 0.0                     # first sample has no delta
    api.times = (500 + 250, 1000 + 1000, 600 + 500)               # kernel includes idle: busy = 1500-250 of 1500
    snap = sampler.system()
    assert snap["cpu_pct"] == pytest.approx(83.3) and snap["load1"] is None


def test_memory_snapshot_mapping():
    meminfo = memory_to_meminfo(FakeApi().status)
    assert meminfo == {"MemTotal": 16 << 20, "MemAvailable": 6 << 20, "SwapTotal": 8 << 20, "SwapFree": 6 << 20}
    snap = sysstats.system_snapshot(1.0, meminfo, None, 8)
    assert snap["mem_used_mb"] == 10240.0 and snap["swap_total_mb"] == 8192.0 and snap["swap_used_mb"] == 2048.0
    none = memory_to_meminfo({"total_phys": 8 << 30, "avail_phys": 1 << 30, "total_pagefile": 4 << 30, "avail_pagefile": 3 << 30})
    assert none["SwapTotal"] == 0 and none["SwapFree"] == 0       # clamped, never negative


def test_sampler_with_windows_backend_sums_descendants():
    api = FakeApi()
    sampler = sysstats.Sampler(backend=WindowsBackend(api))
    assert sampler.resources({"fw": [100]}, now=10.0)["fw"] == {"cpu_pct": 0.0, "rss_mb": 3.0}
    api.cpu = {200: 12.5 + 1.0, 300: 1.0 + 0.5}                   # tree 100 -> 200 -> 300
    out = sampler.resources({"fw": [100], "idle": []}, now=11.0)
    assert out["fw"]["cpu_pct"] == pytest.approx(150.0) and out["idle"] is None


# ---------------------------------------------------------------- selection
def test_backend_selection(capsys):
    assert procinfo.make_backend("linux").name == "linux"
    null = procinfo.make_backend("darwin")
    assert null.name == "none" and "not supported on darwin" in capsys.readouterr().err
    assert null.vivado_processes() == [] and null.process_table() == {} and null.cpu_times() is None
    assert null.meminfo() == {} and null.load1() is None and null.rss_kb(1) == 0 and null.cpu_count() >= 1
    assert sysstats.Sampler(backend=null).system()["mem_total_mb"] == 0.0


def test_discovery_uses_overridden_backend():
    class Backend(procinfo.NullBackend):
        def alive(self, pid):
            return pid == 7
    procinfo.set_backend(Backend())
    try:
        assert discovery.pid_alive(7) and not discovery.pid_alive(8) and not discovery.pid_alive(None)
        assert discovery.scan_vivado() == []
    finally:
        procinfo.set_backend(None)


# ---------------------------------------------------------------- real Win32 layer (CI windows-latest)
@windows_only
def test_real_windows_backend_sees_this_process():
    backend = WindowsBackend()
    me = os.getpid()
    table = backend.process_table()
    assert me in table and table[me] == os.getppid()
    assert backend.alive(me) and not backend.alive(4_000_000)
    assert backend.rss_kb(me) > 0 and backend.cpu_seconds(me) >= 0.0
    api = backend.api
    cmdline, cwd = api.command_line_and_cwd(me)
    if ctypes.sizeof(ctypes.c_void_p) == 8:
        argv = backend._argv(cmdline)
        assert any("python" in a.lower() or "pytest" in a.lower() for a in argv)
        assert os.path.normcase(cwd) == os.path.normcase(os.getcwd())
        assert winapi.split_command_line(cmdline) == api.command_line_to_argv(cmdline)


@windows_only
def test_real_system_stats_are_sane():
    backend = WindowsBackend()
    first = backend.cpu_times()
    sum(i * i for i in range(200_000))
    second = backend.cpu_times()
    assert second[0] >= first[0] and 0.0 <= sysstats.cpu_percent(first, second) <= 100.0
    mem = backend.meminfo()
    assert mem["MemTotal"] > mem["MemAvailable"] > 0 and mem["SwapTotal"] >= mem["SwapFree"] >= 0
    snap = sysstats.system_snapshot(0.0, mem, backend.load1(), backend.cpu_count())
    assert snap["load1"] is None and snap["cpu_count"] >= 1 and snap["mem_total_mb"] > 0


@windows_only
def test_real_sampler_and_selector():
    assert procinfo.get_backend().name == "windows"
    out = sysstats.Sampler().resources({"me": [os.getpid()]}, now=1.0)["me"]
    assert out["rss_mb"] > 0
    assert discovery.pid_alive(os.getpid())
    assert isinstance(discovery.scan_vivado(), list)
