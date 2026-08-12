#!/usr/bin/env python3
"""
fetch-images.py
===============
Fills the ./images/ folder that Supply Chain Control Tower reads from.

Every photograph comes from Wikimedia Commons and is filtered to licences
that permit reuse (public domain, CC0, CC BY, CC BY-SA). The author and
licence of each file are written to images/credits.js, which the app loads
and prints in the corner of each frame. That attribution is a condition of
the CC BY and CC BY-SA licences, so leave it in place.

Standard library only. No pip install.

    python3 fetch-images.py                 download into ./images/
    python3 fetch-images.py --dry-run       show what it would take, download nothing
    python3 fetch-images.py --only logistics warehouse risk
    python3 fetch-images.py --embed app.html
                                            write a single self-contained file
                                            with every photograph base64'd in

The last one is the option to use if the app has to travel as one file with
no folder beside it. It roughly doubles the file size.
"""

import argparse
import base64
import json
import os
import re
import sys
import urllib.parse
import urllib.request

API = "https://commons.wikimedia.org/w/api.php"
UA = "SupplyChainControlTower/1.0 (educational project; contact via repository)"

# Licences that permit reuse. Anything not matching one of these is skipped.
OK_LICENCE = re.compile(
    r"(public domain|^pd|cc0|cc[- ]by([- ]sa)?([- ]\d)?)", re.I
)

# One search per artwork slot. The slot name is the filename the app expects.
# Order matters: the first result that passes every filter is the one taken.
QUERIES = {
    "tower":      "logistics operations control room screens",
    "data":       "barcode scanner warehouse carton",
    "demand":     "supermarket aisle shelves groceries",
    "inventory":  "warehouse pallet racking high bay",
    "plan":       "production planning board factory schedule",
    "sourcing":   "electronic components manufacturing line",
    "production": "car assembly line factory robots",
    "logistics":  "container ship gantry crane port terminal",
    "warehouse":  "forklift warehouse aisle pallets",
    "finance":    "invoice ledger calculator desk",
    "risk":       "container ships anchorage port congestion",
    "review":     "business meeting boardroom table",
    "library":    "library bookshelves reading room",
    "fresh":      "refrigerated container reefer quayside",
    "wall":       "industrial machine production bottleneck factory",
    "game":       "conference table four chairs meeting room",
    "sales":      "retail counter customer service shop",
    "purchasing": "contract signing document pen desk",
    "scm":        "container terminal aerial view",
}

MIN_WIDTH = 1200
THUMB_WIDTH = 1600
MIN_RATIO, MAX_RATIO = 1.15, 2.80   # landscape, not a panorama


def api(params):
    params = dict(params)
    params.update({"action": "query", "format": "json", "formatversion": "2"})
    url = API + "?" + urllib.parse.urlencode(params)
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=45) as r:
        return json.load(r)


def meta(page, key):
    em = (page.get("imageinfo") or [{}])[0].get("extmetadata") or {}
    return re.sub(r"<[^>]+>", "", str(em.get(key, {}).get("value", ""))).strip()


def find(slot, query, verbose=True):
    """Return (thumburl, credit dict) for the best licence-clean landscape hit."""
    try:
        data = api({
            "generator": "search",
            "gsrsearch": query + " filetype:bitmap",
            "gsrnamespace": "6",
            "gsrlimit": "30",
            "prop": "imageinfo",
            "iiprop": "url|size|mime|extmetadata",
            "iiurlwidth": str(THUMB_WIDTH),
        })
    except Exception as e:
        print("  ! search failed for %s: %s" % (slot, e))
        return None, None

    for page in (data.get("query") or {}).get("pages", []):
        ii = (page.get("imageinfo") or [{}])[0]
        if ii.get("mime") != "image/jpeg":
            continue
        w, h = ii.get("width", 0), ii.get("height", 1)
        if w < MIN_WIDTH or not (MIN_RATIO <= w / float(h) <= MAX_RATIO):
            continue
        lic = meta(page, "LicenseShortName") or meta(page, "License")
        if not OK_LICENCE.search(lic):
            continue
        author = meta(page, "Artist") or "Wikimedia Commons contributor"
        return ii.get("thumburl") or ii.get("url"), {
            "author": author[:80],
            "license": lic[:40],
            "title": page.get("title", ""),
            "url": ii.get("descriptionurl", ""),
        }

    if verbose:
        print("  ! nothing passed the filters for %s (try a different query)" % slot)
    return None, None


