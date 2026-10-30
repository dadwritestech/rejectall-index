"""rejectall-index feed for herald: the weekly hardest-to-refuse list, plus grade changes between runs.
Wording stays factual: what was measured, never adjectives about the site."""
import datetime as dt
import json
import os

ROOT = os.path.join(os.path.dirname(__file__), "..")
SITE = "https://dadwritestech.github.io/rejectall-index"


def describe(s):
    bits = []
    if s.get("reject_clicks") is None and s.get("pay_or_ok"):
        return "refusing means paying (pay-or-OK)"
    if s.get("reject_clicks") is None:
        bits.append("no reject option found")
    else:
        bits.append(f"{s['reject_clicks']} click{'s' if s['reject_clicks'] != 1 else ''} to refuse "
                    f"vs {s['accept_clicks']} to accept")
    if s.get("pay_or_ok"):
        bits.append("pay-or-OK")
    n = len(s.get("trackers_after_reject") or [])
    if n:
        bits.append(f"{n} tracker{'s' if n != 1 else ''} after refusing")
    return ", ".join(bits)


def load(path):
    return {s["domain"]: s for s in json.load(open(path, encoding="utf-8"))["sites"]}


def main(today=None):
    today = today or dt.date.today()
    latest = load(os.path.join(ROOT, "data", "latest.json"))
    measured = sorted((s for s in latest.values() if s["status"] == "measured"),
                      key=lambda s: (s["score"], s["domain"]))
    year, week, _ = today.isocalendar()
    if len(measured) >= 3:
        lines = [f"{i}. {s['domain']}: {describe(s)}" for i, s in enumerate(measured[:3], 1)]
        print(json.dumps({
            "id": f"rejectall/weekly/{year}-W{week:02d}",
            "text": "Hardest cookie banners to refuse this week (top sites, measured from Germany):\n\n"
                    + "\n".join(lines),
            "link": SITE,
        }, ensure_ascii=False))

    runs = sorted(d for d in os.listdir(os.path.join(ROOT, "data", "runs"))
                  if os.path.exists(os.path.join(ROOT, "data", "runs", d, "results.json")))
    if len(runs) >= 2:
        prev = load(os.path.join(ROOT, "data", "runs", runs[-2], "results.json"))
        for dom, s in latest.items():
            p = prev.get(dom)
            if not p or s["status"] != "measured" or p["status"] != "measured":
                continue
            if s["grade"] == p["grade"]:
                continue
            better = s["score"] > p["score"]
            print(json.dumps({
                "id": f"rejectall/grade/{dom}/{runs[-1]}",
                "text": (f"{dom} moved from {p['grade']} to {s['grade']} on the cookie reject index"
                         f" ({p['score']} to {s['score']}). Now: {describe(s)}."),
                "link": SITE,
                "priority": 4 if better else 3,
            }, ensure_ascii=False))


if __name__ == "__main__":
    main()
