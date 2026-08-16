# TODO — Solieu26 (Claude Code cùng duy trì)

File này là danh sách việc cần làm/đang cân nhắc cho dự án, do Claude Code cập
nhật kèm theo các commit liên quan (đánh dấu `[x]` khi xong, thêm mục mới khi
phát sinh trong lúc làm việc). Mục đã xong KHÔNG bị xoá — giữ lại làm nhật ký
ngắn gọn để không phải lục `git log` mỗi lần cần nhớ lại đã làm gì.

## Đang ưu tiên — Viewer ("Xem số liệu")

- [ ] Chuyển state của cửa sổ viewer từ `win._x` (gắn lên `Toplevel`) sang
      `self.x` trong `HistoryViewer` — bỏ tham số `win` khỏi hầu hết method.
      Hợp lý hồi còn nằm trong `App` (tránh rối `self`), nhưng giờ
      `HistoryViewer` là class riêng và chỉ có đúng 1 cửa sổ, nên chuyển hẳn
      sang `self` sẽ tự nhiên hơn — nên làm TRƯỚC khi thêm filter/nút mới.
- [ ] "Mở bằng Excel" đang mở file CSV gốc (chưa lọc trạm/giờ, chưa ẩn cột),
      không phải đúng view đang hiển thị — cân nhắc thêm nút "Xuất CSV đang
      xem" (theo filter + cột hiện tại) thay vì chỉ mở file gốc.
- [ ] Chưa có ô tìm kiếm tự do trong bảng (chỉ lọc được theo trạm/giờ/ngày
      qua dropdown).
- [ ] Không xem được nhiều ngày gộp lại — mỗi `history_YYYYMMDD.csv` là 1
      file riêng, muốn xem xu hướng nhiều ngày phải đổi "Ngày" từng cái một.
- [ ] Dropdown "Ngày" phình dần vô hạn theo thời gian dùng — chưa có cơ chế
      dọn/giới hạn số file `history_*.csv` cũ giữ lại trong thư mục xuất.
- [ ] Hiệu năng render Treeview khi số dòng lớn: `_render_viewer` xoá sạch
      rồi insert lại toàn bộ mỗi lần lọc/sort, chạy đồng bộ trên main thread.
      Chưa là vấn đề ở quy mô hiện tại (1 ngày ~ vài trăm dòng); để ý nếu sau
      này hỗ trợ xem nhiều ngày/nhiều trạm cùng lúc.

## Chương trình riêng — Chấm điểm dự báo (`buckets.py`)

`buckets.py` là bảng bucket + engine chấm điểm (dự báo so với quan trắc) cho 6
trường: tổng lượng mây, độ cao màn mây (trần), hiện tượng, hướng gió, tốc độ
gió, tầm nhìn. Đây là chương trình con tách biệt với phần decode/encode/
pipeline hiện có của Solieu26. Việc cần làm trước khi dùng thật:

> **Cập nhật 2026-08-17**: `buckets.py` đã tách làm 2 file — `score_tables.py`
> (đổi tên từ `buckets.py`, chỉ còn `BUCKETS`/`NO_CEILING`, dữ liệu thuần) và
> `scorer.py` (toàn bộ bộ máy chấm: `bucket_of`/`is_hit_window`/
> `is_hit_scalar`/`score_field`/`score_wind`/`score_phenomenon`/`mega_of`/
> `sub_of_hour`/`solve_ceiling`, `import score_tables`). Các mục CŨ bên dưới
> còn nhắc `buckets.py` là nói về code trước khi tách — đọc tương ứng là
> `score_tables.py`/`scorer.py`, không sửa lại nguyên văn để giữ đúng bối
> cảnh lúc quyết định. Cũng đã có `forecast_bucket_logic.py`/
> `forecast_bucket_generator.py` (micro-database `{start_hour, end_hour,
> data_name, bucket_selected}` + GUI nhập dự báo — xem mục "Dự báo" giai đoạn
> 2 bên dưới) import `score_tables.py`, nên câu "chưa được import ở đâu khác
> trong repo" không còn đúng.

