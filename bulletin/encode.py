"""
encode.py
====================
Pure encoding layer: the reverse of decode.py — turn human-entered values
into raw "Qt..." bulletin tokens and assemble one record string.

Imports TABLES from code_tables.py (the same tables decode.py decodes with)
so the two modules can't drift out of sync. Where a decode.py table/formula
is NOT a clean bijection (N_oktas, ww, W1W2, cloud_type all map several codes
to the same decoded value; VV and cloud height are piecewise and lossy),
encode.py takes the raw CODE as input rather than trying to invert the
decoded value — callers (e.g. a GUI) should let the user pick the code,
showing decode.py's own output as a live preview instead of pretending the
inverse is unambiguous.

No file I/O, no Tkinter.
"""

from .code_tables import TABLES


def _reverse_table(table: dict) -> dict:
    """value -> key, keeping the FIRST key seen for a repeated value (e.g.
    N_oktas maps both '9' and '/' to '/' — keeping '/' as the reverse is the
    more canonical choice since it comes first in the table)."""
    rev = {}
    for k, v in table.items():
        rev.setdefault(v, k)
    return rev


REV_N_OKTAS    = _reverse_table(TABLES["N_oktas"])
REV_CLOUD_TYPE = _reverse_table(TABLES["cloud_type"])
REV_WW         = _reverse_table(TABLES["ww"])
REV_W1W2       = _reverse_table(TABLES["W1W2"])


# =============================================================================
# TOKEN ENCODERS (each is the reverse of the matching decode_* function)
# =============================================================================

def encode_head(station_code: str, vv_code: str) -> str:
    """station_code: 'kXX' (3 chars — matches common.STATIONS keys and
    decode_tail's station_code). vv_code: raw 2-digit VV code (00-99), NOT
    a km value — decode.vv_value is piecewise/lossy, so there's no single
    correct code for a given distance."""
    if not station_code or not station_code.startswith('k') or len(station_code) != 3:
        raise ValueError(f"mã trạm không hợp lệ: {station_code!r} (cần dạng 'kXX')")
    vv_code = f"{int(vv_code):02d}"
    return f"{station_code}{vv_code}"


def _split_degrees(value: float, int_digits: int):
    d = int(value)
    m = round((value - d) * 60)
    if m == 60:
        d, m = d + 1, 0
    if not (0 <= d < 10 ** int_digits) or not (0 <= m <= 59):
        raise ValueError(f"toạ độ {value} ngoài phạm vi mã hoá được")
    return d, m


def encode_tail(station_code: str, lat: float, lon: float) -> str:
    if not station_code or not station_code.startswith('k') or len(station_code) != 3:
        raise ValueError(f"mã trạm không hợp lệ: {station_code!r} (cần dạng 'kXX')")
    lat_d, lat_m = _split_degrees(lat, 2)
    lon_d, lon_m = _split_degrees(lon, 3)
    return f"{station_code}{lat_d:02d}{lat_m:02d}{lon_d:03d}{lon_m:02d}"


def encode_total_cloud_wind(total_cloud_N_code: str, dd_deg: float, ff: float) -> str:
    """total_cloud_N_code: raw digit/'/' as used in TABLES['N_oktas'] (the
    CODE, not the decoded value). dd_deg: wind direction in whole degrees
    (rounded to the nearest 10, since the token only stores tens). One
    bulletin token combines total cloud amount + wind, so this encodes all
    three together — the reverse of decode.py's decode_total_cloud() +
    decode_wind(), which split back into two dicts."""
    dd_code = round(dd_deg / 10) % 100
    ff_code = round(ff) % 100
    return f"{total_cloud_N_code}{dd_code:02d}{ff_code:02d}"


def _encode_temp_like(indicator: str, value_c: float) -> str:
    sign = '1' if value_c < 0 else '0'
    ttt = round(abs(value_c) * 10)
    if ttt > 999:
        raise ValueError(f"nhiệt độ {value_c}°C ngoài phạm vi mã hoá được")
    return f"{indicator}{sign}{ttt:03d}"


def encode_temp(value_c: float) -> str:
    return _encode_temp_like('1', value_c)


def encode_dewpoint(value_c: float) -> str:
    return _encode_temp_like('2', value_c)


def encode_weather(ww_code: str, w1_code: str, w2_code: str) -> str:
    return f"7{int(ww_code):02d}{w1_code}{w2_code}"


def encode_cloud(N_oktas_code: str, cloud_type_code: str, hshs_code: str) -> str:
    return f"8{N_oktas_code}{cloud_type_code}{int(hshs_code):02d}"


def encode_pressure(mmhg: float) -> str:
    """Reverse of decode_pressure: the token IS the pressure in mmHg (to one
    decimal) — decode_pressure just relabels it pressure_raw and additionally
    converts to pressure_hpa = raw * 4/3. Token is 4 digits (3 before + 1
    after the decimal point), so only mmhg in [700.0, 800.0) round-trips."""
    raw_x10 = round(mmhg * 10)          # round on the tenths digit FIRST so a
    whole, tenth = divmod(raw_x10, 10)  # 799.99->8000 carry lands in `whole`, not lost
    if not (700 <= whole <= 799):
        raise ValueError(
            f"áp suất {mmhg} mmHg ngoài phạm vi mã hoá được (cần 700.0-799.9 mmHg)")
    return f"{whole:03d}{tenth}"


def encode_name(name: str) -> str:
    """Reverse of decode_name: prefixes the first word with 't' (the marker
    split_record uses to find where the name block starts)."""
    words = name.split()
    if not words:
        return ""
    words[0] = "t" + words[0]
    return " ".join(words)


# =============================================================================
# FULL RECORD ASSEMBLY
# =============================================================================

def encode_record(*, station_code: str, lat: float, lon: float, vv_code: str,
                   total_cloud_N_code: str, wind_dd: float, wind_ff: float,
                   temp_c: float = None, dew_c: float = None,
                   ww_code: str = None, w1_code: str = "/", w2_code: str = "/",
                   clouds: list = None, pressure_mmhg: float = None,
                   station_name: str = "") -> str:
    """Assemble one full raw record string in the token order split_record()
    expects: head wind [temp] [dew] [weather] [cloud...] [pressure] name tail.

    `clouds` is a list of {"N": code, "C": code, "hshs": code} dicts, one per
    reported layer (decode.py keeps up to however many '8...' tokens appear).
    """
    tokens = [encode_head(station_code, vv_code),
              encode_total_cloud_wind(total_cloud_N_code, wind_dd, wind_ff)]
    if temp_c is not None:
        tokens.append(encode_temp(temp_c))
    if dew_c is not None:
        tokens.append(encode_dewpoint(dew_c))
    if ww_code is not None:
        tokens.append(encode_weather(ww_code, w1_code, w2_code))
    for cloud in (clouds or []):
        tokens.append(encode_cloud(cloud["N"], cloud["C"], cloud["hshs"]))
    if pressure_mmhg is not None:
        tokens.append(encode_pressure(pressure_mmhg))
    if station_name:
        tokens.append(encode_name(station_name))
    tokens.append(encode_tail(station_code, lat, lon))
    return " ".join(tokens)
