from flask import Flask, request, jsonify, send_from_directory
import os, json, traceback
from datetime import datetime
import requests
from requests.auth import HTTPBasicAuth
import urllib3

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

app = Flask(__name__)

HA_WEBHOOK_URL = os.getenv("HA_WEBHOOK_URL", "http://sidmsmith.zapto.org:8123/api/webhook/manhattan_app_usage")
HA_HEADERS = {"Content-Type": "application/json"}
APP_NAME = "dispatch"
APP_VERSION = "1.0.0"

AUTH_HOST = os.getenv("MANHATTAN_AUTH_HOST", "salep-auth.sce.manh.com")
API_HOST = os.getenv("MANHATTAN_API_HOST", "salep.sce.manh.com")
USERNAME_BASE = os.getenv("MANHATTAN_USERNAME_BASE", "sdtadmin@")
PASSWORD = os.getenv("MANHATTAN_PASSWORD")
CLIENT_ID = os.getenv("MANHATTAN_CLIENT_ID", "omnicomponent.1.0.0")
CLIENT_SECRET = os.getenv("MANHATTAN_SECRET")

if not PASSWORD or not CLIENT_SECRET:
    raise Exception("Missing MANHATTAN_PASSWORD or MANHATTAN_SECRET environment variables")


def send_ha_message(payload):
    try:
        full_payload = {
            "app_name": APP_NAME,
            "app_version": APP_VERSION,
            "timestamp": datetime.utcnow().isoformat(),
            **payload
        }
        requests.post(HA_WEBHOOK_URL, json=full_payload, headers=HA_HEADERS, timeout=5)
    except:
        pass


def get_manhattan_token(org):
    url = f"https://{AUTH_HOST}/oauth/token"
    username = f"{USERNAME_BASE}{org.lower()}"
    data = {
        "grant_type": "password",
        "username": username,
        "password": PASSWORD,
    }
    auth = HTTPBasicAuth(CLIENT_ID, CLIENT_SECRET)
    try:
        r = requests.post(
            url,
            data=data,
            headers={"Content-Type": "application/x-www-form-urlencoded"},
            auth=auth,
            timeout=30,
            verify=False,
        )
        r.raise_for_status()
        return r.json().get("access_token")
    except:
        return None


@app.route('/api/app_opened', methods=['POST'])
def app_opened():
    send_ha_message({"event": "dispatch_app_opened"})
    return jsonify({"success": True})


@app.route('/api/auth', methods=['POST'])
def auth():
    org = request.json.get('org', '').strip()
    if not org:
        return jsonify({"success": False, "error": "ORG required"})
    token = get_manhattan_token(org)
    if token:
        send_ha_message({"event": "dispatch_auth", "org": org, "success": True})
        return jsonify({"success": True, "token": token})
    send_ha_message({"event": "dispatch_auth", "org": org, "success": False})
    return jsonify({"success": False, "error": "Auth failed"})


@app.route('/api/equipment_types', methods=['POST'])
def equipment_types():
    """Fetch trailer equipment types (same API as check_in)"""
    org = request.json.get('org')
    token = request.json.get('token')
    if not all([org, token]):
        return jsonify({"success": False, "error": "Missing data"})

    url = f"https://{API_HOST}/yard-management/api/yard-management/equipmentType/search"
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
        "selectedOrganization": org,
        "selectedLocation": f"{org}-DM1"
    }
    payload = {
        "Query": "StandardEquipmentTypeId=TRAILER",
        "Size": 9999,
        "needTotalCount": True,
        "Template": {
            "EquipmentTypeId": None,
            "Description": None
        }
    }
    try:
        r = requests.post(url, json=payload, headers=headers, timeout=30, verify=False)
        if r.ok:
            body = r.json()
            data = body.get("data", {})
            if isinstance(data, dict):
                types = data.get("EquipmentType", []) or data.get("equipmentType", [])
                if not types:
                    for v in data.values():
                        if isinstance(v, list):
                            types = v
                            break
            elif isinstance(data, list):
                types = data
            else:
                types = []
            return jsonify({"success": True, "types": types})
        else:
            return jsonify({"success": False, "error": f"HTTP {r.status_code}: {r.text[:500]}"})
    except Exception as e:
        print(f"[EquipmentTypes] Exception: {e}")
        return jsonify({"success": False, "error": str(e)})


