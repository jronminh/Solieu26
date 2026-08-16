"""
decode.py
====================
Pure decoding layer: turn one raw "Qt..." bulletin record (a string) into a
nested dict, and one downloaded bulletin file into a list of such dicts.

No file I/O beyond reading the bulletin files themselves, no FTP, no config —
pipeline.py's export step (flatten_record) is what turns this module's output
into CSV rows.
"""

# =============================================================================
# LOOKUP TABLES
# =============================================================================
TABLES = {
    "N_oktas": {
        '/': '/', '0': '0', '1': '1', '2': '3', '3': '4',
        '4': '5', '5': '6', '6': '8', '7': '9', '8': '10', '9': '/'
    },
    "cloud_type": {
        '0': 'Ci', '1': 'Cc', '2': 'Cs', '3': 'Ac', '4': 'As',
        '5': 'Ns', '6': 'Sc', '7': 'St', '8': 'Cu', '9': 'Cb'
    },
    "hshs_special": {
        '00': 30,
        '56': 1800,  '57': 2000,  '58': 2500,  '59': 2700,
        '60': 3000,  '61': 3300,  '62': 3500,  '63': 4000,  '64': 4200,
        '65': 4500,  '66': 4800,  '67': 5000,  '68': 5500,  '69': 5700,
        '70': 6000,  '71': 6300,  '72': 6500,  '73': 7000,  '74': 7200,
        '75': 7500,  '76': 7800,  '77': 8000,  '78': 8500,  '79': 8700,
        '80': 9000,  '81': 10000, '82': 12000, '83': 13000, '84': 15000,
        '85': 17000, '86': 18000, '87': 20000, '88': 21000, '89': 22000,
        '90': '<50', '91': 50,    '92': 100,   '93': 200,   '94': 300,
        '95': 600,   '96': 1000,  '97': 1500,  '98': 2000,
    },
    "ww": {
        '00': 'Không quan sát được mây',   '01': 'Mây tan (mỏng dần)',
        '02': 'Thời tiết không đổi',       '03': 'Mây hình thành (phát triển)',
        '04': 'Khói',                      '05': 'Mù khô',
        '06': 'Bụi lơ lửng',              '07': 'Bụi',
        '08': 'Lốc bụi',                  '09': 'Bão bụi',
        '10': 'Mù',                        '11': 'Sương mù mỏng',
        '12': 'Sương mù mỏng',             '13': 'Chớp',
        '14': 'Mưa xa',                    '15': 'Mưa xa',
        '16': 'Mưa xa',                    '17': 'Dông',
        '18': 'Tố',                        '19': 'Vòi rồng',
        '20': 'Mưa phùn giờ trước',        '21': 'Mưa giờ trước',
        '22': 'Tuyết giờ trước',           '23': 'Mưa lẫn tuyết giờ trước',
        '24': 'Mưa đông kết giờ trước',    '25': 'Mưa rào giờ trước',
        '26': 'Tuyết rào giờ trước',       '27': 'Mưa đá rào giờ trước',
        '28': 'Sương mù giờ trước',        '29': 'Dông giờ trước',
        '30': 'Bão bụi (cát)',             '31': 'Bão bụi (cát)',
        '32': 'Bão bụi (cát)',             '33': 'Bão bụi (cát) mạnh',
        '34': 'Bão bụi (cát) mạnh',       '35': 'Bão bụi (cát) mạnh',
        '36': 'Tuyết cuốn',               '37': 'Tuyết cuốn',
        '38': 'Tuyết cuốn',               '39': 'Tuyết cuốn',
        '40': 'Sương mù',                  '41': 'Sương mù',
        '42': 'Sương mù',                  '43': 'Sương mù',
        '44': 'Sương mù',                  '45': 'Sương mù',
        '46': 'Sương mù',                  '47': 'Sương mù',
        '48': 'Sương mù',                  '49': 'Sương mù',
        '50': 'Mưa phùn',                  '51': 'Mưa phùn',
        '52': 'Mưa phùn',                  '53': 'Mưa phùn',
        '54': 'Mưa phùn',                  '55': 'Mưa phùn',
        '56': 'Mưa phùn',                  '57': 'Mưa phùn',
        '58': 'Mưa phùn',                  '59': 'Mưa phùn',
        '60': 'Mưa nhẹ',                   '61': 'Mưa nhẹ',
        '62': 'Mưa vừa',                   '63': 'Mưa vừa',
        '64': 'Mưa to',                    '65': 'Mưa to',
        '66': 'Mưa đông kết',              '67': 'Mưa đông kết',
        '68': 'Mưa và tuyết',              '69': 'Mưa và tuyết',
        '70': 'Tuyết nhẹ',                 '71': 'Tuyết nhẹ',
        '72': 'Tuyết trung bình',          '73': 'Tuyết trung bình',
        '74': 'Tuyết mạnh',               '75': 'Tuyết mạnh',
        '76': 'Kim nước đá',               '77': 'Tuyết hạt',
        '78': 'Tuyết hình sao',            '79': 'Hạt nước đá',
        '80': 'Mưa rào nhẹ',              '81': 'Mưa rào vừa',
        '82': 'Mưa to',                    '83': 'Mưa rào lẫn tuyết',
        '84': 'Mưa rào lẫn tuyết',        '85': 'Tuyết rào nhẹ',
        '86': 'Tuyết rào mạnh',           '87': 'Mưa đá rào',
        '88': 'Mưa đá rào',               '89': 'Mưa đá rào',
        '90': 'Mưa đá rào',               '91': 'Mưa sau dông',
        '92': 'Mưa sau dông',             '93': 'Mưa đá sau dông',
        '94': 'Mưa đá sau dông',          '95': 'Dông nhẹ và mưa',
        '96': 'Dông nhẹ và mưa',          '97': 'Dông mạnh có mưa',
        '98': 'Dông với bão bụi',         '99': 'Dông mạnh có mưa đá',
    },
    "W1W2": {
        '0': 'Ít mây',              '1': 'Lượng mây thay đổi',
        '2': 'Nhiều mây',           '3': 'Bão cát',
        '4': 'Sương mù',            '5': 'Mưa phùn',
        '6': 'Mưa',                 '7': 'Tuyết',
        '8': 'Mưa rào',             '9': 'Dông',
    },
    "VV_special": {
        '90': '0.0', '91': '0.1', '92': '0.2', '93': '0.5', '94': '1',
        '95': '2',   '96': '4',   '97': '10',  '98': '20',  '99': '50'
    },
}


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


