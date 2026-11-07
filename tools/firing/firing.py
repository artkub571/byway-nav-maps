"""MoD firing times for the app (runs in GitHub Actions; gov.uk and Overpass
are not reachable from the dev sandbox).

  python tools/firing/firing.py snapshot --out DIR   # raw gov.uk + OSM data
  python tools/firing/firing.py build --raw DIR --out firing.json

Sources: gov.uk firing-times publications (Defence Infrastructure
Organisation, Open Government Licence) and OpenStreetMap military danger
areas (ODbL). Standard library only.
"""
from __future__ import annotations

import argparse
import json
import sys
import time
import urllib.parse
import urllib.request
from pathlib import Path

UA = 'ByWayNav-firing/1.0 (personal app; github actions)'
GOVUK = 'https://www.gov.uk'
OVERPASS = ['https://overpass-api.de/api/interpreter', 'https://overpass.private.coffee/api/interpreter']


def get(url: str, data: bytes | None = None, tries: int = 3) -> bytes:
    last = None
    for i in range(tries):
        try:
            req = urllib.request.Request(url, data=data, headers={'User-Agent': UA})
            with urllib.request.urlopen(req, timeout=180) as r:
                return r.read()
        except Exception as e:  # noqa: BLE001
            last = e
            time.sleep(3 * (i + 1))
    raise RuntimeError(f'{url}: {last}')


def search(q: str, org: str | None) -> list[dict]:
    params = {'q': q, 'count': '100', 'fields': 'title,link,public_timestamp,format,organisations'}
    if org:
        params['filter_organisations'] = org
    j = json.loads(get(f'{GOVUK}/api/search.json?{urllib.parse.urlencode(params)}'))
    return j.get('results', [])


def snapshot(out: Path) -> None:
    out.mkdir(parents=True, exist_ok=True)
    found: dict[str, dict] = {}
    for q in ('firing times', 'firing programme', 'live firing', 'range firing'):
        for org in ('defence-infrastructure-organisation', 'ministry-of-defence', None):
            try:
                for r in search(q, org):
                    found.setdefault(r['link'], r)
            except Exception as e:  # noqa: BLE001
                print('search failed', q, org, e, file=sys.stderr)
            time.sleep(0.5)
    keep = {k: v for k, v in found.items() if 'firing' in (v.get('title') or '').lower()}
    (out / 'search.json').write_text(json.dumps(sorted(keep.values(), key=lambda r: r['link']), indent=1))
    pages = out / 'pages'
    pages.mkdir(exist_ok=True)
    seen = set()

    def save(path: str, depth: int) -> None:
        if path in seen or len(seen) > 400:
            return
        seen.add(path)
        try:
            body = get(f'{GOVUK}/api/content{path}')
        except Exception as e:  # noqa: BLE001
            print('content failed', path, e, file=sys.stderr)
            return
        name = path.strip('/').replace('/', '__')[:200] + '.json'
        (pages / name).write_bytes(body)
        time.sleep(0.3)
        if depth >= 1:
            return
        try:
            j = json.loads(body)
        except ValueError:
            return
        for a in (j.get('details') or {}).get('attachments') or []:
            url = a.get('url') or ''
            if url.startswith(GOVUK):
                url = url[len(GOVUK):]
            html = a.get('attachment_type') == 'html' or (a.get('content_type') or '').startswith('text/html')
            if html and url.startswith('/'):
                save(url, depth + 1)
            elif url.lower().endswith('.pdf'):
                pdf = out / 'pdf'
                pdf.mkdir(exist_ok=True)
                if len(list(pdf.iterdir())) >= 120:
                    continue
                try:
                    (pdf / (url.rsplit('/', 1)[-1][:150])).write_bytes(get(url))
                except Exception as e:  # noqa: BLE001
                    print('pdf failed', url, e, file=sys.stderr)

    for link in keep:
        save(link, 0)
    # OpenStreetMap military danger areas in Great Britain.
    q = ('[out:json][timeout:170];area["ISO3166-1"="GB"][admin_level=2]->.gb;'
         '(way["military"="danger_area"](area.gb);relation["military"="danger_area"](area.gb);'
         'way["landuse"="military"]["name"~"[Rr]ange|[Tt]raining [Aa]rea"](area.gb);'
         'relation["landuse"="military"]["name"~"[Rr]ange|[Tt]raining [Aa]rea"](area.gb););out geom;')
    for ep in OVERPASS:
        try:
            (out / 'danger_areas.json').write_bytes(get(ep, urllib.parse.urlencode({'data': q}).encode()))
            break
        except Exception as e:  # noqa: BLE001
            print('overpass failed', ep, e, file=sys.stderr)
    print(f'{len(keep)} firing publications, {len(seen)} pages saved')


