import pytest

from rejectall.patterns import classify
from rejectall.scoring import score
from rejectall.trackers import summarize


@pytest.mark.parametrize("label,role", [
    ("Accept All Cookies", "accept"), ("Alle akzeptieren", "accept"), ("OK, got it", "accept"),
    ("Tout accepter", "accept"), ("AGREE", "accept"), ("Allow all", "accept"), ("Zustimmen", "accept"),
    ("Reject All", "reject"), ("Alle ablehnen", "reject"), ("Deny", "reject"), ("Decline", "reject"),
    ("Accept only necessary", "reject"), ("Nur notwendige Cookies", "reject"),
    ("Continuer sans accepter →", "reject"), ("Do not accept", "reject"), ("Use necessary cookies only", "reject"),
    ("Cookies Settings", "settings"), ("Einstellungen", "settings"), ("MORE OPTIONS", "settings"),
    ("Personnaliser", "settings"), ("Manage preferences", "settings"),
    ("Save & Exit", "save"), ("Auswahl speichern", "save"), ("Allow selection", "save"),
    ("Confirm my choices", "save"),
    ("Jetzt Pur-Abo abschließen", "pay"),
    ("Sounds good!", None), ("Read our full privacy policy and learn how we use cookies across all our sites today", None),
])
def test_classify(label, role):
    assert classify(label) == role


def test_score_is_deterministic_and_ordered():
    good = {"status": "measured", "accept_clicks": 1, "reject_clicks": 1}
    two = {"status": "measured", "accept_clicks": 1, "reject_clicks": 2}
    none = {"status": "measured", "accept_clicks": 1, "reject_clicks": None}
    trackers = dict(good, pre_consent_trackers=[{"domain": f"t{i}.com"} for i in range(5)])
    assert score(good)[0] == 100 and score(good)[1] == "A"
    assert score(two)[0] == 85
    assert score(none)[0] == 60
    assert score(trackers)[0] == 85
    assert score({"status": "unmeasurable"}) == (None, "?", [])
    assert score(two) == score(dict(two))


def test_score_caps():
    r = {"status": "measured", "accept_clicks": 1, "reject_clicks": 9, "preticked_toggles": 30,
         "pre_consent_trackers": [{"domain": str(i)} for i in range(50)]}
    s, g, pen = score(r)
    assert dict(pen) == {"extra_reject_clicks": 45, "preticked_toggles": 20, "pre_consent_trackers": 40}
    assert s == 0 and g == "F"


def test_tracker_first_party_exclusion(tracker_list):
    reqs = [{"host": "www.google-analytics.com"}, {"host": "ad.doubleclick.net"}, {"host": "ad.doubleclick.net"},
            {"host": "cdn.example"}, {"host": "example.org"}]
    on_news = summarize(reqs, tracker_list, "news.example")
    assert [(t["domain"], t["requests"]) for t in on_news] == [("doubleclick.net", 2), ("google-analytics.com", 1)]
    # Same owner: Google's own trackers on youtube.com are first party.
    assert summarize(reqs, tracker_list, "youtube.com") == []


@pytest.mark.parametrize("label,role", [
    ("Nur unbedingt notwendige Cookies akzeptieren", "reject"),   # europa.eu
    ("Ich stimme zu", "accept"),                                  # tumblr.com
    ("Ausgewähltem zustimmen", "save"),                           # t-online.de
    ("Auswahl akzeptieren", "save"),                              # opera.com
])
def test_labels_seen_in_the_wild(label, role):
    assert classify(label) == role


def test_necessary_only_notice_is_not_penalised_for_missing_reject():
    base = {"status": "measured", "accept_clicks": 1, "reject_clicks": None, "pay_or_ok": False,
            "pre_consent_trackers": []}
    notice = dict(base, banner_text="Our website only uses necessary cookies. Acknowledge")
    plain = dict(base, banner_text="We and our partners use cookies. Accept")
    assert score(notice)[0] == 100 and score(plain)[0] == 60
    assert score(dict(notice, banner_text="Diese Website verwendet nur technisch notwendige Cookies."))[0] == 100
