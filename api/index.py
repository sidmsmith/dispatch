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
APP_VERSION = "1.0.1"

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
            for t in types:
                desc = (t.get("Description") or "").strip()
                eq_id = (t.get("EquipmentTypeId") or "").strip()
                # If Description is missing/blank, use EquipmentTypeId for display and sorting.
                t["Description"] = desc or eq_id
            types.sort(key=lambda t: (t.get("Description") or "").lower())
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


STATE_NAME_TO_ABBR = {
    "ALABAMA": "AL", "ALASKA": "AK", "ARIZONA": "AZ", "ARKANSAS": "AR",
    "CALIFORNIA": "CA", "COLORADO": "CO", "CONNECTICUT": "CT", "DELAWARE": "DE",
    "FLORIDA": "FL", "GEORGIA": "GA", "HAWAII": "HI", "IDAHO": "ID",
    "ILLINOIS": "IL", "INDIANA": "IN", "IOWA": "IA", "KANSAS": "KS",
    "KENTUCKY": "KY", "LOUISIANA": "LA", "MAINE": "ME", "MARYLAND": "MD",
    "MASSACHUSETTS": "MA", "MICHIGAN": "MI", "MINNESOTA": "MN", "MISSISSIPPI": "MS",
    "MISSOURI": "MO", "MONTANA": "MT", "NEBRASKA": "NE", "NEVADA": "NV",
    "NEW HAMPSHIRE": "NH", "NEW JERSEY": "NJ", "NEW MEXICO": "NM", "NEW YORK": "NY",
    "NORTH CAROLINA": "NC", "NORTH DAKOTA": "ND", "OHIO": "OH", "OKLAHOMA": "OK",
    "OREGON": "OR", "PENNSYLVANIA": "PA", "RHODE ISLAND": "RI", "SOUTH CAROLINA": "SC",
    "SOUTH DAKOTA": "SD", "TENNESSEE": "TN", "TEXAS": "TX", "UTAH": "UT",
    "VERMONT": "VT", "VIRGINIA": "VA", "WASHINGTON": "WA", "WEST VIRGINIA": "WV",
    "WISCONSIN": "WI", "WYOMING": "WY", "DISTRICT OF COLUMBIA": "DC",
    "ALBERTA": "AB", "BRITISH COLUMBIA": "BC", "MANITOBA": "MB",
    "NEW BRUNSWICK": "NB", "NEWFOUNDLAND AND LABRADOR": "NL", "NOVA SCOTIA": "NS",
    "NORTHWEST TERRITORIES": "NT", "NUNAVUT": "NU", "ONTARIO": "ON",
    "PRINCE EDWARD ISLAND": "PE", "QUEBEC": "QC", "SASKATCHEWAN": "SK", "YUKON": "YT",
}


def normalize_state(state_raw):
    """Convert a state name or code to its 2-letter abbreviation."""
    if not state_raw:
        return ""
    s = state_raw.strip().upper()
    if len(s) <= 2:
        return s
    return STATE_NAME_TO_ABBR.get(s, s)


def format_city_state(city, state):
    """Format city as Title Case and state as 2-letter abbreviation, return 'City, ST'."""
    c = city.strip().title() if city else ""
    s = normalize_state(state)
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
            return city.title(), normalize_state(state), format_city_state(city, state)

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


HOME_FACILITY_OVERRIDE = os.getenv("MATM_HOME_FACILITY_IDS", "")


