# Spec: room-service — V1

Status: **approved** (2026-11-19, Tech Lead) — Open Questions giữ mặc định: khách chỉ hủy khi `PENDING`, tối đa 5 đơn `PENDING`, không hiện phí dịch vụ trên app, chưa có ảnh món
Module id: `room-service` · Phụ thuộc: `stay-access`, `notifications` · Mức: MVP · Sprint 2 (D06–D08) · Map: [capability-map.md](capability-map.md)
Nguồn quy tắc: `docs/domain-rules.md` §3, §6; `CONSTRAINTS.md` C2.4, C3, C5.4; `docs/chatbot-tools-spec.md` §4.2–4.3.

## Objective

Khách xem menu và đặt đồ ăn tại phòng trên app; Bếp nhận và xử lý đơn trên Web theo đúng state machine; khách theo dõi
trạng thái realtime. Module cung cấp sẵn API mà chatbot (`concierge-actions`) sẽ gọi lại, không cần endpoint riêng cho bot.

**Người dùng:** khách lưu trú, Bếp (`KITCHEN`), Lễ tân (`RECEPTION`, giám sát + hủy).

**User stories**
- Là khách, tôi xem menu theo nhóm (Bữa sáng, Món chính, Đồ uống…), chỉ thấy món đang phục vụ, thêm vào giỏ, ghi chú ("ít cay") và đặt đơn. Tổng tiền tôi thấy là tổng do server tính.
- Là khách, tôi hủy được đơn khi Bếp chưa xác nhận; sau đó chỉ có thể gọi Lễ tân.
- Là khách, tôi xem danh sách và chi tiết đơn của phòng mình, trạng thái tự cập nhật.
- Là Bếp, tôi thấy hàng đợi đơn theo cột trạng thái, bấm một nút để chuyển sang bước tiếp theo, từ chối đơn kèm lý do.
- Là Bếp, tôi bật/tắt món hết hàng, tạm ngưng nhận đơn khi quá tải, và sửa menu (tên, giá, mô tả, nhóm).
- Là Lễ tân, tôi xem mọi đơn, hủy đơn khi khách gọi điện yêu cầu, và được nhắc khi đơn chờ quá 10 phút chưa ai xác nhận.
- Là dev `express-checkout`, tôi lấy được tổng tiền đồ ăn của một stay qua một hàm duy nhất.

**Không thuộc module này:** thanh toán online (giả định 2 — tiền đồ ăn cộng vào hóa đơn phòng), ảnh món ăn, khuyến mãi,
đặt món qua chatbot (`concierge-actions` gọi lại API của module này).

## Tech Stack

Kế thừa các module trước. **Không thêm dependency mới.**

## Thiết kế

### Dữ liệu (migration Alembic)

```
menu_category
  id            uuid PK
  code          text UNIQUE NOT NULL        -- BREAKFAST | MAIN | DRINK | SNACK ... (chatbot lọc theo code)
  name_vi, name_en text NOT NULL
  sort_order    smallint NOT NULL DEFAULT 0
  is_active     boolean NOT NULL DEFAULT true

menu_item
  id              uuid PK
  category_id     uuid FK → menu_category NOT NULL
  name_vi, name_en text NOT NULL
  description_vi, description_en text NULL
  price_vnd       bigint NOT NULL CHECK (price_vnd >= 0)
  available       boolean NOT NULL DEFAULT true     -- Bếp bật/tắt nhanh (hết hàng)
  is_archived     boolean NOT NULL DEFAULT false    -- xóa mềm; không xóa cứng vì đơn cũ tham chiếu
  sort_order      smallint NOT NULL DEFAULT 0
  created_at, updated_at

food_order
  id                 uuid PK
  stay_id            uuid FK → stay NOT NULL
  room_id            uuid FK → room NOT NULL      -- chụp từ StayContext, chỉ để hiển thị/lọc
  status             food_order_status NOT NULL   -- PENDING | CONFIRMED | PREPARING | DELIVERING | COMPLETED | CANCELLED
  total_vnd          bigint NOT NULL              -- server tính khi tạo, không đổi về sau
  order_note         text NULL
  source             text NOT NULL                -- APP | CHATBOT
  estimated_minutes  smallint NULL                -- Bếp đặt khi CONFIRMED
  cancel_reason      text NULL
  cancelled_by       text NULL                    -- GUEST | STAFF:<id> | SYSTEM
  idempotency_key    text NULL
  version            integer NOT NULL DEFAULT 0   -- khóa lạc quan
  created_at, updated_at
  UNIQUE (stay_id, idempotency_key) WHERE idempotency_key IS NOT NULL
  INDEX (status, created_at)

order_item
  id               uuid PK
  order_id         uuid FK → food_order ON DELETE CASCADE
  menu_item_id     uuid FK → menu_item NOT NULL
  name_vi, name_en text NOT NULL       -- chụp tên tại thời điểm đặt
  unit_price_vnd   bigint NOT NULL     -- chụp giá tại thời điểm đặt
  quantity         smallint NOT NULL CHECK (quantity BETWEEN 1 AND 20)
  line_total_vnd   bigint NOT NULL
  note             text NULL

status_history                        -- bảng dùng chung, module housekeeping/express-checkout tái sử dụng
  id            uuid PK
  entity_type   text NOT NULL          -- FOOD_ORDER | HOUSEKEEPING | CHECKOUT
  entity_id     uuid NOT NULL
  from_status   text NULL
  to_status     text NOT NULL
  actor         text NOT NULL          -- GUEST | STAFF:<id> | SYSTEM
  reason        text NULL
  created_at    timestamptz NOT NULL
  INDEX (entity_type, entity_id, created_at)

hotel_settings  (+ cột mới, bảng có từ foundation)
  room_service_open    time NOT NULL DEFAULT '06:00'
  room_service_close   time NOT NULL DEFAULT '22:00'
  room_service_paused  boolean NOT NULL DEFAULT false   -- Bếp tạm ngưng nhận đơn
  default_prep_minutes smallint NOT NULL DEFAULT 25
```

