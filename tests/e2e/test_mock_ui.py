"""Phase timeline, inspector, follow-live, Reports tab and a few regressions, on the mock data (index.html?mock=1)."""
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


def row(page, text):
    """A row of the stage's phase timeline (the outline), by the start of its label."""
    return page.locator(".stagedetail .orow", has_text=re.compile(r"^\s*" + re.escape(text)))


def active_tab(page):
    return page.locator(".stagedetail .itabs .dtab.on").first


def test_stage_rail_lists_stages_and_card_selects(page, mock_url):
    open_mock(page, mock_url, "fw=lockin")
    names = page.locator(".stg .label").all_inner_texts()
    assert [n.replace("optional", "") for n in names] == ["Synthesis", "init_design", "opt_design", "place_design", "phys_opt_design", "route_design", "write_bitstream"]
    expect(stage_card(page, "place_design")).to_have_attribute("aria-pressed", "true")
    stage_card(page, "opt_design").click()
    expect(stage_card(page, "opt_design")).to_have_attribute("aria-pressed", "true")
    expect(stage_card(page, "place_design")).to_have_attribute("aria-pressed", "false")
    expect(page.locator(".stagedetail > .main > .card .label")).to_contain_text("opt_design")


def test_outline_rows_expand_and_collapse(page, mock_url):
    open_mock(page, mock_url, "fw=lockin&sel=impl_1/place_design")
    placer, phase1 = row(page, "Placer"), row(page, "Phase 1 Placer Initialization")
    expect(page.get_by_role("tree")).to_be_visible()
    expect(placer).to_have_attribute("aria-expanded", "true")          # ancestors of the running phase open by themselves
    expect(phase1).to_have_attribute("aria-expanded", "true")
    phase1.locator(".ochev").click()
    expect(phase1).to_have_attribute("aria-expanded", "false")
    expect(row(page, "Phase 1.1")).to_have_count(0)
    placer.locator(".ochev").click()
    expect(placer).to_have_attribute("aria-expanded", "false")
    expect(row(page, "Phase 2 Global Placement")).to_have_count(0)
    placer.locator(".ochev").click()
    expect(row(page, "Phase 2 Global Placement")).to_be_visible()
    expect(row(page, "Phase 1.1")).to_have_count(0)                    # the manual collapse of Phase 1 is kept


def test_row_selection_drives_one_inspector_and_keeps_the_tab(page, mock_url):
    open_mock(page, mock_url, "fw=lockin&sel=impl_1/place_design")
    expect(page.locator(".stagedetail .insp")).to_have_count(1)
    expect(row(page, "Phase 1.3 Build Placer")).to_have_attribute("aria-selected", "true")      # the running leaf
    expect(page.locator(".insp .icrumbs .cur")).to_contain_text("Phase 1.3 Build Placer")
    page.locator(".insp .dtab", has_text="Log").click()
    row(page, "Phase 1.2").click()
    expect(row(page, "Phase 1.2")).to_have_attribute("aria-selected", "true")
    expect(page.locator(".insp .icrumbs .cur")).to_contain_text("Phase 1.2")
    expect(active_tab(page)).to_contain_text("Log")                    # the chosen tab follows the selection
    page.clock.run_for(8000)                                           # a manual selection stays pinned while the phase advances
    expect(row(page, "Phase 1.2")).to_have_attribute("aria-selected", "true")
    expect(page.locator(".insp .icrumbs .cur")).to_contain_text("Phase 1.2")


def test_detail_tabs_switch_panes(page, mock_url):
    open_mock(page, mock_url, "fw=lockin&sel=impl_1/place_design")
    row(page, "Whole step").click()
    tabs = page.locator(".stagedetail .itabs")
    for label, pane in (("Messages", "messages"), ("Log", "log"), ("Reports", "reports"), ("Timing", "timing")):
        tabs.get_by_role("button", name=re.compile("^" + label)).click()
        expect(active_tab(page)).to_contain_text(label)
        visible = page.locator(".stagedetail .insp > .pane:not([hidden])")
        expect(visible).to_have_count(1)
        expect(visible).to_have_class(re.compile("pane-" + pane))
    expect(tabs.get_by_role("button", name=re.compile("^Steps"))).to_have_count(0)


