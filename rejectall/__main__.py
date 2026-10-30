import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def main(argv=None):
    ap = argparse.ArgumentParser(prog="rejectall", description="How many clicks does it take to say no?")
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("pick", help="build data/sites.json from the latest Tranco list")
    p.add_argument("-n", type=int, default=100)
    r = sub.add_parser("run", help="measure every site in data/sites.json")
    r.add_argument("--limit", type=int)
    r.add_argument("--only", nargs="*")
    r.add_argument("--date")
    r.add_argument("--no-llm", action="store_true")
    sub.add_parser("build", help="render site/ (leaderboard + badges) from data/latest.json")
    b = sub.add_parser("badge", help="print an SVG badge for one domain")
    b.add_argument("domain")
    a = ap.parse_args(argv)

    if a.cmd == "pick":
        from .sites import pick_sites, tranco
        meta, rows = tranco(ROOT / "cache", 1000)
        ua = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/140.0 Safari/537.36"
        kept, skipped = pick_sites(rows, ua, a.n)
        out = {"tranco": meta, "rule": "first N domains in Tranco rank order whose homepage answers with HTML; "
               "redirect duplicates dropped", "sites": kept, "skipped": skipped}
        (ROOT / "data").mkdir(exist_ok=True)
        (ROOT / "data" / "sites.json").write_text(json.dumps(out, indent=1), encoding="utf-8")
        print(f"kept {len(kept)} sites, skipped {len(skipped)} (deepest rank {kept[-1]['rank'] if kept else '-'})")
    elif a.cmd == "run":
        from .run import run
        sites = json.loads((ROOT / "data" / "sites.json").read_text(encoding="utf-8"))["sites"]
        if a.only:
            sites = [s for s in sites if s["domain"] in a.only]
        if a.limit:
            sites = sites[:a.limit]
        run(sites, ROOT, a.date, use_llm=not a.no_llm, log=lambda m: print(m, flush=True))
    elif a.cmd == "build":
        from .site import build
        print(build(ROOT))
    elif a.cmd == "badge":
        from .badge import badge_for
        data = json.loads((ROOT / "data" / "latest.json").read_text(encoding="utf-8"))
        hit = [s for s in data["sites"] if s["domain"] == a.domain]
        if not hit:
            sys.exit(f"{a.domain} not in latest run")
        sys.stdout.write(badge_for(hit[0]))


if __name__ == "__main__":
    main()