def resolve_home_facility_ids(headers):
    """Resolve home (terminal) facility IDs.
    1) Check env override MATM_HOME_FACILITY_IDS (comma-separated).
    2) Otherwise query Facility Master for FacilityTypeTerminal = true."""
    if HOME_FACILITY_OVERRIDE.strip():
        ids = [s.strip() for s in HOME_FACILITY_OVERRIDE.split(",") if s.strip()]
        if ids:
            print(f"[HomeFacilities] Using env override: {ids}")
            return set(ids)

    url = f"https://{API_HOST}/facility/api/facility/facility/search"
    payload = {
        "Query": "FacilityTypeTerminal = true",
        "Template": {
            "FacilityId": None,
            "Description": None,
            "FacilityTypeTerminal": None,
            "FacilityAddress": {
                "City": None,
                "State": None,
                "PostalCode": None,
                "Country": None
            }
        },
        "Size": 1000
    }
    try:
        print("[HomeFacilities] Querying FacilityTypeTerminal = true")
        r = requests.post(url, json=payload, headers=headers, timeout=30, verify=False)
        if r.ok:
            data = r.json().get("data", []) or []
            ids = {f.get("FacilityId") for f in data if f.get("FacilityTypeTerminal") and f.get("FacilityId")}
            print(f"[HomeFacilities] Found {len(ids)} terminal facilities")
            return ids
        else:
            print(f"[HomeFacilities] HTTP {r.status_code}: {r.text[:300]}")
    except Exception as e:
        print(f"[HomeFacilities] Exception: {e}")
    return set()


def resolve_tractor_number(tractor_asset_id, terminal_id, headers):
    """Resolve the actual TractorNumber from a HomeAssetId (AssignedTractorAssetId).
    Searches tractor instances and returns the TractorNumber for the assign payload."""
    if not tractor_asset_id:
        return None

    query = f"HomeAssetId = '{tractor_asset_id}'"
    if terminal_id:
        query += f" and HomeTerminalId = '{terminal_id}'"

    url = f"https://{API_HOST}/asset-manager/api/asset-manager/tractor/search"
    payload = {
        "Query": query,
        "Template": {
            "TractorId": None,
            "TractorNumber": None,
            "HomeAssetId": None,
            "HomeTerminalId": None,
            "Active": None
        },
        "Size": 20
    }

    try:
        print(f"[TractorLookup] Resolving TractorNumber for HomeAssetId='{tractor_asset_id}', Terminal='{terminal_id}'")
        r = requests.post(url, json=payload, headers=headers, timeout=30, verify=False)
        if r.ok:
            data = r.json().get("data", []) or []
            if not data:
                print(f"[TractorLookup] No tractor instances found")
                return None
            active = next((t for t in data if t.get("Active") is not False), data[0])
            tractor_num = active.get("TractorNumber")
            print(f"[TractorLookup] Resolved to TractorNumber='{tractor_num}'")
            return tractor_num
        else:
            print(f"[TractorLookup] HTTP {r.status_code}: {r.text[:300]}")
    except Exception as e:
        print(f"[TractorLookup] Exception: {e}")

    return None


def resolve_driver_names(driver_codes, headers):
    """Batch-resolve driver codes to display names via a single driver search API call.
    Returns dict of {DriverCode: 'First Last'} for each resolved driver."""
    if not driver_codes:
        return {}

    codes_list = list(driver_codes)
    in_clause = ",".join(f"'{c}'" for c in codes_list)

    url = f"https://{API_HOST}/asset-manager/api/asset-manager/driver/search"
    payload = {
        "Query": f"DriverCode in ({in_clause})",
        "Template": {
            "DriverId": None,
            "DriverCode": None,
            "DriverDetail": {
                "DriverFirstName": None,
                "DriverLastName": None
            }
        },
        "Size": 9999
    }

    driver_map = {}
    try:
        print(f"[DriverNameLookup] Resolving {len(codes_list)} driver names")
        r = requests.post(url, json=payload, headers=headers, timeout=30, verify=False)
        if r.ok:
            data = r.json().get("data", []) or []
            for d in data:
                code = d.get("DriverCode")
                if not code:
                    continue
                detail = d.get("DriverDetail") or {}
                first = (detail.get("DriverFirstName") or "").strip()
                last = (detail.get("DriverLastName") or "").strip()
                full_name = " ".join(p for p in [first, last] if p)
                if full_name:
                    driver_map[code] = full_name
        else:
            print(f"[DriverNameLookup] HTTP {r.status_code}: {r.text[:300]}")
    except Exception as e:
        print(f"[DriverNameLookup] Exception: {e}")

    print(f"[DriverNameLookup] Resolved {len(driver_map)}/{len(codes_list)} driver names")
    return driver_map