- Giờ phục vụ so theo giờ `Asia/Ho_Chi_Minh`. Cho phép giờ đóng sau nửa đêm (VD 18:00–02:00).

### State machine (khai báo một chỗ)

```python
# backend-api/app/modules/room_service/state.py
TRANSITIONS: dict[tuple[OrderStatus, OrderStatus], frozenset[Actor]] = {
    (PENDING,    CONFIRMED):  {KITCHEN},
    (PENDING,    CANCELLED):  {GUEST, KITCHEN, RECEPTION},
    (CONFIRMED,  PREPARING):  {KITCHEN},
    (CONFIRMED,  CANCELLED):  {KITCHEN, RECEPTION},        # bắt buộc reason
    (PREPARING,  DELIVERING): {KITCHEN},
    (DELIVERING, COMPLETED):  {KITCHEN},
}
```

Một hàm `transition(db, order, to, actor, reason=None)` duy nhất thực hiện, trong một transaction:
1. Khóa hàng (`SELECT ... FOR UPDATE`), kiểm tra `(from, to)` có trong bảng → không có thì `409 INVALID_TRANSITION`.
2. Kiểm tra actor → sai vai trò `403 FORBIDDEN` (kiểm tra vai trò ở router trước, đây là lớp thứ hai).
3. `CANCELLED` từ `CONFIRMED` hoặc do nhân viên → `reason` bắt buộc, không có thì `400`.
4. Ghi `status_history`, gọi `emit_status_changed(entity_type=FOOD_ORDER, ...)`.

Không có code nào khác được gán trực tiếp `order.status`. Có test bảng hóa toàn bộ 6 × 6 cặp trạng thái × 4 actor.

### Tạo đơn

`POST /api/v1/guest/orders` (dependency `current_active_stay`), header tùy chọn `Idempotency-Key` (≤ 64 ký tự):

```json
{ "items": [ { "item_id": "uuid", "quantity": 2, "note": "ít cay" } ], "order_note": "Gõ cửa nhẹ", "source": "APP" }
```

Quy tắc (theo thứ tự, lỗi đầu tiên gặp phải được trả về):

| Điều kiện | Kết quả |
|---|---|
| Body có trường lạ (kể cả `room_id`, `stay_id`, `price_vnd`, `total_vnd`) | `400 VALIDATION_ERROR` |
| 1–20 dòng, mỗi dòng `quantity` 1–20; `item_id` trùng nhau được gộp | sai → `400` |
| Stay `CHECKOUT_PENDING` | `409 STAY_CHECKOUT_PENDING` (từ `current_active_stay`) |
| Ngoài giờ phục vụ hoặc `room_service_paused` | `409 KITCHEN_CLOSED` |
| Món không tồn tại, đã archive, `available=false`, hoặc nhóm `is_active=false` | `409 ITEM_UNAVAILABLE`, `details` liệt kê `item_id` |
| Stay đã có ≥ 5 đơn `PENDING` | `409 TOO_MANY_PENDING_ORDERS` (chống spam) |
| Cùng `Idempotency-Key` trong cùng stay | Trả lại đơn đã tạo (`200`), không tạo đơn mới |
| Hợp lệ | `201` + đơn đầy đủ; giá/tên chụp từ DB; `total_vnd = Σ line_total_vnd` |