# ----------------------------------------------------------------- build

import html as _html
import math
import re
from datetime import date, timedelta

# Ranges the app shows: which notices (publication link, optional attachment
# title pattern), a point in the range and how far its danger areas reach.
# Lane-relevant ranges only; add more as needed.
RANGES = [
    ('spta', 'Salisbury Plain Training Area', '/government/publications/salisbury-plain-training-area-spta-firing-times', None, (51.23, -1.90), 22),
    ('otterburn', 'Otterburn Ranges', '/government/publications/otterburn-firing-times', None, (55.31, -2.20), 18),
    ('dartmoor', 'Dartmoor ranges (Okehampton, Willsworthy, Merrivale)', '/government/publications/dartmoor-firing-times', None, (50.63, -4.00), 14),
    ('warcop', 'Warcop Training Area', '/government/publications/warcop-firing-times', None, (54.59, -2.33), 10),
    # Castlemartin publishes PDFs only (not parsed yet).
    ('lulworth', 'Lulworth Ranges', '/government/publications/lulworth-firing-notice', None, (50.62, -2.21), 8),
    # No separate danger areas in OSM: the training area itself (access=restricted).
    ('sennybridge', 'Sennybridge Training Area', '/government/publications/sennybridge-firing-notice', None, (52.04, -3.62), 15),
    ('catterick', 'Catterick Training Area', '/government/publications/catterick-training-area-firing-and-activity-forecast', None, (54.40, -1.82), 14),
    ('stanta', 'Stanford Training Area (Thetford)', '/government/publications/east-region-firing-times', r'Thetford|Stanford', (52.53, 0.78), 12),
    ('longmoor', 'Longmoor ranges', '/government/publications/south-east-training-estate-firing-times', r'Longmoor', (51.07, -0.86), 6),
    ('pirbright', 'Ash, Bisley and Pirbright ranges', '/government/publications/south-east-training-estate-firing-times', r'Ash|Pirbright', (51.30, -0.68), 6),
]

_MONTHS = {m: i + 1 for i, m in enumerate(
    ['january', 'february', 'march', 'april', 'may', 'june', 'july', 'august', 'september', 'october', 'november', 'december'])}
_WEEKDAYS = ['monday', 'tuesday', 'wednesday', 'thursday', 'friday', 'saturday', 'sunday']


def body_text(body_html: str) -> str:
    """gov.uk HTML -> text with table cells as `cell | ` and rows on lines."""
    t = re.sub(r'<(br|/p|/tr|/h\d|/li)[^>]*>', '\n', body_html)
    t = re.sub(r'</t[dh]>', ' | ', t)
    t = _html.unescape(re.sub(r'<[^>]+>', '', t))
    return re.sub(r'\n\s*\n+', '\n', t)


def _clock(h: str, m: str | None, ap: str) -> int:
    hh = int(h) % 12 + (12 if ap.lower() == 'pm' else 0)
    return hh * 60 + int(m or 0)


def parse_times(s: str) -> list[list[int]] | None:
    """'9am to 5pm' -> [[540, 1020]] (minutes); 'No firing' -> [];
    Dartmoor's 'Firing (day)' / '(day & night)' -> 08:00-17:00 / 08:00-24:00
    (no hours given: deliberately wide). None = not understood."""
    t = s.strip().lower().replace('midnight', '12am').replace('noon', '12pm').replace('.', ':')
    if not t:
        return None
    if 'no firing' in t or t in ('none', 'nil'):
        return []
    if t.startswith('firing'):
        return [[480, 1440]] if 'night' in t else [[480, 1020]]
    out = []
    for m in re.finditer(r'(\d{1,2})(?::(\d{2}))?\s*(am|pm)\s*(?:to|-|–|until)\s*(\d{1,2})(?::(\d{2}))?\s*(am|pm)', t):
        a = _clock(m[1], m[2], m[3])
        b = _clock(m[4], m[5], m[6])
        if b <= a:
            b = 1440  # "to 12am": end of the day
        out.append([a, b])
    return out or None


