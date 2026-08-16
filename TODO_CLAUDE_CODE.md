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

## Backlog khác (chưa ưu tiên)

- [x] Chưa có test nào trong repo. `decode.py` giờ đã tách thuần (không I/O
      ngoài đọc file), viết unit test cho các hàm `decode_*`/`flatten_record`
      sẽ rẻ và có giá trị ngay. — Đã thêm `tests/` (pytest, 73 test):
      `test_decode.py`, `test_pipeline.py`, `test_encode.py`,
      `test_bulletin_generator.py`, cộng `tests/fixtures/qt_files/` (file
      "Qt..." THẬT lấy từ `~/solieu26_dl/data` — 4 file lẻ chọn để phủ ca
      biên: dấu phân cách `=` thay vì `;`, 4 lớp mây, nhiều ngày khác nhau;
      cộng `full_day_20260810/` — trọn 1 ngày 24 file liên tục cho test
      ghép nhiều giờ). Chưa test tầng FTP (`download_files`/`run_pipeline`
      trong pipeline.py) — cần mock `ftplib`, để sau nếu cần.
- [ ] Nhóm chỉ báo `9`/`5`/`A` (dữ liệu bổ sung / xu hướng khí áp 3 giờ /
      mục vùng) đang bị bỏ qua hoàn toàn khi giải mã (xem
      `decode.decode_indicators`) — cần viết lại phần decode nếu có tính
      năng sau này cần đến dữ liệu này.
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
