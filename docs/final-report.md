# Báo cáo tổng kết — Room Service & Housekeeping App + AI Concierge (T60)

Bản nháp cho hồ sơ đồ án, cập nhật đến 2026-11-20. Các mục đánh dấu ⏳ cần điền sau khi triển khai thật và chạy thử tại
đơn vị (T56–T59).

## 1. Bài toán và mục tiêu

Khách sạn mini, homestay, boutique thường nhận yêu cầu của khách qua điện thoại bàn hoặc Zalo: dễ thất lạc, không theo dõi
được trạng thái, Lễ tân quá tải giờ cao điểm. Hệ thống cho phép khách **gọi đồ ăn, gọi dọn phòng, hỏi thông tin và trả phòng
nhanh** trên điện thoại; **Lễ tân, Bếp, Buồng phòng** xử lý trên Web theo đúng phần việc; một **trợ lý ảo (AI Concierge)** trả
lời và thao tác thay khách nhưng **không được bịa** và **không vượt quyền** của khách.

Mục tiêu đã đạt ở mức phần mềm: MVP (Mốc M2) + Mức Tốt (Mốc M3: chatbot thao tác nghiệp vụ, trả phòng nhanh), cùng bộ hồ sơ
kiểm thử, bảo mật, tải, triển khai. Mốc M4 (triển khai thật + chạy thử tại đơn vị) chờ hạ tầng và đơn vị.

## 2. Kiến trúc

| Thành phần | Công nghệ | Vai trò |
|---|---|---|
| `mobile-app` | Flutter 3.50 (Android), Riverpod, go_router | App khách: đăng nhập mã/QR, đặt món, buồng phòng, chat, trả phòng nhanh, FCM |
| `admin-web` | Next.js 15, React, TypeScript, next-intl | Web 3 vai trò (RBAC), realtime SSE, in phiếu/hóa đơn K80 |
| `backend-api` | FastAPI, SQLAlchemy async, PostgreSQL 16, Alembic | Nghiệp vụ, state machine, phân quyền, outbox FCM, SSE |
| `ai-service` | FastAPI, Gemini / OpenAI qua REST | AI Concierge: 6 tool, cổng xác nhận, grounding, guard |

Nguyên tắc thiết kế chính:
- **Phòng của khách chỉ lấy từ token.** Không API, không tool chatbot nào nhận `room_id`/`stay_id` từ client (C4.1).
- **Mã phòng theo kỳ lưu trú**, ngẫu nhiên, lưu hash, thu hồi tức thì khi trả phòng/cấp lại (C4).
- **Backend quyết định mọi thứ:** giá, tổng tiền, quyền, chuyển trạng thái (409 khi sai trạng thái, 403 khi sai vai trò).
- **ai-service không có DB và không có quyền riêng:** gọi backend bằng chính token của khách.
- **Thông báo sau commit** (outbox) để không gửi push cho thay đổi bị rollback.

Tài liệu nghiệp vụ: `docs/domain-rules.md`, `docs/chatbot-tools-spec.md`; spec từng module: `spec/SPEC-*.md`.

## 3. Chức năng đã hoàn thành

Chi tiết: `CHANGELOG.md`. Tóm tắt theo vai trò:

- **Khách:** đăng nhập QR/mã; thực đơn song ngữ, giỏ hàng, theo dõi đơn realtime; dọn phòng/đồ dùng, Không làm phiền;
  Concierge (hỏi đáp từ Knowledge Base, xem menu, đặt món có thẻ xác nhận, gọi dọn phòng, xem trạng thái, trả phòng);
  trả phòng nhanh có tạm tính và đánh giá; thông báo đẩy.
- **Lễ tân:** sơ đồ phòng, check-in/cấp mã/in phiếu, cấp lại mã, check-out; tổng hợp đơn và yêu cầu; quản lý thông tin
  cho Concierge; đối soát và hoàn tất trả phòng nhanh, phụ phí/giảm giá, in hóa đơn; cài đặt khách sạn.
- **Bếp:** hàng đợi realtime, nhận/chế biến/giao/từ chối, quản lý thực đơn, tạm ngưng nhận đơn.
- **Buồng phòng:** hàng đợi dọn phòng/đồ dùng/dọn sau trả phòng, nhận việc, hoàn tất.

## 4. AI Concierge — chống bịa và chống lạm dụng

