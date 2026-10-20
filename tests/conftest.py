import os
import shutil
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from vmon.config import load_config          # noqa: E402
from vmon.expected import CatalogSet         # noqa: E402
from vmon.reports import ReportCache         # noqa: E402

FIXTURES = Path(__file__).parent / "fixtures"
DEAD_PID = 4_000_000          # beyond pid_max on typical systems


@pytest.fixture(scope="session")
def catalogs():
    return CatalogSet()


@pytest.fixture()
def cfg(catalogs):
    config = load_config()
    catalogs.apply_to_config(config)
    return config


@pytest.fixture()
def report_cache(cfg):
    return ReportCache(cfg)


def read_lines(path):
    return Path(path).read_text(errors="replace").split("\n")[:-1]


def marker(path, pid=DEAD_PID, mtime=None):
    path.write_text('<?xml version="1.0"?>\n<ProcessHandle><Process Command="vivado" Pid="%d"/></ProcessHandle>' % pid)
    if mtime:
        os.utime(path, (mtime, mtime))


def touch(path, mtime):
    path.write_text("")
    os.utime(path, (mtime, mtime))


JOBS_XML = """<?xml version="1.0"?>
<Runs Version="1" Minor="0">
  <Run Id="ip_synth_1" FlowId="Vivado_Synthesis"/>
  <Run Id="synth_1" FlowId="Vivado_Synthesis"><Parent Id="ip_synth_1"/></Run>
  <Run Id="impl_1" FlowId="Vivado_Implementation"><Parent Id="synth_1"/><Parent Id="ip_synth_1"/></Run>
</Runs>
"""


def build_runs(tmp_path, name, top, impl_vdi, impl_tcl, synth_vds, impl_markers, impl_pid=DEAD_PID,
               vivado_end=False, t0=1_000_000.0):
    """Fake <name>.runs tree with real log excerpts; impl_markers = list of (step, 'begin'|'end')."""
    runs = tmp_path / (name + ".runs")
    (runs / ".jobs").mkdir(parents=True)
    (runs / ".jobs" / "vrs_config_1.xml").write_text(JOBS_XML)
    for synth in ("ip_synth_1", "synth_1"):
        d = runs / synth
        d.mkdir()
        shutil.copy(synth_vds, d / (top + ".vds"))
        marker(d / ".vivado.begin.rst", mtime=t0)
        touch(d / ".vivado.end.rst", t0 + 100)
        touch(d / "__synthesis_is_complete__", t0 + 100)
    impl = runs / "impl_1"
    impl.mkdir()
    shutil.copy(impl_vdi, impl / (top + ".vdi"))
    shutil.copy(impl_tcl, impl / (top + ".tcl"))
    touch(impl / ".Vivado_Implementation.queue.rst", t0)
    marker(impl / ".vivado.begin.rst", pid=impl_pid, mtime=t0 + 200)
    if vivado_end:
        touch(impl / ".vivado.end.rst", t0 + 5000)
    for i, (step, kind) in enumerate(impl_markers):
        path = impl / (".%s.%s.rst" % (step, kind))
        if kind == "begin":
            marker(path, pid=impl_pid, mtime=t0 + 200 + i * 100)
        else:
            touch(path, t0 + 200 + i * 100)
    return runs


@pytest.fixture(autouse=True)
def isolated_home(tmp_path_factory, monkeypatch):
    """Nothing in the tests may touch the real ~/.cache or ~/.config."""
    monkeypatch.setenv("HOME", str(tmp_path_factory.mktemp("home")))
