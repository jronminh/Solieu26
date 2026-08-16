"""
decode.py
====================
Pure decoding layer: turn one raw "Qt..." bulletin record (a string) into a
nested dict, and one downloaded bulletin file into a list of such dicts.

No file I/O beyond reading the bulletin files themselves, no FTP, no config —
csv_pipeline.py's export step (flatten_record) is what turns this module's
output into CSV rows.

Lookup tables (code -> human-readable value) live in tables.py, not here —
that lets encode.py (the reverse, used by bulletin_generator.py) share the
same tables without importing this whole module.
"""

from tables import TABLES


# =============================================================================
# DECODING
# =============================================================================

def is_pressure_token(t: str) -> bool:
    return len(t) == 4 and t.isdigit() and t.startswith('7')


def split_record(record: str) -> dict:
    tokens = record.split()
    if not tokens:
        return {"head": None, "wind": None, "indicators": [],
                "pressure": None, "name": [], "tail": None}

    n = len(tokens)
    tail = tokens[-1]
    name_start = next((i for i, t in enumerate(tokens) if t.startswith('t')), n - 1)
    name = tokens[name_start:n - 1]

    if tokens[0].startswith('k'):
        head = tokens[0]
        wind = tokens[1] if n > 1 else None
        block_start = 2
    else:
        head = wind = None
        block_start = name_start

    middle = tokens[block_start:name_start]

    pressure = None
    indicators = list(middle)
    for j in range(len(middle) - 1, -1, -1):
        if is_pressure_token(middle[j]):
            pressure = middle[j]
            indicators = middle[:j] + middle[j + 1:]
            break

    return {"head": head, "wind": wind, "indicators": indicators,
            "pressure": pressure, "name": name, "tail": tail}


def _temp_value(token: str):
    if len(token) < 5 or token[0] not in ('1', '2') or token[1] not in ('0', '1'):
        return None
    s = f"{token[2:4]}.{token[4]}"
    if token[1] == '1':
        s = f"-{s}"
    try:
        return float(s)
    except ValueError:
        return None


def hshs_value(code: str, tables: dict):
    """Public: also used by bulletin_generator.py for a live height preview
    while the user types a cloud-base code."""
    try:
        h = int(code)
    except ValueError:
        return None
    if 1 <= h <= 5:
        return h * 30
    if 6 <= h <= 50:
        return round(h * 30 / 50) * 50
    return tables["hshs_special"].get(code)


def vv_value(vv_code: str, tables: dict):
    """Public: also used by bulletin_generator.py for a live visibility
    preview while the user types a VV code."""
    if len(vv_code) < 2:
        return None
    try:
        vv = int(vv_code)
    except ValueError:
        return None
    if vv < 51:
        return f"{vv_code[0]}.{vv_code[1]}"
    if vv <= 55:
        return None
    if vv <= 80:
        return str(vv - 50)
    if vv <= 89:
        return str(vv - 40)
    return tables["VV_special"].get(vv_code)


def _vv_km(vv: str):
    """Coerce vv_value()'s display string (e.g. '3.0', '8') into a float km —
    buckets.py's tam_nhin field needs a number, not a string. Kept separate
    from vv_value() itself (rather than changing its return type) since
    vv_value() is also used by bulletin_generator.py for a live text preview;
    changing its type there would be a behavior change on unrelated UI."""
    if vv is None:
        return None
    try:
        return float(vv)
    except (ValueError, TypeError):
        return None


def _oktas_number(coded: str):
    """Coerce an N_oktas-table value (e.g. '10', '8', or the obscured-sky
    sentinel '/') into an int 0-10 — buckets.py's tong_luong_may field needs a
    number, not a string. '/' is passed through unchanged: it's already the
    exact sentinel buckets.py's "na" list checks for, so bucket_of()/
    is_hit_window() can bỏ cặp on it same as before. Kept separate from
    decode_wind()/decode_cloud()'s existing 'wind_N'/'cloud_Ns' string (rather
    than changing their type) since those feed bulletin_generator.py's live
    preview text too."""
    if coded is None or coded == "/":
        return coded
    try:
        return int(coded)
    except (ValueError, TypeError):
        return None


def decode_head(token: str, tables: dict):
    if not token or not token.startswith('k'):
        return None
    vv = vv_value(token[3:], tables)
    return {"iii": token[:3], "VV": vv, "VV_km": _vv_km(vv)}


def decode_wind(token: str, tables: dict):
    if not token or len(token) < 5:
        return None
    N = tables["N_oktas"].get(token[0])
    N_num = _oktas_number(N)
    try:
        dd = int(token[1:3]) * 10
        ff = int(token[3:5])
    except ValueError:
        return {"wind_N": N, "wind_N_num": N_num, "wind_dd": None, "wind_ff": None}
    return {"wind_N": N, "wind_N_num": N_num, "wind_dd": dd, "wind_ff": ff}


def decode_weather(token: str, tables: dict):
    if len(token) < 5:
        return None
    return {"ww": tables["ww"].get(token[1:3]),
            "W1": tables["W1W2"].get(token[3]),
            "W2": tables["W1W2"].get(token[4])}