def _hshs_value(code: str, tables: dict):
    try:
        h = int(code)
    except ValueError:
        return None
    if 1 <= h <= 5:
        return h * 30
    if 6 <= h <= 50:
        return round(h * 30 / 50) * 50
    return tables["hshs_special"].get(code)


def _vv_value(vv_code: str, tables: dict):
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


def decode_head(token: str, tables: dict):
    if not token or not token.startswith('k'):
        return None
    return {"iii": token[:3], "VV": _vv_value(token[3:], tables)}


def decode_wind(token: str, tables: dict):
    if not token or len(token) < 5:
        return None
    N = tables["N_oktas"].get(token[0])
    try:
        dd = int(token[1:3]) * 10
        ff = int(token[3:5])
    except ValueError:
        return {"wind_N": N, "wind_dd": None, "wind_ff": None}
    return {"wind_N": N, "wind_dd": dd, "wind_ff": ff}


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
            "cloud_hshs": _hshs_value(token[3:5], tables)}


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


def h_cloud(t, out, tb):
    out.setdefault("cloud", [])
    layer = decode_cloud(t, tb)
    if layer:
        out["cloud"].append(layer)


DISPATCH = {'1': h_temp, '2': h_dew, '7': h_weather, '8': h_cloud}


def decode_indicators(indicators: list, tables: dict) -> dict:
    """Only dispatches indicator groups flatten_record() (pipeline.py) actually
    turns into CSV columns (temperature/dewpoint/weather/cloud) — any other
    group code (e.g. '9'/'5'/'A' supplementary/pressure-tendency/regional
    sections) is ignored, since nothing downstream reads it."""
    out = {"temperature": None, "dewpoint": None, "weather": None}
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
