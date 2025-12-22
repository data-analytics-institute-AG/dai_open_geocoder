import os
import requests
import json
import re
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
    # Get Mapping solr-Field -> Outputname
    mapping = load_mapping()
    r = {}
    # Special handling: flatten additional_information field
    # for now excluded
    if 'additional_information' in d:
        values = json.loads(d['additional_information'])
        for k,v in values.items():
            #if v and v != '':
                r[k] = v
        del d['additional_information']
    # Start with empty return dict to be filled
    # rtn = {}
    # loop through all result fields and map if possible
    # for k,v in d.items():
    #     if not v or v == '':
    #         continue
    #     index = next((i for i, m in enumerate(mapping) if m.get("solr_field") == k), None)
    #     if index is not None:
    #         rtn[k] = _as_string(v)
    #         #rtn[mapping[index]['output_name']] = _as_string(v)  translation disabled for now
    #     else:
    #         rtn[k] = _as_string(v)
    return r

def _get_strategy_functions():
    return {
        "exact": _query_exact,
        "fuzzy": _query_fuzzy,
    }

def load_mapping():
    mapping_raw = os.getenv("GEOCODER_DEFINITION")
    # Parse mapping
    try:
        mapping = json.loads(mapping_raw) if mapping_raw else None
    except Exception as e:
        print("  JSON ERROR INSIDE load_mapping:", e)
        return {}
    return mapping

def load_geocoder_config():
    params_raw = os.getenv("GEOCODER_PARAMS")
    strategies_raw = os.getenv("GEOCODER_STRATEGIES")

    # Parse params
    params = (
        [p.strip() for p in params_raw.split(",") if p.strip()]
        if params_raw else None
    )

    # Parse strategies
    try:
        strategies = json.loads(strategies_raw) if strategies_raw else None
    except Exception as e:
        print("  JSON ERROR INSIDE load_geocoder_config:", e)
        strategies = None

    return params, strategies

def _query_exact(rows=5, **kwargs):
    """
    Solr exact query with scoring (edismax). Only non-None kwargs are used.
    """
    # Build "q" as ANDed exact matches
    # e.g., q = 'plz:"53111" AND ort:"Bonn"'
    q_parts = [f'{k}:"{v}"' for k, v in kwargs.items() if v is not None and v != '']
    q = " AND ".join(q_parts) if q_parts else "*:*"

    params = {
        "defType": "edismax",
        "q": q,
        "rows": rows,
        "wt": "json",
        "fl": "*",
    }

    return _solr_select(params)

def _query_fuzzy(rows=5, **kwargs):
    """
    Dynamic fuzzy Solr query without field boosts.

    kwargs: arbitrary field=value pairs, e.g.
        plz="53111", ort="Bonn", strasse="Hauptstrasse", hausnummer="5"

    Only non-None fields are queried. Each field uses _dynamic_fuzzy().
    """
    # Build query parts for non-None fields
    parts = [_dynamic_fuzzy(k, v) for k, v in kwargs.items() if v is not None and v != '']

    # Fallback to match all if nothing provided
    q = " AND ".join(parts) if parts else "*:*"

    params = {
        "defType": "edismax",
        "q": q,
        "ps": 2,
        "mm": "2<75%",
        "tie": "0.1",
        "sow": "true",
        "rows": rows,
        "wt": "json",
        "fl": "*",
    }

    return _solr_select(params)

def query_address(data: dict, rows: int = 5):
    params_cfg, strategies_cfg = load_geocoder_config()

    # Fallback to existing hard-coded behaviour
    if not params_cfg or not strategies_cfg:
        return _query_address_static(data, rows)

    # Clean inputs dynamically
    cleaned = {p: _clean_str(data.get(p)) for p in params_cfg}

    # Require at least plz or ort (fallback to old rule)
    # Is this a rule we truly need in a fully dynamic setup?
    if not _have_plz_or_ort(cleaned.get("plz"), cleaned.get("ort")):
        raise ValueError("Geocoding requires at least one of: plz or ort")

    func_map = _get_strategy_functions()

    for strat in strategies_cfg:
        name = strat["name"]
        func = func_map[strat["func"]]

        # Build kwargs dynamically
        kwargs = {p: cleaned.get(p) for p in params_cfg}

        # Remove parameters not listed in this strategy
        for p in params_cfg:
            if p not in strat["params"]:
                kwargs[p] = None

        res = func(rows=rows, **kwargs)
        docs = res.get("response", {}).get("docs", [])

        if docs:
            normalized = [_normalize_doc(d) for d in docs]
            return {"count": len(normalized), "results": normalized, "strategy": name}
            #return {"strategy": name, "results": normalized, "count": len(normalized)}

    return {"count": 0, "results": [],"strategy": None}
    # return {"strategy": None, "results": [], "count": 0}


def _query_address_static(data: dict, rows: int = 5):
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
            return {"count": len(normalized), "results": normalized, "strategy": name}
            # return {"strategy": name, "results": normalized, "count": len(normalized)}

    # nothing found
    return {"count": 0, "results": [], "strategy": None}
    # return {"strategy": None, "results": [], "count": 0}

def _solr_select(params: dict):
    r = _session.get(_SELECT, params=params, timeout=_TIMEOUT)
    #print("DEBUG: Solr URL called:", r.request.url)
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
    Returns Solr query with fuzziness per token (word).
    Multi-word tokens are split on whitespace, '-' and '+'.
    """
    token = str(token).strip()
    if not token:
        return ""

    # split on whitespace, '-' or '+'
    words = re.split(r'[\s\-\+]+', token)

    parts = []
    for word in words:
        if not word:
            continue
        l = len(word)
        if l <= 3:
            fuzz = ""       # no fuzz
        elif l <= 5:
            fuzz = "~1"
        else:
            fuzz = "~2"
        parts.append(f"{fieldname}:{word}{fuzz}")

    # join with AND to preserve all words
    return " AND ".join(parts)