def test_keyboard_navigation(page, mock_url):
    open_mock(page, mock_url, "fw=lockin")
    page.keyboard.press("k")
    expect(stage_card(page, "opt_design")).to_have_attribute("aria-pressed", "true")
    page.keyboard.press("j")
    page.keyboard.press("j")
    expect(stage_card(page, "phys_opt_design")).to_have_attribute("aria-pressed", "true")
    page.keyboard.press("k")
    expect(stage_card(page, "place_design")).to_have_attribute("aria-pressed", "true")
    expect(row(page, "Placer")).to_have_attribute("aria-expanded", "true")
    page.keyboard.press("Escape")
    expect(row(page, "Placer")).to_have_attribute("aria-expanded", "true")
    page.keyboard.press("c")
    expect(row(page, "Placer")).to_have_attribute("aria-expanded", "false")
    expect(row(page, "Phase 1 Placer Initialization")).to_have_count(0)


def test_outline_tree_keyboard(page, mock_url):
    open_mock(page, mock_url, "fw=lockin&sel=impl_1/place_design")
    expect(page.locator(".orow[tabindex='0']")).to_have_count(1)       # one row in the tab order (roving tabindex)
    placer = row(page, "Placer")
    placer.focus()
    page.keyboard.press("ArrowDown")
    expect(row(page, "Phase 1 Placer Initialization")).to_be_focused()
    page.keyboard.press("ArrowLeft")                                   # collapses the open row
    expect(row(page, "Phase 1 Placer Initialization")).to_have_attribute("aria-expanded", "false")
    page.keyboard.press("ArrowLeft")                                   # then goes to its parent
    expect(placer).to_be_focused()
    page.keyboard.press("ArrowLeft")
    expect(placer).to_have_attribute("aria-expanded", "false")
    page.keyboard.press("ArrowRight")
    expect(placer).to_have_attribute("aria-expanded", "true")
    page.keyboard.press("Enter")
    expect(placer).to_have_attribute("aria-selected", "true")
    expect(page.locator(".insp .icrumbs .cur")).to_have_text("Placer")
    page.keyboard.press("End")
    expect(page.locator(".orow").last).to_be_focused()


def test_outline_keeps_focus_and_scroll_across_live_updates(page, mock_url):
    open_mock(page, mock_url, "fw=lockin&sel=impl_1/place_design")
    placer = row(page, "Placer")
    placer.focus()
    page.evaluate("document.querySelector('.stagedetail .otree').scrollTop = 20")
    page.evaluate("document.querySelectorAll('.stagedetail .orow').forEach((e) => { e._mark = 1; })")
    page.clock.run_for(3000)                                           # several mock ticks re-render the outline
    expect(placer).to_be_focused()
    assert page.evaluate("[...document.querySelectorAll('.stagedetail .orow')].every((e) => e._mark === 1)")   # patched, not rebuilt


def test_follow_live_selects_running_stage_and_can_be_toggled(page, mock_url):
    open_mock(page, mock_url, "fw=lockin")
    follow = page.get_by_role("button", name="follow live")
    expect(follow).to_have_attribute("aria-pressed", "true")
    expect(stage_card(page, "place_design")).to_have_attribute("aria-pressed", "true")
    for label in ("Placer", "Phase 1 Placer Initialization"):
        expect(row(page, label)).to_have_attribute("aria-expanded", "true")
    expect(row(page, "Phase 1.3 Build Placer")).to_have_attribute("aria-selected", "true")           # the running leaf
    stage_card(page, "opt_design").click()
    expect(follow).to_have_attribute("aria-pressed", "false")
    expect(stage_card(page, "opt_design")).to_have_attribute("aria-pressed", "true")
    follow.click()
    expect(follow).to_have_attribute("aria-pressed", "true")
    expect(stage_card(page, "place_design")).to_have_attribute("aria-pressed", "true")


