"""Drill-down, follow-live, Reports tab and a few regressions, on the mock data (index.html?mock=1)."""
import re

import pytest
from playwright.sync_api import expect

pytestmark = pytest.mark.e2e


def open_mock(page, mock_url, hash_="", ready=".stg"):
    """Paused clock: the mock only moves when a test runs it, so nothing changes between two assertions."""
    page.clock.install()
    page.goto(mock_url + ("#" + hash_ if hash_ else ""))
    expect(page.locator(ready).first).to_be_visible()
    page.clock.pause_at(page.evaluate("Date.now()") + 10)


def stage(page, name):
    return page.locator(".stg", has=page.locator(".label", has_text=re.compile(r"^\s*%s(optional)?\s*$" % name)))


def stage_card(page, name):
    return stage(page, name).locator(".card")


def node_card(page, text):
    return page.locator(".stagedetail .card[role=button]", has_text=re.compile(r"^\s*" + re.escape(text)))


def active_tab(page):
    return page.locator(".stagedetail .dtab.on").first


def test_stage_rail_lists_stages_and_card_selects(page, mock_url):
    open_mock(page, mock_url, "fw=lockin")
    names = page.locator(".stg .label").all_inner_texts()
    assert [n.replace("optional", "") for n in names] == ["Synthesis", "init_design", "opt_design", "place_design", "phys_opt_design", "route_design", "write_bitstream"]
    expect(stage_card(page, "place_design")).to_have_attribute("aria-pressed", "true")
    stage_card(page, "opt_design").click()
    expect(stage_card(page, "opt_design")).to_have_attribute("aria-pressed", "true")
    expect(stage_card(page, "place_design")).to_have_attribute("aria-pressed", "false")
    expect(page.locator(".stagedetail > .main > .card .label")).to_contain_text("opt_design")


def test_nested_nodes_expand_and_collapse(page, mock_url):
    open_mock(page, mock_url, "fw=lockin&sel=impl_1/place_design")
    placer = node_card(page, "Placer")
    expect(placer).to_have_attribute("aria-expanded", "false")
    placer.click()
    expect(placer).to_have_attribute("aria-expanded", "true")
    phase1 = node_card(page, "Phase 1 Placer Initialization")
    phase1.click()
    expect(phase1).to_have_attribute("aria-expanded", "true")
    phase13 = node_card(page, "Phase 1.3 Build Placer")
    phase13.click()
    expect(phase13).to_have_attribute("aria-expanded", "true")
    phase13.click()
    expect(phase13).to_have_attribute("aria-expanded", "false")


def test_detail_tabs_switch_panes(page, mock_url):
    open_mock(page, mock_url, "fw=lockin&sel=impl_1/place_design")
    tabs = page.locator(".stagedetail > .main > .body .dtabs").first
    for label, pane in (("Messages", "messages"), ("Log", "log"), ("Reports", "reports"), ("Timing", "timing"), ("Steps", "flow")):
        tabs.get_by_role("button", name=re.compile("^" + label)).click()
        expect(active_tab(page)).to_contain_text(label)
        visible = page.locator(".stagedetail > .main > .body .panel > .pane:not([hidden])")
        expect(visible).to_have_count(1)
        expect(visible).to_have_class(re.compile("pane-" + pane))


def test_keyboard_navigation(page, mock_url):
    open_mock(page, mock_url, "fw=lockin")
    page.keyboard.press("k")
    expect(stage_card(page, "opt_design")).to_have_attribute("aria-pressed", "true")
    page.keyboard.press("j")
    page.keyboard.press("j")
    expect(stage_card(page, "phys_opt_design")).to_have_attribute("aria-pressed", "true")
    page.keyboard.press("k")
    expect(stage_card(page, "place_design")).to_have_attribute("aria-pressed", "true")
    node_card(page, "Placer").click()
    expect(node_card(page, "Placer")).to_have_attribute("aria-expanded", "true")
    page.keyboard.press("Escape")
    expect(node_card(page, "Placer")).to_have_attribute("aria-expanded", "true")
    page.keyboard.press("c")
    expect(node_card(page, "Placer")).to_have_attribute("aria-expanded", "false")


