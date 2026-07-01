import os
import requests
import json
import re
import Levenshtein
import math
from urllib.parse import urljoin

CONFIG = {}
LOADED_CONFIG = False
_SELECT = None
_TIMEOUT = 6
_session = requests.Session()

def load_geocoder_config(config_path=os.environ.get('OGC_CONFIG_FILE', "conf.json")):
    """
    Loads geocoder configuration from a JSON file.
    """
    global CONFIG
    global _SELECT

    if not os.path.exists(config_path):
        raise FileNotFoundError(f"Config file not found: {config_path}")

    try:
        with open(config_path, "r", encoding="utf-8") as f:
            config = json.load(f)

        CONFIG = config

        # Solr URL should be defined. use a default as fallback if not
        if not CONFIG["solr_url"]:
            CONFIG["solr_url"] = "http://solr:8983/solr/addresses"
        _SELECT = urljoin(CONFIG["solr_url"].rstrip("/") + "/", "select")

        # params and strategies must be set. if not throw an error
        if not CONFIG["params"] or not CONFIG["strategies"]:
            print("ERROR conf.json ist nicht vollständig oder korrekt befüllt. 'params' und 'strategies' must be set.", e)
            return None, None

    except json.JSONDecodeError as e:
        print("ERROR conf.json ist nicht vollständig oder korrekt befüllt:", e)
    except Exception as e:
        print("ERROR conf.json ist nicht vollständig oder korrekt befüllt:", e)

def _query_exact(rows=5, **kwargs):
    """
    Solr exact query with scoring (edismax). Only non-None kwargs are used.

    Special handling:
    If CONF["housenumber_field"] is set, and kwargs contains:
      - that field name (e.g. "hnr")
      - "<field>_int" (e.g. "hnr_int")
    then they are combined as:
      (housenumber:hnr OR housenumber:hnr_int)

    All other fields remain exact matches:
      field:"value"
    """
    q_parts = []

    housenumber_field = CONFIG.get("housenumber_field")
    housenumber_int_field = (
        f"{housenumber_field}_int" if housenumber_field else None
    )

    # Handle housenumber special case once
    if housenumber_field:
        hnr = kwargs.get(housenumber_field)
        hnr_int = kwargs.get(housenumber_int_field)

        hnr_parts = []
        if hnr is not None and hnr != "":
            hnr_parts.append(f'{housenumber_field}:"{hnr}"')
        if hnr_int is not None and hnr_int != "":
            hnr_parts.append(f'{housenumber_field}:"{hnr_int}"')

        if hnr_parts:
            q_parts.append(f"({' OR '.join(hnr_parts)})")

    # Handle all remaining fields normally
    for k, v in kwargs.items():
        if v is None or v == "":
            continue
        if k == housenumber_field or k == housenumber_int_field:
            continue
        q_parts.append(f'{k}:"{v}"')

    q = " AND ".join(q_parts) if q_parts else "*:*"

    params = {
        "q": q,
        "rows": rows,
        "wt": "json",
        "fl": "*,score",
    }

    print("DEBUG: solr-Parameter:", params)
    return _solr_select(params)