def test_follow_live_tracks_the_running_phase(page, mock_url):
    open_mock(page, mock_url, "fw=lockin")
    running = page.locator('.orow[data-status="running"]', has_text="Phase 1.3 Build Placer")
    expect(running).to_be_visible()
    expect(running).to_have_attribute("aria-selected", "true")
    page.clock.run_for(8000)        # the mock finishes the running phase every 8th tick and starts the next
    running = page.locator('.orow[data-status="running"]', has_text="Phase 1.4 Constrain")
    expect(running).to_be_visible()
    expect(running).to_have_attribute("aria-selected", "true")                                       # the selection follows it
    expect(row(page, "Phase 1.3 Build Placer")).to_have_attribute("aria-selected", "false")
    expect(row(page, "Phase 1 Placer Initialization")).to_have_attribute("aria-expanded", "true")
    expect(stage_card(page, "place_design")).to_have_attribute("aria-pressed", "true")


def test_follow_off_stays_on_the_chosen_stage_when_the_phase_changes(page, mock_url):
    open_mock(page, mock_url, "fw=lockin")
    stage_card(page, "opt_design").click()
    page.clock.run_for(8000)
    expect(stage_card(page, "opt_design")).to_have_attribute("aria-pressed", "true")
    expect(page.get_by_role("button", name="follow live")).to_have_attribute("aria-pressed", "false")


def open_timing_report(page, mock_url):
    open_mock(page, mock_url, "fw=top&sel=impl_1/route_design")
    page.locator(".stagedetail .itabs").get_by_role("button", name=re.compile("^Reports")).click()
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
    expect(cmp_tabs(page)).to_have_count(1)
    history.get_by_role("button", name=re.compile("Back to the list")).click()
    expect(history.locator(".cmp-card")).to_have_count(0)
    expect(history.locator("table.hx")).to_be_visible()
    expect(cmp_tabs(page)).to_have_count(1)                   # leaving the view keeps the tab


def cmp_tabs(page):
    return page.locator("#tabs [role=tab].ctab")


def compare_two_lockin_builds(page, mock_url):
    open_mock(page, mock_url, "page=history&hfw=lockin", ready="table.hx")
    history = page.get_by_label("Build history", exact=True)
    boxes = history.get_by_role("checkbox")
    boxes.nth(0).check()
    boxes.nth(1).check()
    history.get_by_role("button", name="Compare", exact=True).click()
    expect(history.locator(".cmp-card").first).to_be_visible()
    return history


def test_comparison_tab_survives_switching_reload_and_closes(page, mock_url):
    history = compare_two_lockin_builds(page, mock_url)
    tab = cmp_tabs(page).first
    expect(tab).to_have_attribute("aria-selected", "true")
    expect(tab).to_contain_text("lockin")
    page.locator("#tabs [role=tab]:not(.ctab)").first.click()
    expect(history).to_be_hidden()
    expect(tab).to_have_attribute("aria-selected", "false")
    tab.click()
    expect(history.locator(".cmp-card").first).to_be_visible()
    history.locator(".cmp-tab", has_text="Removed").click()
    page.locator("#tabs [role=tab]:not(.ctab)").first.click()
    tab.click()
    expect(history.locator(".cmp-tab[aria-pressed=true]")).to_contain_text("Removed")
    page.goto(mock_url)                                       # no hash: only localStorage remembers the tab
    expect(cmp_tabs(page)).to_have_count(1)
    expect(history.locator(".cmp-card").first).to_be_visible()
    cmp_tabs(page).first.focus()
    page.keyboard.press("Delete")
    expect(cmp_tabs(page)).to_have_count(0)
    expect(history).to_be_hidden()
    expect(page.locator("#tabs [role=tab].active")).to_have_count(1)


def test_same_pair_focuses_the_open_comparison_tab(page, mock_url):
    history = compare_two_lockin_builds(page, mock_url)
    page.get_by_role("button", name="History").click()
    boxes = history.get_by_role("checkbox")
    boxes.nth(0).check()
    boxes.nth(1).check()
    history.get_by_role("button", name="Compare", exact=True).click()
    expect(cmp_tabs(page)).to_have_count(1)