def test_follow_live_selects_running_stage_and_can_be_toggled(page, mock_url):
    open_mock(page, mock_url, "fw=lockin")
    follow = page.get_by_role("button", name="follow live")
    expect(follow).to_have_attribute("aria-pressed", "true")
    expect(stage_card(page, "place_design")).to_have_attribute("aria-pressed", "true")
    for label in ("Placer", "Phase 1 Placer Initialization", "Phase 1.3 Build Placer"):
        expect(node_card(page, label)).to_have_attribute("aria-expanded", "true")
    stage_card(page, "opt_design").click()
    expect(follow).to_have_attribute("aria-pressed", "false")
    expect(stage_card(page, "opt_design")).to_have_attribute("aria-pressed", "true")
    follow.click()
    expect(follow).to_have_attribute("aria-pressed", "true")
    expect(stage_card(page, "place_design")).to_have_attribute("aria-pressed", "true")


def test_follow_live_tracks_the_running_phase(page, mock_url):
    open_mock(page, mock_url, "fw=lockin")
    expect(node_card(page, "Phase 1.3 Build Placer")).to_have_attribute("aria-expanded", "true")
    page.clock.run_for(8000)        # the mock finishes the running phase every 8th tick and starts the next
    expect(node_card(page, "Phase 1.3 Build Placer")).to_have_attribute("aria-expanded", "false")
    expect(node_card(page, "Phase 1.4 Constrain")).to_have_attribute("aria-expanded", "true")
    expect(stage_card(page, "place_design")).to_have_attribute("aria-pressed", "true")


def test_follow_off_stays_on_the_chosen_stage_when_the_phase_changes(page, mock_url):
    open_mock(page, mock_url, "fw=lockin")
    stage_card(page, "opt_design").click()
    page.clock.run_for(8000)
    expect(stage_card(page, "opt_design")).to_have_attribute("aria-pressed", "true")
    expect(page.get_by_role("button", name="follow live")).to_have_attribute("aria-pressed", "false")


def open_timing_report(page, mock_url):
    open_mock(page, mock_url, "fw=top&sel=impl_1/route_design")
    page.locator(".stagedetail > .main > .body .dtabs").first.get_by_role("button", name=re.compile("^Reports")).click()
    pane = page.locator(".stagedetail .pane-reports").first
    expect(pane.locator("tr.prow").first).to_be_visible()
    return pane


def test_reports_tab_lists_chips_and_renders_the_selected_report(page, mock_url):
    pane = open_timing_report(page, mock_url)
    chips = pane.locator(".rsel .rchip")
    expect(chips).to_have_text(["Timing summary", "Power", "Route status", "Utilization"])
    expect(chips.first).to_have_class(re.compile(r"\bon\b"))
    expect(pane.locator("section.report header b")).to_have_text("Timing summary")
    chips.filter(has_text="Utilization").click()
    expect(pane.locator("section.report header b")).to_have_text("Utilization")
    expect(chips.filter(has_text="Utilization")).to_have_class(re.compile(r"\bon\b"))
    expect(pane.locator(".paths-h")).to_have_count(0)


def test_raw_report_opens_in_a_modal_and_escape_returns_focus(page, mock_url):
    pane = open_timing_report(page, mock_url)
    raw = pane.get_by_role("button", name="raw")
    raw.focus()
    raw.click()
    modal = page.get_by_role("dialog", name=re.compile("Timing summary|raw", re.I))
    expect(modal).to_be_visible()
    expect(modal.locator("pre")).not_to_be_empty()
    expect(modal.get_by_role("button", name="Close")).to_be_focused()
    page.keyboard.press("Escape")
    expect(modal).to_be_hidden()
    expect(raw).to_be_focused()


