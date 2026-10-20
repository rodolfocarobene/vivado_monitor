import json

from conftest import FIXTURES, read_lines
from vmon.logparse import LogParser, hms_to_seconds, parse_number
from vmon.logtail import LogTail


def parse(cfg, path, catalogs=None):
    parser = LogParser(cfg, catalogs)
    parser.feed(read_lines(path))
    return parser


def dump(node):
    return [node.kind, node.label, node.status, node.line_start, node.line_end, node.own, node.elapsed_s,
            [dump(c) for c in node.children]]


def steps(parser):
    return {c.label: c for c in parser.root.children}


def test_message_counting_and_rollup(cfg):
    parser = parse(cfg, FIXTURES / "lockin" / "main_wrapper.vdi")
    assert parser.version == "2023.2"
    totals = parser.root.rolled_counts()
    by_sev = [0, 0, 0, 0]
    for _, sev, _, _ in parser.messages:
        by_sev[sev] += 1
    assert totals == by_sev and totals[1] > 0
    link, opt = steps(parser)["link_design"], steps(parser)["opt_design"]
    # the tool's summary counts are cumulative over the session
    assert opt.summary[1] - link.summary[1] == opt.rolled_counts()[1]
    assert link.line_start == 1                               # preamble belongs to the first step


def test_phase_nesting_and_status(cfg):
    parser = parse(cfg, FIXTURES / "lockin" / "main_wrapper.vdi")
    place = steps(parser)["place_design"]
    assert place.status == "running"
    placer = place.children[0]
    assert placer.kind == "task" and placer.status == "running"
    phase1 = placer.children[0]
    assert phase1.label == "Placer Initialization" and phase1.status == "running"
    assert phase1.children[0].status == "done"
    assert [c.number for c in phase1.children[:2]] == ["1.1", "1.2"]
    assert phase1.children[0].key == "p1.1"
    assert steps(parser)["opt_design"].status == "done"


def test_task_without_ending_closes_on_time_line(cfg):
    parser = parse(cfg, FIXTURES / "lockin" / "main_wrapper.vdi")
    drc = steps(parser)["opt_design"].children[0]
    assert drc.label == "DRC Task" and drc.status == "done" and drc.elapsed_s == 20.0


def test_phase_elapsed_is_difference_of_cumulative_readings(cfg):
    parser = parse(cfg, FIXTURES / "lockin" / "main_wrapper.vdi")
    logic = next(c for c in steps(parser)["opt_design"].children if c.label == "Logic Optimization Task")
    init, timer = logic.children[0], logic.children[1]
    assert init.elapsed_s == 24.0                 # cumulative 0:24 since the task start
    assert timer.elapsed_s == 173.0               # cumulative 3:17 minus 0:24


def test_timing_history_and_na(cfg):
    parser = parse(cfg, FIXTURES / "qick" / "d_1_wrapper.vdi")
    sections = steps(parser)
    place = [(h["label"], h["wns"], h["tns"]) for h in sections["place_design"].history]
    assert ("Estimated", -0.132, -10.875) in place and ("Post Placement", 0.038, None) in place
    route = sections["route_design"].history
    assert any(h["whs"] is None and h["ths"] is None for h in route)         # WHS=N/A
    assert route[-1]["label"] == "Post Routing" and route[-1]["wns"] == 0.006
    assert parse_number("N/A") is None and hms_to_seconds("01:02:03.5") == 3723.5


def test_synth_pairs(cfg):
    parser = parse(cfg, FIXTURES / "lockin" / "main_wrapper.vds")
    synth = steps(parser)["synth_design"]
    labels = [c.label for c in synth.children]
    assert "RTL Elaboration" in labels and "Constraint Validation" in labels
    assert all(c.status == "done" for c in synth.children)
    assert synth.status == "done" and synth.peak_mem is not None


def test_write_bitstream_stages_from_catalog(cfg, catalogs):
    parser = LogParser(cfg, catalogs)
    parser.feed(["# Vivado v2023.2 (64-bit)", "Command: write_bitstream -force x.bit",
                 "Running DRC as a precondition to command write_bitstream", "Loading data files...",
                 "Creating bitmap...", "INFO: [Vivado 12-1842] Bitgen Completed Successfully.",
                 "write_bitstream completed successfully"])
    bit = steps(parser)["write_bitstream"]
    assert [c.label for c in bit.children] == ["Running DRC", "Loading data files", "Creating bitmap",
                                               "Bitgen completed"]
    assert bit.status == "done" and all(c.status == "done" for c in bit.children)


def test_incremental_equals_whole_in_arbitrary_chunks(cfg):
    lines = read_lines(FIXTURES / "qick" / "d_1_wrapper.vdi")
    whole = LogParser(cfg)
    whole.feed(lines)
    for size in (1, 7, 100):
        chunked = LogParser(cfg)
        for i in range(0, len(lines), size):
            chunked.feed(lines[i:i + size])
        assert json.dumps(dump(chunked.root)) == json.dumps(dump(whole.root))
        assert chunked.messages == whole.messages


def test_logtail_partial_lines_and_truncation(tmp_path):
    path = tmp_path / "x.vdi"
    path.write_bytes(b"line one\nline tw")
    tail = LogTail(path)
    assert tail.poll() == (["line one"], False)
    with open(path, "ab") as fh:
        fh.write(b"o\nthree\n")
    assert tail.poll() == (["line two", "three"], False)
    assert tail.poll() == ([], False)
    assert tail.read_range(2, 3) == ["line two", "three"]
    path.write_bytes(b"new\n")                     # truncation -> restart from 0
    lines, reset = tail.poll()
    assert lines == ["new"] and reset


def test_logtail_chunked_parse_matches_whole(cfg, tmp_path):
    source = (FIXTURES / "qick" / "d_1_wrapper.vdi").read_bytes()
    target = tmp_path / "live.vdi"
    target.write_bytes(b"")
    tail, parser = LogTail(target), LogParser(cfg)
    for i in range(0, len(source), 997):          # splits mid-line
        with open(target, "ab") as fh:
            fh.write(source[i:i + 997])
        parser.feed(tail.poll()[0])
    whole = parse(cfg, FIXTURES / "qick" / "d_1_wrapper.vdi")
    assert json.dumps(dump(parser.root)) == json.dumps(dump(whole.root))