def test_live_rows_and_live_comparison(page, mock_url):
    open_mock(page, mock_url, "page=history&hfw=all", ready="table.hx")
    history = page.get_by_label("Build history", exact=True)
    live = history.locator("tbody tr.live")
    assert live.count() >= 1
    expect(live.first.locator(".livebadge")).to_be_visible()
    expect(history.locator("tbody tr").first).to_have_class(re.compile(r"\blive\b"))   # pinned on top
    live.first.get_by_role("checkbox").check()
    history.locator("tbody tr:not(.live) td.pick input").first.check()
    history.get_by_role("button", name="Compare", exact=True).click()
    expect(history.locator(".cmp-card").first).to_be_visible()
    expect(history.locator(".cmp-live .livebadge")).to_have_count(1)
    expect(history.locator(".cmp-live")).to_contain_text("as of")
    expect(cmp_tabs(page).first).to_contain_text("live")
    page.get_by_role("button", name="History").click()
    history.get_by_role("switch", name="Finished only").check()
    expect(history.locator("tbody tr.live")).to_have_count(0)


def test_firmware_compare_button_preticks_live_row(page, mock_url):
    open_mock(page, mock_url, "fw=lockin")
    page.locator(".fw-head").get_by_role("button", name="Compare", exact=True).click()
    history = page.get_by_label("Build history", exact=True)
    expect(history.locator("tbody tr.live input:checked")).to_have_count(1)
    expect(history.locator(".hx-hint")).to_contain_text("compare with lockin (live)")


def test_compare_across_firmwares(page, mock_url):
    open_mock(page, mock_url, "page=history&hfw=all", ready="table.hx")
    history = page.get_by_label("Build history", exact=True)
    rows = history.locator("tbody tr")
    expect(rows.first.locator(".sub.path")).not_to_be_empty()
    names = {row.locator(".hx-open").inner_text() for row in rows.all()[:4]}
    assert len(names) > 1
    first = rows.nth(0).get_by_role("checkbox")
    first.check()
    other = next(r for r in rows.all() if r.locator(".hx-open").inner_text() != rows.nth(0).locator(".hx-open").inner_text())
    other.get_by_role("checkbox").check()
    history.get_by_role("button", name="Compare", exact=True).click()
    expect(history.locator(".cmp-card").first).to_be_visible()
    expect(history.locator(".cmp-fw")).to_have_count(2)
    expect(history.locator(".cmp-b .cmp-sub.mono")).to_have_count(2)
    expect(history.locator(".hx-n")).to_contain_text("↔")


def test_finished_only_filter_hides_failed_and_stopped(page, mock_url):
    open_mock(page, mock_url, "page=history&hfw=all", ready="table.hx")
    history = page.get_by_label("Build history", exact=True)
    total = history.locator("tbody tr").count()
    history.locator("tbody tr td.pick input").first.check()
    toggle = history.get_by_role("switch", name="Finished only")
    toggle.check()
    shown = history.locator("tbody tr").count()
    assert 0 < shown < total
    expect(history.locator(".pill[data-status=failed], .pill[data-status=stopped]")).to_have_count(0)
    expect(history.locator(".hx-n")).to_have_text("%d builds" % shown)
    toggle.uncheck()
    expect(history.locator("tbody tr")).to_have_count(total)


def test_finished_only_from_hash(page, mock_url):
    open_mock(page, mock_url, "page=history&hfw=all&hdone=1", ready="table.hx")
    history = page.get_by_label("Build history", exact=True)
    expect(history.get_by_role("switch", name="Finished only")).to_be_checked()
    expect(history.locator(".pill[data-status=failed]")).to_have_count(0)


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


def test_ooc_runs_run_in_parallel_on_the_time_axis(page, mock_url):
    """OOC runs are independent: their bars overlap in time, none waits for the previous one."""
    open_mock(page, mock_url, "fw=top&sel=synth")
    row(page, "IP out-of-context").locator(".ochev").click()
    runs = page.locator(".stagedetail .orow[aria-level='3']")
    expect(runs).to_have_count(12)
    spans = runs.evaluate_all("els => els.map(e => { const r = e.querySelector('.gb').getBoundingClientRect(); return [r.left, r.right]; })")
    assert all(b[0] < a[1] for a, b in zip(spans, spans[1:]))         # each starts before the previous one ends


