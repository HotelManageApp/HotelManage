# Spec: housekeeping — V1

Status: **approved** (2026-11-19, Tech Lead) — Open Questions giữ mặc định: thêm `TURNOVER` và "trả lại việc" (cập nhật `domain-rules.md` trong PR triển khai), quá hạn 15 phút, giới hạn 1–5 mỗi loại đồ dùng, chưa dọn định kỳ tự động
Module id: `housekeeping` · Phụ thuộc: `stay-access`, `notifications` · Mức: MVP · Sprint 2 (D08–D10) · Map: [capability-map.md](capability-map.md)
Nguồn quy tắc: `docs/domain-rules.md` §2, §4, §6; `CONSTRAINTS.md` C3, C5.4; `docs/chatbot-tools-spec.md` §4.4.

## Objective

Khách yêu cầu dọn phòng hoặc thêm đồ dùng (khăn, nước, đồ vệ sinh…) trên app; Buồng phòng nhận việc, làm và báo xong trên Web;
khách theo dõi trạng thái realtime. Module cũng tự tạo **việc dọn phòng sau khi khách trả phòng** để phòng quay về `VACANT`
mà Lễ tân không phải bấm tay.

**Người dùng:** khách lưu trú, Buồng phòng (`HOUSEKEEPING`), Lễ tân (`RECEPTION`, giám sát + hủy).

**User stories**
- Là khách, tôi bấm "Dọn phòng", chọn "Ngay bây giờ" hoặc một khung giờ, thêm ghi chú, gửi yêu cầu.
- Là khách, tôi chọn đồ cần thêm (2 khăn tắm, 4 chai nước) và gửi; tôi hủy được khi chưa có ai nhận việc.
- Là khách, tôi bật "Không làm phiền" để Buồng phòng biết không gõ cửa.
- Là nhân viên Buồng phòng, tôi thấy danh sách việc theo thứ tự ưu tiên, bấm "Nhận việc" để việc gắn với tôi, rồi "Bắt đầu" và "Hoàn tất".
- Là nhân viên Buồng phòng, sau khi khách trả phòng tôi thấy việc "Dọn phòng trả" và khi hoàn tất thì phòng tự chuyển sang trống.
- Là Lễ tân, tôi xem mọi yêu cầu, hủy hộ khách, và thấy ai đang làm việc nào.

**Không thuộc module này:** kiểm tra minibar/tính phí đồ dùng, quản lý kho vật tư, lịch dọn định kỳ hằng ngày, báo hỏng thiết bị.

## Tech Stack

Kế thừa các module trước. **Không thêm dependency mới.**

## Thay đổi nghiệp vụ cần cập nhật tài liệu

Spec thêm loại việc **`TURNOVER`** (dọn phòng sau khi trả phòng, do hệ thống tạo, không gắn với khách đang ở).
Khi spec được duyệt, PR triển khai phải cập nhật `docs/domain-rules.md` §2 và §4 cho khớp (theo luật trong `CLAUDE.md`).
Loại `TURNOVER` **không** xuất hiện trong tool `request_housekeeping` của chatbot.

## Thiết kế

### Dữ liệu (migration Alembic)

```
housekeeping_request
  id                 uuid PK
  room_id            uuid FK → room NOT NULL
  stay_id            uuid FK → stay NULL          -- NULL với TURNOVER
  type               hk_type NOT NULL             -- CLEANING | AMENITY | TURNOVER
  status             hk_status NOT NULL           -- REQUESTED | ASSIGNED | IN_PROGRESS | DONE | CANCELLED
  preferred_time     timestamptz NULL             -- NULL = càng sớm càng tốt (ASAP)
  note               text NULL
  source             text NOT NULL                -- APP | CHATBOT | SYSTEM
  assigned_to        uuid FK → staff NULL
  assigned_at, started_at, done_at timestamptz NULL
  cancel_reason      text NULL
  cancelled_by       text NULL
  idempotency_key    text NULL
  version            integer NOT NULL DEFAULT 0
  created_at, updated_at
  UNIQUE (stay_id) WHERE type = 'CLEANING' AND status IN ('REQUESTED','ASSIGNED','IN_PROGRESS')
  UNIQUE (room_id) WHERE type = 'TURNOVER' AND status IN ('REQUESTED','ASSIGNED','IN_PROGRESS')
  UNIQUE (stay_id, idempotency_key) WHERE idempotency_key IS NOT NULL

housekeeping_request_item           -- chỉ cho AMENITY
  id            uuid PK
  request_id    uuid FK → housekeeping_request ON DELETE CASCADE
  code          amenity_code NOT NULL    -- TOWEL | WATER | TOILETRIES | PILLOW | BLANKET | SLIPPERS | OTHER
  quantity      smallint NOT NULL CHECK (quantity BETWEEN 1 AND 5)

stay  (+ cột mới)
  do_not_disturb       boolean NOT NULL DEFAULT false
  dnd_updated_at       timestamptz NULL
```