TRIP_STATUS_MAP = {
    "1000": "Not Dispatched",
    "2000": "Dispatched",
    "3000": "In Transit",
    "4000": "Delivered",
    "5000": "Completed",
    "6000": "Cancelled"
}


def format_dt_short(iso_str):
    """Format ISO datetime to compact display like 'MM/DD HH:MM'"""
    if not iso_str:
        return "-"
    try:
        dt = datetime.fromisoformat(iso_str)
        return dt.strftime("%m/%d %H:%M")
    except:
        return iso_str[:16] if len(iso_str) >= 16 else iso_str


def calc_duration(start_iso, end_iso):
    """Calculate duration string between two ISO timestamps"""
    if not start_iso or not end_iso:
        return "-"
    try:
        start = datetime.fromisoformat(start_iso)
        end = datetime.fromisoformat(end_iso)
        delta = end - start
        total_minutes = int(delta.total_seconds() / 60)
        hours = total_minutes // 60
        minutes = total_minutes % 60
        return f"{hours}h {minutes:02d}m"
    except:
        return "-"


def transform_trip(raw_trip):
    """Transform a raw Manhattan API trip into the frontend display format"""
    segments = raw_trip.get("TripSegment", []) or []
    segments_sorted = sorted(segments, key=lambda s: s.get("Sequence", 0))

    first_seg = segments_sorted[0] if segments_sorted else {}
    last_seg = segments_sorted[-1] if segments_sorted else {}

    status_obj = raw_trip.get("TripStatusId", {}) or {}
    status_code = status_obj.get("TripStatusId", "") if isinstance(status_obj, dict) else str(status_obj)
    status_label = TRIP_STATUS_MAP.get(status_code, status_code)

    origin = first_seg.get("OriginFacilityId", "-")
    destination = first_seg.get("DestinationFacilityId", "-")

    pickup_start = first_seg.get("PlannedOriginDepartureStart")
    delivery_end = last_seg.get("PlannedDestinationArrivalStart")

    total_distance = sum(s.get("OneWayDistance", 0) or 0 for s in segments_sorted)

    shipments = []
    for s in segments_sorted:
        sid = s.get("ShipmentId")
        if sid:
            shipments.append({
                "ShipmentId": sid,
                "Distance": f"{s.get('OneWayDistance', 0):.1f} mi",
                "Origin": s.get("OriginFacilityId", "-"),
                "Destination": s.get("DestinationFacilityId", "-")
            })

    unique_facilities = set()
    for s in segments_sorted:
        if s.get("OriginFacilityId"):
            unique_facilities.add(s["OriginFacilityId"])
        if s.get("DestinationFacilityId"):
            unique_facilities.add(s["DestinationFacilityId"])

    driver = raw_trip.get("AssignedDriverId") or "-"

    duration_hours = None
    if pickup_start and delivery_end:
        try:
            dt_start = datetime.fromisoformat(pickup_start)
            dt_end = datetime.fromisoformat(delivery_end)
            duration_hours = (dt_end - dt_start).total_seconds() / 3600.0
        except:
            pass

    return {
        "TripId": raw_trip.get("TripId", "-"),
        "Status": status_label,
        "StatusCode": status_code,
        "Origin": origin,
        "Destination": destination,
        "PickupWindow": format_dt_short(pickup_start),
        "DeliveryWindow": format_dt_short(delivery_end),
        "TotalDuration": calc_duration(pickup_start, delivery_end),
        "DurationHours": duration_hours,
        "TotalStops": len(unique_facilities),
        "TotalSegments": len(segments_sorted),
        "TotalDistance": f"{total_distance:.1f} mi",
        "Backhaul": "Yes" if len(segments_sorted) > 2 else "No",
        "CurrentDriver": driver,
        "Carrier": raw_trip.get("AssignedCarrierId", "-"),
        "Tractor": raw_trip.get("AssignedTractorAssetId", "-"),
        "Overview": {
            "Carrier": raw_trip.get("AssignedCarrierId", "-"),
            "Distance": f"{total_distance:.1f} mi",
            "Segments": str(len(segments_sorted))
        },
        "Shipments": shipments,
        "DriverAssignment": {
            "Name": driver,
            "Role": "Assigned Driver" if driver != "-" else "Unassigned"
        },
        "Segments": [{
            "SegmentId": s.get("SegmentId", "-"),
            "Sequence": s.get("Sequence", 0),
            "ShipmentId": s.get("ShipmentId") or "-",
            "Origin": s.get("OriginFacilityId", "-"),
            "Destination": s.get("DestinationFacilityId", "-"),
            "Departure": format_dt_short(s.get("PlannedOriginDepartureStart")),
            "Arrival": format_dt_short(s.get("PlannedDestinationArrivalStart")),
            "Distance": f"{s.get('OneWayDistance', 0) or 0:.1f} mi",
            "Trailer": s.get("AssignedTrailerNumber") or s.get("AssignedTrailerId") or "-"
        } for s in segments_sorted]
    }


