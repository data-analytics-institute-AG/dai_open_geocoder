import os
import requests
from urllib.parse import urljoin


SOLR_URL = os.getenv("SOLR_URL", "http://solr:8983/solr/addresses")
_SELECT = urljoin(SOLR_URL.rstrip("/") + "/", "select")
_TIMEOUT = 6
_session = requests.Session()

def _clean_str(v):
    return (v or "").strip()

def _have_plz_or_ort(plz, ort):
    return bool(_clean_str(plz)) or bool(_clean_str(ort))

def _as_string(v):
    if v is None: return ""
    return v[0] if isinstance(v, list) else v

def _normalize_doc(d):
    """Return a consistent shape for API consumers."""
    return {
        "id": d.get("id"),
        "plz": d.get("plz"),
        "ort": _as_string(d.get("ort")),
        "strasse": _as_string(d.get("strasse")),
        "hausnummer": _as_string(d.get("hausnummer")),
        "koordinate": d.get("koordinate"),
        "score": float(d.get("score", 0.0)),
    }

# ---------- exact strategies (use fq filters) ----------
def _query_exact(plz=None, ort=None, strasse=None, hausnummer=None, rows=5):
    fqs = []
    if plz:        fqs.append(f'plz:"{plz}"')
    if ort:        fqs.append(f'ort:"{ort}"')
    if strasse:    fqs.append(f'strasse:"{strasse}"')
    if hausnummer: fqs.append(f'hausnummer:"{hausnummer}"')

    params = {
        "defType": "edismax",
        "q": "*:*",
        "rows": rows,
        "wt": "json",
        "fl": "id,plz,ort,strasse,hausnummer,koordinate,score",
    }
    for fq in fqs:
        # multiple fq= entries allowed
        params.setdefault("fq", [])
        params["fq"].append(fq)

    return _solr_select(params)

def _query_fuzzy(plz=None, ort=None, strasse=None, hausnummer=None, rows=5):
    """
    Fuzzy query with explicit field names, dynamic fuzziness per token.
    Each field is queried separately, preserving context.
    """
    parts = []
    if plz:        parts.append(_dynamic_fuzzy("plz", plz))
    if ort:        parts.append(_dynamic_fuzzy("ort", ort))
    if strasse:    parts.append(_dynamic_fuzzy("strasse", strasse))
    if hausnummer: parts.append(_dynamic_fuzzy("hausnummer", hausnummer))

    # If nothing provided, fallback to match all
    q = " AND ".join(parts) or "*:*"

    params = {
        "defType": "edismax",
        "q": q,
        "qf": "plz^5 ort^4 strasse^6 hausnummer^3",
        "pf": "strasse^10 ort^6",
        "ps": 2,
        "mm": "2<75%",
        "tie": "0.1",
        "sow": "true",
        "rows": rows,
        "wt": "json",
        "fl": "id,plz,ort,strasse,hausnummer,koordinate,score",
    }

    return _solr_select(params)
def query_address(data: dict, rows: int = 5):
    """
    Try geocoding with cascading strategies. Only execute if plz or ort provided.

    Order:
      1) All params exact
      2) All params except hausnummer exact
      3) All params fuzzy
      4) All params except hausnummer fuzzy
      5) Only ort + strasse fuzzy
      6) Only plz + strasse fuzzy

    Returns:
      dict: {
        "strategy": "<name>",
        "results": [ ... up to rows ... ],
        "count": <int>
      }
      or {} if no match.
    """
    plz        = _clean_str(data.get("plz"))
    ort        = _clean_str(data.get("ort"))
    strasse    = _clean_str(data.get("strasse"))
    hausnummer = _clean_str(data.get("hausnummer"))

    if not _have_plz_or_ort(plz, ort):
        raise ValueError("Geocoding requires at least one of: plz or ort")

    strategies = [
        # name, callable, kwargs
        ("exact_all",               _query_exact, {"plz": plz, "ort": ort, "strasse": strasse, "hausnummer": hausnummer}),
        ("exact_no_hausnummer",     _query_exact, {"plz": plz, "ort": ort, "strasse": strasse, "hausnummer": None}),
        ("fuzzy_all",               _query_fuzzy, {"plz": plz, "ort": ort, "strasse": strasse, "hausnummer": hausnummer}),
        ("fuzzy_no_hausnummer",     _query_fuzzy, {"plz": plz, "ort": ort, "strasse": strasse, "hausnummer": None}),
        ("fuzzy_ort_strasse",       _query_fuzzy, {"plz": None, "ort": ort, "strasse": strasse, "hausnummer": None}),
        ("fuzzy_plz_strasse",       _query_fuzzy, {"plz": plz, "ort": None, "strasse": strasse, "hausnummer": None}),
    ]

    for name, func, kwargs in strategies:
        res = func(rows=rows, **kwargs)
        docs = res.get("response", {}).get("docs", [])
        if docs:
            normalized = [_normalize_doc(d) for d in docs]
            return {"strategy": name, "results": normalized, "count": len(normalized)}

    # nothing found
    return {"strategy": None, "results": [], "count": 0}