def _query_fuzzy(rows=5, **kwargs):
    """
    Dynamic fuzzy Solr query.
    """
    configured_fields = set(CONFIG.get("params", []))
    fuzzy_field_map = CONFIG.get("params_fuzzy") or {}

    housenumber_field = CONFIG.get("housenumber_field")
    housenumber_int_field = (
        f"{housenumber_field}_int" if housenumber_field else None
    )

    parts = []

    hnr_clause = _build_housenumber_fuzzy_clause(
        kwargs=kwargs,
        housenumber_field=housenumber_field,
        housenumber_int_field=housenumber_int_field,
    )

    if hnr_clause:
        parts.append(hnr_clause)

    for fieldname, value in kwargs.items():
        if _is_empty(value):
            continue

        if fieldname in {housenumber_field, housenumber_int_field}:
            continue

        if fieldname not in configured_fields:
            continue

        solr_fieldname = fuzzy_field_map.get(fieldname, fieldname)

        clause = _dynamic_fuzzy(
            fieldname=solr_fieldname,
            token=value,
            use_multiword_variants=fieldname in fuzzy_field_map,
        )

        if clause:
            parts.append(clause)

    q = " AND ".join(parts) if parts else "*:*"

    params = {
        "q": q,
        "sow": "true",
        "rows": rows,
        "wt": "json",
        "fl": "*,score",
    }

    # Two-tier ranking:
    # 1. Solr score descending
    # 2. For equal scores, closest int house number ascending
    if housenumber_field and housenumber_int_field:
        queried_hnr = kwargs.get(housenumber_field)
        queried_hnr_int = _extract_first_int(queried_hnr)

        if queried_hnr_int is not None:
            distance_expr = f"dist(1,{housenumber_int_field},{queried_hnr_int})"
            params["sort"] = f"score desc, {distance_expr} asc"
        else:
            params["sort"] = "score desc"

    print("DEBUG: solr-Parameter:", params)
    return _solr_select(params)

def query_address(data: dict, rows: int = 5):
    global LOADED_CONFIG
    # makes sure config is only loaded once per instance
    if not LOADED_CONFIG:
        load_geocoder_config()
        LOADED_CONFIG = True
    params_cfg = CONFIG["params"]
    strategies_cfg = CONFIG["strategies"]

    # Clean inputs dynamically
    cleaned = {p: _clean_str(data.get(p)) for p in params_cfg}

    # special handling: housenumber if we have a housenumber field defined:
    # housenumbers are kept in two variations:
    # 1.: original housenumber (CONFIG["housenumber_field"])
    # 2.: housenumber without suffix (CONFIG["housenumber_field"]_int)
    # the solr is then called with (hnr:1 OR hnr:2). This should increase the quality when matching housenumbers
    if cleaned[CONFIG["housenumber_field"]]:
        new_hnr_key = str(CONFIG["housenumber_field"]) + "_int"
        match = re.match(r"^\d+", cleaned[CONFIG["housenumber_field"]].strip())
        if match:
            cleaned[new_hnr_key] = str(match.group())
        else:
            cleaned[new_hnr_key] = None

    func_map = _get_strategy_functions()

    for strat in strategies_cfg:
        name = strat["name"]
        func = func_map[strat["func"]]

        # Build kwargs dynamically
        kwargs = cleaned.copy()

        # check if all parameters of strat are set: if not, do not use this strat
        if not all(p in kwargs for p in strat['params']):
            continue

        # Remove parameters not listed in this strategy
        for p in params_cfg:
            if p not in strat["params"]:
                if p == CONFIG["housenumber_field"]:
                    kwargs[str(CONFIG["housenumber_field"]) + "_int"] = None
                kwargs[p] = None

        res = func(rows=rows, **kwargs)
        docs = res.get("response", {}).get("docs", [])

        if docs:
            normalized = [_normalize_doc(d, kwargs) for d in docs]
            return {"count": len(normalized), "results": normalized, "strategy": name}

    return {"count": 0, "results": [],"strategy": None}

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
        load_geocoder_config()
        LOADED_CONFIG = True
    if not CONFIG["coordinate_field"]:
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

def _build_housenumber_fuzzy_clause(
    kwargs,
    housenumber_field,
    housenumber_int_field,
):
    if not housenumber_field:
        return None

    parts = []

    hnr = kwargs.get(housenumber_field)
    hnr_int = kwargs.get(housenumber_int_field)

    if not _is_empty(hnr):
        parts.append(
            _dynamic_fuzzy(
                fieldname=housenumber_field,
                token=hnr,
                use_multiword_variants=False,
            )
        )

    if not _is_empty(hnr_int):
        parts.append(
            _dynamic_fuzzy(
                fieldname=housenumber_field,
                token=hnr_int,
                use_multiword_variants=False,
            )
        )

    parts = [part for part in parts if part]

    if not parts:
        return None

    if len(parts) == 1:
        return parts[0]

    return f"({' OR '.join(parts)})"