- Dùng lại `status_history` (entity_type `HOUSEKEEPING`) từ `room-service`.
- `amenity_code=OTHER` bắt buộc có `note`. Tên hiển thị vi/en của từng mã nằm trong file i18n, không trong DB.

### State machine

```python
# housekeeping/state.py
TRANSITIONS = {
    (REQUESTED,   ASSIGNED):    {HOUSEKEEPING},           # nhận việc: assigned_to = chính người bấm
    (ASSIGNED,    IN_PROGRESS): {HOUSEKEEPING},           # chỉ người được gán
    (IN_PROGRESS, DONE):        {HOUSEKEEPING},           # chỉ người được gán
    (ASSIGNED,    REQUESTED):   {HOUSEKEEPING},           # trả lại việc (chỉ người được gán)
    (REQUESTED,   CANCELLED):   {GUEST, RECEPTION},
}
```

- Một hàm `transition(...)` như `room-service`: khóa hàng, kiểm tra cặp trạng thái → `409 INVALID_TRANSITION`, vai trò → `403`,
  `version` lệch → `409 CONFLICT`, ghi `status_history`, gọi `emit_status_changed`.
- **Chỉ người được gán** mới chuyển `IN_PROGRESS`/`DONE`/trả lại việc; người khác cùng vai trò → `403`.
  Hai người cùng bấm "Nhận việc" → một thành công, một `409 CONFLICT`.
- `(ASSIGNED → REQUESTED)` là bổ sung so với `domain-rules.md` (khi nhân viên nhận nhầm hoặc hết ca) — cập nhật tài liệu cùng PR.
- Lễ tân hủy phải có `reason`. Khách chỉ hủy khi `REQUESTED`.
- `TURNOVER` không cho `GUEST` thao tác và không bị hủy bởi `on_stay_closed`.

### Tạo yêu cầu (khách)

`POST /api/v1/guest/housekeeping-requests` (`current_active_stay`), header tùy chọn `Idempotency-Key`:

```json
{ "type": "AMENITY", "amenities": [ { "code": "TOWEL", "quantity": 2 } ], "preferred_time": "ASAP", "note": "", "source": "APP" }
```

| Điều kiện | Kết quả |
|---|---|
| Trường lạ (kể cả `room_id`, `stay_id`, `assigned_to`), `type=TURNOVER` | `400 VALIDATION_ERROR` |
| `AMENITY` thiếu `amenities`; `CLEANING` có `amenities`; `OTHER` thiếu `note`; tối đa 10 dòng | `400` |
| `preferred_time` không phải `"ASAP"` và nằm ngoài khoảng `[now, now + 24h]` hoặc sau `expected_checkout_at` | `400` |
| Stay `CHECKOUT_PENDING` | `409 STAY_CHECKOUT_PENDING` |
| Đã có `CLEANING` đang mở | `409 CONFLICT` kèm `details.existing_request_id` |
| Stay đã có ≥ 3 `AMENITY` đang mở | `409 TOO_MANY_OPEN_REQUESTS` |
| Cùng `Idempotency-Key` | Trả lại yêu cầu đã tạo (`200`) |
| Hợp lệ | `201` — output khớp tool `request_housekeeping` (`request_id`, `type`, `status`, `preferred_time`, `created_at`) |

Tạo `CLEANING` khi đang bật "Không làm phiền" → tự tắt "Không làm phiền" (khách đã chủ động mời vào dọn).