### Pipeline chấm điểm dự kiến — 6 giai đoạn, cấu thành còn thiếu

Bản đồ tổng quan (chi tiết từng mục nằm trong checklist bên dưới):

1. **Quan trắc** — ĐÃ CÓ phần lớn: `csv_pipeline.download_files()` →
   `decode.decode_history()` → CSV `history_*.csv`.
2. **Dự báo** — CHƯA CÓ GÌ. Không có UI cho dự báo viên chọn bucket ở cả 6
   trường, không có khái niệm "dự báo" trong `gui.py`/`dialogs.py`.
3. **Adapter quan trắc → giá trị vô hướng cho `buckets.py`** — 2/6 xong
   (`VV_km`, `wind_N_num`), 4/6 còn thiếu: đổi tên key mây cho
   `solve_ceiling()`, giữ mã `ww` gốc cho hiện tượng, quy đổi độ→16 hướng gió,
   chuẩn hoá đơn vị tốc độ gió. Đây là mảng trống lớn nhất — xem checklist.
4. **Matcher ghép cặp dự báo ↔ quan trắc** (trạm + giờ/buổi) — CHƯA CÓ. Cần
   chốt chính sách: dự báo hiện tượng chọn theo "buổi" (khung nhiều giờ) nhưng
   quan trắc theo giờ lẻ — lấy giờ nào đại diện?
5. **Scorer** (`score_field`/`score_wind`/`score_phenomenon` trong
   `buckets.py`) — ĐÃ XONG VỀ LOGIC, đã dò tay xác nhận đúng qua nhiều lần
   chạy ngẫu nhiên (2026-08-17). Còn thiếu `tests/test_buckets.py` chính thức
   (mới có script ad-hoc ở `/tmp`, không nằm trong repo).
6. **Lưu trữ** `forecasts`/`observations`/`scores` khoá theo trạm+giờ — CHƯA
   CÓ (hiện chỉ có `config.ini` + CSV xuất, không có lớp lưu trữ truy vấn
   qua lại được).

Việc cần làm trước khi dùng thật (checklist chi tiết):

- [x] Gán bảng `hien_tuong["groups"]` (mã ww → mega-nhóm) trong `buckets.py`.
      Phân loại theo nhãn + xác nhận với anh Minh 2026-08-16 (13/18/19 gộp
      dong_mua_rao; 04/06 gộp mu_mu_kho; 66-69/83-86 → N_0; 20-29 "giờ trước"
      tính như hiện tượng hiện tại). Khớp đủ 100/100 mã ww, không trùng/thiếu
      (kiểm bằng script đối chiếu `tables.py["ww"]`).
- [ ] **Phát hiện khi gán groups**: `decode_weather()` (`decode.py:127`) chỉ
      trả NHÃN tiếng Việt của ww, không giữ mã gốc. Mã `64`/`65` ("Mưa to" =
      mưa thường to → mega `mua_mua_phun`) và mã `82` ("Mưa to" = mưa rào dữ
      dội → mega `dong_mua_rao`) có CÙNG NHÃN nhưng KHÁC mega-bucket — nếu bên
      gọi chỉ có nhãn thì không phân biệt được. `mega_of()` trong `buckets.py`
      dùng mã làm khóa nên tự nó đúng; cần sửa `decode_weather()` giữ lại mã
      gốc (vd trả thêm `"ww_code": token[1:3]`) trước khi nối `buckets.py` vào
      pipeline thật.
- [ ] Xác nhận các mốc còn đánh dấu `KIỂM:` trong `buckets.py`: mép 6000m
      (trần), mép 10km (tầm nhìn), đơn vị tốc độ gió/tầm nhìn, cơ sở ngưỡng
      lặng gió (tính theo tốc độ quan trắc hay dự báo).
- [ ] Viết adapter đổi tên key mây cho `solve_ceiling()`: `decode_cloud()`
      trả `{"cloud_C","cloud_Ns","cloud_hshs"}`, còn `solve_ceiling` cần
      `{"type","amount","height"}` — chưa có lớp chuyển đổi nào nối 2 bên.
