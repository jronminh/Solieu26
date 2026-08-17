"""
score_tables.py
====================
Cấu hình bucket cho 6 trường dự báo được chấm điểm: tổng lượng mây, độ cao
màn mây (trần), hiện tượng, hướng gió, tốc độ gió, tầm nhìn.

Chỉ chứa dữ liệu (BUCKETS + hằng số NO_CEILING) — không có hàm chấm điểm ở
đây; bộ máy chấm nằm ở module riêng, chỉ import BUCKETS/NO_CEILING từ đây.

Mô hình chung: dự báo viên chọn thẳng 1 bucket (không nhập số); quan trắc là
1 giá trị vô hướng, được quy về dạng so được tùy kind rồi so lệch với bucket
dự báo trong phạm vi tolerance của trường đó.

Vài mốc nghiệp vụ (đơn vị gió/tầm nhìn, mép 6000m/10km) còn chờ xác nhận —
xem TODO.md.

Lược đồ mỗi trường:
  kind        : "linear" | "circular" | "categorical" | "forecast_window"
  unit        : đơn vị của giá trị đã giải (để khỏi lệch đơn vị)
  tolerance   : số bucket lệch vẫn tính đúng. 1 = luật ±1; 0 = phải khớp đúng bucket.
  na          : các giá trị coi là "không chấm" -> scorer BỎ CẶP ở trường này
  source_table: bảng trong bulletin/code_tables.py mà giá trị này giải ra từ đó

  linear thêm : bounds (ngưỡng TRONG, tăng dần; n ngưỡng -> n+1 bucket)
                side ("right": [dưới, trên); "left": (dưới, trên])
  circular thêm: n (số hướng), labels (nhãn từng hướng). Giá trị là CHỈ SỐ hướng
                 0..n-1 (hoặc nhãn), KHÔNG phải độ; ±1 cuộn vòng.
  categorical thêm: groups (mã -> nhóm), ordered (False -> không có trục -> tolerance=0)
  forecast_window thêm: windows [(lo,hi),...] cửa sổ chồng nhau (quan trắc so trực tiếp)
"""

# Sentinel cho trạng thái "không có trần" (trường do_cao_man_may) — là một
# BUCKET (trên cùng), không phải "thiếu số liệu".
NO_CEILING = "không màn"