### Việc dọn phòng sau trả phòng (TURNOVER)

- Đăng ký `register_on_stay_closed` (chạy trong transaction đóng stay):
  1. Mọi yêu cầu `CLEANING`/`AMENITY` của stay còn `REQUESTED`/`ASSIGNED` → `CANCELLED` (`actor=SYSTEM`, `reason=STAY_CLOSED`);
     `IN_PROGRESS` → giữ nguyên để nhân viên tự hoàn tất.
  2. Tạo một `TURNOVER` (`source=SYSTEM`, `stay_id=NULL`) cho phòng, nếu chưa có cái đang mở.
- `TURNOVER` chuyển `DONE` → cùng transaction đặt `room.status = VACANT` (chỉ khi phòng đang `CLEANING`).
- Endpoint `POST /rooms/{id}/mark-vacant` của `stay-access` vẫn giữ cho Lễ tân; khi dùng, `TURNOVER` đang mở của phòng
  chuyển `CANCELLED` (`reason=MARKED_VACANT_BY_RECEPTION`).
- `TURNOVER` không gửi push cho khách (không còn khách); vẫn phát SSE cho Web.

### API

**Khách** (`/api/v1/guest`):

| Method | Path | Quyền | Mô tả |
|---|---|---|---|
| POST | `/housekeeping-requests` | `current_active_stay` | Tạo yêu cầu (ở trên) |
| GET | `/housekeeping-requests?status=` | `current_stay` | Yêu cầu của stay hiện tại (không gồm TURNOVER) |
| GET | `/housekeeping-requests/{id}` | `current_stay` | Chi tiết + lịch sử; của stay khác → `403`. Trả tên nhân viên dạng rút gọn ("Chị Lan"), không trả id |
| POST | `/housekeeping-requests/{id}/cancel` | `current_stay` | Chỉ khi `REQUESTED` |
| PUT | `/me/do-not-disturb` | `current_active_stay` | `{enabled}` → `204`; phát SSE `STAY` cho HOUSEKEEPING/RECEPTION |

**Nhân viên** (`/api/v1`):

| Method | Path | Quyền | Mô tả |
|---|---|---|---|
| GET | `/housekeeping-requests?status=&type=&mine=` | `HOUSEKEEPING`, `RECEPTION` | Mặc định: việc chưa kết thúc + kết thúc trong 12 giờ qua. Trả `room_number`, `do_not_disturb`; không trả tên khách cho `HOUSEKEEPING` |
| GET | `/housekeeping-requests/{id}` | `HOUSEKEEPING`, `RECEPTION` | Chi tiết + lịch sử |
| POST | `/housekeeping-requests/{id}/transition` | `HOUSEKEEPING` | `{to, version}` |
| POST | `/housekeeping-requests/{id}/cancel` | `RECEPTION` | `{reason, version}` |

**Thứ tự ưu tiên trên danh sách** (server sắp xếp): `TURNOVER` → `AMENITY` → `CLEANING` có `preferred_time` đã tới/ASAP → còn lại theo
`preferred_time`; trong cùng nhóm, cũ trước.

**Nhắc quá hạn:** yêu cầu `REQUESTED` quá 15 phút (tính từ `max(created_at, preferred_time)`) → SSE `housekeeping_overdue` tới
`HOUSEKEEPING` và `RECEPTION` một lần (cột `overdue_notified_at`), dùng chung job chạy mỗi phút của `room-service`.

**Nội bộ (cho express-checkout):** `count_open_requests(db, stay_id)`.

### Mẫu thông báo (bổ sung `notifications/templates`)

`HOUSEKEEPING.ASSIGNED|IN_PROGRESS|DONE|CANCELLED` bằng vi/en. Quay lại `REQUESTED` (trả việc) không gửi push.

### admin-web

- **Buồng phòng `/housekeeping`:** hai tab "Việc chờ" và "Việc của tôi". Thẻ việc: số phòng (chữ lớn), loại (biểu tượng),
  danh sách đồ dùng, giờ mong muốn, ghi chú, nhãn "Không làm phiền" nổi bật, đếm phút chờ, viền đỏ khi quá hạn.
  Nút một chạm theo trạng thái: "Nhận việc" → "Bắt đầu" → "Hoàn tất"; menu phụ "Trả lại việc".
  Giao diện ưu tiên **máy tính bảng/điện thoại dọc** (nhân viên cầm theo khi đi dọn): nút ≥ 48px, một cột ở màn hẹp.
