# Báo cáo kiểm thử bảo mật — T54 (2026-11-20)

Phạm vi: `backend-api`, `ai-service`, `admin-web` (bản gộp Phase 1–5: nhánh `feature/HMA-*` tới HMA-53), chạy local bằng
docker compose (`APP_ENV=dev`, `LLM_PROVIDER=fake`). `mobile-app` chỉ xét ở mức lưu token và gọi API (không kiểm thử nhị phân APK).
Chuẩn đối chiếu: `CONSTRAINTS.md` C3–C5, OWASP API Security Top 10 (2023).

**Kết luận:** không còn lỗi mức **High/Critical** ảnh hưởng bản phát hành. Tìm thấy 2 lỗi mức Medium/Low đã sửa kèm test hồi quy
(F1, F2) và 2 điểm cần xử lý ở bước triển khai/công cụ (F3, F4).

## 1. Cách kiểm thử

| Hạng mục | Công cụ / cách làm | Kết quả |
|---|---|---|
| Bí mật trong mã và lịch sử git | `gitleaks v8.21.2` (`git --log-opts=--all`, mọi nhánh; và `dir` cả cây làm việc) | Lịch sử: **0**. Cây làm việc: 4 khóa sinh tự động trong `admin-web/.next/` (build Next, đã nằm trong `.gitignore`) — không phải bí mật trong mã |
| Lỗ hổng thư viện Python | `pip-audit` trên `uv export` của `backend-api`, `ai-service` | **0** |
| Lỗ hổng thư viện JS | `npm audit --omit=dev` (`admin-web`) | **0**; devDependencies: xem F4 |
| Thử tấn công trực tiếp | Script thăm dò 45 kiểm tra vào stack đang chạy (mã phòng, JWT, IDOR, RBAC, gán trường, lộ thông tin, CORS, header, giới hạn tài nguyên, log, thu hồi phiên) | 43/45 → 45/45 sau khi sửa F1, F2 |
| Test tự động sẵn có | `pytest` backend (780), ai-service (305), `vitest` admin-web (104) — gồm C5.1–C5.4, cổng xác nhận, chống `room_id` | Đạt |

## 2. Kết quả theo yêu cầu

### 2.1 Dò mã phòng (C4.3, C4.4)
- Mã 8 ký tự, CSPRNG, bảng chữ bỏ ký tự dễ nhầm (`0 1 O I L`); DB chỉ lưu hash; mã không xuất hiện trong danh sách/chi tiết stay.
- Số phòng không dùng làm mã được (`401`).
- 6 lần thử sai trong một phút từ một IP → `429` kèm `Retry-After`; khóa theo thiết bị sau 10 lần sai/giờ có test tự động (`test_guest_auth.py`).
- Thông báo sai mã chung chung, không cho biết phòng/stay có tồn tại.

### 2.2 IDOR / BOLA (C4.1, C5.1)
- Khách A đọc/hủy đơn đồ ăn, yêu cầu dọn phòng của khách B → `403/404`; danh sách của A không có dữ liệu B; id lạ → `404` không kèm chi tiết.
- Chatbot: tool không có tham số phòng/stay; LLM gửi `room_id` → `VALIDATION_ERROR`, backend không được gọi (test `test_read_tools.py`, `test_confirmation.py`); E2E CP-F: khách B chỉ thấy yêu cầu của B.

### 2.3 RBAC / BFLA (C3, C5.3)
- Kiểm tra mẫu: Bếp tạo stay / xem hàng đợi trả phòng / xem buồng phòng, Buồng phòng xem đơn / xem stay / thêm phụ phí, Lễ tân chuyển trạng thái chế biến → đều `403`.
- `test_route_guards.py` bảo đảm **mọi** route nhân viên khai báo quyền; `test_rbac.py`, test từng module cho ma trận vai trò.

### 2.4 JWT và thu hồi phiên (C4.2)
- Token khách chỉ mang `stay_id`, `room_id`, `jti`, `exp`, `iat`, `typ` — không có mã phòng hay tên khách.
- Sửa payload (đổi `stay_id`), `alg=none`, chuỗi rác, token nhân viên dùng cho API khách → `401`; token khách dùng cho API nhân viên → `401`.
- Thuật toán cố định khi giải mã (`algorithms=[HS256]`, bắt buộc các claim).
- Check-out tại quầy, trả phòng nhanh hoàn tất, cấp lại mã → mọi thiết bị `401` ngay; mã cũ không đăng nhập được.
- Refresh token nhân viên: cookie `HttpOnly; Secure; SameSite=Strict`, có kiểm tra CSRF; lưu dạng hash.

## 3. OWASP API Security Top 10 (2023)