def _solr_select(params: dict):
    r = _session.get(_SELECT, params=params, timeout=_TIMEOUT)
    r.raise_for_status()
    return r.json()

def _coerce_float(x, name):
    try:
        return float(x)
    except Exception:
        raise ValueError(f"Invalid {name}: {x!r}")

def _coerce_int(x, name):
    try:
        return int(x)
    except Exception:
        raise ValueError(f"Invalid {name}: {x!r}")

def query_reverse(data: dict):
    """
    Reverse geocoding via Solr spatial search.

    Expected keys in `data`:
      - lat (required, float/str)
      - lon (required, float/str)
      - max_results (optional, int) default: 5 (clamped 1..100)
      - max_radius (optional, float, km) default: 1.0 (must be >0)

    Returns:
      list[dict]: nearest matches inside radius, sorted by distance asc.
                  Each item contains: id, plz, ort, strasse, hausnummer,
                  koordinate, distance_km, score
    """
    if "lat" not in data or "lon" not in data:
        raise ValueError("Missing coordinates: require 'lat' and 'lon'")

    lat = _coerce_float(data["lat"], "lat")
    lon = _coerce_float(data["lon"], "lon")
    max_results = _coerce_int(data.get("max_results", 5), "max_results")
    max_radius = float(data.get("max_radius", 1000.0))

    # sanity limits
    if max_results < 1: max_results = 1
    if max_results > 100: max_results = 100
    if max_radius <= 0:
        raise ValueError("max_radius must be > 0 (km)")

    # Build Solr params:
    # - geofilt restricts to the circle of radius d (km)
    # - geodist() used for sorting and returned as distance
    params = {
        "q": "*:*",
        "rows": max_results,
        "wt": "json",
        "sort": "geodist() asc",
        "sfield": "koordinate",
        "pt": f"{lat},{lon}",
        "fq": f"{{!geofilt sfield=koordinate pt={lat},{lon} d={max_radius}}}",
        # return standard fields + computed distance as 'distance_km'
        "fl": "id,plz,ort,strasse,hausnummer,koordinate,score,"
              "distance_km:geodist()",
    }

    res = _solr_select(params)
    docs = res.get("response", {}).get("docs", [])

    # Normalize result shape; ensure only first array element is returned
    results = []
    for d in docs:
        # ort/strasse/hausnummer may be single values or lists depending on schema
        def as_list(v):
            if v is None:
                return ""
            return v[0] if isinstance(v, list) else v

        results.append({
            "id": d.get("id"),
            "plz": d.get("plz"),
            "ort": d.get("ort"),
            "strasse": d.get("strasse"),
            "hausnummer": d.get("hausnummer"),
            "koordinate": d.get("koordinate"),   # typically "lat,lon" string for LatLonPointSpatialField
            "distance_km": float(d.get("distance_km", 0.0)),
        })

    return results

def _dynamic_fuzzy(fieldname, token):
    """
    Returns token with fuzziness depending on length:
      - len <= 3: no fuzz (~0)
      - len 4-5: ~1
      - len >=6: ~2
    """
    token = str(token).strip()
    if not token:
        return ""
    l = len(token)
    if l <= 3:
        return fieldname + ":" + token  # no fuzz for very short terms
    elif l <= 5:
        return f"{fieldname}:{token}~1"
    else:
        return f"{fieldname}:{token}~2"
