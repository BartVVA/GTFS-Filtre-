# -*- coding: utf-8 -*-
"""
Coeur du filtrage GTFS : lecture, inventaire des valeurs disponibles,
application des filtres en cascade, ecriture d'un zip GTFS filtre.

Ne depend que de la stdlib (csv, zipfile, io) -> reutilisable hors QGIS.
"""

import csv
import io
import zipfile
from datetime import datetime

ROUTE_TYPE_LABELS = {
    0: "Tram",
    1: "Métro",
    2: "Train (rail lourd)",
    3: "Bus",
    4: "Ferry",
    5: "Cable tram",
    6: "Téléphérique / télécabine",
    7: "Funiculaire",
    11: "Trolleybus",
    12: "Monorail",
}


def _read_table(zf, name):
    if name not in zf.namelist():
        return []
    with zf.open(name) as f:
        text = io.TextIOWrapper(f, encoding="utf-8-sig", newline="")
        reader = csv.DictReader(text)
        return [row for row in reader]


def load_gtfs(path):
    """Charge toutes les tables GTFS d'un zip dans un dict {nom_fichier: [rows]}."""
    with zipfile.ZipFile(path, "r") as zf:
        names = zf.namelist()
        tables = {}
        for name in names:
            if name.endswith(".txt"):
                tables[name] = _read_table(zf, name)
    return tables, names


def summarize(tables):
    """
    Inspecte les tables chargees et retourne l'inventaire des valeurs
    disponibles pour construire dynamiquement l'interface de filtres.
    """
    routes = tables.get("routes.txt", [])
    agencies = tables.get("agency.txt", [])
    trips = tables.get("trips.txt", [])
    stops = tables.get("stops.txt", [])
    calendar = tables.get("calendar.txt", [])
    calendar_dates = tables.get("calendar_dates.txt", [])

    route_types = sorted({int(r["route_type"]) for r in routes if r.get("route_type", "").strip() != ""})

    agency_ids = sorted({a["agency_id"] for a in agencies if a.get("agency_id")})
    agency_names = {a.get("agency_id", ""): a.get("agency_name", "") for a in agencies}

    routes_list = sorted(
        [
            {
                "route_id": r.get("route_id", ""),
                "short_name": r.get("route_short_name", ""),
                "long_name": r.get("route_long_name", ""),
                "route_type": r.get("route_type", ""),
                "agency_id": r.get("agency_id", ""),
            }
            for r in routes
        ],
        key=lambda r: (r["short_name"], r["route_id"]),
    )

    has_direction_id = any("direction_id" in t and t["direction_id"] != "" for t in trips)
    has_wheelchair_trips = any("wheelchair_accessible" in t and t["wheelchair_accessible"] != "" for t in trips)
    has_bikes_allowed = any("bikes_allowed" in t and t["bikes_allowed"] != "" for t in trips)
    has_wheelchair_stops = any("wheelchair_boarding" in s and s["wheelchair_boarding"] != "" for s in stops)

    dates = set()
    for c in calendar:
        if c.get("start_date"):
            dates.add(c["start_date"])
        if c.get("end_date"):
            dates.add(c["end_date"])
    for cd in calendar_dates:
        if cd.get("date"):
            dates.add(cd["date"])
    date_min = min(dates) if dates else None
    date_max = max(dates) if dates else None

    lats = [float(s["stop_lat"]) for s in stops if s.get("stop_lat")]
    lons = [float(s["stop_lon"]) for s in stops if s.get("stop_lon")]
    bbox = (min(lons), min(lats), max(lons), max(lats)) if lats and lons else None

    return {
        "route_types": route_types,
        "agency_ids": agency_ids,
        "agency_names": agency_names,
        "routes": routes_list,
        "has_direction_id": has_direction_id,
        "has_wheelchair_trips": has_wheelchair_trips,
        "has_bikes_allowed": has_bikes_allowed,
        "has_wheelchair_stops": has_wheelchair_stops,
        "date_min": date_min,
        "date_max": date_max,
        "n_stops": len(stops),
        "bbox": bbox,
    }


def _expand_with_parent_stations(stop_ids, stops):
    """
    GTFS autorise une hierarchie de stops via parent_station (quai -> station,
    station -> station mere, entree -> station, etc.). Si on filtre stops.txt
    en ne gardant que les stop_id presents dans stop_times.txt, on perd les
    stations parentes referencees uniquement via parent_station, ce qui rend
    le GTFS invalide ("no stop with id X defined, cannot reference here").

    Cette fonction ajoute recursivement tous les parent_station necessaires.
    """
    parent_by_id = {s["stop_id"]: s.get("parent_station") for s in stops if s.get("stop_id")}
    result = set(stop_ids)
    to_process = list(stop_ids)
    while to_process:
        sid = to_process.pop()
        parent = parent_by_id.get(sid)
        if parent and parent not in result:
            result.add(parent)
            to_process.append(parent)
    return result