def _dynamic_fuzzy(fieldname, token, use_multiword_variants=False):
    """
    Returns a Solr query with fuzziness per word.

    Multi-word tokens are split on whitespace, '-', '+', and '.'.

    If use_multiword_variants=True, this returns:
        (
          field:"original token"^10
          OR (field:word1~1 AND field:word2~2)
          OR field:word1word2~2
        )

    Otherwise:
        field:word1~1 AND field:word2~2
    """
    token = str(token).strip()

    if not token:
        return ""

    words = _split_fuzzy_words(token)

    if not words:
        return ""

    word_parts = [
        f"{fieldname}:{word}{_fuzzy_length(word)}"
        for word in words
    ]

    word_query = " AND ".join(word_parts)

    if not use_multiword_variants:
        return word_query

    allwords = _compact_fuzzy_token(token)

    variants = [
        f'{fieldname}:"{token}"^10',
        f"({word_query})",
    ]

    if allwords and allwords not in words:
        variants.append(f"{fieldname}:{allwords}{_fuzzy_length(allwords)}")

    return f"({' OR '.join(variants)})"

def _normalize_doc(d, args={}):
    """Return a consistent shape for API consumers."""
    r = {}
    # TwoFold Way:
    #   - either there is a defined json RESULT_FIELD - configurable in conf.json - which has the results to publish in it
    #   - or all fields are returned
    if CONFIG["result_field"] and CONFIG["result_field"] in d:
        values = json.loads(d[CONFIG["result_field"]])
        for k,v in values.items():
            r[k] = v
    else:
        r = d
    # Qualities auf den Eingangsparametern berechnen
    if args:
        r['quality'] = {}
    for arg in args:
        if args[arg] and args[arg] != '' and arg in d:
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

def _solr_select(params: dict):
    r = _session.get(_SELECT, params=params, timeout=_TIMEOUT)

    if not r.ok:
        print("SOLR ERROR STATUS:", r.status_code)
        print("SOLR ERROR BODY:", r.text)
        r.raise_for_status()

    return r.json()

###################### HELPER FUNCTIONS ####################################

def _split_fuzzy_words(token):
    token = str(token).replace("\\", "")
    return [
        word
        for word in re.split(r"[\s\-\+\.]+", token)
        if word
    ]


def _compact_fuzzy_token(token):
    token = str(token).replace("\\", "")
    return re.sub(r"[\s\-\+\.]+", "", token)


def _fuzzy_length(word):
    """
    Solr/Lucene fuzzy edit distance is max 2.
    """
    length = len(word)

    if length <= 1:
        return ""

    if length <= 5:
        return "~1"

    return "~2"

def _is_empty(value):
    return value is None or value == ""

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

def _get_strategy_functions():
    return {
        "exact": _query_exact,
        "fuzzy": _query_fuzzy,
    }

# escapes special characters for solr and cleans up unnecessary whitespace
def _clean_str(v):
    if not v:
        return v
    SOLR_SPECIAL_CHARS = re.compile(r'(\+|\-|&&|\||!|\(|\)|\{|\}|\[|\]|\^|"|~|\*|\?|:|\\|\/)')
    v = SOLR_SPECIAL_CHARS.sub(r'\\\1', v)
    return (v or "").strip()

def _as_string(v):
    if v is None: return ""
    return v[0] if isinstance(v, list) else v

def _extract_first_int(value):
    """
    Extract the first integer from a house-number-like value.
    """
    if _is_empty(value):
        return None

    match = re.search(r"\d+", str(value))
    if not match:
        return None

    return int(match.group(0))