def _merge(iv: list[list[int]]) -> list[list[int]]:
    out: list[list[int]] = []
    for a, b in sorted(iv):
        if out and a <= out[-1][1]:
            out[-1][1] = max(out[-1][1], b)
        else:
            out.append([a, b])
    return out


def parse_notice(title: str, text: str) -> dict[str, list[list[int]]]:
    """One monthly / six-week notice -> {ISO date: intervals}. Several areas
    in one notice are combined (any area firing counts)."""
    days: dict[str, list[list[int]]] = {}

    def add(d: date, iv):
        if iv is None:
            return
        days.setdefault(d.isoformat(), [])
        days[d.isoformat()] = _merge(days[d.isoformat()] + iv)

    mm = re.search(r'Firing times for ([A-Za-z]+) (\d{4})', text) or re.search(
        r'\b(January|February|March|April|May|June|July|August|September|October|November|December) (\d{4})', title)
    month = (_MONTHS[mm[1].lower()], int(mm[2])) if mm and mm[1].lower() in _MONTHS else None
    # Dartmoor-style table rows: "26 October 2026 | a | b | c |"
    for m in re.finditer(r'(\d{1,2}) ([A-Za-z]+) (\d{4})\s*\|((?:\s*[^|\n]+?\s*\|){1,3})', text):
        if m[2].lower() not in _MONTHS:
            continue
        cells = [c for c in m[4].split('|') if c.strip()]
        ivs = [parse_times(c) for c in cells]
        if any(v is not None for v in ivs):
            add(date(int(m[3]), _MONTHS[m[2].lower()], int(m[1])), [x for v in ivs if v for x in v])
    # Dated rows: "01 November: | 10am to 4pm |"
    for m in re.finditer(r'(\d{1,2})(?:st|nd|rd|th)? ([A-Za-z]+):?\s*\|\s*([^|\n]+?)\s*\|', text):
        if m[2].lower() not in _MONTHS or not month:
            continue
        mon = _MONTHS[m[2].lower()]
        year = month[1] + (1 if mon < month[0] - 6 else 0)
        try:
            add(date(year, mon, int(m[1])), parse_times(m[3]))
        except ValueError:
            pass
    # Weekday pattern for the whole month: "Monday: | 9am to 5pm |"
    pattern = {}
    for m in re.finditer(r'(Monday|Tuesday|Wednesday|Thursday|Friday|Saturday|Sunday):?\s*\|\s*([^|\n]+?)\s*\|', text):
        iv = parse_times(m[2])
        if iv is not None:
            wd = _WEEKDAYS.index(m[1].lower())
            pattern[wd] = _merge(pattern.get(wd, []) + iv)
    if pattern and month:
        d = date(month[1], month[0], 1)
        while d.month == month[0]:
            if d.weekday() in pattern and d.isoformat() not in days:
                add(d, pattern[d.weekday()])
            d += timedelta(days=1)
    return days


def _rings(e: dict) -> list[list[list[float]]]:
    if e['type'] == 'way':
        g = e.get('geometry') or []
        return [[[p['lon'], p['lat']] for p in g]] if len(g) >= 4 else []
    # Relation: chain outer member ways into rings.
    parts = [[[p['lon'], p['lat']] for p in (m.get('geometry') or [])]
             for m in e.get('members', []) if m.get('role') in ('outer', '') and m.get('geometry')]
    rings = []
    while parts:
        ring = parts.pop(0)
        changed = True
        while changed and ring[0] != ring[-1]:
            changed = False
            for i, p in enumerate(parts):
                if p[0] == ring[-1]:
                    ring += p[1:]
                elif p[-1] == ring[-1]:
                    ring += p[::-1][1:]
                else:
                    continue
                parts.pop(i)
                changed = True
                break
        if len(ring) >= 4:
            rings.append(ring)
    return rings


