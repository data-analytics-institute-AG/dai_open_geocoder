import os
import requests
import json
import re
import Levenshtein
import math
from urllib.parse import urljoin


SOLR_URL = None
COORDINATE_FIELD = None
RESULT_FIELD = None
LOADED_CONFIG = False
_SELECT = None
_TIMEOUT = 6
_session = requests.Session()

# escapes special characters for solr and cleans up unnecessary whitespace
def _clean_str(v):
    if not v:
        return v
    SOLR_SPECIAL_CHARS = re.compile(r'(\+|-|&&|\|\||!|\(|\)|\{|\}|\[|\]|\^|"|~|\*|\?|:|\\|/)')
    v = SOLR_SPECIAL_CHARS.sub(r'\\\1', v)
    return (v or "").strip()

def _as_string(v):
    if v is None: return ""
    return v[0] if isinstance(v, list) else v

def _normalize_doc(d, args={}):
    """Return a consistent shape for API consumers."""
    r = {}
    # TwoFold Way:
    #   - either there is a defined json RESULT_FIELD - configurable in conf.json - which has the results to publish in it
    #   - or all fields are returned
    if RESULT_FIELD and RESULT_FIELD in d:
        values = json.loads(d[RESULT_FIELD])
        for k,v in values.items():
            r[k] = v
    else:
        r = d
    # Qualities auf den Eingangsparametern berechnen
    if args:
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
    global SOLR_URL
    global COORDINATE_FIELD
    global RESULT_FIELD
    global _SELECT

    if not os.path.exists(config_path):
        raise FileNotFoundError(f"Config file not found: {config_path}")

    try:
        with open(config_path, "r", encoding="utf-8") as f:
            config = json.load(f)

        params = config.get("params")
        strategies = config.get("strategies")
        # Try reading solr url from config, use fallback if not present
        try:
            SOLR_URL = config.get("solr_url")
        except:
            SOLR_URL = "http://solr:8983/solr/addresses"
        _SELECT = urljoin(SOLR_URL.rstrip("/") + "/", "select")

        # Try reading coordinate field from config, if not present reverse geocode cannot be used
        try:
            COORDINATE_FIELD = config.get("coordinate_field")
        except:
            COORDINATE_FIELD = None

        # Try reading result field from config, if not present whole document is returned
        try:
            RESULT_FIELD = config.get("result_field")
        except:
            RESULT_FIELD = None

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
    # Build "q" as ANDed exact matches
    # e.g., q = 'plz:"53111" AND ort:"Bonn"'
    q_parts = [f'{k}:"{v}"' for k, v in kwargs.items() if v is not None and v != '']
    q = " AND ".join(q_parts) if q_parts else "*:*"

    params = {
        "defType": "edismax",
        "q": q,
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
    # makes sure config is only loaded once per instance
    params_cfg, strategies_cfg = load_geocoder_config()
    LOADED_CONFIG = True

    # Clean inputs dynamically
    cleaned = {p: _clean_str(data.get(p)) for p in params_cfg}

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
            normalized = [_normalize_doc(d, kwargs) for d in docs]
            return {"count": len(normalized), "results": normalized, "strategy": name}

    return {"count": 0, "results": [],"strategy": None}

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
    Reverse geocoding via Solr spatial search. Requires a coordinate_field configured in conf.json.
    The coordinate field needs to be of type location

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
    # makes sure config is only loaded once per instance
    global LOADED_CONFIG
    if not LOADED_CONFIG:
        params_cfg, strategies_cfg = load_geocoder_config()
        LOADED_CONFIG = True
    print(COORDINATE_FIELD)
    if not COORDINATE_FIELD:
        raise ValueError("Missing Configuration: 'coordinate_field' needs to be configured in conf.json")
    if "lat" not in data or "lon" not in data:
        raise ValueError("Missing coordinates: require 'lat' and 'lon'")

    lat = _coerce_float(data["lat"], "lat")
    lon = _coerce_float(data["lon"], "lon")
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
        "sfield": COORDINATE_FIELD,
        "pt": f"{lat},{lon}",
        "fq": f"{{!geofilt sfield={COORDINATE_FIELD} pt={lat},{lon} d={max_radius}}}",
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
            if word[0].isdigit():
                fuzz = "~1"       # no fuzz
            else:
                fuzz = ""
        elif l <= 5:
            fuzz = "~1"
        else:
            fuzz = "~2"
        parts.append(f"{fieldname}:{word}{fuzz}")

    # join with AND to preserve all words
    return " AND ".join(parts)
