# Changelog

Định dạng theo [Keep a Changelog](https://keepachangelog.com/vi/1.1.0/); phiên bản theo SemVer.

## [1.0.0] — chờ phát hành (release candidate: `feature/HMA-58-release-prep`)

Bản đầu tiên của Room Service & Housekeeping App + AI Concierge: app khách Android, Web quản trị 3 vai trò, backend-api,
ai-service. Kế hoạch đưa lên `main`: `docs/release-1.0.0.md`.

### Thêm mới

**Đăng nhập & mã phòng (stay-access, staff-auth)**
- Lễ tân check-in sinh mã phòng ngẫu nhiên 8 ký tự + QR cho từng kỳ lưu trú, in phiếu nhận phòng khổ K80; DB chỉ lưu hash;
  cấp lại mã một chạm.
- App đổi mã lấy `stay_session_token` (JWT có `stay_id`, `room_id`, `jti`, hạn theo ngày trả phòng); check-out, trả phòng nhanh,
  cấp lại mã thu hồi token ngay (`401`).
- Rate limit đổi mã: 5 lần/phút/IP, khóa 15 phút sau 10 lần sai/giờ/thiết bị.
- Nhân viên đăng nhập email + mật khẩu (Argon2), access token ngắn hạn + refresh cookie `HttpOnly; Secure; SameSite=Strict`;
  RBAC `RECEPTION` / `KITCHEN` / `HOUSEKEEPING` kiểm tra ở backend cho mọi route; CLI quản trị tài khoản.

**Đặt đồ ăn (room-service)**
- Menu song ngữ, bật/tắt món, giờ phục vụ, tạm ngừng nhận đơn; giỏ hàng và đặt món trên app (Idempotency-Key).
- Vòng đời đơn `PENDING → CONFIRMED → PREPARING → DELIVERING → COMPLETED` / `CANCELLED`; giá chốt lúc đặt; tối đa 5 đơn chờ.
- Web Bếp: hàng đợi realtime, âm báo; Web Lễ tân: tổng hợp đơn, hủy có lý do; nhắc đơn chờ quá 10 phút.

**Buồng phòng (housekeeping)**
- Khách gọi dọn phòng / thêm đồ dùng, chọn giờ, "Không làm phiền"; mỗi stay tối đa 1 yêu cầu dọn đang mở.
- Web Buồng phòng nhận việc → đang làm → xong; tự tạo việc dọn phòng trả khi stay đóng; sơ đồ phòng có trạng thái dọn.

**Thông báo (notifications)**
- Outbox + worker gửi FCM HTTP v1 sau khi commit (retry, xóa token hỏng), không chứa dữ liệu nhạy cảm; lời cảm ơn khi trả phòng.
- Web nhận cập nhật realtime qua SSE theo kênh vai trò; app tự đồng bộ 15 s khi push trễ.

**Trả phòng nhanh (express-checkout)**
- Khách xem tạm tính, chấm sao, gửi yêu cầu; Lễ tân thêm phụ phí/giảm giá, chốt hóa đơn (khóa khi còn đơn mở),
  in hóa đơn K80, chọn hình thức thanh toán, hoàn tất (đóng stay, thu hồi phiên, phòng chờ dọn) hoặc từ chối có lý do.
- Hóa đơn tại quầy cho mọi stay; check-out tại quầy bị chặn khi có yêu cầu trả phòng nhanh đang mở.

**AI Concierge (concierge-guide, concierge-actions)**
- Knowledge Base + địa điểm gần đó (tìm không dấu), Lễ tân quản lý trên Web, thử câu hỏi.
- Chatbot Gemini/OpenAI với 6 tool: hướng dẫn, menu, đặt món, dọn phòng, yêu cầu của tôi, trả phòng nhanh.
- Cổng xác nhận phía server cho đặt món và trả phòng (tóm tắt do server dựng từ backend, chữ ký HMAC, hết hạn 10 phút,
  Idempotency-Key); không tool nào nhận `room_id`; kiểm tra grounding chống bịa giờ/giá/khoảng cách; canary chống lộ prompt;
  tối đa 4 lượt tool và 1 lệnh ghi mỗi tin; hạn mức 10 tin/phút, 100 tin/ngày.
- App: khung chat, gợi ý mở màn hình, thẻ xác nhận đơn, nút "Xem đơn"/"Xem yêu cầu".

**Vận hành & chất lượng**
- CI cho 4 package + quét bí mật; image production, `docker-compose.prod.yml` với Caddy (HTTPS, HSTS); `docs/deploy.md`.
- APK release ký bằng keystore ngoài repo, CI build theo tag `v*`; `docs/release-apk.md`.
- Header bảo mật trên API và Web (nosniff, chống nhúng iframe, CSP `frame-ancestors`); `docs/security-report.md`.
- Kiểm thử tải 50 khách: p95 26 ms, 0 lỗi 5xx (`docs/load-test.md`).
- Bộ eval chatbot: S1 (bộ câu hỏi hướng dẫn) + S2–S4 live (`/eval-bot`).

### Cơ sở dữ liệu

Migration Alembic `0001`–`0010` (base, staff_auth, stay_access, notifications, menu, food_orders, housekeeping,
concierge_data, chat_message, express_checkout). Cài mới: `alembic upgrade head` (compose prod tự chạy).

### Đã biết / chưa làm trong 1.0.0

- Chưa thanh toán online, chưa hóa đơn VAT điện tử, chưa lên Google Play (APK cài trực tiếp).
- `/eval-bot` live và đo p95 chatbot cần khóa LLM thật; chạy trước khi gắn tag.
- devDependency `vitest@3` có cảnh báo `npm audit` (chỉ máy dev/CI) — nâng cấp ở bản sau (`docs/security-report.md` F4).