| # | Rủi ro | Đánh giá |
|---|---|---|
| API1 | Broken Object Level Authorization | Đạt — `stay_id` chỉ lấy từ token; `ensure_same_stay` ở mọi tài nguyên có id (2.2) |
| API2 | Broken Authentication | Đạt — rate limit mã phòng và mật khẩu nhân viên (12 lần sai → `429` từ lần thứ 6), JWT ký cố định thuật toán, thu hồi tức thì (2.1, 2.4) |
| API3 | Broken Object Property Level Authorization | Đạt — mọi body `extra="forbid"`: gửi `total_vnd`, `unit_price_vnd`, `room_id`, sửa `status` qua form stay → `400`; response khách không có trường nội bộ |
| API4 | Unrestricted Resource Consumption | Đạt — `limit` phân trang có trần (`limit=100000` → `400`), tối đa 20 dòng/đơn, 5 đơn chờ/stay, tin chat ≤ 1000 ký tự, hạn mức chat 10/phút & 100/ngày, tối đa 4 lượt tool/tin |
| API5 | Broken Function Level Authorization | Đạt (2.3) |
| API6 | Unrestricted Access to Sensitive Business Flows | Đạt — đặt món/trả phòng qua chatbot có cổng xác nhận phía server (HMAC, hết hạn 10 phút, Idempotency-Key); một yêu cầu trả phòng mở mỗi stay |
| API7 | Server Side Request Forgery | Không áp dụng — không có endpoint nhận URL để server gọi; ai-service chỉ gọi backend nội bộ và nhà cung cấp LLM cố định |
| API8 | Security Misconfiguration | **F1, F2** (đã sửa); `/docs`, `/openapi.json` tắt khi `APP_ENV=prod`; lỗi 500 không lộ stack trace/SQL; không cấp CORS cho origin lạ; `x-powered-by` đã tắt |
| API9 | Improper Inventory Management | Đạt — một phiên bản API `/api/v1`; tài liệu API tắt ở prod; endpoint dev (`seed-dev*`) chỉ là CLI và từ chối khi `APP_ENV≠dev` |
| API10 | Unsafe Consumption of APIs | Đạt — kết quả tool/LLM coi là dữ liệu (`<tool_result>`), kiểm tra grounding, canary chống lộ prompt, giá/tổng chỉ lấy từ backend |

Log: không chứa mã phòng, JWT, mật khẩu nhân viên (đã quét log backend và ai-service sau toàn bộ phiên thử) — C4.5.

## 4. Phát hiện

| ID | Mức | Mô tả | Xử lý | Test hồi quy |
|---|---|---|---|---|
| F1 | Low | API (`backend-api`, `ai-service`) thiếu `X-Content-Type-Options`, `X-Frame-Options`, `Referrer-Policy`, `Cache-Control` cho dữ liệu cá nhân | Middleware `request_context` thêm `nosniff`, `DENY`, `no-referrer`, `no-store` (giữ nguyên `Cache-Control` riêng của SSE) | `tests/integration/test_http_contract.py::test_every_response_carries_the_security_headers` (2 service) |
| F2 | Medium | `admin-web` không chống nhúng iframe → clickjacking màn Lễ tân (hoàn tất trả phòng, cấp lại mã) | `next.config.ts` gửi `X-Frame-Options: DENY`, CSP `frame-ancestors 'none'; base-uri 'self'; form-action 'self'`, `nosniff`, `Referrer-Policy`, `Permissions-Policy` | `admin-web/tests/security/headers.test.ts` |
| F3 | Medium (triển khai) | Rate limit theo IP dùng `request.client.host`. Sau reverse proxy (T56), nếu uvicorn không tin header proxy thì mọi khách chung một IP → giới hạn 5 lần/phút thành từ chối dịch vụ chung; nếu tin mọi nguồn thì kẻ tấn công giả `X-Forwarded-For` để lách giới hạn | Không đổi code. **T56 phải** chạy uvicorn với `--proxy-headers` và `FORWARDED_ALLOW_IPS=<IP proxy>` (chỉ tin proxy của mình) | Kiểm tra thủ công sau deploy: 6 lần sai từ một máy → `429`, máy khác vẫn đăng nhập được |
| F4 | Medium (công cụ dev) | devDependency `vitest@3` kéo theo `tinypool` (GHSA-5gmw-xhrv-c9v3, critical) và `@vitest/mocker` (GHSA-82fw-gwwq-j7x9). Chỉ chạy trên máy dev/CI, **không có trong bản build** | Nâng `vitest@5` cần đồng bộ `@types/node` (xung đột peer) — để task riêng; CI không mở server UI của vitest | `npm audit` (dev) sạch sau khi nâng |

## 5. Còn lại / ngoài phạm vi

- Chạy lại toàn bộ bộ thử trên staging/production sau T56 (header, HTTPS/HSTS ở reverse proxy, F3).
- Kiểm thử APK (lưu token trong secure storage, chặn cleartext ngoài dev) khi có bản release ký (T57).
- `/eval-bot` live với LLM thật (S4 tấn công đổi phòng) — cần khóa LLM.
- Theo `docs/roadmap-d01-d27.md`, lỗi phát hiện sau khi tạo `release/1.0.0` sửa trên nhánh `release/*`; nhánh release chưa được tạo (chờ Tech Lead merge các PR vào `develop`), nên F1/F2 nằm trên `feature/HMA-54-security-pass`.
