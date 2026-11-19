# Capability Map: Room Service & Housekeeping App + AI Concierge — V1

Status: **approved** (2026-11-19, Tech Lead) — gồm cả 9 giả định cuối file

Đồ án gồm nhiều capability kiểm thử độc lập (đăng nhập phiên lưu trú, đặt đồ ăn, dọn phòng, thông báo, chatbot,
trả phòng) → tách module trước khi viết spec. Mỗi module là một **lát dọc** (vertical slice) xuyên qua
`backend-api` / `ai-service` / `admin-web` / `mobile-app` khi cần, có spec riêng `spec/SPEC-<module-id>.md`.

| Module id | Trách nhiệm | Phụ thuộc | Mức | Sprint |
|---|---|---|---|---|
| `foundation` | Monorepo, CI, docker compose, khung FastAPI/Next.js/Flutter, migration nền, quy ước lỗi/API, i18n vi/en | — | MVP | D01 |
| `staff-auth` | Tài khoản nhân viên, đăng nhập JWT, RBAC `RECEPTION`/`KITCHEN`/`HOUSEKEEPING`, layout Web theo vai trò | foundation | MVP | D03–D05 |
| `stay-access` | Phòng & kỳ lưu trú, check-in/out, sinh mã phiên/QR, đổi lấy `stay_session_token`, revoke, rate limit, màn đăng nhập app | staff-auth | MVP | D02–D05 |
| `notifications` | FCM outbox gửi app khách; SSE realtime cho Web theo kênh vai trò; đăng ký `fcm_token` | stay-access | MVP | D10–D11 |
| `room-service` | Menu, đặt đồ ăn, state machine đơn, màn Bếp, màn đặt món & theo dõi trên app | stay-access, notifications | MVP | D06–D08 |
| `housekeeping` | Yêu cầu dọn phòng / đồ dùng, state machine, màn Buồng phòng, màn yêu cầu trên app | stay-access, notifications | MVP | D08–D10 |
| `concierge-guide` | Knowledge Base, tool `get_hotel_info_and_guide`, endpoint `/chat`, UI chat trên app, chống bịa | stay-access | MVP | D12–D13 |
| `express-checkout` | Yêu cầu trả phòng, đối soát hóa đơn, duyệt/từ chối trên Web Lễ tân, revoke + tạo việc dọn phòng | stay-access, notifications, room-service, housekeeping | Tốt | D15–D17 |
| `concierge-actions` | Tool Calling nghiệp vụ (menu, đặt món có cổng xác nhận, dọn phòng, `get_my_requests`, trả phòng), chống injection/đổi `room_id`, `/eval-bot` | concierge-guide, room-service, housekeeping, express-checkout | Tốt | D17–D20 |

```
foundation → staff-auth → stay-access → notifications ─┬→ room-service ──┬→ express-checkout → concierge-actions
                                       └→ concierge-guide ─────────────────────────────────────┘
                                                        └→ housekeeping ──┘
```

**Thứ tự xây:** `foundation` → `staff-auth` → `stay-access` → `notifications` → (`room-service`, `housekeeping`,
`concierge-guide` song song) → `express-checkout` → `concierge-actions`.

> Ghi chú: roadmap đặt `notifications` ở D10–D11, sau `room-service`. Theo map, `room-service` vẫn bắt đầu D06
> nhưng chỉ phát sự kiện vào outbox; `notifications` chỉ cần xong trước khi đóng MVP (D14). Không có vòng phụ thuộc.

Ranh giới giao tiếp:
- `stay-access` cung cấp dependency `current_stay` (lấy `stay_id`/`room_id` từ token) — mọi module khách dùng chung, không module nào tự đọc `room_id` từ request.
- `notifications` cung cấp `emit_status_changed(entity_type, entity_id, stay_id, status)` — các module nghiệp vụ chỉ gọi hàm này.
- `concierge-*` gọi `backend-api` bằng chính `stay_session_token` của khách, không có quyền nhân viên.

Ngoài map (không phải capability, nằm trong roadmap Sprint 4): kiểm thử bảo mật/tải, build APK release, deploy, thử nghiệm thực tế.

---

## Giả định cần xác nhận (ảnh hưởng tới mọi spec module)

1. **Một khách sạn / một bản deploy** (single-tenant). Không làm đa khách sạn.
2. **Không thanh toán online.** "Đối soát hóa đơn" = Lễ tân xem tổng tiền phòng + đồ ăn trên Web và thu tiền ngoài hệ thống.
3. **Không có vai trò ADMIN riêng.** Tài khoản nhân viên tạo bằng script seed/CLI; `KITCHEN` quản lý menu, `RECEPTION` quản lý Knowledge Base & thông tin khách sạn.
4. **LLM chính: Gemini** (có free tier), qua một lớp adapter để đổi sang OpenAI bằng biến môi trường.
5. **Realtime Web dùng SSE** (đơn giản hơn WebSocket, đủ cho luồng một chiều server → web).
6. **Chỉ Android** (APK). iOS ngoài phạm vi.
7. **Ngôn ngữ:** giao diện vi/en; chatbot trả lời theo ngôn ngữ của khách.
8. **Hạ tầng deploy:** Docker container trên một cloud PaaS/VPS + PostgreSQL managed; chọn cụ thể ở Sprint 4.
9. **Giá phòng** nhập tay ở bước check-in (không làm module đặt phòng/quản lý giá).
