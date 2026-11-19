# Roadmap D01 – D27

27 ngày, 4 sprint trên Jira (project key giả định `HMA`), đồng bộ MS Project.
Mỗi task Jira ↔ một nhánh `feature/HMA-<n>-<mo-ta>` ↔ một PR vào `develop`.

## Luồng nhánh

```
feature/HMA-* ──PR──▶ develop ──(D22)──▶ release/1.0.0 ──PR (Tech Lead)──▶ main ──tag v1.0.0
                                              ▲                                 │
                                              └──── fix trên release/* ─────────┘ merge ngược về develop
hotfix/HMA-* (từ main) ──PR (Tech Lead)──▶ main, rồi merge ngược về develop
```

- Chỉ Tech Lead merge vào `main`. CI xanh + ≥ 1 review là điều kiện merge vào `develop`.
- Cuối mỗi sprint: demo trên `develop` (môi trường staging), review & retro.

---

## Sprint 1 — D01–D05: Nền móng & bảo mật mã phòng

| Ngày | Hạng mục | Package | Kết quả (Definition of Done) |
|---|---|---|---|
| D01 | Chốt stack, khởi tạo monorepo, branch protection, CI lint/test rỗng, `.env.example` | all | CI chạy xanh trên PR đầu tiên |
| D01–D02 | Thiết kế ERD: room, stay, stay_session, staff, menu, food_order, housekeeping_request, checkout_request, status_history, kb_entry | backend-api | Migration Alembic + seed dữ liệu mẫu |
| D02–D03 | Cơ chế mã phòng: check-in sinh mã/QR, `POST /auth/room-code` → `stay_session_token`, revoke khi check-out, rate limit | backend-api | Integration test 401/403/429 (C5.1, C5.2) |
| D03–D04 | Auth nhân viên (email+mật khẩu, JWT), RBAC `RECEPTION`/`KITCHEN`/`HOUSEKEEPING` | backend-api | Test RBAC 403 (C5.3) |
| D04–D05 | Khung Web: đăng nhập, layout theo vai trò, màn Check-in/Check-out | admin-web | Lễ tân check-in và thấy mã/QR |
| D05 | Khung Flutter: màn nhập mã/quét QR, lưu token an toàn (secure storage) | mobile-app | Đăng nhập bằng mã thật trên staging |

**Mốc M1 (D05):** đăng nhập mã phòng end-to-end, check-out làm token hết hiệu lực.

## Sprint 2 — D06–D14: Hoàn thiện MVP

| Ngày | Hạng mục | Package | DoD |
|---|---|---|---|
| D06–D07 | API menu + đặt đồ ăn + state machine | backend-api | Test chuyển trạng thái 409 (C5.4) |
| D06–D08 | App: xem menu, giỏ hàng, đặt món, lịch sử đơn | mobile-app | Đặt món thành công trên staging |
| D07–D08 | Web Bếp: hàng đợi đơn, cập nhật trạng thái, bật/tắt món | admin-web | Bếp xử lý trọn vòng đời đơn |
| D08–D09 | API + App yêu cầu dọn phòng / đồ dùng | backend-api, mobile-app | Tạo & theo dõi yêu cầu |
| D09–D10 | Web Buồng phòng: nhận việc, cập nhật trạng thái | admin-web | Buồng phòng xử lý trọn vòng đời |
| D10–D11 | FCM: đăng ký token, outbox gửi thông báo khi đổi trạng thái; WebSocket/SSE cho Web | backend-api, mobile-app, admin-web | Thông báo ≤ 5 s |
| D11 | Web Lễ tân: bảng tổng hợp mọi yêu cầu, hủy đơn, khiếu nại | admin-web | — |
| D12–D13 | AI Concierge — luồng Guide: Knowledge Base, `get_hotel_info_and_guide`, UI chat trên app | ai-service, mobile-app | Trả lời đúng KB, không bịa |
| D14 | Kiểm thử tích hợp MVP, sửa lỗi, demo Sprint 2 | all | 6 chức năng MVP chạy trên staging |

**Mốc M2 (D14):** MVP hoàn chỉnh (đăng nhập mã phòng, đặt đồ ăn, dọn phòng, realtime + FCM, Web 3 vai trò, chatbot hướng dẫn viên).

## Sprint 3 — D15–D21: Mức Tốt

| Ngày | Hạng mục | Package | DoD |
|---|---|---|---|
| D15–D16 | Express Checkout: API + state machine + revoke token + tạo việc dọn phòng | backend-api | Test revoke sau `COMPLETED` |
| D16–D17 | App: nút trả phòng nhanh + theo dõi; Web Lễ tân: đối soát hóa đơn, duyệt/từ chối | mobile-app, admin-web | Trọn luồng trả phòng |
| D17–D19 | Chatbot Tool Calling: `get_available_menu`, `create_room_service_order` (bước xác nhận), `request_housekeeping`, `get_my_requests`, `request_express_checkout` | ai-service | Schema đúng `docs/chatbot-tools-spec.md` |
| D19–D20 | Chặn prompt injection & đổi `room_id`; server-side confirm gate cho đặt món | ai-service | `/eval-bot` pass 4 kịch bản |
| D21 | Đa ngôn ngữ (vi/en), hoàn thiện UI, demo Sprint 3 | all | — |

**Mốc M3 (D21):** Chatbot thao tác nghiệp vụ + Express Checkout hoạt động trên staging.

## Sprint 4 — D22–D27: Kiểm thử, phát hành, thử nghiệm thực tế

| Ngày | Hạng mục | Kết quả |
|---|---|---|
| D22 | Feature freeze; tạo `release/1.0.0` từ `develop` | Chỉ nhận bugfix trên `release/*` |
| D22–D23 | Kiểm thử bảo mật: dò mã phòng, IDOR, RBAC, JWT revoke, OWASP API Top 10, secret scan | Báo cáo bảo mật, không còn lỗi High |
| D23 | Kiểm thử tải: 50 khách đồng thời (k6/Locust) | Không 5xx, p95 đạt C6 |
| D24 | Build `flutter build apk --release` (ký key release), deploy Backend + ai-service + Web lên cloud, DB managed, HTTPS | URL production + file APK |
| D24 | PR `release/1.0.0` → `main`, **Tech Lead duyệt merge**, tag `v1.0.0`, merge ngược về `develop` | `main` = bản phát hành |
| D25–D26 | Chạy thử nghiệm tại đơn vị thực tế: nhập dữ liệu phòng/menu/KB, đào tạo nhân viên, thu phản hồi | Biên bản thử nghiệm |
| D26 | Hotfix (nếu có) qua `hotfix/*` → `main` (Tech Lead) | — |
| D27 | Tổng kết: báo cáo, video demo, tài liệu hướng dẫn sử dụng, slide bảo vệ | Hồ sơ đồ án hoàn chỉnh |

**Mốc M4 (D27):** APK + Web quản trị + Backend đã deploy, đã chạy thử tại đơn vị.

## Rủi ro & dự phòng

| Rủi ro | Giảm thiểu |
|---|---|
| Chi phí/độ trễ LLM | Cache câu hỏi KB phổ biến; model nhỏ cho Guide; timeout + thông báo fallback |
| FCM không tới (máy tắt nền) | App đồng bộ trạng thái khi mở; Web nhắc đơn quá hạn |
| Trễ tiến độ Mức Tốt | MVP đóng băng ở D14; Mức Tốt cắt theo thứ tự ưu tiên: Tool Calling đặt món → Express Checkout → các tool còn lại |
| Lộ mã phòng | Cấp lại mã 1 click trên Web; rate limit; revoke tức thì |