def analyze_trip_backhaul(segments_sorted, home_facility_ids):
    """Determine if a trip has a backhaul based on segment flow relative to home facilities.
    Outbound = home → non-home. Backhaul = non-home → home AFTER first outbound."""
    outbound_seqs = []
    inbound_candidates = []

    for seg in segments_sorted:
        origin_fid = seg.get("OriginFacilityId")
        dest_fid = seg.get("DestinationFacilityId")
        origin_home = origin_fid in home_facility_ids if origin_fid else False
        dest_home = dest_fid in home_facility_ids if dest_fid else False
        seq = seg.get("Sequence", 0)

        if origin_home and not dest_home:
            outbound_seqs.append(seq)
        elif not origin_home and dest_home:
            inbound_candidates.append(seq)

    if not outbound_seqs or not inbound_candidates:
        return False

    first_outbound_seq = outbound_seqs[0]
    return any(s > first_outbound_seq for s in inbound_candidates)


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


def derive_trip_terminal(segments_sorted):
    """Derive a single TerminalId from segments. Returns the terminal only
    if all non-null TrailerAssetTerminalId values agree; otherwise None."""
    terminals = set()
    for seg in segments_sorted:
        t = seg.get("TrailerAssetTerminalId")
        if t:
            terminals.add(t)
    if len(terminals) == 1:
        return terminals.pop()
    return None


def transform_trip(raw_trip, facility_map=None, home_facility_ids=None, driver_name_map=None):
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

    if destination == origin and len(segments_sorted) >= 2:
        penultimate = segments_sorted[-2]
        destination_fid = penultimate.get("DestinationFacilityId", "-")
        dest_city, dest_state, destination = get_location_parts(penultimate, "Destination", fmap)

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

    driver_code = raw_trip.get("AssignedDriverId") or "-"
    dname_map = driver_name_map or {}
    driver_name = dname_map.get(driver_code, "")
    driver_display = f"{driver_code}: {driver_name}" if driver_name else driver_code

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
        "Backhaul": "Yes" if (home_facility_ids and analyze_trip_backhaul(segments_sorted, home_facility_ids)) else "No",
        "CurrentDriver": driver_display,
        "Carrier": raw_trip.get("AssignedCarrierId", "-"),
        "Tractor": raw_trip.get("AssignedTractorNumber") or "-",
        "Trailer": raw_trip.get("AssignedTrailerNumber") or (first_seg.get("AssignedTrailerNumber") if first_seg else None) or "-",
        "Overview": {
            "Carrier": raw_trip.get("AssignedCarrierId", "-"),
            "Distance": f"{total_distance:.1f} mi",
            "Segments": str(len(segments_sorted))
        },
        "Shipments": shipments,
        "DriverAssignment": {
            "Name": driver_display,
            "Role": "Assigned Driver" if driver_code != "-" else "Unassigned"
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
        } for s in segments_sorted],
        "AssignData": {
            "TractorAssetId": raw_trip.get("AssignedTractorAssetId"),
            "TractorNumber": raw_trip.get("AssignedTractorNumber") or None,
            "TrailerNumber": raw_trip.get("AssignedTrailerNumber") or None,
            "CarrierId": raw_trip.get("AssignedCarrierId"),
            "TerminalId": derive_trip_terminal(segments_sorted),
            "StatusCode": status_code,
            "Segments": [{
                "SegmentId": s.get("SegmentId"),
                "ShipmentId": s.get("ShipmentId"),
                "TrailerNumber": s.get("AssignedTrailerNumber") or None
            } for s in segments_sorted]
        }
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
            "AssignedTractorNumber": None,
            "AssignedTrailerNumber": None,
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

            all_driver_codes = set()
            for trip in raw_trips:
                dc = trip.get("AssignedDriverId")
                if dc:
                    all_driver_codes.add(dc)

            print(f"[SearchTrips] Resolving {len(all_facility_ids)} unique facilities, {len(all_driver_codes)} drivers")
            facility_map = resolve_facility_locations(all_facility_ids, headers)
            driver_name_map = resolve_driver_names(all_driver_codes, headers)

            home_fids = resolve_home_facility_ids(headers)

            trips = [transform_trip(t, facility_map, home_fids, driver_name_map) for t in raw_trips]

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

            backhaul_filter = filters.get("backhaulFilter")
            if backhaul_filter == "yes":
                trips = [t for t in trips if t.get("Backhaul") == "Yes"]
            elif backhaul_filter == "no":
                trips = [t for t in trips if t.get("Backhaul") == "No"]

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


