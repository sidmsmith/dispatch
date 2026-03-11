# Dispatch v1.0.1

A web application for searching, filtering, and assigning Manhattan Active Transportation Management (TMS) trips. Designed for both desktop and mobile browsers.

## Overview

Dispatch allows users to search for trips using a variety of filters, view results in a sortable table (desktop) or card list (mobile), inspect trip details, and assign trips to drivers. The app connects to the Manhattan Active TMS APIs to retrieve live trip, facility, and equipment data.

---

## Screens

### Authentication

When the app loads, users enter their Organization code (e.g., `LB-DEMO`) to authenticate against the Manhattan platform. Authentication can also be pre-filled via URL parameters (`ORG` or `Organization`), allowing seamless integration with other tools and bookmarks.

### Screen 1 — Filters

After authentication, users are presented with a set of filter fields:

| Filter | Type | Behavior |
|---|---|---|
| **Destination City** | Text input | Case-insensitive "contains" match against any segment's destination city |
| **Destination State** | Dropdown | US states and Canadian provinces (2-letter code). Matches any segment's destination state |
| **Total Duration** | Dual-handle slider (0–60 hours) | Filters by trip duration from first pickup to final delivery |
| **Total Number of Segments** | Dual-handle slider (1–7) | Filters by the number of segments on the trip |
| **Total Number of Stops** | Dual-handle slider (1–30) | Filters by the calculated number of unique stops (see Stops Calculation below) |
| **Backhaul** | 3-way toggle (Any / Has Backhaul / No Backhaul) | Filters by backhaul status (see Backhaul Calculation below) |
| **Required Equipment** | Dropdown | Filters by equipment type, loaded from the Equipment Type API |
| **Pickup Start Date-Time** | Two datetime pickers (From / To) | Filters on Sequence 1 segment's `PlannedOriginDepartureStart` |
| **Today?** | Checkbox | Shortcut to fill both date fields with today's date (00:00 – 23:59) |

**Filter persistence:** All filter values are automatically saved to the browser's localStorage whenever they change. The next time the user visits the app, the filters are restored. The "Today?" checkbox intelligently re-calculates to the current date upon restore rather than using a stale saved date.

**Reset Filters:** A link below the Search button resets all filters to their defaults and clears the saved values from localStorage.

**Validation:** If both date fields are filled and the end date is not later than the start date, the Search Trips button is disabled.

### Screen 2 — Results

Displays all matching trips in a table (desktop) or card list (mobile).

**Columns displayed:** Trip ID, Status, Origin, Destination, Pickup, Delivery, Duration, Stops, Segments, Backhaul, Distance, Driver, Carrier.

- **Status** is displayed as a human-readable label (e.g., "Not Dispatched") based on the status code.
- **Origin** is derived from the first segment (Sequence = 1).
- **Destination** is derived from the last segment (highest Sequence number).
- **Duration** is displayed as "X Days Y Hours Z Minutes" format.
- **Pickup and Delivery dates** are displayed in the user's local timezone with the format `MM/DD/YY, HH:MM AM/PM EST`.
- Cities are displayed in Title Case and states in uppercase (e.g., "Los Angeles, CA").

**Active filter chips** appear above the results showing which filters are applied. Clicking the X on a chip removes that filter and re-runs the search.

**Navigation arrows** (left/right chevrons) in the detail panel allow navigating between trips without closing the panel.

### Detail Panel

Clicking a trip opens a detail panel:
- **Desktop:** Slides in from the right side of the results table.
- **Mobile:** Opens as a bottom sheet overlay.

The panel shows:
- Trip ID with previous/next navigation arrows
- Overview: Carrier, Tractor, Total Distance, Duration, Stops
- Segments table: Sequence, Origin, Destination, Departure time, Distance
- Driver Assignment with an "Assign Trip to Me" button

---

## Trip Status Codes

| Code | Description |
|---|---|
| 1000 | Not Dispatched |
| 2000 | Dispatched |
| 3000 | In Transit |
| 4000 | Delivered |
| 5000 | Completed |
| 6000 | Cancelled |

The API query is hardcoded to filter for `TripStatusId = '1000'` (Not Dispatched) trips only.

---

## Stops Calculation

The stop count represents the number of distinct physical locations a driver visits on a trip, including the starting point. The logic works as follows:

