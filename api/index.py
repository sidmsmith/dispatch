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
    """Return raw ISO string with 'Z' suffix so frontend can parse as UTC."""
    if not iso_str:
        return None
    return iso_str + "Z" if not iso_str.endswith("Z") else iso_str


def calc_duration_minutes(start_iso, end_iso):
    """Calculate duration in minutes between two ISO timestamps."""
    if not start_iso or not end_iso:
        return None
    try:
        start = datetime.fromisoformat(start_iso)
        end = datetime.fromisoformat(end_iso)
        return int((end - start).total_seconds() / 60)
    except:
        return None


def format_city_state(city, state):
    """Format city as Title Case and state as UPPER, return 'City, ST'."""
    c = city.strip().title() if city else ""
    s = state.strip().upper() if state else ""
    if c and s:
        return f"{c}, {s}"
    return c or s or ""


def resolve_facility_locations(facility_ids, headers):
    """Batch-resolve FacilityIds to 'City, State' via a single facility search API call.
    Returns dict of {FacilityId: 'City, ST'} for each resolved facility."""
    if not facility_ids:
        return {}

    facility_map = {}
    ids_list = list(facility_ids)
    in_clause = ",".join(f"'{fid}'" for fid in ids_list)

    url = f"https://{API_HOST}/facility/api/facility/facility/search"
    payload = {
        "Query": f"FacilityId in ({in_clause})",
        "Template": {
            "FacilityId": None,
            "Description": None,
            "FacilityAddress": {
                "City": None,
                "State": None,
                "PostalCode": None,
                "Country": None
            }
        },
        "Size": 9999
    }

    try:
        print(f"[FacilityLookup] Resolving {len(ids_list)} facilities in single query")
        r = requests.post(url, json=payload, headers=headers, timeout=30, verify=False)
        if r.ok:
            data = r.json().get("data", []) or []
            for fac in data:
                fid = fac.get("FacilityId")
                if not fid:
                    continue
                addr = fac.get("FacilityAddress") or {}
                city = addr.get("City", "")
                state = addr.get("State", "")
                formatted = format_city_state(city, state)
                if formatted:
                    facility_map[fid] = formatted
        else:
            print(f"[FacilityLookup] HTTP {r.status_code}: {r.text[:300]}")
    except Exception as e:
        print(f"[FacilityLookup] Exception: {e}")

    print(f"[FacilityLookup] Resolved {len(facility_map)}/{len(ids_list)} facilities")
    return facility_map


def get_location_parts(segment, direction, facility_map):
    """Return (city, state, display_string) for a segment's origin or destination."""
    addr = segment.get(f"{direction}Address")
    if addr and isinstance(addr, dict):
        city = (addr.get("City") or "").strip()
        state = (addr.get("State") or "").strip()
        if city or state:
            return city.title(), state.upper(), format_city_state(city, state)

    fid = segment.get(f"{direction}FacilityId", "-")
    resolved = facility_map.get(fid)
    if resolved and ", " in resolved:
        parts = resolved.rsplit(", ", 1)
        return parts[0], parts[1], resolved
    elif resolved:
        return resolved, "", resolved
    return "", "", fid


def format_location(segment, direction, facility_map):
    """Resolve a segment's origin or destination to 'City, State' display string."""
    _, _, display = get_location_parts(segment, direction, facility_map)
    return display


def build_stop_key(facility_id, lat, lon):
    """Build a stable stop key from facility or lat/lon for de-duplication."""
    if facility_id:
        return ("FACILITY", facility_id)
    if lat is not None and lon is not None:
        return ("GEO", f"{lat:.6f}|{lon:.6f}")
    return ("UNKNOWN", "UNKNOWN")


def compute_trip_stops(segments_sorted):
    """Compute ordered stops with consecutive de-duplication.
    First stop = origin of first segment; then each segment's destination in order.
    Only skips a stop if it matches the immediately previous stop."""
    if not segments_sorted:
        return 0, []

    stops = []
    first = segments_sorted[0]
    first_key = build_stop_key(
        first.get("OriginFacilityId"),
        first.get("OriginLatitude"),
        first.get("OriginLongitude")
    )
    stops.append(first_key)

    for seg in segments_sorted:
        dest_key = build_stop_key(
            seg.get("DestinationFacilityId"),
            seg.get("DestinationLatitude"),
            seg.get("DestinationLongitude")
        )
        if dest_key != stops[-1]:
            stops.append(dest_key)

    return len(stops), stops


