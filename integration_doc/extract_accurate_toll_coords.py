"""Extract accurate toll-plaza coordinates from CartrackGeofence rows.

The toll-plaza coordinates in toll_geofences_for_cartrack.csv are
approximations I derived from public data — 3-4 decimal places of
precision, ~100m error margin. Map markers don't line up with the
actual booths on satellite view.

But the user has already drawn each toll geofence themselves in the
Cartrack Fleet Web UI. Those polygons are positioned precisely on the
real booth. Our sync_geofences() routine has pulled them into the
local CartrackGeofence table as polygon_wkt strings. So the
authoritative coordinates live IN OUR OWN DATABASE — we just need to
extract them.

Algorithm:
  1. Query CartrackGeofence where category='toll' AND polygon_wkt is set
  2. Parse each polygon_wkt (Cartrack returns WKT-flavoured strings —
     could be "POLYGON((lng1 lat1, lng2 lat2, ...))" or a CSV / JSON
     blob; we handle the most common shapes)
  3. Compute the centroid (geometric center) of the polygon points
  4. Compute the bounding radius (max distance from centroid to any
     polygon vertex) — that's the smallest circle that fully covers
     the geofence
  5. Output as a JSON file the rest of the toolchain can consume

Usage on PythonAnywhere:
  python integration_doc/extract_accurate_toll_coords.py

Output:
  integration_doc/accurate_toll_coords.json
"""
import json
import math
import os
import re
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.dirname(_HERE)
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)


def _parse_polygon_points(wkt):
    """Extract a list of (lat, lng) tuples from a Cartrack polygon string.

    Tries three formats in order:
      1. WKT POLYGON  — "POLYGON((lng lat, lng lat, ...))"
      2. JSON array  — '[[lat,lng], [lat,lng], ...]'
      3. CSV pairs   — "lat,lng;lat,lng;..."  (or comma-separated)

    The order WKT uses (lng first, then lat) is the inverse of the
    "human" order (lat,lng) — easy to flip accidentally. We detect
    based on plausible PH coordinate ranges (lat 4-22, lng 116-127)
    and swap if the values are obviously transposed.
    """
    if not wkt or not isinstance(wkt, str):
        return []
    s = wkt.strip()
    points = []

    # Format 1: WKT POLYGON
    m = re.search(r'POLYGON\s*\(\s*\(\s*(.+?)\s*\)\s*\)', s,
                  re.IGNORECASE | re.DOTALL)
    if m:
        body = m.group(1)
        for pair in body.split(','):
            parts = pair.strip().split()
            if len(parts) >= 2:
                try:
                    a, b = float(parts[0]), float(parts[1])
                    # WKT convention: longitude first, latitude second.
                    points.append((b, a))   # store as (lat, lng)
                except ValueError:
                    continue
        if points:
            return _maybe_swap_lat_lng(points)

    # Format 2: JSON array
    if s.startswith('[') or s.startswith('{'):
        try:
            data = json.loads(s)
            # [[a,b], [a,b], ...]
            if isinstance(data, list):
                for item in data:
                    if isinstance(item, (list, tuple)) and len(item) >= 2:
                        try:
                            points.append((float(item[0]), float(item[1])))
                        except (ValueError, TypeError):
                            continue
            # {coordinates: [[lng,lat], ...]} — GeoJSON-ish
            elif isinstance(data, dict) and 'coordinates' in data:
                coords = data['coordinates']
                # Flatten one level if needed
                if (coords and isinstance(coords, list)
                        and coords and isinstance(coords[0], list)
                        and coords[0] and isinstance(coords[0][0], list)):
                    coords = coords[0]
                for item in (coords or []):
                    if isinstance(item, (list, tuple)) and len(item) >= 2:
                        try:
                            # GeoJSON: [lng, lat]
                            points.append((float(item[1]), float(item[0])))
                        except (ValueError, TypeError):
                            continue
            if points:
                return _maybe_swap_lat_lng(points)
        except (json.JSONDecodeError, ValueError):
            pass

    # Format 3: CSV pairs separated by semicolons or `;`
    for sep in (';', '|', '\n'):
        if sep in s:
            for pair in s.split(sep):
                parts = re.split(r'[,\s]+', pair.strip())
                if len(parts) >= 2:
                    try:
                        points.append((float(parts[0]), float(parts[1])))
                    except ValueError:
                        continue
            if points:
                return _maybe_swap_lat_lng(points)

    return []


