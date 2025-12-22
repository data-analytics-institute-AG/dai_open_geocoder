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
    - GET:  Query parameters (?strasse=&hausnummer=&plz=&ort=).
    """
    if request.method == "POST":
        data = request.get_json(force=True)
    else:
        data = {
            "strasse": request.args.get("strasse"),
            "hausnummer": request.args.get("hausnummer"),
            "plz": request.args.get("plz"),
            "ort": request.args.get("ort"),
        }

    # optional: allow client to control how many to return (default 5)
    rows = request.args.get("rows") if request.method == "GET" else (data.get("rows") if isinstance(data, dict) else None)
    try:
        rows = int(rows) if rows is not None else 5
    except Exception:
        rows = 5

    try:
        result = query_address(data, rows=rows)
    except ValueError as e:
        return jsonify({"error": str(e)}), 400

    return jsonify(result), 200

# -------------------------------
# Reverse Geocoding (POST + GET)
# -------------------------------
@geocode_bp.route("/reverse", methods=["POST", "GET"])
def reverse_geocode():
    """
    Reverse geocoding:
    - POST: JSON body with {"lat": ..., "lon": ..., "maxResults": ..., "maxDistance": ...}
    - GET:  Query parameters (?lat=&lon=&maxResults=&maxDistance=)
    """
    if request.method == "POST":
        data = request.get_json(force=True)
        lat = data.get("lat")
        lon = data.get("lon")
        maxDistance = data.get("maxDistance")
        maxResults = data.get("maxResults")
    else:
        lat = request.args.get("lat")
        lon = request.args.get("lon")
        maxDistance = request.args.get("maxDistance")
        maxResults = request.args.get("maxResults")

    if not lat or not lon:
        return jsonify({"error": "Missing coordinates (lat, lon)."}), 400

    result = query_reverse({"lat": lat, "lon": lon, "maxResults": maxResults, "maxDistance": maxDistance})
    if result is None:
        return jsonify({"error": "No match found"}), 404

    return jsonify(result), 200