- **Lễ tân `/reception/housekeeping`:** danh sách mọi việc có lọc trạng thái/loại/phòng, cột "Người làm", nút hủy (bắt buộc lý do).
  Sơ đồ phòng (`stay-access`) hiển thị biểu tượng "Không làm phiền" và "Đang dọn".
- Cập nhật qua `useStaffEvents`, tải lại khi kết nối lại.

### mobile-app

- **Màn "Dọn phòng & đồ dùng":**
  - Nút "Dọn phòng": chọn "Ngay bây giờ" hoặc khung giờ trong 24 giờ tới (bước 30 phút), ghi chú. Nếu đã có yêu cầu đang mở thì nút chuyển thành "Xem yêu cầu".
  - "Thêm đồ dùng": lưới biểu tượng các mã đồ dùng với bộ đếm 1–5, mục "Khác" bắt buộc ghi chú.
  - Công tắc "Không làm phiền".
- **Yêu cầu của tôi:** danh sách + chi tiết với thanh tiến trình, tên rút gọn người phụ trách, nút hủy khi `REQUESTED`.
  Route `/requests/HOUSEKEEPING/<id>`; làm mới theo FCM và chính sách 15 s.
- Dùng `Idempotency-Key` khi gửi như `room-service`.
- **Trang chủ:** thêm ô "Dọn phòng" và gộp yêu cầu đang mở vào thẻ "Đang xử lý".

## Commands

Kế thừa `foundation`. Bổ sung:

```bash
cd backend-api && uv run pytest -q tests/unit/housekeeping tests/integration/housekeeping
cd ../admin-web && npm test -- housekeeping
cd ../mobile-app && flutter test test/housekeeping
```

## Project Structure

```
backend-api/app/modules/housekeeping/
  models.py  schemas.py  state.py  service.py  repository.py  router_guest.py  router_staff.py  api.py  hooks.py (on_stay_closed)  jobs.py
backend-api/migrations/versions/xxxx_housekeeping.py
backend-api/tests/unit/housekeeping/  tests/integration/housekeeping/
admin-web/src/app/[locale]/(staff)/housekeeping/  page.tsx
admin-web/src/app/[locale]/(staff)/reception/housekeeping/
admin-web/src/components/housekeeping/  TaskList.tsx  TaskCard.tsx
mobile-app/lib/features/housekeeping/  housekeeping_screen.dart  amenity_picker.dart  request_detail_screen.dart  housekeeping_repository.dart
mobile-app/test/housekeeping/
```

## Code Style

Theo `room-service`: mọi đổi trạng thái qua `transition`, repository phía khách lọc theo `ctx.stay_id`, phát sự kiện qua `emit_status_changed`.

## Testing Strategy

| Mức | Nội dung bắt buộc |
|---|---|
| Unit | Bảng `TRANSITIONS`: 25 cặp × 4 actor; quy tắc "chỉ người được gán"; kiểm tra `preferred_time`; thứ tự ưu tiên danh sách |
| Integration — tạo | Body có `room_id`/`assigned_to`/`type=TURNOVER` → `400`; `AMENITY` thiếu `amenities` → `400`; `CLEANING` thứ hai khi đang mở → `409 CONFLICT`; `AMENITY` thứ 4 → `409`; `CHECKOUT_PENDING` → `409`; trùng `Idempotency-Key` → một yêu cầu; tạo `CLEANING` tắt "Không làm phiền" |
| Integration — **C5.4** | Chuyển không hợp lệ → `409 INVALID_TRANSITION`; hai người cùng nhận việc → một `409 CONFLICT`; người không được gán bấm "Hoàn tất" → `403` |
| Integration — **C5.1/C3** | Khách stay A xem/hủy yêu cầu stay B → `403`; `KITCHEN` gọi mọi endpoint housekeeping → `403`; `RECEPTION` gọi `/transition` → `403`; `HOUSEKEEPING` gọi `/cancel` → `403`; `HOUSEKEEPING` không nhận tên khách |
| Integration — TURNOVER | Đóng stay: yêu cầu mở bị hủy `STAY_CLOSED`, `IN_PROGRESS` giữ nguyên, tạo đúng một `TURNOVER`; `TURNOVER` → `DONE` đặt phòng `VACANT`; `mark-vacant` hủy `TURNOVER` đang mở; `TURNOVER` không tạo outbox push |
| Integration | Mỗi chuyển trạng thái có một `status_history` + một outbox (trừ TURNOVER và trả việc); nhắc quá hạn phát một lần |
| admin-web | Chỉ hiện nút hợp lệ theo trạng thái và người được gán; nhãn "Không làm phiền"; bố cục một cột ở màn hẹp |
| mobile-app | Bộ chọn đồ dùng giới hạn 1–5, "Khác" bắt buộc ghi chú; nút "Dọn phòng" chuyển thành "Xem yêu cầu" khi đã có yêu cầu mở |