def _maybe_swap_lat_lng(points):
    """Heuristic — if 'lat' values look like longitudes (>100), the
    parser probably grabbed them in the wrong order. Swap so lat
    stays in the plausible PH range (4-22) and lng stays in 116-127.
    """
    if not points:
        return points
    sample_lat = points[0][0]
    sample_lng = points[0][1]
    if 100 < sample_lat < 130 and 4 < sample_lng < 25:
        # Transposed — swap.
        return [(lng, lat) for (lat, lng) in points]
    return points


def _centroid(points):
    """Average lat, average lng. Good enough for small polygons (toll
    geofences are <500m across)."""
    if not points:
        return None
    lats = [p[0] for p in points]
    lngs = [p[1] for p in points]
    return (sum(lats) / len(lats), sum(lngs) / len(lngs))


def _haversine_m(lat1, lng1, lat2, lng2):
    """Distance between two GPS points in metres."""
    R = 6_371_000
    rlat1, rlat2 = math.radians(lat1), math.radians(lat2)
    dlat = math.radians(lat2 - lat1)
    dlng = math.radians(lng2 - lng1)
    a = (math.sin(dlat / 2) ** 2
         + math.cos(rlat1) * math.cos(rlat2) * math.sin(dlng / 2) ** 2)
    return 2 * R * math.asin(math.sqrt(a))


def _bounding_radius_m(centroid, points):
    """Max distance from centroid to any polygon vertex, in metres."""
    if not centroid or not points:
        return 0
    return max(_haversine_m(centroid[0], centroid[1], p[0], p[1])
                for p in points)


def main():
    """Generate accurate_toll_coords.json from the local DB."""
    # Boot the Flask app so SQLAlchemy is configured.
    import app_v3
    from models_v2 import db, CartrackGeofence

    with app_v3.app.app_context():
        rows = (CartrackGeofence.query
                .filter(CartrackGeofence.category == 'toll')
                .filter(CartrackGeofence.polygon_wkt.isnot(None))
                .order_by(CartrackGeofence.name)
                .all())

        print(f'Found {len(rows)} toll geofences with polygon data.\n')

        out = []
        skipped = 0
        for r in rows:
            pts = _parse_polygon_points(r.polygon_wkt)
            if not pts:
                print(f'  SKIP (unparseable polygon): {r.name}')
                skipped += 1
                continue
            c = _centroid(pts)
            radius_m = _bounding_radius_m(c, pts)
            # Pad the radius slightly — geofence drawn tight to booth
            # would be hard to capture with GPS jitter. 20m buffer.
            radius_padded = int(radius_m + 20)
            entry = {
                'cartrack_id': r.cartrack_id,
                'name':        r.name,
                'category':    'toll',
                'lat':         round(c[0], 6),
                'lng':         round(c[1], 6),
                'radius_m':    radius_padded,
                'polygon_points':  len(pts),
                'tight_radius_m':  round(radius_m, 1),
            }
            out.append(entry)
            print(f'  OK  {r.name:35s} centroid=({c[0]:.6f}, {c[1]:.6f}) r={radius_padded}m ({len(pts)} pts)')

        out_path = os.path.join(_HERE, 'accurate_toll_coords.json')
        with open(out_path, 'w', encoding='utf-8') as f:
            json.dump(out, f, indent=2, ensure_ascii=False)

        print(f'\nWrote {len(out)} accurate plaza entries to:')
        print(f'  {out_path}')
        print(f'Skipped {skipped} entries (unparseable polygon).')
        print()
        print('Next: download this file and share with the assistant — it')
        print('will regenerate the toll_plazas_map.html with these')
        print('booth-accurate coordinates instead of the rough approximations.')


if __name__ == '__main__':
    main()