@app.route('/api/trip_stops', methods=['POST'])
def trip_stops():
    """Fetch shipment stop data for a list of ShipmentIds.
    Returns stops grouped by ShipmentId with facility addresses resolved."""
    org = request.json.get('org')
    token = request.json.get('token')
    shipment_ids = request.json.get('shipment_ids', [])

    if not all([org, token]):
        return jsonify({"success": False, "error": "Missing org/token"})

    if not shipment_ids:
        return jsonify({"success": True, "stops": {}})

    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
        "selectedOrganization": org,
        "selectedLocation": f"{org}-DM1"
    }

    unique_ids = list(set(shipment_ids))
    in_clause = ",".join(f"'{sid}'" for sid in unique_ids)

    url = f"https://{API_HOST}/shipment/api/shipment/shipment/search"
    payload = {
        "Query": f"ShipmentId in ({in_clause})",
        "Template": {
            "ShipmentId": None,
            "Stop": {
                "StopSequence": None,
                "FacilityId": None,
                "StopActionId": {"StopActionId": None},
                "PlannedArrivalDateTime": None,
                "PlannedDepartureDateTime": None
            }
        },
        "Size": len(unique_ids)
    }

    try:
        print(f"[TripStops] Fetching stops for {len(unique_ids)} shipments")
        r = requests.post(url, json=payload, headers=headers, timeout=30, verify=False)
        if not r.ok:
            return jsonify({"success": False, "error": f"HTTP {r.status_code}: {r.text[:300]}"})

        data = r.json().get("data", []) or []

        all_fac_ids = set()
        for shipment in data:
            for stop in (shipment.get("Stop") or []):
                fid = stop.get("FacilityId")
                if fid:
                    all_fac_ids.add(fid)

        facility_map = resolve_facility_locations(all_fac_ids, headers)

        stops_by_shipment = {}
        for shipment in data:
            sid = shipment.get("ShipmentId")
            if not sid:
                continue
            raw_stops = shipment.get("Stop") or []
            sorted_stops = sorted(raw_stops, key=lambda s: s.get("StopSequence", 0))
            stops_by_shipment[sid] = []
            for stop in sorted_stops:
                fid = stop.get("FacilityId") or "-"
                action_obj = stop.get("StopActionId") or {}
                action = action_obj.get("StopActionId", "") if isinstance(action_obj, dict) else str(action_obj)
                stops_by_shipment[sid].append({
                    "StopSequence": stop.get("StopSequence", 0),
                    "FacilityId": fid,
                    "Address": facility_map.get(fid, "-"),
                    "StopAction": action or "-",
                    "PlannedArrival": format_dt_short(stop.get("PlannedArrivalDateTime")),
                    "PlannedDeparture": format_dt_short(stop.get("PlannedDepartureDateTime"))
                })

        print(f"[TripStops] Resolved stops for {len(stops_by_shipment)}/{len(unique_ids)} shipments")
        return jsonify({"success": True, "stops": stops_by_shipment})

    except Exception as e:
        print(f"[TripStops] Exception: {e}")
        traceback.print_exc()
        return jsonify({"success": False, "error": str(e)})


