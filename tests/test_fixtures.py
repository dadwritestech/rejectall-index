"""End-to-end on fixture banners: real headless Chromium, fake tracker hosts."""
import json

import pytest

from rejectall.measure import measure

FAST = dict(settle=0.4, layer_wait=0.4, after_wait=0.4, scan_step=0.3)


class StubLocator:
    """Stands in for the LLM: maps button text to a role."""

    def __init__(self, mapping):
        self.mapping = mapping
        self.calls = 0

    def locate(self, buttons):
        self.calls += 1
        roles = {b["id"]: self.mapping[b["text"]] for b in buttons if b["text"] in self.mapping}
        return roles, {"model": "stub", "prompt": "...", "answer": str(roles), "error": None, "ms": 0}


def run(page, server, tracker_list, tmp_path, name, locator=None):
    return measure(page, f"{server}/{name}", "127.0.0.1", tmp_path / name, tracker_list, locator, **FAST)


def test_one_layer(page, server, tracker_list, tmp_path):
    r = run(page, server, tracker_list, tmp_path, "one_layer.html")
    assert r["status"] == "measured"
    assert (r["accept_clicks"], r["reject_clicks"], r["reject_second_layer"]) == (1, 1, False)
    assert r["verified"] is True
    assert {t["domain"] for t in r["pre_consent_trackers"]} == {"google-analytics.com", "doubleclick.net"}
    assert (tmp_path / "one_layer.html" / "evidence.json").exists()
    assert "01_landing.jpg" in r["screenshots"] and "03_after_reject.jpg" in r["screenshots"]
    assert not r["llm_used"]


def test_two_layer_german(page, server, tracker_list, tmp_path):
    r = run(page, server, tracker_list, tmp_path, "two_layer.html")
    assert (r["accept_clicks"], r["reject_clicks"], r["reject_second_layer"]) == (1, 2, True)
    assert r["reject_path"] == "second_layer_button"
    assert r["verified"] is True
    # The tracker fired by *accept* never ran, because we never accepted.
    log = json.loads((tmp_path / "two_layer.html" / "requests.json").read_text())
    assert not any("after.gif" in q["url"] for q in log)


def test_preticked_legitimate_interest(page, server, tracker_list, tmp_path):
    r = run(page, server, tracker_list, tmp_path, "preticked_li.html")
    assert r["reject_path"] == "untick_and_save_layer2"
    assert r["preticked_toggles"] == 3 and r["preticked_legit_interest"] == 3
    assert r["reject_clicks"] == 1 + 3 + 1
    assert r["verified"] is True


def test_layer1_checkboxes(page, server, tracker_list, tmp_path):
    r = run(page, server, tracker_list, tmp_path, "layer1_checkboxes.html")
    assert r["reject_path"] == "untick_and_save_layer1"
    assert r["reject_clicks"] == 4 and r["preticked_toggles"] == 3


def test_shadow_dom(page, server, tracker_list, tmp_path):
    r = run(page, server, tracker_list, tmp_path, "shadow_dom.html")
    assert (r["accept_clicks"], r["reject_clicks"]) == (1, 1)
    assert r["verified"] is True


def test_iframe_cmp(page, server, tracker_list, tmp_path):
    r = run(page, server, tracker_list, tmp_path, "iframe_cmp.html")
    assert (r["accept_clicks"], r["reject_clicks"], r["reject_second_layer"]) == (1, 2, True)
    assert r["verified"] is True


def test_no_reject(page, server, tracker_list, tmp_path):
    r = run(page, server, tracker_list, tmp_path, "no_reject.html")
    assert r["status"] == "measured"
    assert r["accept_clicks"] == 1 and r["reject_clicks"] is None and r["reject_path"] == "none_found"


def test_continue_without_accepting(page, server, tracker_list, tmp_path):
    r = run(page, server, tracker_list, tmp_path, "continue_without.html")
    assert r["reject_clicks"] == 1 and r["verified"] is True


def test_pay_or_ok(page, server, tracker_list, tmp_path):
    r = run(page, server, tracker_list, tmp_path, "pay_or_ok.html")
    assert r["pay_or_ok"] is True and r["reject_clicks"] is None


def test_no_banner(page, server, tracker_list, tmp_path):
    r = run(page, server, tracker_list, tmp_path, "no_banner.html")
    assert r["status"] == "no_banner" and r["pre_consent_trackers"] == []


def test_bot_wall_is_unmeasurable_and_untouched(page, server, tracker_list, tmp_path):
    r = run(page, server, tracker_list, tmp_path, "bot_wall.html")
    assert r["status"] == "unmeasurable" and r["reason"].startswith("bot wall")
    assert not any(e["event"] == "click" for e in r["events"])


def test_llm_fallback_only_when_rules_fail(page, server, tracker_list, tmp_path):
    loc = StubLocator({"Sounds good!": "accept", "Nope": "reject"})
    r = run(page, server, tracker_list, tmp_path, "llm_fallback.html", loc)
    assert r["llm_used"] is True and loc.calls == 1 and len(r["llm_calls"]) == 1
    assert (r["accept_clicks"], r["reject_clicks"]) == (1, 1)
    loc2 = StubLocator({})
    r2 = run(page, server, tracker_list, tmp_path, "one_layer.html", loc2)
    assert loc2.calls == 0 and r2["llm_used"] is False


def test_per_purpose_rejects_are_not_reject_all(page, server, tracker_list, tmp_path):
    r = run(page, server, tracker_list, tmp_path, "per_purpose.html")
    assert r["pay_or_ok"] is True
    assert r["reject_path"] == "per_purpose_and_save_layer2"
    assert r["reject_clicks"] == 1 + 2 + 1


def test_late_bigger_modal_wins_and_leftover_banner_fails_verification(page, server, tracker_list, tmp_path):
    r = run(page, server, tracker_list, tmp_path, "late_modal.html")
    assert (r["accept_clicks"], r["reject_clicks"], r["reject_path"]) == (1, 1, "first_layer_button")
    assert any("We use cookies" in t for t in r["extra_banners"])
    # The site's own bar is still open after rejecting the modal: not verified.
    assert r["verified"] is False and "Yes, I agree" in r["remaining_consent_buttons"]


def test_save_with_optional_boxes_already_off_is_a_one_click_reject(page, server, tracker_list, tmp_path):
    r = run(page, server, tracker_list, tmp_path, "unticked_save.html")
    assert (r["accept_clicks"], r["reject_clicks"], r["reject_path"]) == (1, 1, "untick_and_save_layer1")
    assert r["preticked_toggles"] == 0 and r["verified"] is True


def test_banner_that_slides_off_screen_counts_as_closed(page, server, tracker_list, tmp_path):
    r = run(page, server, tracker_list, tmp_path, "slide_out.html")
    assert r["reject_path"] == "first_layer_button" and r["verified"] is True


def test_banner_faded_out_on_an_ancestor_counts_as_closed(page, server, tracker_list, tmp_path):
    r = run(page, server, tracker_list, tmp_path, "fade_out.html")
    assert r["reject_path"] == "first_layer_button" and r["verified"] is True
