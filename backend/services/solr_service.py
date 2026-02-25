import os
import requests
import json
import re
import Levenshtein
import math
from urllib.parse import urljoin


SOLR_URL = os.getenv("SOLR_URL", "http://solr:8983/solr/addresses")
_SELECT = urljoin(SOLR_URL.rstrip("/") + "/", "select")
_TIMEOUT = 6
_session = requests.Session()

def _clean_str(v):
    return (v or "").strip()

def _as_string(v):
    if v is None: return ""
    return v[0] if isinstance(v, list) else v

def _normalize_doc(d, args):
    """Return a consistent shape for API consumers."""
    r = {}
    # TODO: if additional_information is not given, return all "normal" fields of solr
    if 'additional_information' in d:
        values = json.loads(d['additional_information'])
        for k,v in values.items():
            #if v and v != '':
                r[k] = v
        del d['additional_information']
    # Qualities auf den Eingangsparametern berechnen
    r['quality'] = {}
    for arg in args:
        if args[arg] and args[arg] != '':
            if isinstance(d[arg], list):
            # loop through the options and return best match
                bestQuality = 0
                for elem in d[arg]:
                    quality =  math.ceil(Levenshtein.ratio(str(args[arg]).lower(), str(elem).lower())*100)
                    if quality > bestQuality:
                        bestQuality = quality
                r['quality'][arg] = bestQuality
            else:
                r['quality'][arg] = math.ceil(Levenshtein.ratio(str(args[arg]).lower(), str(d[arg]).lower())*100)
    # Scores von Solr hinzufügen
    if 'score' in d:
        r['quality']['solr_score'] = d['score']
    if 'distance_km' in d:
        r['distance_km'] = d['distance_km']
    return r

def _get_strategy_functions():
    return {
        "exact": _query_exact,
        "fuzzy": _query_fuzzy,
    }

def load_geocoder_config(config_path="conf.json"):
    """
    Loads geocoder configuration from a JSON file.

    Expected structure:
    {
        "params": [...],
        "strategies": {...}
    }
    """

    if not os.path.exists(config_path):
        raise FileNotFoundError(f"Config file not found: {config_path}")

    try:
        with open(config_path, "r", encoding="utf-8") as f:
            config = json.load(f)

        params = config.get("params")
        strategies = config.get("strategies")

        return params, strategies

    except json.JSONDecodeError as e:
        print("ERROR conf.json ist nicht vollständig oder korrekt befüllt:", e)
        return None, None
    except Exception as e:
        print("ERROR conf.json ist nicht vollständig oder korrekt befüllt:", e)
        return None, None

def _query_exact(rows=5, **kwargs):
    """
    Solr exact query with scoring (edismax). Only non-None kwargs are used.
    """
    # print(f"Parameter in _query_exact: {kwargs}")
    # Build "q" as ANDed exact matches
    # e.g., q = 'plz:"53111" AND ort:"Bonn"'
    q_parts = [f'{k}:"{v}"' for k, v in kwargs.items() if v is not None and v != '']
    q = " AND ".join(q_parts) if q_parts else "*:*"
    #q = ", ".join(q_parts) if q_parts else "*:*"

    params = {
        "defType": "edismax",
        "q": q,
        #"q.op":"AND",
        "rows": rows,
        "wt": "json",
        "fl": "*,score",
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
        "fl": "*,score",
    }

    return _solr_select(params)

def query_address(data: dict, rows: int = 5):
    params_cfg, strategies_cfg = load_geocoder_config()

    # Clean inputs dynamically
    cleaned = {p: _clean_str(data.get(p)) for p in params_cfg}

    func_map = _get_strategy_functions()

    for strat in strategies_cfg:
        name = strat["name"]
        func = func_map[strat["func"]]

        # Build kwargs dynamically
        kwargs = {p: cleaned.get(p) for p in params_cfg}

        # print(f"Parameter in query_address: {kwargs}")

        # Remove parameters not listed in this strategy
        for p in params_cfg:
            if p not in strat["params"]:
                kwargs[p] = None

        res = func(rows=rows, **kwargs)
        docs = res.get("response", {}).get("docs", [])

        if docs:
            normalized = [_normalize_doc(d, kwargs) for d in docs]
            return {"count": len(normalized), "results": normalized, "strategy": name}
            #return {"strategy": name, "results": normalized, "count": len(normalized)}

    return {"count": 0, "results": [],"strategy": None}
    # return {"strategy": None, "results": [], "count": 0}

def _solr_select(params: dict):
    r = _session.get(_SELECT, params=params, timeout=_TIMEOUT)
    # print("DEBUG: Solr URL called:", r.request.url)
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
    #max_results = _coerce_int(data.get("rows", 10), "rows")
    max_results = max(min(int(data.get("rows")), 10), 1)
    max_radius = float(data.get("max_radius", 1000.0))

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
        "fl": "*,distance_km:geodist()",
    }

    res = _solr_select(params)
    docs = res.get("response", {}).get("docs", [])

    # Normalize result shape; ensure only first array element is returned
    if docs:
        normalized = [_normalize_doc(d) for d in docs]
        return normalized

    return None

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