def _simplify(pts: list[list[float]], tol_m: float = 25) -> list[list[float]]:
    if len(pts) <= 4:
        return pts
    k = math.cos(math.radians(pts[0][1]))
    xy = [(p[0] * 111320 * k, p[1] * 110540) for p in pts]

    def dp(i: int, j: int, keep: set):
        (x1, y1), (x2, y2) = xy[i], xy[j]
        dx, dy = x2 - x1, y2 - y1
        n = math.hypot(dx, dy) or 1e-9
        best, bi = 0.0, -1
        for q in range(i + 1, j):
            x, y = xy[q]
            d = abs(dy * x - dx * y + x2 * y1 - y2 * x1) / n
            if d > best:
                best, bi = d, q
        if best > tol_m:
            keep.add(bi)
            dp(i, bi, keep)
            dp(bi, j, keep)

    last = len(pts) - 1
    keep = {0, last}
    if xy[0] == xy[last]:
        # Closed ring: the chord start-end is a point, so split at the vertex
        # farthest from the start and simplify both halves.
        far = max(range(1, last), key=lambda q: math.hypot(xy[q][0] - xy[0][0], xy[q][1] - xy[0][1]))
        keep.add(far)
        dp(0, far, keep)
        dp(far, last, keep)
    else:
        dp(0, last, keep)
    return [[round(pts[i][0], 5), round(pts[i][1], 5)] for i in sorted(keep)]


def _km(a, b) -> float:
    return math.hypot((a[1] - b[1]) * 111.32 * math.cos(math.radians(a[0])), (a[0] - b[0]) * 110.54)


def build(raw: Path, out: Path, today: date | None = None) -> dict:
    today = today or date.today()
    pages = {}
    for f in (raw / 'pages').glob('*.json'):
        try:
            j = json.loads(f.read_text())
        except ValueError:
            continue
        pages[j.get('base_path') or ''] = j
    osm = json.loads((raw / 'danger_areas.json').read_text()).get('elements', []) if (raw / 'danger_areas.json').exists() else []
    ranges = []
    for rid, name, pub, title_re, centre, radius in RANGES:
        days: dict[str, list[list[int]]] = {}
        sources = []
        parent = pages.get(pub)
        for path, j in pages.items():
            if not path.startswith(pub + '/'):
                continue
            title = j.get('title') or ''
            if title_re and not re.search(title_re, title):
                continue
            got = parse_notice(title, body_text((j.get('details') or {}).get('body') or ''))
            if got:
                sources.append({'title': title, 'url': GOVUK + path})
                for d, iv in got.items():
                    days[d] = _merge(days.get(d, []) + iv)
        keep_from = (today - timedelta(days=1)).isoformat()
        days = {d: v for d, v in sorted(days.items()) if d >= keep_from}
        areas = []
        for e in osm:
            t = e.get('tags') or {}
            mil = t.get('military')
            if mil not in ('danger_area', 'range') and not (
                    rid == 'sennybridge' and mil == 'training_area' and t.get('access') == 'restricted'):
                continue
            for ring in _rings(e):
                c = (sum(p[1] for p in ring) / len(ring), sum(p[0] for p in ring) / len(ring))
                if _km(c, centre) <= radius:
                    areas.append({'name': t.get('name') or t.get('military').replace('_', ' '),
                                  'ring': _simplify(ring)})
        ranges.append({
            'id': rid, 'name': name,
            'url': GOVUK + pub,
            'notices': sources,
            'days': days,
            'areas': areas,
            'parent_updated': (parent or {}).get('public_updated_at'),
        })
    doc = {'kind': 'byway-nav-firing', 'version': 1, 'built': today.isoformat(),
           'licence': 'Firing times: gov.uk, Open Government Licence v3.0. Danger areas: © OpenStreetMap contributors (ODbL).',
           'ranges': ranges}
    out.write_text(json.dumps(doc, separators=(',', ':')))
    return doc


def main() -> None:
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest='cmd', required=True)
    s = sub.add_parser('snapshot')
    s.add_argument('--out', required=True)
    b = sub.add_parser('build')
    b.add_argument('--raw', required=True)
    b.add_argument('--out', required=True)
    args = ap.parse_args()
    if args.cmd == 'snapshot':
        snapshot(Path(args.out))
    else:
        doc = build(Path(args.raw), Path(args.out))
        for r in doc['ranges']:
            print(f"{r['id']:12s} {len(r['days']):3d} days {len(r['areas']):3d} areas  {len(r['notices'])} notices")
        print(f"-> {args.out} ({Path(args.out).stat().st_size // 1024} KB)")


if __name__ == '__main__':
    main()