Coverage `app/modules/housekeeping` ≥ 80%.

## Boundaries

- **Always:** đổi trạng thái qua `transition`; `assigned_to` chỉ lấy từ nhân viên đang đăng nhập; cập nhật `docs/domain-rules.md` cho `TURNOVER` và "trả lại việc" trong PR triển khai.
- **Ask first:** cho Lễ tân gán việc cho nhân viên cụ thể; thêm mã đồ dùng; đổi ngưỡng 3 `AMENITY` mở / 15 phút quá hạn; tính phí đồ dùng.
- **Never:** nhận `room_id`/`assigned_to` từ client; cho khách tạo `TURNOVER`; đổi `room.status` ngoài luồng `TURNOVER DONE` / `mark-vacant`.

## Success Criteria

1. Khách phòng 101 yêu cầu dọn phòng "Ngay bây giờ" → thẻ hiện trên Web Buồng phòng trong ≤ 1 s; gửi yêu cầu thứ hai thì app chỉ cho xem yêu cầu đang có.
2. Nhân viên A nhận việc → khách nhận push "Đã có nhân viên nhận"; nhân viên B không bấm được "Bắt đầu" việc đó.
3. A đi hết `IN_PROGRESS → DONE`; khách nhận push mỗi bước ≤ 5 s.
4. Khách yêu cầu 2 khăn + 4 nước → thẻ hiển thị đúng danh sách; khách hủy được khi chưa ai nhận.
5. Khách bật "Không làm phiền" → thẻ và sơ đồ phòng hiện nhãn trong ≤ 1 s.
6. Check-out phòng 101 → yêu cầu đang chờ bị hủy, xuất hiện việc "Dọn phòng trả"; hoàn tất → phòng 101 chuyển `VACANT` trên sơ đồ.
7. Màn Buồng phòng dùng tốt trên điện thoại dọc 360px.
8. Toàn bộ test trong Testing Strategy xanh; coverage `housekeeping` ≥ 80%, toàn backend ≥ 70%.

## Out of Scope (Deferred)

- Lễ tân/quản lý phân công việc cho từng nhân viên: V1 nhân viên tự nhận việc.
- Dọn phòng định kỳ hằng ngày tự động cho phòng đang ở: chờ phản hồi đơn vị thử nghiệm.
- Kiểm tra minibar, báo hỏng thiết bị, đồ thất lạc: nghiệp vụ riêng.
- Quản lý kho khăn/nước: ngoài phạm vi.
- Ảnh xác nhận đã dọn: cần lưu file.

## Open Questions

1. Có chấp nhận bổ sung `TURNOVER` và "trả lại việc" vào `domain-rules.md` không? (Spec đề xuất có, để phòng tự về `VACANT`.)
2. Ngưỡng quá hạn 15 phút cho Buồng phòng (Bếp là 10 phút) có hợp lý không?
3. Đồ dùng có cần giới hạn theo số khách (VD tối đa 2 khăn/khách) không? V1 chỉ giới hạn 1–5 mỗi loại.
4. Khách sạn mini có dọn phòng hằng ngày tự động không? Nếu có, nên đưa vào V1 thay vì để khách tự yêu cầu.