`source` chỉ nhận `APP` hoặc `CHATBOT` (dùng cho thống kê, không ảnh hưởng quyền).

### API

**Khách** (`/api/v1/guest`):

| Method | Path | Quyền | Mô tả |
|---|---|---|---|
| GET | `/menu?category=&search=` | `current_stay` | `{service_hours, is_open_now, categories:[...], items:[{item_id, name, category, price_vnd, available, description}]}` — tên/mô tả theo `lang` của session; chỉ món chưa archive, nhóm active. Khớp output tool `get_available_menu` |
| POST | `/orders` | `current_active_stay` | Tạo đơn (ở trên) |
| GET | `/orders?status=` | `current_stay` | Đơn của stay hiện tại, mới nhất trước |
| GET | `/orders/{id}` | `current_stay` | Chi tiết + lịch sử trạng thái; đơn của stay khác → `403` |
| POST | `/orders/{id}/cancel` | `current_stay` | Chỉ khi `PENDING`; khác → `409 INVALID_TRANSITION` |

**Nhân viên** (`/api/v1`):

| Method | Path | Quyền | Mô tả |
|---|---|---|---|
| GET | `/orders?status=&date=` | `KITCHEN`, `RECEPTION` | Hàng đợi; mặc định các đơn chưa kết thúc + đơn kết thúc trong 12 giờ qua. Trả `room_number`, không trả tên khách cho `KITCHEN` |
| GET | `/orders/{id}` | `KITCHEN`, `RECEPTION` | Chi tiết + lịch sử |
| POST | `/orders/{id}/transition` | `KITCHEN` | `{to, estimated_minutes?, reason?, version}`; `version` lệch → `409 CONFLICT` (hai người bấm cùng lúc) |
| POST | `/orders/{id}/cancel` | `KITCHEN`, `RECEPTION` | `{reason, version}` |
| GET/POST/PATCH | `/menu/categories`, `/menu/items`, `/menu/items/{id}` | `KITCHEN` | Quản lý menu; "xóa" = `is_archived=true` |
| POST | `/menu/items/{id}/availability` | `KITCHEN` | `{available}` |
| PATCH | `/settings/room-service` | `KITCHEN` | `{paused}`; giờ mở/đóng chỉ `RECEPTION` sửa |
| PATCH | `/settings/room-service/hours` | `RECEPTION` | `{open, close, default_prep_minutes}` |

**Nội bộ (Python, cho module khác):**

```python
# room_service/api.py
async def get_stay_food_total(db, stay_id: UUID) -> FoodBill        # đơn COMPLETED + đơn chưa kết thúc (tách riêng), cho express-checkout
async def count_open_orders(db, stay_id: UUID) -> int
```

### Đóng stay & nhắc đơn quá hạn

- Đăng ký `register_on_stay_closed`: mọi đơn `PENDING`/`CONFIRMED` → `CANCELLED` (`actor=SYSTEM`, `reason=STAY_CLOSED`).
  Đơn `PREPARING`/`DELIVERING` **giữ nguyên** (đồ đã làm, vẫn tính tiền) và hiện cảnh báo cho Lễ tân trên Web.
- Nhắc quá hạn: một tác vụ chạy mỗi phút trong worker nền (cùng cơ chế với outbox worker) tìm đơn `PENDING` quá 10 phút,
  phát sự kiện SSE `order_overdue` tới `RECEPTION` và `KITCHEN` **một lần** cho mỗi đơn (cột `overdue_notified_at`).

### admin-web

- **Bếp `/kitchen`:** bảng cột `PENDING | CONFIRMED | PREPARING | DELIVERING`; thẻ đơn: số phòng, giờ đặt (đếm phút), danh sách món + ghi chú
  (chữ lớn, đọc được từ xa), nút hành động chính một chạm cho bước tiếp theo, menu phụ "Từ chối" (bắt buộc lý do).
  Khi xác nhận, chọn nhanh thời gian dự kiến (15/25/40 phút). Thẻ quá 10 phút viền đỏ. Cập nhật qua `useStaffEvents`, tải lại khi kết nối lại.
  Danh sách "Hoàn tất/Hủy hôm nay" thu gọn bên dưới.