- [x] Ép `VV` (tầm nhìn) và `wind_N` (tổng lượng mây) thành số cho
      `buckets.py`. Thêm 2 hàm riêng trong `decode.py` — `_vv_km()` và
      `_oktas_number()` — KHÔNG sửa `vv_value()`/`hshs_value()` dùng chung với
      `bulletin_generator.py` (né đúng rủi ro nêu ở mục trước: đổi kiểu trả về
      của 2 hàm đó sẽ đổi chữ hiện trong preview Tkinter). Kết quả: `VV_km`
      (float, mới) nằm CẠNH `VV` (chuỗi, giữ nguyên) trong `decode_head()`;
      `wind_N_num` (int, hoặc `'/'` giữ nguyên nếu trời bị che khuất — đúng
      sentinel `na` mà `buckets.py["tong_luong_may"]` đã khai) nằm CẠNH
      `wind_N` trong `decode_wind()`. `csv_pipeline.flatten_record()` vẫn chỉ
      đọc `VV`/`wind_N` (chuỗi) như cũ nên CSV xuất ra Y HỆT trước — đã kiểm
      lại bằng tay giá trị `visibility_km`/`total_cloud_N` không đổi. Còn
      thiếu: `bucket_of`/`buckets.py` chưa THỰC SỰ dùng `VV_km`/`wind_N_num`
      (chưa nối, xem mục "Nối buckets.py vào pipeline" cuối danh sách).
- [x] Đổi tên `pipeline.py` → `csv_pipeline.py` để phân biệt với 1 pipeline
      CHẤM ĐIỂM sẽ thêm sau (dùng dữ liệu đã ép kiểu ở trên) — cùng lúc với
      việc ép kiểu ở mục ngay trên, theo yêu cầu giữ CSV cũ nguyên vẹn mà vẫn
      rõ ràng đây là 2 việc khác nhau. Đã sửa import ở `gui.py`
      (`import csv_pipeline`), đổi tên `tests/test_pipeline.py` →
      `tests/test_csv_pipeline.py`, và mọi docstring/comment tham chiếu tên
      file cũ (`config.py`, `gui_common.py`, `history_viewer.py`, `decode.py`,
      `bulletin_generator.py`, `tests/conftest.py`, `README.md`).
- [ ] Viết hàm quy đổi hướng gió từ độ (`decode_wind()` trả 0–360°) sang chỉ
      số 1 trong 16 hướng (0–15) mà `huong_gio` trong `buckets.py` cần —
      chưa có hàm này ở đâu trong repo.
- [ ] Chuẩn hoá đơn vị tốc độ gió (`wind_ff`) về m/s thống nhất giữa các
      trạm (decode.py hiện không đảm bảo đơn vị đồng nhất) trước khi đưa
      vào `toc_do_gio`.
- [ ] Thiết kế UI/cấu trúc dữ liệu cho dự báo viên chọn bucket ở cả 6 trường
      — hiện `gui.py`/`dialogs.py` chưa có khái niệm "bucket"/"dự báo"/"chấm
      điểm" nào.
- [ ] Thiết kế kho lưu `forecasts`/`observations`/`scores` khoá theo trạm +
      giờ (SQLite hay khác) — hiện chưa có lớp lưu trữ nào ngoài `config.ini`
      và CSV xuất.
- [ ] Viết matcher ghép cặp dự báo ↔ quan trắc (chính sách ghép trạm/giờ, xử
      lý trường hợp không tìm được cặp khớp).
- [ ] Viết test cho `buckets.py` (`tests/test_buckets.py` — chưa có).
- [ ] Nối `buckets.py` vào pipeline khi các mục trên xong.

## Backlog khác (chưa ưu tiên)