@app.route('/api/search_trips', methods=['POST'])
def search_trips():
    """Search trips using Manhattan TMS trip/search API"""
    org = request.json.get('org')
    token = request.json.get('token')
    filters = request.json.get('filters', {})
    if not all([org, token]):
        return jsonify({"success": False, "error": "Missing org or token"})

    send_ha_message({"event": "dispatch_search_trips", "org": org, "filters": filters})

    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
        "selectedOrganization": org,
        "selectedLocation": f"{org}-DM1"
    }

    valid_trailer_asset_ids = None
    equipment_type_id = filters.get("equipmentTypeId")
    if equipment_type_id:
        try:
            asset_url = f"https://{API_HOST}/asset-manager/api/asset-manager/trailerAsset/search"
            asset_payload = {
                "Query": f"EquipmentTypeId = '{equipment_type_id}'",
                "Template": {
                    "TrailerAssetId": None,
                    "EquipmentTypeId": None,
                    "CarrierId": None,
                    "TerminalId": None
                },
                "Sort": [],
                "Size": 200
            }
            print(f"[SearchTrips] Fetching trailer assets for EquipmentTypeId={equipment_type_id}")
            ar = requests.post(asset_url, json=asset_payload, headers=headers, timeout=30, verify=False)
            if ar.ok:
                asset_body = ar.json()
                asset_data = asset_body.get("data", []) or []
                valid_trailer_asset_ids = {a.get("TrailerAssetId") for a in asset_data if a.get("TrailerAssetId")}
                print(f"[SearchTrips] Found {len(valid_trailer_asset_ids)} trailer assets: {valid_trailer_asset_ids}")
            else:
                print(f"[SearchTrips] Trailer asset search failed: {ar.status_code}")
        except Exception as e:
            print(f"[SearchTrips] Trailer asset search exception: {e}")

    query_parts = ["TripSegment.Sequence = '1'"]

    pickup_from = filters.get("pickupFrom")
    pickup_to = filters.get("pickupTo")
    if pickup_from:
        query_parts.append(f"TripSegment.PlannedOriginDepartureStart >= '{pickup_from}:00'")
    if pickup_to:
        query_parts.append(f"TripSegment.PlannedOriginDepartureStart < '{pickup_to}:00'")

    query_string = " and ".join(query_parts)

    url = f"https://{API_HOST}/shipment/api/shipment/trip/search"
    payload = {
        "Query": query_string,
        "Template": {
            "TripId": None,
            "TripStatusId": None,
            "CreatedTimestamp": None,
            "AssignedCarrierId": None,
            "AssignedDriverId": None,
            "AssignedTractorAssetId": None,
            "TripSegment": None
        },
        "Sort": [{"attribute": "CreatedTimestamp", "direction": "asc"}],
        "Size": 9999
    }

    try:
        print(f"[SearchTrips] Query: {query_string}")
        r = requests.post(url, json=payload, headers=headers, timeout=30, verify=False)
        print(f"[SearchTrips] Status: {r.status_code}")

        if r.ok:
            body = r.json()
            raw_trips = body.get("data", []) or []

            if valid_trailer_asset_ids is not None:
                filtered = []
                for trip in raw_trips:
                    segs = trip.get("TripSegment", []) or []
                    if any(s.get("AssignedTrailerAssetId") in valid_trailer_asset_ids for s in segs):
                        filtered.append(trip)
                print(f"[SearchTrips] Equipment filter: {len(raw_trips)} -> {len(filtered)} trips")
                raw_trips = filtered

            trips = [transform_trip(t) for t in raw_trips]

            duration_min = filters.get("durationMin")
            duration_max = filters.get("durationMax")
            if duration_min is not None or duration_max is not None:
                d_lo = float(duration_min) if duration_min is not None else 0
                d_hi = float(duration_max) if duration_max is not None else 9999
                trips = [t for t in trips if t.get("DurationHours") is not None and d_lo <= t["DurationHours"] <= d_hi]

            seg_min = filters.get("segmentsMin")
            seg_max = filters.get("segmentsMax")
            if seg_min is not None or seg_max is not None:
                s_lo = int(seg_min) if seg_min is not None else 1
                s_hi = int(seg_max) if seg_max is not None else 9999
                trips = [t for t in trips if s_lo <= t.get("TotalSegments", 0) <= s_hi]

            return jsonify({
                "success": True,
                "trips": trips,
                "count": len(trips)
            })
        else:
            error_text = r.text[:500]
            print(f"[SearchTrips] Error: {error_text}")
            return jsonify({"success": False, "error": f"HTTP {r.status_code}: {error_text}"})
    except Exception as e:
        print(f"[SearchTrips] Exception: {e}")
        import traceback
        traceback.print_exc()
        return jsonify({"success": False, "error": str(e)})


