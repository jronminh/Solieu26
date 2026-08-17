"""
code_tables.py
====================
Lookup tables shared by decode.py (decoding) and encode.py (the reverse) —
the single source of truth for every code -> human-readable-value mapping
in the "Qt..." bulletin format. Kept in its own module (rather than living
in decode.py) so encode.py doesn't have to import decode.py just to reach
the tables, and so the two stay in sync by construction.

No logic here — just data.
"""

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
    # Nhóm bổ sung "A" + dd + L + Cg: hướng/khoảng cách/xu thế mây dông (Cb)
    # quan sát quanh trạm — không phải hiện tượng tại trạm. 2 mã dùng chung
    # 1 nhãn khoảng cách (0/5, 1/6, 2/7, 3/8, 4/9).
    "storm_distance": {
        '0': '<10km',    '5': '<10km',
        '1': '10-20km',  '6': '10-20km',
        '2': '20-50km',  '7': '20-50km',
        '3': '50-100km', '8': '50-100km',
        '4': '>100km',   '9': '>100km',
    },
    "storm_trend": {
        '0': 'Đang tan',            '1': 'Phát triển chậm',
        '2': 'Phát triển rõ rệt',   '3': 'Phát triển dữ dội',
    },
}