1. **Sort all segments** by Sequence number (ascending).
2. **First stop** = the Origin of Segment 1 (where the trip begins).
3. **Walk through each segment in order** and take the Destination of each segment as the next potential stop.
4. **Consecutive de-duplication:** A stop is only added if it is **different from the immediately previous stop**. This handles the common pattern where a segment's destination is the same as the next segment's origin (the driver doesn't "stop" twice at the same location).
5. **Stop identity** is determined by:
   - **Facility ID** (preferred) — if the segment has an `OriginFacilityId` or `DestinationFacilityId`, that ID is used as the unique key.
   - **Geo-coordinates** (fallback) — if no Facility ID is present, latitude/longitude are used (rounded to 6 decimal places).
   - Segments with neither are treated as unknown but still countable.
6. **All segments are included**, including empty-leg segments (where `ShipmentId` is null). Empty legs represent deadhead moves that still count as physical stops.

### Example

A trip with 4 segments:

| Seq | Origin | Destination |
|---|---|---|
| 1 | DC-01 | STORE-A |
| 2 | STORE-A | VENDOR-B |
| 3 | VENDOR-B | DC-01 |
| 4 | DC-01 | STORE-C |

**Stop walk-through:**
- Start: DC-01 (origin of Seq 1) → **Stop 1**
- Seq 1 destination: STORE-A (different from DC-01) → **Stop 2**
- Seq 2 destination: VENDOR-B (different from STORE-A) → **Stop 3**
- Seq 3 destination: DC-01 (different from VENDOR-B) → **Stop 4**
- Seq 4 destination: STORE-C (different from DC-01) → **Stop 5**

**Total: 5 stops**

### De-duplication Example

| Seq | Origin | Destination |
|---|---|---|
| 1 | DC-01 | STORE-A |
| 2 | STORE-A | DC-01 |

- Start: DC-01 → **Stop 1**
- Seq 1 destination: STORE-A (different) → **Stop 2**
- Seq 2 destination: DC-01 (different from STORE-A) → **Stop 3**

**Total: 3 stops** (DC-01 appears twice because it is not *consecutively* duplicated — STORE-A appears between the two visits)

If instead Segment 2's destination were also STORE-A:

| Seq | Origin | Destination |
|---|---|---|
| 1 | DC-01 | STORE-A |
| 2 | STORE-A | STORE-A |

- Start: DC-01 → **Stop 1**
- Seq 1 destination: STORE-A → **Stop 2**
- Seq 2 destination: STORE-A (same as previous — **skipped**)

**Total: 2 stops**

---

## Backhaul Calculation

A trip is classified as having a **backhaul** if it contains an inbound leg (returning to a home facility) that occurs after an outbound leg (leaving a home facility). This indicates the driver is picking up freight on the return trip rather than deadheading back empty.

### How Home Facilities Are Determined

Home facilities (DCs, terminals, cross-docks) are identified in one of two ways:
1. **Environment variable override** (`MATM_HOME_FACILITY_IDS`): A comma-separated list of Facility IDs (e.g., `"DC-01,XD-02"`). If set, this takes priority.
2. **Facility Master query**: If no override is set, the app queries the Manhattan Facility API for all facilities where `FacilityTypeTerminal = true`.

### Classification Logic

Each segment is classified based on the relationship between its origin and destination relative to home facilities:

| Origin | Destination | Classification |
|---|---|---|
| Home facility | Non-home facility | **Outbound** (delivering to a store/vendor) |
| Non-home facility | Home facility | **Inbound** (potential backhaul) |
| Home → Home, Non-home → Non-home | — | Other (not counted) |

### Backhaul Determination

1. Sort all segments by Sequence.
2. Identify all **outbound** segments (home → non-home) and all **inbound candidates** (non-home → home).
3. Find the Sequence number of the **first outbound** segment.
4. Check if **any inbound candidate** has a Sequence number **greater than** the first outbound Sequence.
5. If yes → the trip **has a backhaul**. If no → it does not.

### Example

| Seq | Origin | Destination | Classification |
|---|---|---|---|
| 1 | DC-01 (home) | STORE-A | Outbound |
| 2 | STORE-A | VENDOR-B | Other |
| 3 | VENDOR-B | DC-01 (home) | Inbound |

- First outbound: Sequence 1
- Inbound at Sequence 3 (3 > 1)
- **Result: Has Backhaul = Yes**

The inbound at Sequence 3 indicates the driver picked up freight at VENDOR-B on the way back to the DC, rather than returning empty.

### Non-Backhaul Example

| Seq | Origin | Destination | Classification |
|---|---|---|---|
| 1 | DC-01 (home) | STORE-A | Outbound |
| 2 | STORE-A | STORE-B | Other |

- First outbound: Sequence 1
- No inbound segments exist
- **Result: Has Backhaul = No**

---

## API Data Flow

1. **Authentication:** OAuth2 token obtained from the Manhattan auth service using the organization code.
2. **Equipment Types:** Loaded from `/asset-manager/api/asset-manager/equipmentType/search` to populate the Required Equipment dropdown.
3. **Trip Search:** Queries `/shipment/api/shipment/trip/search` with a filter for `TripSegment.Sequence = '1'` and `TripStatusId = '1000'`, plus optional date range filters on `PlannedOriginDepartureStart`.
4. **Facility Resolution:** Unique Facility IDs from all trip segments are batch-resolved via `/facility/api/facility/facility/search` to obtain City/State information for display.
5. **Home Facility Resolution:** Terminal facilities are identified (for backhaul calculation) via Facility Master query or environment override.
6. **Post-Filtering:** After the API returns results, additional filters are applied server-side:
   - Date range strict validation (re-checks Sequence 1 departure)
   - Equipment type (matched via trailer asset lookup)
   - Duration range
   - Segment count range
   - Stop count range
   - Backhaul status
   - Destination city (case-insensitive contains, any segment)
   - Destination state (exact 2-letter match, any segment)

---

## Theming

The app supports multiple visual themes, selectable via the gear icon:

| Theme | Description |
|---|---|
| Light | Default blue theme |
| Dark | Dark background with light text |
| Manhattan | Manhattan Associates branded dark theme |
| Love's Travel Stops | Red-themed with Love's logo |
| Rockline Industries | Green-themed with Rockline logo |

Themes can be hidden from the UI by passing `?Theme=N` in the URL.

The selected theme is persisted in localStorage.

---

## Deployment

- **Hosting:** Vercel
- **Backend:** Python (Flask) deployed as a Vercel serverless function
- **Frontend:** Single-page HTML/CSS/JavaScript application
- **Repository:** https://github.com/sidmsmith/dispatch

---

## URL Parameters

| Parameter | Description |
|---|---|
| `ORG` or `Organization` | Pre-fills the organization code and auto-authenticates |
| `Theme` | Set to `N` to hide the theme selector |