def test_worst_paths_expand_to_a_block_chain_with_clock_table(page, mock_url):
    pane = open_timing_report(page, mock_url)
    expect(pane.locator(".paths-h")).to_contain_text("Worst paths")
    rows = pane.locator("tr.prow")
    expect(rows.first).to_be_visible()
    assert rows.count() > 1
    rows.first.click()
    chain = pane.locator(".pchain").first
    expect(chain).to_be_visible()
    expect(pane.locator(".pb-cap").first).to_contain_text("launch")
    expect(chain.locator(".pb.end .pb-cap")).to_contain_text("capture")
    assert chain.locator(".pb").count() >= 2
    toggle = pane.get_by_role("button", name="Clock & required")
    expect(toggle).to_have_attribute("aria-expanded", "false")
    toggle.click()
    expect(toggle).to_have_attribute("aria-expanded", "true")
    expect(pane.get_by_role("cell", name="Required time")).to_be_visible()


def test_history_lists_builds_and_row_opens_the_firmware(page, mock_url):
    open_mock(page, mock_url, "fw=lockin")
    page.get_by_role("button", name="History").click()
    history = page.get_by_label("Build history", exact=True)
    expect(history).to_be_visible()
    page.locator("#hx-fw").select_option(label="All firmwares")
    assert history.locator("tbody tr").count() >= 8
    expect(page.get_by_role("button", name="History")).to_have_attribute("aria-pressed", "true")
    history.locator(".hx-open", has_text="top").first.click()
    expect(history).to_be_hidden()
    expect(page.locator("[role=tab].active")).to_contain_text("top")


def test_compare_view_opens_with_two_picks(page, mock_url):
    open_mock(page, mock_url, "page=history&hfw=lockin", ready="table.hx")
    history = page.get_by_label("Build history", exact=True)
    expect(history).to_be_visible()
    compare = history.get_by_role("button", name="Compare", exact=True)
    expect(compare).to_be_disabled()
    boxes = history.get_by_role("checkbox")
    boxes.nth(0).check()
    boxes.nth(1).check()
    expect(compare).to_be_enabled()
    compare.click()
    expect(history.locator(".cmp-card").first).to_be_visible()
    expect(history.get_by_role("button", name=re.compile("Back to the list"))).to_be_visible()
    page.keyboard.press("Escape")
    expect(history.locator(".cmp-card")).to_have_count(0)
    expect(history.locator("table.hx")).to_be_visible()


def test_notifications_popover_opens_and_escape_closes_it(page, mock_url):
    open_mock(page, mock_url, "fw=lockin")
    bell = page.get_by_role("button", name="Notifications")
    popover = page.get_by_role("dialog", name="Notifications")
    expect(popover).to_be_hidden()
    bell.click()
    expect(popover).to_be_visible()
    page.keyboard.press("Escape")
    expect(popover).to_be_hidden()
    expect(bell).to_be_focused()


def test_narrow_layout_hosts_the_detail_under_the_selected_stage(page, mock_url):
    page.set_viewport_size({"width": 820, "height": 1000})
    open_mock(page, mock_url, "fw=lockin")
    selected = page.locator(".stagelist > .stg.sel")
    expect(selected).to_have_count(1)
    expect(selected.locator(".stagedetail")).to_have_count(1)
    stage_card(page, "opt_design").click()
    expect(page.locator(".stagelist > .stg.sel")).to_contain_text("opt_design")
    expect(page.locator(".stagelist > .stg.sel .stagedetail")).to_have_count(1)
    assert page.locator(".stagedetail").count() == 1
    assert not page.evaluate("document.documentElement.scrollWidth > innerWidth")


def test_ooc_runs_are_not_chained_by_rail_lines(page, mock_url):
    """OOC runs are independent: no connector between them, while the stage's own children stay connected."""
    open_mock(page, mock_url, "fw=top&sel=synth")
    node_card(page, "IP out-of-context").click()
    rails = page.locator(".pane-flow.parallel > .node > .rail")
    expect(rails.first).to_be_visible()
    assert rails.count() == 12
    shown = rails.evaluate_all("els => els.map(e => getComputedStyle(e, '::after').display + getComputedStyle(e, '::before').display)")
    assert set(shown) == {"nonenone"}
    first = page.locator(".stagedetail > .main > .body .pane-flow > .node > .rail").first
    assert first.evaluate("e => getComputedStyle(e, '::after').display") != "none"