def transform_trip(raw_trip, facility_map=None):
    """Transform a raw Manhattan API trip into the frontend display format"""
    segments = raw_trip.get("TripSegment", []) or []
    segments_sorted = sorted(segments, key=lambda s: s.get("Sequence", 0))

    first_seg = segments_sorted[0] if segments_sorted else {}
    last_seg = segments_sorted[-1] if segments_sorted else {}

    status_obj = raw_trip.get("TripStatusId", {}) or {}
    status_code = status_obj.get("TripStatusId", "") if isinstance(status_obj, dict) else str(status_obj)
    status_label = TRIP_STATUS_MAP.get(status_code, status_code)

    fmap = facility_map or {}

    origin_fid = first_seg.get("OriginFacilityId", "-")
    destination_fid = last_seg.get("DestinationFacilityId", "-")
    origin = format_location(first_seg, "Origin", fmap) if first_seg else "-"
    dest_city, dest_state, destination = get_location_parts(last_seg, "Destination", fmap) if last_seg else ("", "", "-")

    all_dest_cities = set()
    all_dest_states = set()
    for s in segments_sorted:
        sc, ss, _ = get_location_parts(s, "Destination", fmap)
        if sc:
            all_dest_cities.add(sc.lower())
        if ss:
            all_dest_states.add(ss.upper())

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

    stop_count, _ = compute_trip_stops(segments_sorted)

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
        "DestinationCity": dest_city,
        "DestinationState": dest_state,
        "AllDestCities": list(all_dest_cities),
        "AllDestStates": list(all_dest_states),
        "OriginFacility": origin_fid,
        "DestinationFacility": destination_fid,
        "PickupWindow": format_dt_short(pickup_start),
        "DeliveryWindow": format_dt_short(delivery_end),
        "TotalDurationMinutes": calc_duration_minutes(pickup_start, delivery_end),
        "DurationHours": duration_hours,
        "TotalStops": stop_count,
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
            "Origin": format_location(s, "Origin", fmap),
            "Destination": format_location(s, "Destination", fmap),
            "OriginFacility": s.get("OriginFacilityId", "-"),
            "DestinationFacility": s.get("DestinationFacilityId", "-"),
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

    pickup_from = filters.get("pickupFrom")
    pickup_to = filters.get("pickupTo")

    query_parts = ["TripSegment.Sequence = '1'", "TripStatusId='1000'"]
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

            if pickup_from or pickup_to:
                date_filtered = []
                for trip in raw_trips:
                    segs = trip.get("TripSegment", []) or []
                    seq1 = next((s for s in segs if s.get("Sequence") == 1), None)
                    if not seq1:
                        continue
                    dep = seq1.get("PlannedOriginDepartureStart", "")
                    if pickup_from and dep < f"{pickup_from}:00":
                        continue
                    if pickup_to and dep >= f"{pickup_to}:00":
                        continue
                    date_filtered.append(trip)
                print(f"[SearchTrips] Date post-filter: {len(raw_trips)} -> {len(date_filtered)} trips")
                raw_trips = date_filtered

            if valid_trailer_asset_ids is not None:
                filtered = []
                for trip in raw_trips:
                    segs = trip.get("TripSegment", []) or []
                    if any(s.get("AssignedTrailerAssetId") in valid_trailer_asset_ids for s in segs):
                        filtered.append(trip)
                print(f"[SearchTrips] Equipment filter: {len(raw_trips)} -> {len(filtered)} trips")
                raw_trips = filtered

            all_facility_ids = set()
            for trip in raw_trips:
                for seg in (trip.get("TripSegment", []) or []):
                    ofid = seg.get("OriginFacilityId")
                    dfid = seg.get("DestinationFacilityId")
                    oaddr = seg.get("OriginAddress")
                    daddr = seg.get("DestinationAddress")
                    if ofid and not (oaddr and isinstance(oaddr, dict) and oaddr.get("City")):
                        all_facility_ids.add(ofid)
                    if dfid and not (daddr and isinstance(daddr, dict) and daddr.get("City")):
                        all_facility_ids.add(dfid)

            print(f"[SearchTrips] Resolving {len(all_facility_ids)} unique facilities")
            facility_map = resolve_facility_locations(all_facility_ids, headers)

            trips = [transform_trip(t, facility_map) for t in raw_trips]

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

            stops_min = filters.get("stopsMin")
            stops_max = filters.get("stopsMax")
            if stops_min is not None or stops_max is not None:
                st_lo = int(stops_min) if stops_min is not None else 1
                st_hi = int(stops_max) if stops_max is not None else 9999
                trips = [t for t in trips if st_lo <= t.get("TotalStops", 0) <= st_hi]

            dest_city_filter = (filters.get("destinationCity") or "").strip().lower()
            if dest_city_filter:
                trips = [t for t in trips if any(dest_city_filter in c for c in t.get("AllDestCities", []))]

            dest_state_filter = (filters.get("destinationState") or "").strip().upper()
            if dest_state_filter:
                trips = [t for t in trips if dest_state_filter in t.get("AllDestStates", [])]

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
