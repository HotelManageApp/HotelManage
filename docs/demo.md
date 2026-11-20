# Chạy thử toàn bộ hệ thống trên một máy (demo)

Dành cho người muốn xem sản phẩm mà không cần cài Python, Node hay Flutter. Chỉ cần **Docker Desktop**.
Bản demo chạy trên máy của bạn, dữ liệu mẫu, không gửi gì ra ngoài (trừ khi bạn tự bật AI thật ở bước 5).

## 1. Cài đặt (một lần)

1. Cài **Docker Desktop**: https://www.docker.com/products/docker-desktop/ → mở lên, chờ biểu tượng cá voi báo "running".
   Cần trống ~6 GB ổ đĩa và nên có ≥ 8 GB RAM.
2. Lấy mã nguồn — một trong hai cách:
   - Có Git: `git clone -b feature/HMA-61-demo-kit https://github.com/HotelManageApp/HotelManage.git`
   - Không có Git: tải ZIP
     https://github.com/HotelManageApp/HotelManage/archive/refs/heads/feature/HMA-61-demo-kit.zip rồi giải nén.

## 2. Chạy

Mở terminal (Windows: PowerShell) **trong thư mục mã nguồn** (thư mục có file `docker-compose.demo.yml`):

```bash
docker compose -f docker-compose.demo.yml up -d --build
```

Lần đầu mất khoảng 5–10 phút (tải và build). Xong khi lệnh trả về và các dịch vụ báo `Started`. Kiểm tra:

| Mở | Thấy |
|---|---|
| http://localhost:3000 | Trang đăng nhập "Quản trị khách sạn" |
| http://localhost:8010/health | `{"status":"ok","db":"ok","version":"demo"}` |

Nếu báo cổng đã bị dùng (3000, 8010, 8011): tắt chương trình đang dùng cổng đó rồi chạy lại.

## 3. Web quản trị — 3 vai trò

Mở http://localhost:3000. Tài khoản (mật khẩu chung `Demo@12345`):

| Vai trò | Email |
|---|---|
| Lễ tân | `reception@dev.local` |
| Bếp | `kitchen@dev.local` |
| Buồng phòng | `housekeeping@dev.local` |

Mỗi vai trò mở trên **một trình duyệt riêng** (VD Chrome, Edge, cửa sổ ẩn danh) — một trình duyệt chỉ giữ một phiên.
Dữ liệu mẫu: 6 phòng trống, 7 món, thông tin khách sạn và địa điểm lân cận; bếp mở cả ngày.

## 4. App khách (Android)

App là file APK (bạn của bạn gửi kèm: `hotel-guest-emulator.apk`). Cách dễ nhất là **máy ảo Android**:

1. Cài **Android Studio** → *Device Manager* → tạo một máy ảo (Pixel bất kỳ, Android 14+) → bật máy ảo.
2. Kéo thả file `hotel-guest-emulator.apk` vào cửa sổ máy ảo để cài.
3. Mở app → nhập mã phòng (xem bước 6). App gọi máy tính qua địa chỉ `10.0.2.2` — không cần cấu hình gì.

Điện thoại thật: cần build APK trỏ tới IP máy tính trong mạng Wi-Fi (`flutter build apk --debug
--dart-define=API_BASE_URL=http://<IP>:8010 --dart-define=AI_BASE_URL=http://<IP>:8011 --dart-define=APP_ENV=dev`
trong thư mục `mobile-app/`, cần Flutter) và mở cổng 8010/8011 trên tường lửa.

Không có thông báo đẩy trong bản demo (cần Firebase); app tự cập nhật mỗi 15 giây hoặc khi kéo xuống.

## 5. (Tùy chọn) Chatbot với AI thật

Mặc định chatbot dùng AI giả (một câu trả lời cố định). Có khóa Gemini (https://aistudio.google.com → *Get API key*):

```powershell
$env:LLM_PROVIDER="gemini"; $env:GEMINI_API_KEY="<khóa>"; docker compose -f docker-compose.demo.yml up -d ai-service
```

(macOS/Linux: `LLM_PROVIDER=gemini GEMINI_API_KEY=<khóa> docker compose -f docker-compose.demo.yml up -d ai-service`.)
Câu hỏi của khách sẽ được gửi tới nhà cung cấp AI đó.

## 6. Thử nhanh 10 phút

1. **Lễ tân:** Sơ đồ phòng → phòng 101 → **Check-in** (tên, ngày trả phòng, tiền phòng) → phiếu có mã 8 ký tự + QR.
2. **App:** nhập mã → vào màn chính "Phòng 101".
3. **App:** Đặt đồ ăn → 2 Phở bò + 1 Nước cam → Đặt đơn. **Bếp** thấy đơn ngay → Nhận → Bắt đầu nấu → Mang đi giao →
   Đã giao xong; app thấy trạng thái đổi.
4. **App:** Dọn phòng & đồ dùng → xin 2 khăn tắm. **Buồng phòng** → Nhận việc → Bắt đầu → Hoàn tất.
5. **App:** Hỏi Concierge (AI thật): "Mấy giờ ăn sáng?", "Cho tôi 1 phở bò" → thẻ xác nhận → Xác nhận.
6. **App:** Trả phòng nhanh → Xác nhận. **Lễ tân** → tab Trả phòng → thêm phụ phí → Chốt hóa đơn → In → chọn Tiền mặt →
   Hoàn tất. App về màn chào kèm lời cảm ơn; phòng 101 chuyển "Chờ dọn".

Kịch bản đầy đủ từng tính năng: `docs/user-guide-*.md` (theo vai trò).

## 7. Dừng / làm lại

```bash
docker compose -f docker-compose.demo.yml down        # dừng, giữ dữ liệu
docker compose -f docker-compose.demo.yml down -v     # dừng và xóa sạch dữ liệu demo
```

Chạy lại bước 2 để bật (sau `down -v` sẽ có lại dữ liệu mẫu ban đầu).

> Bản demo dùng giá trị cấu hình công khai, **không** dùng cho khách sạn thật. Triển khai thật: `docs/deploy.md`.
