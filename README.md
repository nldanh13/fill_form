# Trợ lý điền phiếu hàng tháng

Web app cục bộ quản lý và tự động điền Google Forms đánh giá kỹ thuật điều dưỡng.

## Chạy bằng npm

Mở terminal tại thư mục dự án và chạy:

```bash
npm install
npm start
```

`npm start` tự khởi động dịch vụ Python, giao diện và mở `http://127.0.0.1:3000`. Trong lần đầu, chương trình tự tạo môi trường Python, cài Playwright và Chromium. Các lần sau chỉ cần `npm start`.

Trên Windows, bạn vẫn có thể nhấp đúp `local_app/start_windows.bat` nếu không muốn mở terminal.

## Thành phần

- Giao diện React (`app/`, `components/ui/`): tổng quan theo tháng, chạy tác vụ, tiến độ, lịch sử, form và nhân sự. Gọi API tại `http://127.0.0.1:8765`.
- Dịch vụ Python (`local_app/server.py`, `local_app/worker.py`, `local_app/db.py`): SQLite, hàng đợi tác vụ, dừng an toàn, chạy thử và Playwright.
- Dữ liệu nguồn (form, danh sách nhân sự, ngân hàng nhận xét...): `local_app/source/`.
- Cơ sở dữ liệu, log, hồ sơ trình duyệt: tự tạo tại `local_app/data/` khi chạy lần đầu — không cần commit hay gửi đi.

Ứng dụng chỉ lắng nghe tại `127.0.0.1`. Hồ sơ Chromium, database, log và `local_app/.venv` đều bị loại khỏi Git và khỏi zip đóng gói.

## Đóng gói bản sạch để gửi đi

```bash
npm run clean
```

Lệnh này tạo file `dist-clean/tro-ly-dien-phieu-clean-<thời-điểm>.zip` chỉ chứa mã nguồn và dữ liệu cấu hình cần thiết — tự động loại bỏ `node_modules`, cache build, `.venv`, hồ sơ trình duyệt, database/log runtime.
