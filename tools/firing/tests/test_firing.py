"""Tests for the MoD firing-times parser (run: python -m pytest -q tools/firing/tests)."""
import json
import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import firing  # noqa: E402

WEEKDAY = """Firing times for November 2026:
These are the standard firing times subject to operational requirement extensions:
SPTA
      Monday: | 
      9am to 5pm | 
      Tuesday: | 
      9am to 11:30pm | 
      Wednesday: | 
      9am to 5pm | 
      Thursday: | 
      9am to 11:30pm | 
      Friday: | 
      9am to 5pm | 
      Saturday: | 
      9am to 11:30pm | 
      Sunday: | 
      9am to 1pm | 
"""

DATED = """Firing times for November 2026:
Otterburn Ranges
      01 November: | 
      10am to 4pm | 
      07 November: | 
      No firing | 
      30 November: | 
      7:30am to midnight | 
"""

DARTMOOR = """October
      Date | 
      Okehampton | 
      Willsworthy | 
      Merrivale | 
      26 October 2026 | 
      No firing | 
      Firing (day & night) | 
      No firing | 
      30 October 2026 | 
      No firing | 
      No firing | 
      No firing | 
November
      03 November 2026 | 
      No firing | 
      Firing (day) | 
      No firing | 
"""


def test_times():
    assert firing.parse_times('9am to 5pm') == [[540, 1020]]
    assert firing.parse_times('9am to 11:30pm') == [[540, 1410]]
    assert firing.parse_times('7:30am to midnight') == [[450, 1440]]
    assert firing.parse_times('9am to 5:30pm and 8pm to midnight') == [[540, 1050], [1200, 1440]]
    assert firing.parse_times('No firing') == []
    assert firing.parse_times('Firing (day)') == [[480, 1020]]
    assert firing.parse_times('Firing (day & night)') == [[480, 1440]]
    assert firing.parse_times('see website') is None


def test_weekday_pattern_fills_the_month():
    days = firing.parse_notice('SPTA firing times: November 2026', WEEKDAY)
    assert len(days) == 30
    assert days['2026-11-01'] == [[540, 780]]  # a Sunday: 9am to 1pm
    assert days['2026-11-03'] == [[540, 1410]]  # a Tuesday


def test_dated_rows():
    days = firing.parse_notice('Otterburn November 2026', DATED)
    assert days == {'2026-11-01': [[600, 960]], '2026-11-07': [], '2026-11-30': [[450, 1440]]}


def test_dartmoor_table_any_range_counts():
    days = firing.parse_notice('Dartmoor six week firing times', DARTMOOR)
    assert days['2026-10-26'] == [[480, 1440]]
    assert days['2026-10-30'] == []
    assert days['2026-11-03'] == [[480, 1020]]


def test_build_matches_areas_by_distance(tmp_path):
    raw = tmp_path / 'raw'
    (raw / 'pages').mkdir(parents=True)
    pub = '/government/publications/salisbury-plain-training-area-spta-firing-times'
    (raw / 'pages' / 'p.json').write_text(json.dumps({'base_path': pub, 'title': 'SPTA firing times'}))
    (raw / 'pages' / 'a.json').write_text(json.dumps({
        'base_path': pub + '/spta-november', 'title': 'SPTA firing times: November 2026',
        'details': {'body': WEEKDAY.replace(' | ', '</td>').replace('\n', '<br>')}}))
    square = lambda lat, lon, n: [{'lat': lat + dy, 'lon': lon + dx} for dx, dy in ((0, 0), (0.01, 0), (0.01, 0.01), (0, 0.01), (0, 0))][:n]
    (raw / 'danger_areas.json').write_text(json.dumps({'elements': [
        {'type': 'way', 'tags': {'military': 'danger_area', 'name': 'Imber Range'}, 'geometry': square(51.23, -2.06, 5)},
        {'type': 'way', 'tags': {'military': 'danger_area', 'name': 'Far away'}, 'geometry': square(54.0, -2.0, 5)},
        {'type': 'way', 'tags': {'military': 'training_area', 'name': 'Open training area'}, 'geometry': square(51.2, -1.9, 5)},
    ]}))
    doc = firing.build(raw, tmp_path / 'firing.json', today=date(2026, 11, 2))
    spta = next(r for r in doc['ranges'] if r['id'] == 'spta')
    assert [a['name'] for a in spta['areas']] == ['Imber Range']
    assert len(spta['areas'][0]['ring']) == 5, 'closed rings keep their shape'
    assert '2026-11-01' in spta['days'] and '2026-10-31' not in spta['days']
    assert spta['notices'][0]['url'].endswith('/spta-november')


def test_simplify_keeps_closed_rings():
    import math
    ring = [[-2.0 + 0.05 * math.cos(a / 20 * 2 * math.pi), 51.2 + 0.03 * math.sin(a / 20 * 2 * math.pi)] for a in range(20)]
    ring.append(ring[0])
    out = firing._simplify(ring, 25)
    assert out[0] == out[-1] and len(out) >= 8