@app.route('/api/precheck_driver', methods=['POST'])
def precheck_driver():
    """Validate driver + tractor before assignment.
    Checks: trip status, driver exists/active/carrier/terminal,
    tractor exists/active/carrier/terminal."""
    org = request.json.get('org')
    token = request.json.get('token')
    driver_code = request.json.get('driver_code')
    carrier_id = request.json.get('carrier_id')
    terminal_id = request.json.get('terminal_id')
    tractor_asset_id = request.json.get('tractor_asset_id')
    status_code = request.json.get('status_code')

    if not all([org, token, driver_code]):
        return jsonify({"success": False, "error": "Missing required fields"})

    NON_ASSIGNABLE_STATUSES = {"4000": "Delivered", "5000": "Completed", "6000": "Cancelled"}
    if status_code and status_code in NON_ASSIGNABLE_STATUSES:
        label = NON_ASSIGNABLE_STATUSES[status_code]
        return jsonify({"success": False,
            "error": f"Trip is in '{label}' status and cannot accept driver assignment"})

    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
        "selectedOrganization": org,
        "selectedLocation": f"{org}-DM1"
    }

    import concurrent.futures

    driver_result = {"data": None, "error": None}
    tractor_result = {"data": None, "error": None}

    def lookup_driver():
        url = f"https://{API_HOST}/asset-manager/api/asset-manager/driver/search"
        payload = {
            "Query": f"DriverCode = '{driver_code}'",
            "Template": {"DriverId": None, "DriverCode": None, "CarrierId": None, "TerminalId": None, "Active": None},
            "Size": 5
        }
        print(f"[Precheck] Looking up DriverCode='{driver_code}'")
        r = requests.post(url, json=payload, headers=headers, timeout=30, verify=False)
        if not r.ok:
            driver_result["error"] = f"Driver lookup failed: HTTP {r.status_code}"
            return
        body = r.json()
        data = body.get("data", []) or []
        driver_result["data"] = data[0] if data else None

    def lookup_tractor():
        if not tractor_asset_id:
            return
        url = f"https://{API_HOST}/asset-manager/api/asset-manager/tractorAsset/search"
        payload = {
            "Query": f"TractorAssetId = '{tractor_asset_id}'",
            "Template": {"TractorAssetId": None, "CarrierId": None, "TerminalId": None, "Active": None},
            "Size": 5
        }
        print(f"[Precheck] Looking up TractorAssetId='{tractor_asset_id}'")
        r = requests.post(url, json=payload, headers=headers, timeout=30, verify=False)
        if not r.ok:
            tractor_result["error"] = f"Tractor lookup failed: HTTP {r.status_code}"
            return
        body = r.json()
        data = body.get("data", []) or []
        tractor_result["data"] = data[0] if data else None

    with concurrent.futures.ThreadPoolExecutor(max_workers=2) as executor:
        executor.submit(lookup_driver)
        executor.submit(lookup_tractor)

    try:
        if driver_result["error"]:
            return jsonify({"success": False, "error": driver_result["error"]})
        driver = driver_result["data"]
        if not driver:
            return jsonify({"success": False, "error": f"Driver code '{driver_code}' not found in the system"})

        driver_active = driver.get("Active")
        driver_carrier = driver.get("CarrierId")
        driver_terminal = driver.get("TerminalId")
        print(f"[Precheck] Driver: Active={driver_active}, CarrierId={driver_carrier}, TerminalId={driver_terminal}")

        if driver_active is False:
            return jsonify({"success": False, "error": f"Driver '{driver_code}' is inactive"})

        if carrier_id and driver_carrier and carrier_id != driver_carrier:
            return jsonify({"success": False,
                "error": f"Carrier mismatch: trip carrier is '{carrier_id}' but driver '{driver_code}' belongs to carrier '{driver_carrier}'"})

        if terminal_id and driver_terminal and terminal_id != driver_terminal:
            return jsonify({"success": False,
                "error": f"Terminal mismatch: trip terminal is '{terminal_id}' but driver '{driver_code}' belongs to terminal '{driver_terminal}'"})

        if tractor_asset_id:
            if tractor_result["error"]:
                return jsonify({"success": False, "error": tractor_result["error"]})
            tractor = tractor_result["data"]
            if not tractor:
                return jsonify({"success": False, "error": f"Tractor '{tractor_asset_id}' not found in the system"})

            tractor_active = tractor.get("Active")
            tractor_carrier = tractor.get("CarrierId")
            tractor_terminal = tractor.get("TerminalId")
            print(f"[Precheck] Tractor: Active={tractor_active}, CarrierId={tractor_carrier}, TerminalId={tractor_terminal}")

            if tractor_active is False:
                return jsonify({"success": False, "error": f"Tractor '{tractor_asset_id}' is inactive"})

            if carrier_id and tractor_carrier and carrier_id != tractor_carrier:
                return jsonify({"success": False,
                    "error": f"Carrier mismatch: trip carrier is '{carrier_id}' but tractor '{tractor_asset_id}' belongs to carrier '{tractor_carrier}'"})

            if terminal_id and tractor_terminal and terminal_id != tractor_terminal:
                return jsonify({"success": False,
                    "error": f"Terminal mismatch: trip terminal is '{terminal_id}' but tractor '{tractor_asset_id}' belongs to terminal '{tractor_terminal}'"})

        return jsonify({"success": True})

    except Exception as e:
        print(f"[Precheck] Exception: {e}")
        traceback.print_exc()
        return jsonify({"success": False, "error": str(e)})


