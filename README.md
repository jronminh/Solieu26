# Solieu26

Công cụ desktop (Tkinter, Windows/Linux) để **tải và tra cứu số liệu quan trắc khí tượng** từ FTP, cùng một công cụ phụ để **sinh dữ liệu điện báo mẫu** phục vụ kiểm thử.

## Hai công cụ trong repo

### `main.py` — Tải & xem số liệu
- Tải file điện báo dạng `Qt...` từ FTP theo trạm/khoảng thời gian, giải mã, xuất ra CSV theo ngày (`history_YYYYMMDD.csv`).
- Xem lại số liệu đã tải, lọc theo trạm/ngày/giờ, trong bảng ngay trong ứng dụng.
- Có thể tự chạy định kỳ (auto-query timer), lưu cấu hình vào `config.ini`.

Chạy:
```bash
python main.py [đường dẫn config.ini]
```

### `bulletin_generator.py` — Sinh điện báo mẫu
Công cụ độc lập, không đụng tới FTP hay cấu hình của `main.py`. Nhập bảng "Thời gian / Trường dữ liệu / Giá trị" cho từng trạm, công cụ tự merge theo giờ và sinh ra các bản ghi `Qt...` hợp lệ — dùng để kiểm thử `bulletin/decode.py`/`pipeline/decode.py` mà không cần tải thật từ FTP.

Chạy:
```bash
python -m bulletin.bulletin_generator
```

## Cấu trúc mã nguồn

| File | Vai trò |
|---|---|
| `main.py` | Điểm vào GUI chính, class `App` (cửa sổ, luồng worker, log, timer) |
| `dialogs.py` | Các hộp thoại độc lập: `SettingsDialog` (Thiết lập), `AdvancedDialog` (Tải số liệu) |
| `viewer.py` | Cửa sổ "Xem số liệu" |
| `common.py` | Hằng số/tiện ích dùng chung cho UI |
| `runner.py` | Chạy 1 lượt pipeline (fetch + decode) trên worker thread, poll kết quả về UI |
| `auto_query.py` | Timer "Tự động truy vấn" |
| `pipeline/fetch.py` | Tải file `Qt...` qua FTP |
| `pipeline/decode.py` | Giải mã các file đã tải, xuất CSV theo ngày |
| `pipeline/obs.py`, `pipeline/forecast.py`, `pipeline/scoring.py` | Adapter quan trắc/dự báo + chấm điểm cho khối `scoring/` |
| `bulletin/decode.py` | Giải mã một bản ghi `Qt...` thành dict (thuần, không I/O ngoài đọc file) |
| `bulletin/encode.py` | Chiều ngược lại của `bulletin/decode.py` — dựng bản ghi `Qt...` từ giá trị |
| `bulletin/code_tables.py` | Bảng tra cứu mã → giá trị, dùng chung bởi `bulletin/decode.py`/`bulletin/encode.py` |
| `bulletin/bulletin_generator.py` | Công cụ Tk độc lập sinh điện báo mẫu (dùng `bulletin/encode.py`/`bulletin/decode.py`) |
| `utils/config_utils.py` | Đường dẫn, hằng số FTP, đọc/ghi `config.ini` |
| `make_icon.py` | Sinh `icon.ico` cho bản build .exe |
| `version_info.txt` | Metadata cho bản build PyInstaller (`Solieu26.exe`) |

## Yêu cầu

- Python 3.9+ (chỉ dùng thư viện chuẩn: `tkinter`, `ftplib`, `csv`, `configparser`...)
- Không cần cài thêm gói ngoài để chạy `main.py`/`bulletin/bulletin_generator.py`

## Kiểm thử

```bash
pip install pytest
pytest
```

168 test trong `tests/` phủ `bulletin/`, `pipeline/`, `scoring/`, dùng file `Qt...` mẫu thật trong `tests/fixtures/`.

## Phiên bản

Xem [tags](../../tags) `v1.0`–`v4.0` cho các mốc lớn của dự án (đổi tên, tái kiến trúc module, thêm công cụ sinh điện báo, hoàn thiện bulletin_generator + bộ test).

## Tác giả

congminh9981 (congminh9981@gmail.com) — Claude (Anthropic), đồng tác giả.

## License

[MIT](LICENSE)