- **Bếp `/kitchen/menu`:** bảng món theo nhóm, công tắc "Còn món", sửa giá/tên/mô tả, thêm món, lưu trữ món. Nút "Tạm ngưng nhận đơn".
- **Lễ tân `/reception/orders`:** danh sách mọi đơn có lọc trạng thái/phòng, xem chi tiết + lịch sử, nút hủy (bắt buộc lý do). Không có nút chuyển trạng thái của Bếp.
  Toast `order_overdue`. Cài đặt giờ phục vụ ở `/reception/settings`.

### mobile-app

- **Menu:** tab theo nhóm, ô tìm kiếm, món `available=false` hiện mờ "Tạm hết", ngoài giờ hiện băng "Bếp mở cửa 06:00–22:00" và khóa nút đặt.
- **Giỏ hàng:** tăng/giảm số lượng, ghi chú từng món và cả đơn; giỏ lưu cục bộ theo `stay_id` (xóa khi đăng xuất). Tổng tạm tính chỉ để hiển thị.
- **Đặt đơn:** sinh `Idempotency-Key` (UUID) một lần cho mỗi lần bấm "Đặt", dùng lại khi retry mạng. Thành công → màn chi tiết đơn với tổng tiền **từ response**.
  `409 ITEM_UNAVAILABLE` → đánh dấu món lỗi trong giỏ, tải lại menu.
- **Đơn của tôi:** danh sách + chi tiết với thanh tiến trình trạng thái, thời gian dự kiến, nút hủy khi `PENDING` (có xác nhận).
  Route `/requests/FOOD_ORDER/<id>` cho thông báo đẩy. Làm mới theo FCM và theo chính sách dự phòng 15 s của `notifications`.
- **Trang chủ:** thêm ô "Đặt đồ ăn" và thẻ "Đơn đang xử lý" nếu có.

### Mẫu thông báo (bổ sung `notifications/templates`)

`FOOD_ORDER.CONFIRMED|PREPARING|DELIVERING|COMPLETED|CANCELLED` bằng vi/en (`PENDING` không gửi push cho khách vì chính khách vừa tạo).

## Commands

Kế thừa `foundation`. Bổ sung:

```bash
cd backend-api
uv run python -m app.cli seed-menu --from-file seeds/menu.example.csv
uv run pytest -q tests/unit/room_service tests/integration/room_service
cd ../admin-web && npm test -- kitchen
cd ../mobile-app && flutter test test/room_service
```

## Project Structure

```
backend-api/app/modules/room_service/
  models.py  schemas.py  state.py  service.py  repository.py  router_guest.py  router_staff.py  api.py  jobs.py (nhắc quá hạn)
backend-api/app/modules/shared/status_history.py
backend-api/migrations/versions/xxxx_room_service.py
backend-api/seeds/menu.example.csv
backend-api/tests/unit/room_service/  tests/integration/room_service/
admin-web/src/app/[locale]/(staff)/kitchen/  page.tsx  menu/
admin-web/src/app/[locale]/(staff)/reception/orders/  settings/
admin-web/src/components/kitchen/  OrderBoard.tsx  OrderCard.tsx  RejectDialog.tsx  MenuTable.tsx
mobile-app/lib/features/room_service/  menu_screen.dart  cart_controller.dart  order_list_screen.dart  order_detail_screen.dart  room_service_repository.dart
mobile-app/test/room_service/
```

## Code Style

Theo `foundation`. Riêng module này:
- Tiền luôn là `int` (VND), không dùng `float`/`Decimal` lẫn lộn; tổng tính ở service, không ở router hay client.
- Mọi đổi trạng thái đi qua `transition(...)`; repository phía khách luôn có điều kiện `stay_id = ctx.stay_id`.

## Testing Strategy

