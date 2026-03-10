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


@app.route('/api/search_trips', methods=['POST'])
def search_trips():
    """Search trips with filter criteria (placeholder - API TBD)"""
    org = request.json.get('org')
    token = request.json.get('token')
    filters = request.json.get('filters', {})
    if not all([org, token]):
        return jsonify({"success": False, "error": "Missing org or token"})

    send_ha_message({"event": "dispatch_search_trips", "org": org, "filters": filters})

    # Placeholder: return mock trips until real API is provided
    mock_trips = []
    for i in range(25):
        trip_num = f"TRIP-{10123 + i:05d}"
        mock_trips.append({
            "TripId": trip_num,
            "Status": "Available",
            "Origin": f"{filters.get('destinationCity', 'New York')}, {filters.get('destinationState', 'NY')}",
            "Destination": "Philadelphia, PA",
            "PickupWindow": "10/25 08:00-10:00",
            "DeliveryWindow": "10/25 14:00-16:00",
            "TotalDuration": "4h 30m",
            "TotalStops": 3,
            "TotalSegments": 3,
            "Backhaul": "No",
            "RequiredEquipment": filters.get('requiredEquipment', 'Reefer'),
            "CurrentDriver": "-",
            "Overview": {
                "Customer": "Acme Corp",
                "Weight": "15,000 lbs",
                "Volume": "1,200 cu ft"
            },
            "Shipments": [
                {"ShipmentId": f"SH-{8876 + i * 2}", "Volume": f"{4500 + i * 100} lbs"},
                {"ShipmentId": f"SH-{8877 + i * 2}", "Volume": f"{5000 + i * 100} lbs"}
            ],
            "DriverAssignment": {
                "Name": "John Doe",
                "Role": "Current Driver"
            }
        })

    return jsonify({"success": True, "trips": mock_trips, "count": len(mock_trips)})


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