def download(url, path):
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=90) as r:
        data = r.read()
    with open(path, "wb") as f:
        f.write(data)
    return len(data)


def write_credits(folder, credits):
    js = ("/* Generated by fetch-images.py. Attribution for the photographs in\n"
          "   this folder. Required by the CC BY and CC BY-SA licences. */\n"
          "window.PHOTO_CREDITS = " + json.dumps(credits, indent=2, ensure_ascii=False) + ";\n")
    with open(os.path.join(folder, "credits.js"), "w", encoding="utf-8") as f:
        f.write(js)


def embed(html_path, folder):
    """Base64 every downloaded photograph into a single self-contained file."""
    data = {}
    for slot in QUERIES:
        p = os.path.join(folder, slot + ".jpg")
        if os.path.exists(p):
            with open(p, "rb") as f:
                data[slot] = "data:image/jpeg;base64," + base64.b64encode(f.read()).decode()
    if not data:
        sys.exit("No images in %s yet. Run without --embed first." % folder)

    credits = {}
    cpath = os.path.join(folder, "credits.js")
    if os.path.exists(cpath):
        raw = open(cpath, encoding="utf-8").read()
        m = re.search(r"window\.PHOTO_CREDITS\s*=\s*(\{.*\});", raw, re.S)
        if m:
            credits = json.loads(m.group(1))

    html = open(html_path, encoding="utf-8").read()
    block = ("<script>\nwindow.PHOTO_CREDITS = %s;\nwindow.PHOTO_DATA = %s;\n</script>\n"
             % (json.dumps(credits, ensure_ascii=False), json.dumps(data)))
    marker = '<script src="images/credits.js"'
    i = html.find(marker)
    if i == -1:
        i = html.find("<script>")
        html = html[:i] + block + html[i:]
    else:
        j = html.find("</script>", i) + len("</script>\n")
        html = html[:i] + block + html[j:]

    out = os.path.splitext(html_path)[0] + "-standalone.html"
    open(out, "w", encoding="utf-8").write(html)
    mb = os.path.getsize(out) / 1048576.0
    print("Wrote %s (%.1f MB, %d photographs embedded)" % (out, mb, len(data)))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--only", nargs="*", default=None)
    ap.add_argument("--folder", default="images")
    ap.add_argument("--embed", metavar="APP_HTML", default=None)
    a = ap.parse_args()

    if a.embed:
        return embed(a.embed, a.folder)

    slots = a.only if a.only else list(QUERIES)
    unknown = [s for s in slots if s not in QUERIES]
    if unknown:
        sys.exit("Unknown slot(s): %s\nKnown: %s" % (", ".join(unknown), ", ".join(QUERIES)))

    if not a.dry_run:
        os.makedirs(a.folder, exist_ok=True)

    credits = {}
    cpath = os.path.join(a.folder, "credits.js")
    if os.path.exists(cpath):
        m = re.search(r"window\.PHOTO_CREDITS\s*=\s*(\{.*\});",
                      open(cpath, encoding="utf-8").read(), re.S)
        if m:
            credits = json.loads(m.group(1))

    got = 0
    for slot in slots:
        print("%-11s %s" % (slot, QUERIES[slot]))
        url, credit = find(slot, QUERIES[slot])
        if not url:
            continue
        print("            %s  [%s]" % (credit["title"], credit["license"]))
        if a.dry_run:
            got += 1
            continue
        try:
            n = download(url, os.path.join(a.folder, slot + ".jpg"))
            print("            saved %s/%s.jpg  %d kB" % (a.folder, slot, n // 1024))
            credits[slot] = credit
            got += 1
        except Exception as e:
            print("  ! download failed: %s" % e)

    if not a.dry_run and credits:
        write_credits(a.folder, credits)
        print("\nWrote %s/credits.js" % a.folder)

    print("\n%d of %d slots filled." % (got, len(slots)))
    if not a.dry_run:
        print("Open the app. Any slot still missing keeps its drawn diagram.")


if __name__ == "__main__":
    main()