| Mức | Nội dung bắt buộc |
|---|---|
| Unit | Bảng `TRANSITIONS`: toàn bộ 36 cặp × 4 actor → hợp lệ/`409`/`403` đúng như `domain-rules.md` §3; tính tổng; kiểm tra giờ phục vụ kể cả qua nửa đêm |
| Integration — tạo đơn | Giá/tên chụp từ DB, client gửi `price_vnd`/`total_vnd`/`room_id` → `400`; món hết hàng → `409 ITEM_UNAVAILABLE`; ngoài giờ / tạm ngưng → `409 KITCHEN_CLOSED`; `CHECKOUT_PENDING` → `409`; đơn PENDING thứ 6 → `409`; cùng `Idempotency-Key` hai lần → một đơn |
| Integration — **C5.4** | Mọi chuyển không hợp lệ qua API → `409 INVALID_TRANSITION`; hai Bếp bấm cùng lúc với cùng `version` → một thành công, một `409 CONFLICT` |
| Integration — **C5.1/C3** | Khách stay A xem/hủy đơn stay B → `403`; `HOUSEKEEPING` gọi mọi endpoint đơn/menu → `403`; `RECEPTION` gọi `/transition` → `403`; `KITCHEN` sửa giờ phục vụ → `403`; `KITCHEN` không nhận tên khách |
| Integration | Mỗi chuyển trạng thái tạo đúng một `status_history` và một outbox (kiểm tra qua `FakePushSender`); hủy từ `CONFIRMED` không có `reason` → `400` |
| Integration | Đóng stay: đơn `PENDING/CONFIRMED` → `CANCELLED (STAY_CLOSED)`; `PREPARING` giữ nguyên; `get_stay_food_total` đúng |
| Integration | Đơn `PENDING` 11 phút → một sự kiện `order_overdue`, chạy job lần hai không phát lại |
| admin-web (Vitest) | Thẻ đơn chỉ hiện nút hợp lệ theo trạng thái; từ chối bắt buộc lý do; sự kiện SSE cập nhật đúng cột |
| mobile-app | Giỏ hàng cộng/gộp đúng; retry dùng lại `Idempotency-Key`; `ITEM_UNAVAILABLE` đánh dấu món; hiển thị tổng từ response |

Coverage `app/modules/room_service` ≥ 80%.

## Boundaries

- **Always:** tính giá/tổng ở server; chụp giá và tên vào `order_item`; đổi trạng thái qua `transition`; phát sự kiện qua `emit_status_changed`.
- **Ask first:** thêm trạng thái mới hoặc đổi quyền chuyển trạng thái (phải sửa `docs/domain-rules.md` cùng PR); thêm phí dịch vụ/VAT; cho khách hủy sau `CONFIRMED`; đổi ngưỡng 5 đơn PENDING / 10 phút quá hạn.
- **Never:** nhận giá hoặc `room_id` từ client; xóa cứng `menu_item` đã có đơn; gán `order.status` ngoài `transition`; tạo endpoint riêng cho chatbot bỏ qua kiểm tra của API khách.

## Success Criteria

1. Bếp seed menu → khách phòng 101 thấy menu đúng ngôn ngữ, món tắt hiện "Tạm hết", ngoài giờ không đặt được.
2. Khách đặt 2 phở + 1 nước cam → Bếp thấy thẻ mới trên Web trong ≤ 1 s kèm toast; khách thấy tổng tiền khớp DB.
3. Bếp đi hết `CONFIRMED → PREPARING → DELIVERING → COMPLETED`; mỗi bước khách nhận push ≤ 5 s và màn chi tiết cập nhật.
4. Khách hủy được khi `PENDING`; sau `CONFIRMED` nút hủy biến mất và API trả `409`.
5. Mạng chập chờn khiến app gửi lại yêu cầu đặt → chỉ có một đơn.
6. Đơn không ai xác nhận sau 10 phút → Lễ tân và Bếp nhận nhắc một lần.
7. Check-out khi còn đơn `PENDING` → đơn bị hủy tự động với lý do `STAY_CLOSED`.
8. Đổi giá món sau khi đặt → đơn cũ giữ giá cũ.
9. Toàn bộ test trong Testing Strategy xanh; coverage `room_service` ≥ 80%, toàn backend ≥ 70%.

## Out of Scope (Deferred)

- Ảnh món ăn: cần hạ tầng upload/lưu trữ file; V1 chỉ có chữ.
- Tùy chọn món (size, topping, combo): tăng độ phức tạp giá; dùng ghi chú thay thế.
- Phí dịch vụ, VAT, khuyến mãi: Lễ tân xử lý khi đối soát.
- In phiếu bếp (máy in nhiệt tại bếp): màn hình Web đủ cho V1.
- Thống kê doanh thu đồ ăn: sau khi chạy thử thực tế.
- Phân công người giao món: Bếp tự giao, không theo dõi theo nhân viên.

## Open Questions

1. Khách có được hủy sau khi Bếp đã xác nhận (trước khi nấu) không? Spec hiện theo `domain-rules.md`: chỉ khi `PENDING`.
2. Giới hạn 5 đơn `PENDING` mỗi stay có phù hợp không?
3. Có cần phí dịch vụ phòng (VD +10%) hiển thị ngay trên app không, hay để Lễ tân cộng khi trả phòng?
4. Đơn vị thử nghiệm có ảnh món sẵn không? Nếu có, nên đưa ảnh vào V1 (cần thêm module lưu file).
