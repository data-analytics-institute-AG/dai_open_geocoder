from flask import Blueprint, request, jsonify
from services.solr_service import query_address, query_reverse
from flask import request

geocode_bp = Blueprint("geocode", __name__)

# -------------------------------
# Forward Geocoding (POST + GET)
# -------------------------------
@geocode_bp.route("/geocode", methods=["POST", "GET"])
def geocode():
    """
    Forward geocoding:
    - POST: JSON body with address fields.
    - GET:  Query parameters, default:(?strasse=&hausnummer=&plz=&ort=).
    """
    # Collect parameters from GET or POST
    if request.method == "GET":
        raw_params = request.args
    else:  # POST
        # supports form data or JSON payloads
        if request.is_json:
            raw_params = request.get_json() or {}
        else:
            raw_params = request.form

    # optional: allow client to control how many to return (default 10)
    rows = request.args.get("rows") if request.method == "GET" else (raw_params.get("rows") if isinstance(raw_params, dict) else None)
    try:
        rows = min(int(rows),10) if rows is not None else 10
    except Exception:
        rows = 10

    try:
        address_result = query_address(raw_params, rows=rows)
        final_response = {"input": raw_params}
        final_response.update(address_result)
        # result['input'] = raw_params
    except ValueError as e:
        return jsonify({"input":raw_params,"error": str(e)}), 400

    return jsonify(final_response), 200

# -------------------------------
# Reverse Geocoding (POST + GET)
# -------------------------------
@geocode_bp.route("/reverse", methods=["POST", "GET"])
def reverse_geocode():
    """
    Reverse geocoding:
    - POST: JSON body with {"lat": ..., "lon": ..., "rows": ..., "maxDistance": ...}
    - GET:  Query parameters (?lat=&lon=&rows=&maxDistance=)
    """
    if request.method == "POST":
        data = request.get_json()
        lat = data.get("lat")
        lon = data.get("lon")
        maxDistance = data.get("maxDistance")
        rows = data.get("rows")
    else:
        lat = request.args.get("lat")
        lon = request.args.get("lon")
        maxDistance = request.args.get("maxDistance")
        rows = request.args.get("rows")

    if not lat or not lon:
        return jsonify({"error": "Missing coordinates (lat, lon)."}), 400

    try:
        rows = min(int(rows),10) if rows is not None else 10
    except Exception:
        rows = 10

    if not maxDistance:
        maxDistance = 1

    result = query_reverse({"lat": lat, "lon": lon, "rows": rows, "maxDistance": maxDistance})
    if result is None:
        return jsonify({"error": "No match found"}), 404

    return jsonify(result), 200