@app.route('/api/trip_detail', methods=['POST'])
def trip_detail():
    """Get trip detail (placeholder - API TBD)"""
    org = request.json.get('org')
    token = request.json.get('token')
    trip_id = request.json.get('trip_id')
    if not all([org, token, trip_id]):
        return jsonify({"success": False, "error": "Missing data"})

    return jsonify({"success": True, "message": "Detail API TBD"})


@app.route('/api/assign_trip', methods=['POST'])
def assign_trip():
    """Assign trip to current user (placeholder - API TBD)"""
    org = request.json.get('org')
    token = request.json.get('token')
    trip_id = request.json.get('trip_id')
    if not all([org, token, trip_id]):
        return jsonify({"success": False, "error": "Missing data"})

    send_ha_message({"event": "dispatch_assign_trip", "org": org, "trip_id": trip_id})

    return jsonify({"success": True, "message": f"Trip {trip_id} assigned successfully"})


@app.route('/api/ha-track', methods=['POST'])
def ha_track():
    data = request.json or {}
    event_name = data.get('event_name')
    metadata = data.get('metadata', {})
    send_ha_message({"event": event_name, **metadata})
    return jsonify({"success": True})


@app.route('/manhlogo.png')
def serve_logo():
    return send_from_directory(os.path.join(os.path.dirname(os.path.dirname(__file__)), 'public'), 'manhlogo.png')


@app.route('/', defaults={'path': ''})
@app.route('/<path:path>')
def serve_static(path):
    if path.endswith('.js'):
        return jsonify({'error': 'File not found'}), 404
    return send_from_directory(os.path.join(os.path.dirname(os.path.dirname(__file__)), 'public'), 'index.html')


if __name__ == '__main__':
    app.run(debug=True, port=5000)