| Rủi ro | Biện pháp (phía server, không chỉ dựa vào prompt) |
|---|---|
| Bịa giờ, giá, khoảng cách, số điện thoại | Mọi dữ kiện trong câu trả lời phải có trong kết quả tool của lượt đó; vi phạm → thay bằng câu "chưa có thông tin" |
| Tự đặt món / trả phòng khi khách chưa đồng ý | Cổng xác nhận: lượt 1 chỉ xem trước, server dựng bản tóm tắt từ backend; lượt 2 cần chữ ký HMAC hợp lệ, chưa hết hạn 10 phút, khách xác nhận (nút hoặc câu được phân loại), cùng hash nội dung; `Idempotency-Key` chống tạo trùng |
| Thao tác cho phòng khác | Tool không có tham số phòng; tham số lạ → từ chối, backend không được gọi |
| Prompt injection, lộ prompt | Kết quả tool là dữ liệu trong `<tool_result>`; canary ngẫu nhiên + chặn trùng > 40 ký tự với system prompt |
| Lạm dụng chi phí | 10 tin/phút, 100 tin/ngày mỗi stay; tối đa 4 lượt tool, 1 lệnh ghi mỗi tin; tin ≤ 1000 ký tự |
| Đang chờ trả phòng | Server không đưa tool ghi cho LLM |

## 5. Kiểm thử và chất lượng

| Hạng mục | Kết quả (bản ứng viên `feature/HMA-58-release-prep`) |
|---|---|
| backend-api | 786 test, độ phủ 96 % |
| ai-service | 305 test, độ phủ 97,8 % |
| admin-web | 104 test (Vitest), lint + typecheck sạch |
| mobile-app | 128 test (widget/unit), `flutter analyze` sạch |
| E2E local | CP-D 37/37; CP-E 19/19; CP-F 19/19 bước (trả phòng nhanh SC1–SC6, Concierge thao tác với backend thật) |
| Bảo mật (`docs/security-report.md`) | gitleaks, pip-audit, npm audit, 45 kiểm tra tấn công trực tiếp, OWASP API Top 10; không còn lỗi High; 2 lỗi đã sửa kèm test hồi quy |
| Tải (`docs/load-test.md`) | 50 khách đồng thời, 11 495 request: 0 lỗi 5xx, p95 26 ms (ngưỡng 500 ms) |
| Chatbot live (`/eval-bot`) | ⏳ cần khóa LLM thật: S1 (≥ 95 % đúng, 0 bịa, p95 < 8 s), S2–S4 100 % × 3 lần |

Quy mô mã (không tính mã sinh tự động): ứng dụng ≈ 23 200 dòng (backend 8 500, ai 3 400, web 5 600, app 5 700);
test ≈ 17 000 dòng.

Quy trình: 60 task / 61 nhánh `feature/HMA-*`, mỗi nhánh một commit Conventional Commits kèm mã Jira; CI lint + test cho
từng package và quét bí mật; mọi lỗi phát hiện ở checkpoint đều có test hồi quy.

## 6. Triển khai và phát hành

- Production: `docker-compose.prod.yml` (Caddy HTTPS tự động, migrate tự chạy, secrets qua biến môi trường của nền tảng),
  đã chạy thử trọn bộ qua HTTPS trên máy (`docs/deploy.md` §5). ⏳ Triển khai lên máy chủ thật.
- APK: ký bằng keystore release ngoài repo, CI build theo tag (`docs/release-apk.md`). ⏳ Keystore của đơn vị, cài trên 3 máy.
- Phát hành: `docs/release-1.0.0.md` (PR vào `develop`, `release/1.0.0`, PR vào `main` do Tech Lead, tag `v1.0.0`).
- Chạy thử: hướng dẫn 1 trang cho 4 vai trò (`docs/user-guide-*.md`), mẫu biên bản `docs/field-trial-report.md`.
  ⏳ Kết quả chạy thử và xác nhận của đơn vị.

## 7. Hạn chế và hướng phát triển

- Chưa thanh toán online / VietQR, chưa hóa đơn VAT điện tử, chưa phát hành trên Google Play, chưa có app iOS.
- Báo cáo doanh thu, thống kê đánh giá, nhiều cơ sở (multi-property) chưa có.
- Chatbot phụ thuộc nhà cung cấp LLM bên ngoài (chi phí, độ trễ); có thể cache câu hỏi phổ biến, dùng model nhỏ cho hỏi đáp.
- Nâng `vitest` lên bản mới (cảnh báo `npm audit` ở môi trường dev).

## 8. Hồ sơ bảo vệ

| Hạng mục | Trạng thái |
|---|---|
| Báo cáo tổng kết (tài liệu này) | Bản nháp — cập nhật mục ⏳ sau T56–T59 |
| Slide bảo vệ | ⏳ Dàn ý đề xuất: bài toán → kiến trúc → demo 3 vai trò → AI Concierge an toàn (mục 4) → kiểm thử/bảo mật/tải (mục 5) → triển khai → hạn chế |
| Video demo | ⏳ Kịch bản đề xuất (5–7 phút): check-in & QR → đặt món trên app, Bếp xử lý, push → hỏi Concierge, đặt món qua thẻ xác nhận → dọn phòng → trả phòng nhanh, Lễ tân chốt và hoàn tất → khách bị đăng xuất kèm lời cảm ơn |
| Hotfix sau chạy thử | ⏳ qua `hotfix/*` → `main` (Tech Lead) |