def decode_cloud(token: str, tables: dict):
    if len(token) < 5:
        return None
    return {"cloud_Ns": tables["N_oktas"].get(token[1]),
            "cloud_C":  tables["cloud_type"].get(token[2]),
            "cloud_hshs": hshs_value(token[3:5], tables)}


def decode_storm(token: str, tables: dict):
    """A + dd + L + Cg: hướng/khoảng cách/xu thế mây dông (Cb) quan sát quanh
    trạm (không phải hiện tượng tại trạm) — vd 'A1411' -> hướng 140°, cách
    10-20km, đang phát triển chậm."""
    if len(token) < 5:
        return None
    try:
        dd = int(token[1:3]) * 10
    except ValueError:
        dd = None
    return {"storm_dd": dd,
            "storm_L":  tables["storm_distance"].get(token[3]),
            "storm_Cg": tables["storm_trend"].get(token[4])}


def decode_pressure(token: str):
    if not token or len(token) != 4:
        return None
    try:
        raw = float(f"{token[0:3]}.{token[3]}")
        return {"pressure_raw": raw, "pressure_hpa": round(raw * 4 / 3, 1)}
    except ValueError:
        return None


def decode_name(name_tokens: list):
    if not name_tokens:
        return None
    return ' '.join(name_tokens)[1:]


def decode_tail(token: str):
    """
    kXX + DDMM + DDDMM → {station_code, lat, lon}.

    Coordinates in the bulletin are DEGREES-MINUTES (DDMM), NOT decimal. We
    convert straight to decimal degrees (dd + mm/60) so the lat/lon columns are
    directly usable — ready for mapping / distance calculations without error.
    """
    if not token or not token.startswith('k') or len(token) != 12:
        return None
    try:
        lat_d, lat_m = int(token[3:5]),  int(token[5:7])
        lon_d, lon_m = int(token[7:10]), int(token[10:12])
        return {"station_code": token[0:3],
                "lat": round(lat_d + lat_m / 60, 4),
                "lon": round(lon_d + lon_m / 60, 4)}
    except ValueError:
        return None


def h_temp(t, out, tb):    out["temperature"] = _temp_value(t)
def h_dew(t, out, tb):     out["dewpoint"]    = _temp_value(t)
def h_weather(t, out, tb): out["weather"]     = decode_weather(t, tb)
def h_storm(t, out, tb):   out["storm"]       = decode_storm(t, tb)


def h_cloud(t, out, tb):
    out.setdefault("cloud", [])
    layer = decode_cloud(t, tb)
    if layer:
        out["cloud"].append(layer)


DISPATCH = {'1': h_temp, '2': h_dew, '7': h_weather, '8': h_cloud, 'A': h_storm}


def decode_indicators(indicators: list, tables: dict) -> dict:
    """Only dispatches indicator groups flatten_record() (csv_pipeline.py) actually
    turns into CSV columns (temperature/dewpoint/weather/cloud/storm) — any
    other group code (e.g. '9'/'5' supplementary/pressure-tendency sections)
    is ignored, since nothing downstream reads it."""
    out = {"temperature": None, "dewpoint": None, "weather": None, "storm": None}
    for t in indicators:
        if not t:
            continue
        h = DISPATCH.get(t[0])
        if h:
            h(t, out, tables)
    return out


def decode_record(record: str, tables: dict = TABLES) -> dict:
    p = split_record(record)
    out = {"raw": record}
    out["head"]     = decode_head(p["head"], tables) if p["head"] else None
    out["wind"]     = decode_wind(p["wind"], tables) if p["wind"] else None
    out.update(decode_indicators(p["indicators"], tables))
    out["pressure"] = decode_pressure(p["pressure"]) if p["pressure"] else None
    out["station"]  = decode_name(p["name"])
    out["location"] = decode_tail(p["tail"])
    return out


# =============================================================================
# BULLETIN FILES → DECODED RECORDS
# =============================================================================

def get_qt_data(file_path: str) -> list:
    with open(file_path, 'r', encoding='utf-8') as f:
        data = f.read()
    if not data:
        return []
    sep = ';' if ';' in data else '='
    return data.split(sep)[:-1]


def decode_qt_file(file_path: str, tables: dict = TABLES) -> list:
    records = get_qt_data(file_path)
    results = []
    for record in records:
        try:
            results.append(decode_record(record, tables))
        except Exception as e:
            results.append({"error": str(e), "raw": record})
    return results


def decode_history(local_files: list) -> list:
    """
    Decode every downloaded file and keep EVERY station's record (not just one) —
    the full day's station × hour matrix. Station filtering happens later, in the
    CSV viewer, not here: the FTP download is already not station-specific (each
    hourly file bundles every station), so there is nothing to gain by filtering
    before export.
    """
    results = []
    for file_path in sorted(local_files):
        for record in decode_qt_file(file_path):
            if record.get("location"):
                results.append({"file": file_path, "data": record})
    return results
