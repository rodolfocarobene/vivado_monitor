"""Smoke test of the real server (Monitor + HTTP API) driven through the browser."""
import re

import pytest
from playwright.sync_api import expect

pytestmark = pytest.mark.e2e


def test_real_server_renders_firmware_stages_messages_and_report(page, real_url):
    responses = []
    page.on("response", lambda r: responses.append((r.url.split("?")[0].replace(real_url, "/"), r.status)))
    page.goto(real_url)
    tab = page.get_by_role("tab").first
    expect(tab).to_contain_text("top")
    expect(page.locator("#conn")).to_have_attribute("data-state", "live")
    stages = page.locator(".stg .label")
    expect(stages.filter(has_text="Route")).to_have_count(1)
    expect(stages.filter(has_text="Write Bitstream")).to_have_count(1)

    page.keyboard.press("m")
    expect(page.locator(".mv-list [data-act=mv-row]").first).to_be_visible()
    assert ("/api/triage", 200) in responses

    page.keyboard.press("f")
    page.locator(".stg", has=page.locator(".label", has_text=re.compile(r"^\s*Route\s*$"))).click()
    page.locator(".stagedetail > .main > .body .dtabs").first.get_by_role("button", name=re.compile("^Reports")).click()
    pane = page.locator(".stagedetail .pane-reports").first
    pane.locator(".rsel .rchip", has_text="Timing").click()
    expect(pane.locator("section.report header b")).to_have_text("Timing")
    pane.get_by_role("button", name="raw").click()
    expect(page.get_by_role("dialog").locator("pre")).to_contain_text("Timing Summary")
    assert any(url == "/api/report" and code == 200 for url, code in responses)