def test_attention_rows_can_be_dismissed_and_shown_again(page, mock_url):
    """One list holds alerts, top issues and hints: the counts stay when rows are dismissed, 'show' brings them back."""
    open_mock(page, mock_url, "fw=lockin")
    attn = page.locator(".attn")
    rows = attn.locator(".arow")
    count = attn.locator(".attn-n")
    total = count.inner_text()
    expect(rows).to_have_count(3)                    # three by default, the rest behind "Show N more"
    attn.get_by_role("button", name=re.compile(r"^Show \d+ more")).click()
    n = rows.count()
    assert n >= 4
    assert int(total) == n
    rows.first.locator(".al-x").click()
    expect(rows).to_have_count(n - 1)
    while rows.count():
        rows.first.locator(".al-x").click()
    expect(rows).to_have_count(0)
    expect(count).to_have_text(total)
    page.clock.run_for(3000)                         # live updates keep them dismissed
    expect(rows).to_have_count(0)
    attn.get_by_role("button", name=re.compile("dismissed")).click()
    expect(rows).to_have_count(n)


def test_hint_fix_lives_in_the_attention_list_and_the_stage_links_to_it(page, mock_url):
    """The fix text is owned by the hero row; the stage detail only has a one-line link that opens it."""
    open_mock(page, mock_url, "fw=lockin&sel=impl_1/place_design")
    expect(page.locator(".afix-body")).to_have_count(0)
    expect(page.locator(".stagedetail .hint-x")).to_have_count(0)          # no second copy in the stage detail
    link = page.locator(".stagedetail .hlink")
    expect(link).to_have_count(1)
    expect(link).to_contain_text("suggested actions")
    link.click()
    fix = page.locator(".arow .afix[aria-expanded=true]")
    expect(fix).to_have_count(1)
    expect(page.locator(".afix-body")).to_contain_text("AltSpreadLogic_high")
    fix.click()
    expect(page.locator(".afix-body")).to_have_count(0)


def test_build_strip_has_a_segment_per_stage_and_selects_it(page, mock_url):
    open_mock(page, mock_url, "fw=lockin")
    segs = page.locator(".pseg")
    expect(segs).to_have_count(7)
    expect(segs.nth(3)).to_have_attribute("data-status", "running")
    expect(segs.nth(3).locator(".pnow")).to_have_count(1)
    expect(segs.nth(6)).to_have_attribute("data-status", "pending")
    segs.nth(2).click()
    expect(stage_card(page, "opt_design")).to_have_attribute("aria-pressed", "true")
    expect(segs.nth(2)).to_have_class(re.compile(r"\bsel\b"))


def test_hero_verdict_and_metric_tiles(page, mock_url):
    open_mock(page, mock_url, "fw=lockin")
    expect(page.locator(".verdict")).to_contain_text("expected to finish")
    expect(page.locator(".verdict")).to_contain_text("timing failing")
    expect(page.locator(".t-timing .tbadge")).to_have_text("ESTIMATE")
    expect(page.locator(".tile")).to_have_count(4)
    page.locator(".t-msgs").click()                                         # a tile opens its view
    expect(page.locator(".msgview")).to_be_visible()


def test_hero_verdict_of_a_finished_build_never_promises_a_fix(page, mock_url):
    open_mock(page, mock_url, "fw=top")
    expect(page.locator(".verdict")).to_contain_text("Finished")
    expect(page.locator(".verdict")).to_contain_text("timing met")
    expect(page.locator(".verdict")).not_to_contain_text("later steps")
    expect(page.locator(".t-timing .tbadge")).to_have_text("FINAL")


def test_running_build_has_no_export_menu(page, mock_url):
    open_mock(page, mock_url, "fw=lockin")
    expect(page.locator(".hmenuwrap")).to_be_hidden()                       # a running build has nothing to export


def test_export_menu_of_a_finished_build(page, mock_url):
    open_mock(page, mock_url, "fw=top")
    more = page.get_by_role("button", name="More actions")
    menu = page.locator(".hmenu")
    expect(menu).to_be_hidden()
    more.click()
    expect(menu.get_by_role("menuitem")).to_have_text(["Export summary (Markdown)", "Open printable HTML"])
    page.keyboard.press("Escape")
    expect(menu).to_be_hidden()
    expect(more).to_be_focused()


# ---- mobile (< 700px): drill-in navigation, one screen per level

PHONE = {"width": 390, "height": 844}


def open_phone(page, mock_url, hash_="fw=lockin"):
    page.set_viewport_size(PHONE)
    open_mock(page, mock_url, hash_, ready=".m-row")