@app.route('/api/assign_trip', methods=['POST'])
def assign_trip():
    """Assign a driver to a trip via Dispatch /assignAssetResources."""
    org = request.json.get('org')
    token = request.json.get('token')
    trip_id = request.json.get('trip_id')
    driver_code = request.json.get('driver_code')
    assign_data = request.json.get('assign_data', {})

    if not all([org, token, trip_id, driver_code]):
        return jsonify({"success": False, "error": "Missing required fields (org, token, trip_id, driver_code)"})

    send_ha_message({"event": "dispatch_assign_trip", "org": org, "trip_id": trip_id, "driver_code": driver_code})

    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
        "selectedOrganization": org,
        "selectedLocation": f"{org}-DM1"
    }

    segments_payload = []
    for seg in assign_data.get("Segments", []):
        segments_payload.append({
            "ShipmentId": seg.get("ShipmentId"),
            "SegmentId": seg.get("SegmentId"),
            "TrailerNumber": seg.get("TrailerNumber")
        })

    payload = {
        "TripId": trip_id,
        "DriverCode": driver_code,
        "DriverCode2": None,
        "DriverCode3": None,
        "TractorNumber": assign_data.get("TractorNumber"),
        "Segments": segments_payload,
        "KeepTractorAssignment": False
    }

    url = f"https://{API_HOST}/dispatch/api/dispatch/assignAssetResources"

    try:
        print(f"[AssignTrip] Assigning driver {driver_code} to trip {trip_id}")
        print(f"[AssignTrip] Payload: {json.dumps(payload)}")
        r = requests.post(url, json=payload, headers=headers, timeout=30, verify=False)
        print(f"[AssignTrip] Status: {r.status_code}")
        print(f"[AssignTrip] Response: {r.text[:500]}")

        if r.ok:
            body = r.json()
            if body.get("success") is False:
                error_msg = body.get("error") or body.get("message") or str(body)
                return jsonify({"success": False, "error": f"Assignment failed: {error_msg}"})
            return jsonify({"success": True, "message": f"Driver {driver_code} assigned to trip {trip_id}"})
        else:
            error_text = r.text[:500]
            return jsonify({"success": False, "error": f"HTTP {r.status_code}: {error_text}"})
    except Exception as e:
        print(f"[AssignTrip] Exception: {e}")
        traceback.print_exc()
        return jsonify({"success": False, "error": str(e)})


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
