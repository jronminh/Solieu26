# Feedback — Đặc tả thiết kế lại Solieu26

Đối chiếu `dac_ta_thiet_ke_lai_solieu26.md` với code hiện tại (`main.py`, `dialogs.py`, `viewer.py`, `pipeline/`, `TODO.md`). Phần lớn đặc tả khả thi; các điểm dưới đây cần chốt lại trước khi triển khai.

## 1. Mục 1 — tiền đề sai

Đặc tả nói đổi ô "Máy chủ" từ Entry sang Label chỉ-đọc, nhưng ô này **đã là Label chỉ-đọc** (`main.py:117-135`, qua nhánh else của `info_row()`). Không cần đổi gì. Nên xóa bullet này khỏi đặc tả hoặc ghi rõ "giữ nguyên" để khỏi gây hiểu nhầm là còn việc phải làm.

## 2. Mục 6 — điều kiện ẩn dropdown Trạm đã lỗi thời

Đặc tả bảo ẩn dropdown Trạm trong "Xem điểm chấm" vì "việc ghép đa trạm thật chưa hoàn tất". Theo `TODO.md` (chốt 2026-08-20), việc ghép đa trạm trong `join_forecast_obs()` đã xong — `station_code` trong `score_YYYYMMDD.csv` giờ là trạm thật, không còn là "1 trạm đại diện". Đề nghị sửa đặc tả: thêm dropdown Trạm thay vì ẩn.

## 3. Mục 5 — thiếu quy tắc lưu khi file có nhiều trạm

`forecast_YYYYMMDD.csv` là 1 file/ngày chứa nhiều trạm (mỗi dòng tự khai báo `station_code`). Đặc tả không nói rõ: khi cửa sổ "Dự báo — trạm X" lưu, có giữ lại dòng của các trạm khác đã lưu trước đó trong cùng file không. Nếu không làm rõ, cách lưu ngây thơ (chỉ ghi records của trạm đang sửa) sẽ xóa mất dự báo của các trạm khác. Đề nghị thêm vào mục 5: "Khi lưu, phải đọc file cũ, giữ nguyên dòng của trạm khác, chỉ thay dòng của trạm đang sửa."

## 4. Mục 4 — chưa xử lý trường hợp Trạm = "Tất cả các trạm"

Nút "Dự báo cho trạm/ngày này..." cần 1 trạm cụ thể để đặt tên cửa sổ (`Dự báo — trạm {station}, {ngày}`). Khi Viewer đang lọc "Tất cả các trạm" thì không có trạm cụ thể nào để truyền. Đề nghị chốt 1 trong 2 hướng:
- (a) khóa/ẩn nút này khi Trạm = "Tất cả các trạm", hoặc
- (b) bắt buộc chọn 1 trạm cụ thể trước khi nút khả dụng.

## 5. Ghi chú phụ — file mockup thiếu

File mockup `Redesign Solieu26.dc.html` được nhắc trong đặc tả (dòng 3) nhưng không có trong repo (`reference/` chỉ có `dac_ta_thiet_ke_lai_solieu26.md`, `forecast_bucket_generator.py`, `Bang_cham_huong_gio_16_huong.md`). Nếu còn giữ file này, nên đính kèm cùng đặc tả để đối chiếu chi tiết bố cục/màu sắc thay vì chỉ dựa vào mô tả text.