BUCKETS = {

    # ------------------------------------------------------------------ #
    # 1. TỔNG LƯỢNG MÂY — chấm khác 5 trường kia. Đơn vị: phần bầu trời   #
    #    (0-10).                                                          #
    #                                                                    #
    #    Dự báo viên CHỌN 1 CỬA SỔ (không nhập số): 9 cửa sổ chồng nhau,  #
    #    mỗi cửa rộng 2, bước 1 (idx 0=0-2 ... idx 8=8-10). Quan trắc là  #
    #    một số nguyên 0-10 (không bucket hóa).                           #
    #                                                                    #
    #    ±1 áp cho CỬA SỔ dự báo, không phải cho giá trị: dự báo idx i -> #
    #    dải chấp nhận là hợp của cửa i-1, i, i+1 (kẹp mép ở idx 0 và 8).  #
    #    VD: dự báo "2-4" (idx 2) -> đúng nếu số thực rơi trong [1,5].     #
    #                                                                    #
    #    Chấm bằng is_hit_window(), không dùng bucket_of/is_hit chung —   #
    #    trường này không có bounds/side.                                 #
    # ------------------------------------------------------------------ #
    "tong_luong_may": {
        "kind": "forecast_window",
        "unit": "phần bầu trời (0-10)",
        "source_table": "N_oktas",
        # (lo, hi) mỗi cửa sổ, inclusive hai đầu. Index = lựa chọn dự báo viên.
        "windows": [(0, 2), (1, 3), (2, 4), (3, 5), (4, 6),
                    (5, 7), (6, 8), (7, 9), (8, 10)],
        "tolerance": 1,          # ±1 CỬA SỔ dự báo (không phải ±1 giá trị)
        "value_range": (0, 10),
        "na": ["/"],             # quan trắc che khuất -> bỏ cặp (thực tế hiếm)
    },

    # ------------------------------------------------------------------ #
    # 2. ĐỘ CAO MÀN MÂY (trần) — không lấy thẳng từ mã, cần giải qua      #
    #    solver riêng ra mét. 15 bucket theo thứ tự:                      #
    #    <50 | 50-100 | 100-150 | 150-200 | 200-300 | 300-400 | 400-500 |#
    #    500-600 | 600-1000 | 1000-1500 | 1500-2000 | 2000-2500 |        #
    #    2500-6000 | >6000 | KHÔNG MÀN                                    #
    #                                                                    #
    #    "Không màn" là BUCKET TRÊN CÙNG, kề ">6000" (không phải bỏ cặp)  #
    #    nên ±1 vẫn chạy giữa 2 trạng thái đó.                            #
    #                                                                    #
    #    side="right": giá trị bằng ngưỡng rơi vào bucket TRÊN (khớp      #
    #    "<50", và 6000 m vào ">6000"). Nhiều mốc trùng giá trị thật có   #
    #    thể gặp trong dữ liệu — side quyết định bucket của chúng.        #
    # ------------------------------------------------------------------ #
    "do_cao_man_may": {
        "kind": "linear",
        "unit": "mét",
        "source_table": "hshs_special (qua solver)",
        "needs_solver": True,         # chỉ nhánh quan trắc mới cần giải qua solver
        # 13 ngưỡng -> 14 bucket số (index 0..13); "không màn" = index 14 -> 15 lựa chọn.
        "bounds": [50, 100, 150, 200, 300, 400, 500, 600,
                   1000, 1500, 2000, 2500, 6000],
        "side": "right",
        "tolerance": 1,               # ±1 BUCKET (dù các bucket không chồng nhau)
        # "không màn" là 1 bucket (index cao nhất), không phải bỏ cặp — solver
        # trả sentinel này khi không lớp mây nào đạt ngưỡng trần, kể cả trời quang.
        "no_ceiling": NO_CEILING,
        "na": [None],                 # None = THIẾU số liệu thật (khác "không màn") -> bỏ cặp
        # Quan trắc: số mét, hoặc NO_CEILING nếu không có trần, hoặc None nếu thiếu.
    },

    # ------------------------------------------------------------------ #
    # 3. HIỆN TƯỢNG — 2 TẦNG: MEGA (loại) × SUB (buổi trong ngày).       #
    #                                                                    #
    #    TẦNG MEGA — loại hiện tượng, khớp CHÍNH XÁC 100% (tolerance 0):  #
    #      0 dông, mưa rào                                                #
    #      1 mưa thường, mưa phùn                                         #
    #      2 sương mù                                                     #
    #      3 mù, mù khô                                                   #
    #      4 N_0 (không có hiện tượng / không thuộc 4 nhóm trên)          #
    #                                                                    #
    #    TẦNG SUB — buổi trong ngày, GIỐNG NHAU trong mọi mega, ±1 KẸP   #
    #    MÉP (n=5): 0 tối, 1 đêm, 2 sáng, 3 trưa, 4 chiều. Dự báo cho     #
    #    24 giờ nên đây là DÃY THẲNG — tối và chiều là hai đầu, KHÔNG kề. #
    #                                                                    #
    #    Chấm: MEGA khớp đúng VÀ buổi lệch <= 1 -> đúng.                  #
    # ------------------------------------------------------------------ #
    "hien_tuong": {
        "kind": "phenomenon",           # 2 tầng: mega (exact) × sub (±1 vòng)
        "unit": "mega (loại) × sub (buổi)",
        "source_table": "ww + giờ",
        # --- TẦNG MEGA: khớp chính xác ---
        "mega_buckets": [               # 5 mega theo THỨ TỰ
            "dong_mua_rao",
            "mua_mua_phun",
            "suong_mu",
            "mu_mu_kho",
            "N_0",
        ],
        "mega_labels": {
            "dong_mua_rao": "Dông, mưa rào",
            "mua_mua_phun": "Mưa thường, mưa phùn",
            "suong_mu":     "Sương mù",
            "mu_mu_kho":    "Mù, mù khô",
            "N_0":          "Không có hiện tượng (hoặc không thuộc 4 nhóm trên)",
        },
        "mega_tolerance": 0,            # khớp chính xác 100%
        # Mã ww (2 ký tự) -> mega:
        #   - 13 (chớp không sấm), 18 (tố), 19 (vòi rồng): báo hiệu/đi kèm
        #     dông -> gộp dong_mua_rao.
        #   - 04 (khói), 06 (bụi lơ lửng): giảm tầm nhìn như mù khô -> gộp
        #     mu_mu_kho.
        #   - 66,67 (mưa đông kết), 68,69 (mưa+tuyết), 83-86 (rào lẫn
        #     tuyết/tuyết rào): hiếm gặp VN -> N_0 hết, không tách riêng.
        #   - 20-29 (hiện tượng "giờ trước"): tính như hiện tượng hiện tại,
        #     xếp theo loại, không gộp hết vào N_0.
        #
        # Lưu ý: mã 64/65 và 82 cùng nhãn tiếng Việt "Mưa to" nhưng khác
        # mega-bucket (mưa thường to -> mua_mua_phun; mưa rào dữ dội ->
        # dong_mua_rao). Việc tra "groups" dùng MÃ GỐC làm khóa nên đầu vào
        # phải giữ mã ww, không chỉ nhãn đã dịch, nếu không 2 trường hợp này
        # sẽ không phân biệt được.
        "groups": {
            # --- dong_mua_rao: dông, mưa rào, mưa đá rào, sau dông; chớp/tố/vòi
            #     rồng gộp vào (báo hiệu/đi kèm dông) ---
            **{c: "dong_mua_rao" for c in [
                "13", "17", "18", "19", "25", "27", "29",
                "80", "81", "82", "87", "88", "89", "90",
                "91", "92", "93", "94", "95", "96", "97", "98", "99",
            ]},
            # --- mua_mua_phun: mưa phùn, mưa THƯỜNG (không phải mưa rào) ---
            **{c: "mua_mua_phun" for c in [
                "20", "21",
                "50", "51", "52", "53", "54", "55", "56", "57", "58", "59",
                "60", "61", "62", "63", "64", "65",
            ]},
            # --- suong_mu: sương mù (kể cả mỏng, giờ trước) ---
            **{c: "suong_mu" for c in [
                "11", "12", "28",
                "40", "41", "42", "43", "44", "45", "46", "47", "48", "49",
            ]},
            # --- mu_mu_kho: mù, mù khô, khói, bụi lơ lửng ---
            **{c: "mu_mu_kho" for c in ["04", "05", "06", "10"]},
            # --- N_0: phần còn lại (mây tan/hình thành/không đổi, mưa xa chưa
            #     tới trạm, tuyết/băng/mưa đông kết/hỗn hợp mưa-tuyết hiếm gặp
            #     VN, bụi/lốc bụi/bão bụi-cát/tuyết cuốn) ---
            **{c: "N_0" for c in [
                "00", "01", "02", "03",
                "07", "08", "09",
                "14", "15", "16",
                "22", "23", "24", "26",
                "30", "31", "32", "33", "34", "35", "36", "37", "38", "39",
                "66", "67", "68", "69",
                "70", "71", "72", "73", "74", "75", "76", "77", "78", "79",
                "83", "84", "85", "86",
            ]},
        },
        # --- TẦNG SUB: buổi trong ngày, ±1 kẹp mép ---
        "sub_buckets": ["toi", "dem", "sang", "trua", "chieu"],
        "sub_labels": {
            "toi": "Tối", "dem": "Đêm", "sang": "Sáng",
            "trua": "Trưa", "chieu": "Chiều",
        },
        # Ánh xạ GIỜ quan trắc -> buổi: [giờ bắt đầu, giờ kết thúc). Nghiệp vụ
        # tách rõ tối (19->24) và đêm (0->5) nên không khoảng nào cuộn qua nửa đêm.
        "sub_hours": {
            "toi":   (19, 24),
            "dem":   (0, 5),
            "sang":  (5, 10),
            "trua":  (10, 14),
            "chieu": (14, 19),
        },
        "sub_tolerance": 1,             # ±1 buổi
        "sub_circular": False,          # KHÔNG cuộn vòng: dự báo 24h, tối..chiều là
                                        # một dãy thẳng, tối và chiều là hai đầu, kẹp mép
        "na": [],
    },

    # ------------------------------------------------------------------ #
    # 4. HƯỚNG GIÓ — biến vòng, 16 hướng = 16 bucket.                    #
    #    Index 0 = N, theo chiều kim đồng hồ (0=N,1=NNE,...,15=NNW).      #
    #    Dự báo lẫn quan trắc đều là HƯỚNG rời rạc (0..15 hoặc nhãn),     #
    #    không phải độ. ±1 hướng, cuộn vòng: N (0) kề NNW (15) và NNE(1).#
    #    Ghép cặp với tốc độ gió khi chấm: có/không chấm hướng phụ thuộc  #
    #    tốc độ (<=2 m/s thì bỏ hướng).                                   #
    # ------------------------------------------------------------------ #
    "huong_gio": {
        "kind": "circular",
        "unit": "hướng (16 hướng, 0=N, chiều kim đồng hồ)",
        "source_table": "(dd -> 16 hướng)",
        "n": 16,
        "labels": ["N", "NNE", "NE", "ENE", "E", "ESE", "SE", "SSE",
                   "S", "SSW", "SW", "WSW", "W", "WNW", "NW", "NNW"],
        "tolerance": 1,               # ±1 hướng, cuộn vòng
        "na": [None],                 # VRB / lặng -> hướng không xác định -> bỏ cặp
        # Nếu đầu vào là nhãn ("N", "NNE"...) thì map qua "labels"; nếu là độ
        # thì phải quy về 1 trong 16 hướng trước khi vào đây.
    },

    # ------------------------------------------------------------------ #
    # 5. TỐC ĐỘ GIÓ — cửa sổ chồng nhau như tổng lượng mây. Đơn vị m/s.  #
    #    Cửa rộng 3, bước 1: 0-3,1-4,2-5,...,15-18, cửa cuối "16-21 và    #
    #    kéo dài thêm" -> coi là 16 trở lên. Quan trắc: số 0..16 m/s.     #
    #    Dự báo viên chọn 1 cửa.                                          #
    #                                                                    #
    #    Ghép cặp với hướng gió khi chấm: tốc độ >15 m/s thì bỏ chấm tốc  #
    #    độ; khi được chấm thì dùng ±1 cửa như model chung.               #
    # ------------------------------------------------------------------ #
    "toc_do_gio": {
        "kind": "forecast_window",
        "unit": "m/s",
        "source_table": "(ff trong mã)",
        # cửa rộng 3, bước 1 (lo=0..15) + cửa cuối 16 trở lên. Quan trắc tối
        # đa 16 nên mép trên vô hạn không ảnh hưởng điểm.
        "windows": [(i, i + 3) for i in range(16)] + [(16, float("inf"))],
        "tolerance": 1,          # ±1 cửa (model chung; áp khi tốc độ được chấm)
        "value_range": (0, 16),
        "na": [None],
    },

    # ------------------------------------------------------------------ #
    # 6. TẦM NHÌN — biến thẳng, đơn vị km.                                #
    #    <0.5 | 0.5-1 | 1-1.5 | 1.5-2 | 2-4 | 4-6 | 6-10 | >10           #
    #    Dự báo viên chọn 1 trong 8 bucket; quan trắc là 1 số km -> bucket #
    #    hóa -> so ±1 bucket với bucket dự báo.                          #
    #    side="right": giá trị bằng ngưỡng rơi vào bucket TRÊN (0.5 vào   #
    #    "0.5-1", không vào bucket dưới; 10.0 vào ">10").                #
    # ------------------------------------------------------------------ #
    "tam_nhin": {
        "kind": "linear",
        "unit": "km",
        "source_table": "VV_special",
        # 7 ngưỡng -> 8 bucket: <0.5 | 0.5-1 | 1-1.5 | 1.5-2 | 2-4 | 4-6 | 6-10 | >10
        "bounds": [0.5, 1, 1.5, 2, 4, 6, 10],
        "side": "right",
        "tolerance": 1,
        "na": [None],
    },
}