def test_phone_hides_the_desktop_chrome_and_never_scrolls_sideways(page, mock_url):
    open_phone(page, mock_url)
    expect(page.locator(".m-tabs")).to_be_visible()
    expect(page.locator("#m-switch")).to_contain_text("lockin")
    expect(page.locator(".tabs")).to_be_hidden()
    expect(page.locator(".m-hero")).to_be_visible()
    expect(page.locator(".m-row")).to_have_count(7)
    assert not page.evaluate("document.documentElement.scrollWidth > innerWidth")


def test_phone_drill_in_pushes_a_level_and_back_pops_it(page, mock_url):
    page.emulate_media(reduced_motion="reduce")      # no slide-in: row positions are measured below
    open_phone(page, mock_url)
    page.locator(".m-row", has_text="place_design").click()
    crumbs = page.locator(".m-crumbs button")
    expect(crumbs).to_have_text(["lockin", "place_design"])
    rows = page.locator(".m-row")
    expect(rows.first).to_be_visible()
    depth1 = rows.first.evaluate("e => e.getBoundingClientRect().left")
    page.locator(".m-row", has_text="Placer").click()
    expect(crumbs).to_have_text(["lockin", "place_design", "Placer"])
    expect(rows.first).to_be_visible()
    assert abs(rows.first.evaluate("e => e.getBoundingClientRect().left") - depth1) < 1   # flat: no indentation at depth 2
    page.go_back()                                                           # the phone's Back button
    expect(crumbs).to_have_text(["lockin", "place_design"])
    page.locator(".m-back").click()
    expect(page.locator(".m-crumbs")).to_have_count(0)
    expect(page.locator(".m-hero")).to_be_visible()


def test_phone_sheet_shows_messages_and_back_closes_it(page, mock_url):
    open_phone(page, mock_url, "fw=lockin&mnode=impl_1/place_design")
    page.locator(".m-act", has_text="Messages").click()
    sheet = page.locator("#m-sheet")
    expect(sheet).to_be_visible()
    expect(sheet.locator(".m-sh-tabs button").first).to_have_attribute("aria-selected", "true")
    expect(sheet.locator(".grp-h").first).to_be_visible()
    sheet.locator(".m-sh-tabs button", has_text="Log").click()
    expect(sheet.locator(".m-sh-tabs button", has_text="Log")).to_have_attribute("aria-selected", "true")
    page.go_back()
    expect(sheet).to_be_hidden()
    expect(page.locator(".m-crumbs button").last).to_have_text("place_design")


def test_phone_follow_live_jumps_to_the_running_node_and_manual_navigation_pauses_it(page, mock_url):
    open_phone(page, mock_url)
    chip = page.locator(".m-follow").first
    expect(chip).to_have_attribute("aria-pressed", "false")
    chip.click()
    expect(page.locator(".m-follow").first).to_have_attribute("aria-pressed", "true")
    expect(page.locator(".m-crumbs button").nth(1)).to_have_text("place_design")
    page.locator(".m-crumbs button").first.click()                           # a manual jump pauses following
    expect(page.locator(".m-hero")).to_be_visible()
    expect(page.locator(".m-follow").first).to_have_attribute("aria-pressed", "false")


def test_phone_switcher_lists_firmwares_and_switches(page, mock_url):
    open_phone(page, mock_url)
    page.locator("#m-switch").click()
    sheet = page.locator("#m-sheet")
    expect(sheet.locator(".m-frow")).not_to_have_count(0)
    expect(sheet.locator(".m-mtr")).to_have_count(3)
    sheet.locator(".m-frow", has_text="top").first.click()
    expect(sheet).to_be_hidden()
    expect(page.locator("#m-switch")).to_contain_text("top")


def test_phone_tabs_open_messages_and_the_real_history_page(page, mock_url):
    open_phone(page, mock_url)
    page.locator("[data-act='m-tab'][data-tab='Messages']").click()
    expect(page.locator(".msgview")).to_be_visible()
    expect(page.locator(".m-screen")).to_be_hidden()
    page.locator("[data-act='m-tab'][data-tab='History']").click()
    expect(page.locator("#history .hx")).to_be_visible()
    assert not page.evaluate("document.documentElement.scrollWidth > innerWidth")
    page.locator("[data-act='m-tab'][data-tab='Build']").click()
    expect(page.locator(".m-hero")).to_be_visible()