def _time_to_seconds(hhmmss):
    h, m, s = (int(x) for x in hhmmss.split(":"))
    return h * 3600 + m * 60 + s


def _active_service_ids(calendar, calendar_dates, date_str):
    dow_fields = ["sunday", "monday", "tuesday", "wednesday", "thursday",
                  "friday", "saturday"]
    d = datetime.strptime(date_str, "%Y%m%d")
    day_field = dow_fields[int(d.strftime("%w"))]

    active = set()
    for row in calendar:
        if (row.get(day_field) == "1"
                and row.get("start_date", "") <= date_str
                and row.get("end_date", "") >= date_str):
            active.add(row["service_id"])
    for row in calendar_dates:
        if row.get("date") != date_str:
            continue
        if row.get("exception_type") == "1":
            active.add(row["service_id"])
        elif row.get("exception_type") == "2":
            active.discard(row["service_id"])
    return active


def apply_filters(tables, filters):
    """
    filters : dict, toutes les cles sont optionnelles (None ou absente = pas de filtre)
      route_types      : list[int]
      agency_ids       : list[str]
      route_ids        : list[str]
      trip_ids         : list[str]
      direction_id     : "0" | "1"
      date             : "YYYYMMDD"
      start_time       : "HH:MM:SS"
      end_time         : "HH:MM:SS"
      stop_ids         : list[str]
      wheelchair_trips : "0" | "1" | "2"
      bikes_allowed    : "0" | "1" | "2"
      bbox             : (min_lon, min_lat, max_lon, max_lat)  -- EPSG:4326

    Retourne un nouveau dict de tables filtrees, pretes a etre ecrites.
    """
    routes = tables.get("routes.txt", [])
    trips = tables.get("trips.txt", [])
    stop_times = tables.get("stop_times.txt", [])
    stops = tables.get("stops.txt", [])
    shapes = tables.get("shapes.txt", [])
    calendar = tables.get("calendar.txt", [])
    calendar_dates = tables.get("calendar_dates.txt", [])
    agency = tables.get("agency.txt", [])
    frequencies = tables.get("frequencies.txt", [])
    transfers = tables.get("transfers.txt", [])
    pathways = tables.get("pathways.txt", [])

    # --- 1. Agences ---
    agency_f = agency
    if filters.get("agency_ids"):
        agency_f = [a for a in agency if a.get("agency_id") in filters["agency_ids"]]
    kept_agency_ids = {a.get("agency_id") for a in agency_f} if filters.get("agency_ids") else None

    # --- 2. Routes (mode + agence + ligne) ---
    routes_f = routes
    if filters.get("route_types") is not None:
        routes_f = [r for r in routes_f if int(r.get("route_type", -1)) in filters["route_types"]]
    if kept_agency_ids is not None:
        routes_f = [r for r in routes_f if r.get("agency_id") in kept_agency_ids]
    if filters.get("route_ids"):
        routes_f = [r for r in routes_f if r.get("route_id") in filters["route_ids"]]
    kept_route_ids = {r["route_id"] for r in routes_f}

    # --- 3. Trips (route + direction + trip_id + accessibilite) ---
    trips_f = [t for t in trips if t.get("route_id") in kept_route_ids]
    if filters.get("trip_ids"):
        trips_f = [t for t in trips_f if t.get("trip_id") in filters["trip_ids"]]
    if filters.get("direction_id") is not None:
        trips_f = [t for t in trips_f if t.get("direction_id") == filters["direction_id"]]
    if filters.get("wheelchair_trips") is not None:
        trips_f = [t for t in trips_f if t.get("wheelchair_accessible") == filters["wheelchair_trips"]]
    if filters.get("bikes_allowed") is not None:
        trips_f = [t for t in trips_f if t.get("bikes_allowed") == filters["bikes_allowed"]]

    # --- 4. Date -> service_id actifs ---
    if filters.get("date"):
        active_services = _active_service_ids(calendar, calendar_dates, filters["date"])
        trips_f = [t for t in trips_f if t.get("service_id") in active_services]

    kept_trip_ids = {t["trip_id"] for t in trips_f}

    # --- 5. Stop_times (trip + horaire) ---
    stop_times_f = [st for st in stop_times if st.get("trip_id") in kept_trip_ids]
    if filters.get("start_time") or filters.get("end_time"):
        start_s = _time_to_seconds(filters["start_time"]) if filters.get("start_time") else -1
        end_s = _time_to_seconds(filters["end_time"]) if filters.get("end_time") else 10**9
        stop_times_f = [
            st for st in stop_times_f
            if start_s <= _time_to_seconds(st.get("departure_time") or st.get("arrival_time")) <= end_s
        ]
        remaining_trip_ids = {st["trip_id"] for st in stop_times_f}
        trips_f = [t for t in trips_f if t["trip_id"] in remaining_trip_ids]
        kept_trip_ids = remaining_trip_ids
        stop_times_f = [st for st in stop_times_f if st["trip_id"] in kept_trip_ids]

    # --- 6. Filtre spatial (bbox) et/ou liste explicite de stop_id ---
    if filters.get("bbox") or filters.get("stop_ids"):
        allowed_stop_ids = {s["stop_id"] for s in stops}
        if filters.get("bbox"):
            min_lon, min_lat, max_lon, max_lat = filters["bbox"]
            allowed_stop_ids &= {
                s["stop_id"] for s in stops
                if s.get("stop_lat") and s.get("stop_lon")
                and min_lat <= float(s["stop_lat"]) <= max_lat
                and min_lon <= float(s["stop_lon"]) <= max_lon
            }
        if filters.get("stop_ids"):
            allowed_stop_ids &= set(filters["stop_ids"])

        stop_times_f = [st for st in stop_times_f if st.get("stop_id") in allowed_stop_ids]
        remaining_trip_ids = {st["trip_id"] for st in stop_times_f}
        trips_f = [t for t in trips_f if t["trip_id"] in remaining_trip_ids]
        kept_trip_ids = remaining_trip_ids

    # --- 7. Recalcul final en cascade ---
    kept_trip_ids = {t["trip_id"] for t in trips_f}
    stop_times_f = [st for st in stop_times_f if st["trip_id"] in kept_trip_ids]

    kept_stop_ids = {st["stop_id"] for st in stop_times_f}
    kept_stop_ids = _expand_with_parent_stations(kept_stop_ids, stops)
    stops_f = [s for s in stops if s["stop_id"] in kept_stop_ids]

    kept_shape_ids = {t.get("shape_id") for t in trips_f if t.get("shape_id")}
    shapes_f = [sh for sh in shapes if sh.get("shape_id") in kept_shape_ids]

    kept_service_ids = {t["service_id"] for t in trips_f}
    calendar_f = [c for c in calendar if c.get("service_id") in kept_service_ids]
    calendar_dates_f = [c for c in calendar_dates if c.get("service_id") in kept_service_ids]

    kept_route_ids_final = {t["route_id"] for t in trips_f}
    routes_f = [r for r in routes_f if r["route_id"] in kept_route_ids_final]

    frequencies_f = [f for f in frequencies if f.get("trip_id") in kept_trip_ids]
    transfers_f = [
        tr for tr in transfers
        if tr.get("from_stop_id") in kept_stop_ids and tr.get("to_stop_id") in kept_stop_ids
    ]
    pathways_f = [
        p for p in pathways
        if p.get("from_stop_id") in kept_stop_ids and p.get("to_stop_id") in kept_stop_ids
    ]

    result = dict(tables)  # conserve les fichiers non geres tels quels (fare_*, feed_info...)
    result.update({
        "agency.txt": agency_f,
        "routes.txt": routes_f,
        "trips.txt": trips_f,
        "stop_times.txt": stop_times_f,
        "stops.txt": stops_f,
        "shapes.txt": shapes_f,
        "calendar.txt": calendar_f,
        "calendar_dates.txt": calendar_dates_f,
        "frequencies.txt": frequencies_f,
        "transfers.txt": transfers_f,
        "pathways.txt": pathways_f,
    })

    stats = {
        "routes": (len(routes_f), len(routes)),
        "trips": (len(trips_f), len(trips)),
        "stop_times": (len(stop_times_f), len(stop_times)),
        "stops": (len(stops_f), len(stops)),
        "shapes": (len(shapes_f), len(shapes)),
    }
    return result, stats


def write_gtfs(tables, original_names, output_path):
    """Ecrit un zip GTFS a partir des tables (filtrees ou non)."""
    with zipfile.ZipFile(output_path, "w", zipfile.ZIP_DEFLATED) as zf:
        for name in original_names:
            if not name.endswith(".txt"):
                continue
            rows = tables.get(name, [])
            if not rows:
                continue
            buf = io.StringIO()
            fieldnames = list(rows[0].keys())
            writer = csv.DictWriter(buf, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerows(rows)
            zf.writestr(name, buf.getvalue())