- [x] Chưa có test nào trong repo. `decode.py` giờ đã tách thuần (không I/O
      ngoài đọc file), viết unit test cho các hàm `decode_*`/`flatten_record`
      sẽ rẻ và có giá trị ngay. — Đã thêm `tests/` (pytest, 73 test):
      `test_decode.py`, `test_pipeline.py` (nay là `test_csv_pipeline.py`,
      xem mục đổi tên bên dưới), `test_encode.py`,
      `test_bulletin_generator.py`, cộng `tests/fixtures/qt_files/` (file
      "Qt..." THẬT lấy từ `~/solieu26_dl/data` — 4 file lẻ chọn để phủ ca
      biên: dấu phân cách `=` thay vì `;`, 4 lớp mây, nhiều ngày khác nhau;
      cộng `full_day_20260810/` — trọn 1 ngày 24 file liên tục cho test
      ghép nhiều giờ). Chưa test tầng FTP (`download_files`/`run_pipeline`
      trong `csv_pipeline.py`) — cần mock `ftplib`, để sau nếu cần.
- [x] Nhóm `A` (hướng/khoảng cách/xu thế mây dông Cb quanh trạm) — đã thêm
      `decode_storm()` trong `decode.py` (dispatch qua `DISPATCH['A']`), bảng
      `storm_distance`/`storm_trend` trong `tables.py`, và 3 cột CSV mới
      (`storm_dd_deg`/`storm_distance`/`storm_trend`) trong
      `flatten_record()` (nay ở `csv_pipeline.py`, xem mục đổi tên bên dưới).
      Phát hiện nhờ đối chiếu với `jupyter/decode_universal.ipynb`
      (`decoded_BATHK`, nhóm `A_dd_L_Cg`) ở `E:\Code\Python\decode_universal`
      — cách giải mã cũ có sẵn nhưng chưa từng nối vào dự án Solieu26. Kèm
      test trong `tests/test_decode.py` và `tests/test_pipeline.py` (nay
      `tests/test_csv_pipeline.py`).
- [ ] Nhóm chỉ báo `9`/`5` (dữ liệu bổ sung / xu hướng khí áp 3 giờ) vẫn đang
      bị bỏ qua hoàn toàn khi giải mã (xem `decode.decode_indicators`) — cần
      viết lại phần decode nếu có tính năng sau này cần đến dữ liệu này.
- [ ] Biểu đồ/plot theo thời gian — ý tưởng đã nêu, chưa quyết định phạm vi.

## Đã hoàn thành gần đây

- [x] Bỏ khả năng chạy `core.py` CLI độc lập — chỉ còn chạy qua `gui.py`.
- [x] Module hóa: `core.py` → `config.py` (path/CONFIG/ini) + `decode.py`
      (giải mã thuần) + `core.py` (FTP + xuất CSV + `run_pipeline`);
      `gui.py` → `gui_common.py` (hằng số/helper) + `history_viewer.py`
      (class `HistoryViewer`) + `dialogs.py` (class `SettingsDialog`,
      `AdvancedDialog`) + `gui.py` (class `App`). Dùng class riêng (nhận
      `app` qua constructor), không dùng mixin.
- [x] Dọn Settings: bỏ tuỳ chọn "xoá file sau khi tải xong" và "mở thư mục
      CSV"; "Tự động truy vấn khi khởi động" mặc định bật.
- [x] Dọn thư mục làm việc: bỏ `build/`, `dist/`, `__pycache__/`, `data/` cũ,
      và 2 bản `config.ini` chứa mật khẩu FTP thật còn sót lại ngoài repo.
- [x] Đổi tên `core.py` → `pipeline.py` — tên "core" còn sót từ hồi chưa tách
      module, không còn mô tả đúng vai trò (chỉ còn tầng FTP + xuất CSV +
      `run_pipeline`, không phải "cái gì cũng có" như tên "core" gợi ý nữa).

## Quy ước cập nhật

- Đánh dấu `[x]` và thêm ghi chú ngắn khi hoàn thành một mục.
- Thêm mục mới ngay khi phát sinh trong lúc làm việc (kể cả nếu chưa làm
  liền) — đừng để trôi mất trong hội thoại.
- Không xoá mục đã hoàn thành; nếu một mục không còn phù hợp nữa thì gạch
  chú thích lý do thay vì xoá thẳng.
