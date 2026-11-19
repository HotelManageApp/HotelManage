# Spec: express-checkout — V1

Status: **approved** (2026-11-19, Tech Lead) — Open Questions giữ mặc định: gửi yêu cầu bất kỳ lúc nào, thêm `BILLING_VERIFIED → REJECTED` (cập nhật `domain-rules.md` trong PR triển khai), chưa có dòng đặt cọc, đánh giá chỉ lưu lại
Module id: `express-checkout` · Phụ thuộc: `stay-access`, `notifications`, `room-service`, `housekeeping` · Mức: Tốt · Sprint 3 (D15–D17) · Map: [capability-map.md](capability-map.md)
Nguồn quy tắc: `docs/domain-rules.md` §5; `CONSTRAINTS.md` C3, C4.2, C5.4; `docs/chatbot-tools-spec.md` §4.5.

## Objective

Khách gửi yêu cầu trả phòng ngay trên app (hoặc qua chatbot ở `concierge-actions`); Lễ tân đối soát hóa đơn trên Web
(tiền phòng + đồ ăn + phụ phí), khách xem hóa đơn trên app, Lễ tân thu tiền ngoài hệ thống rồi duyệt hoàn tất.
Hoàn tất thì **mọi token của khách bị thu hồi ngay**, phòng chuyển sang chờ dọn và việc `TURNOVER` được tạo tự động.

**Người dùng:** khách lưu trú, Lễ tân (`RECEPTION`).

**User stories**
- Là khách, tôi bấm "Trả phòng nhanh", xem tạm tính, chấm điểm trải nghiệm (tùy chọn) và xác nhận gửi yêu cầu.
- Là khách, tôi nhận thông báo khi hóa đơn đã được đối soát và xem chi tiết từng khoản trên app trước khi xuống quầy.
- Là khách, nếu yêu cầu bị từ chối (VD còn đơn chưa giao, cần kiểm tra phòng), tôi thấy lý do và dùng app bình thường trở lại.
- Là Lễ tân, tôi thấy yêu cầu mới ngay trên Web, xem hóa đơn tự tổng hợp, thêm phụ phí/giảm giá, chốt hóa đơn, in phiếu,
  chọn hình thức thanh toán và duyệt hoàn tất.
- Là Lễ tân, tôi xem được hóa đơn tạm tính của bất kỳ phòng nào, kể cả khi khách trả phòng tại quầy.

**Không thuộc module này:** thanh toán online (giả định 2), hóa đơn VAT điện tử, gọi trả phòng qua chatbot (`concierge-actions` gọi API của module này).

## Tech Stack

Kế thừa các module trước. **Không thêm dependency mới.** In hóa đơn bằng CSS in (cùng cách với phiếu check-in, ưu tiên K80).

## Thiết kế

### Dữ liệu (migration Alembic)

```
checkout_request
  id                 uuid PK
  stay_id            uuid FK → stay NOT NULL
  status             checkout_status NOT NULL   -- CHECKOUT_REQUESTED | BILLING_VERIFIED | COMPLETED | REJECTED
  source             text NOT NULL              -- APP | CHATBOT
  feedback_rating    smallint NULL CHECK (feedback_rating BETWEEN 1 AND 5)
  feedback_note      text NULL                  -- tối đa 500 ký tự
  bill_snapshot      jsonb NULL                 -- chốt khi BILLING_VERIFIED, không sửa về sau
  total_vnd          bigint NULL                -- = bill_snapshot.total_vnd
  payment_method     text NULL                  -- CASH | BANK_TRANSFER | CARD | OTHER (ghi nhận, không xử lý tiền)
  reject_reason      text NULL
  verified_by, completed_by, rejected_by  uuid FK → staff NULL
  verified_at, completed_at, rejected_at  timestamptz NULL
  overdue_notified_at timestamptz NULL
  version            integer NOT NULL DEFAULT 0
  created_at, updated_at
  UNIQUE (stay_id) WHERE status IN ('CHECKOUT_REQUESTED','BILLING_VERIFIED')

stay_charge                                     -- phụ phí/giảm giá Lễ tân nhập
  id            uuid PK
  stay_id       uuid FK → stay NOT NULL
  kind          text NOT NULL                   -- EXTRA | DISCOUNT
  description   text NOT NULL                   -- "Minibar: 2 bia", "Trả phòng trễ"
  amount_vnd    bigint NOT NULL CHECK (amount_vnd > 0)   -- DISCOUNT được trừ khi tính tổng
  created_by    uuid FK → staff
  created_at    timestamptz NOT NULL
  deleted_at    timestamptz NULL                -- xóa mềm, chỉ trước khi chốt hóa đơn
```

- Dùng lại `status_history` (entity_type `CHECKOUT`).
- `stay_charge` gắn với stay (không gắn với yêu cầu) để dùng được cả khi trả phòng tại quầy.

### Hóa đơn

Một hàm duy nhất tính hóa đơn, dùng cho tạm tính, đối soát và in:

```python
# express_checkout/billing.py
async def build_bill(db, stay_id: UUID) -> Bill:
    # room:     stay.room_charge_vnd (nhập khi check-in, Lễ tân sửa được qua PATCH /stays/{id} của stay-access)
    # food:     từng đơn COMPLETED (room_service.get_stay_food_total) → dòng theo đơn, kèm món
    # extras:   stay_charge kind=EXTRA chưa xóa
    # discount: stay_charge kind=DISCOUNT chưa xóa
    # total_vnd = room + food + extras − discount; nếu < 0 → lỗi 409 NEGATIVE_TOTAL
    # open_orders: số đơn PENDING/CONFIRMED/PREPARING/DELIVERING (không cộng tiền, chỉ cảnh báo)
```

```json
{
  "stay": { "room_number": "101", "guest_name": "Nguyen Van A", "checkin_at": "...", "expected_checkout_at": "..." },
  "lines": [
    { "type": "ROOM",     "description": "Tiền phòng", "amount_vnd": 1200000 },
    { "type": "FOOD",     "description": "Đơn #A1B2 (2 món)", "amount_vnd": 130000, "order_id": "uuid" },
    { "type": "EXTRA",    "description": "Minibar: 2 bia", "amount_vnd": 60000 },
    { "type": "DISCOUNT", "description": "Khách quen", "amount_vnd": 50000 }
  ],
  "total_vnd": 1340000,
  "open_orders": 0,
  "currency": "VND",
  "generated_at": "..."
}
```

### State machine

```python
TRANSITIONS = {
    (CHECKOUT_REQUESTED, BILLING_VERIFIED): {RECEPTION},
    (CHECKOUT_REQUESTED, REJECTED):         {RECEPTION},   # bắt buộc reason
    (BILLING_VERIFIED,   COMPLETED):        {RECEPTION},   # bắt buộc payment_method
    (BILLING_VERIFIED,   REJECTED):         {RECEPTION},   # bắt buộc reason (VD khách không đồng ý hóa đơn)
}
```

- `(BILLING_VERIFIED → REJECTED)` bổ sung so với `domain-rules.md` §5 (khách khiếu nại hóa đơn, cần sửa và chốt lại) — cập nhật tài liệu trong PR triển khai.
- Hàm `transition(...)` cùng mẫu với `room-service`: khóa hàng, `409 INVALID_TRANSITION`, `403`, `version` lệch `409 CONFLICT`,
  ghi `status_history`, gọi `emit_status_changed(entity_type=CHECKOUT, ...)`.

**Tác động lên stay theo từng bước (cùng transaction):**

| Bước | Tác động |
|---|---|
| Tạo `CHECKOUT_REQUESTED` | `stay.status = CHECKOUT_PENDING` → khách không tạo đơn/yêu cầu mới (`current_active_stay` trả `409`) |
| `→ BILLING_VERIFIED` | Điều kiện: `open_orders = 0`, không thì `409 OPEN_ORDERS_EXIST`. Chụp `bill_snapshot`, `total_vnd`. Sau bước này không sửa `stay_charge`/tiền phòng được nữa (`409 BILL_LOCKED`) |
| `→ COMPLETED` | Gọi `stay_access.close_stay(db, stay_id, actor)`: stay `CLOSED`, revoke mọi session, phòng `CLEANING`, chạy các hook `on_stay_closed` (hủy yêu cầu mở, tạo `TURNOVER`, xóa lịch sử chat, gửi lời cảm ơn) |
| `→ REJECTED` | `stay.status = ACTIVE`; khách gửi lại yêu cầu mới được |

- `close_stay` là **cùng một hàm** mà check-out tại quầy của `stay-access` dùng — không có hai đường đóng stay.
- Check-out tại quầy (`POST /stays/{id}/checkout`) khi stay đang có yêu cầu mở → `409 CHECKOUT_REQUEST_OPEN`; Web chuyển Lễ tân sang màn yêu cầu đó.

### API

**Khách** (`/api/v1/guest`):

| Method | Path | Quyền | Mô tả |
|---|---|---|---|
| GET | `/checkout/preview` | `current_stay` | Hóa đơn tạm tính (cùng `build_bill`, gắn nhãn `is_estimate: true`); không trả `guest_name` thừa |
| POST | `/checkout-requests` | `current_active_stay` | `{guest_confirmed: true, feedback_rating?, feedback_note?, source}` → `201 {checkout_request_id, status, open_orders, message_key}` (khớp output tool §4.5). Thiếu `guest_confirmed=true` hoặc có trường lạ → `400`. Đã có yêu cầu mở → `409 CONFLICT` kèm `existing_request_id` (do stay đã `CHECKOUT_PENDING`, `current_active_stay` trả `409 STAY_CHECKOUT_PENDING` — cả hai mã đều được tool hiểu là "đã gửi trước đó") |
| GET | `/checkout-requests/current` | `current_stay` | Yêu cầu gần nhất + `bill_snapshot` nếu đã chốt; `404` nếu chưa có |

**Nhân viên** (`/api/v1`, quyền `RECEPTION`):

| Method | Path | Mô tả |
|---|---|---|
| GET | `/checkout-requests?status=` | Hàng đợi; mặc định yêu cầu mở + kết thúc trong 24 giờ qua |
| GET | `/checkout-requests/{id}` | Chi tiết + hóa đơn hiện tại (hoặc snapshot) + feedback + lịch sử |
| POST | `/checkout-requests/{id}/verify` | `{version}` → `BILLING_VERIFIED` |
| POST | `/checkout-requests/{id}/complete` | `{payment_method, version}` → `COMPLETED` |
| POST | `/checkout-requests/{id}/reject` | `{reason, version}` → `REJECTED` |
| GET | `/stays/{id}/bill` | Hóa đơn tạm tính của bất kỳ stay nào đang mở (dùng cả cho trả phòng tại quầy) |
| POST | `/stays/{id}/charges` · DELETE `/stays/{id}/charges/{charge_id}` | Thêm/xóa phụ phí, giảm giá; `BILL_LOCKED` khi đã chốt |

`KITCHEN`/`HOUSEKEEPING` gọi bất kỳ endpoint nào ở trên → `403`.

**Nhắc quá hạn:** yêu cầu ở `CHECKOUT_REQUESTED` quá 10 phút → SSE `checkout_overdue` tới `RECEPTION` một lần (dùng chung job mỗi phút).

### Thông báo (bổ sung `notifications/templates`)

| Trạng thái | Push cho khách | SSE |
|---|---|---|
| `CHECKOUT_REQUESTED` | Không (khách vừa tự gửi) | `RECEPTION` + toast + âm báo |
| `BILLING_VERIFIED` | "Hóa đơn đã sẵn sàng, mời Quý khách xem và xuống quầy" (không ghi số tiền trong payload) | `RECEPTION` |
| `REJECTED` | "Yêu cầu trả phòng chưa được duyệt: xem lý do" | `RECEPTION` |
| `COMPLETED` | Không gửi riêng — lời cảm ơn do sự kiện `STAY/CLOSED` của `notifications` gửi (tránh hai thông báo) | `RECEPTION` |

### admin-web (`/reception/checkout`)

- **Hàng đợi:** thẻ theo trạng thái, số phòng, giờ gửi, số đơn đồ ăn còn mở (cảnh báo đỏ nếu > 0), điểm đánh giá.
- **Chi tiết / bảng đối soát:** các dòng hóa đơn tự tổng hợp; sửa tiền phòng (gọi `PATCH /stays/{id}`); thêm phụ phí/giảm giá với
  mô tả bắt buộc; nút "Chốt hóa đơn" (khóa khi còn đơn mở, có link sang `/reception/orders` lọc theo phòng);
  sau khi chốt: nút "In hóa đơn", chọn hình thức thanh toán, "Hoàn tất trả phòng" (hộp thoại xác nhận nói rõ khách sẽ bị đăng xuất);
  "Từ chối" (bắt buộc lý do) ở cả hai bước.
- **Trả phòng tại quầy** (màn chi tiết stay của `stay-access`): thêm nút "Xem hóa đơn" mở cùng bảng đối soát (`/stays/{id}/bill`) và in được.
- Cập nhật qua `useStaffEvents`, tải lại khi kết nối lại.

### mobile-app

- **Trang chủ:** nút "Trả phòng nhanh" (ẩn khi đã có yêu cầu mở; thay bằng thẻ trạng thái trả phòng).
- **Màn xác nhận:** tạm tính từ `/checkout/preview` có nhãn "Tạm tính — Lễ tân sẽ đối soát", cảnh báo nếu còn đơn đang xử lý,
  chọn sao 1–5 và ghi chú (tùy chọn), nút "Xác nhận trả phòng" (gửi `guest_confirmed: true`).
- **Màn theo dõi:** thanh tiến trình `Đã gửi → Đã đối soát → Hoàn tất`; khi `BILLING_VERIFIED` hiện hóa đơn chi tiết từ `bill_snapshot`;
  khi `REJECTED` hiện lý do và nút quay về trang chủ. Route `/requests/CHECKOUT/<id>`; làm mới theo FCM và chính sách 15 s.
- Khi đang `CHECKOUT_PENDING`: các nút đặt món/dọn phòng hiện trạng thái khóa với chú thích; xem đơn cũ vẫn được.
- Sau `COMPLETED`: request kế tiếp nhận `401` → màn chào hiện lời cảm ơn (phân biệt bằng mã `revoke_reason=CHECKOUT` trả trong body `401`:
  `{"error":{"code":"UNAUTHORIZED","details":[{"reason":"STAY_CLOSED"}]}}` — không lộ thông tin khác).

## Commands

```bash
cd backend-api && uv run pytest -q tests/unit/express_checkout tests/integration/express_checkout
cd ../admin-web && npm test -- checkout
cd ../mobile-app && flutter test test/express_checkout
```

## Project Structure

```
backend-api/app/modules/express_checkout/
  models.py  schemas.py  state.py  billing.py  service.py  repository.py  router_guest.py  router_staff.py  jobs.py
backend-api/app/modules/stay_access/service.py      # tách close_stay() dùng chung (sửa nhỏ)
backend-api/migrations/versions/xxxx_express_checkout.py
backend-api/tests/unit/express_checkout/  tests/integration/express_checkout/
admin-web/src/app/[locale]/(staff)/reception/checkout/  page.tsx  [id]/
admin-web/src/components/checkout/  BillTable.tsx  ChargeForm.tsx  PrintableBill.tsx
mobile-app/lib/features/express_checkout/  checkout_confirm_screen.dart  checkout_status_screen.dart  checkout_repository.dart
mobile-app/test/express_checkout/
```

## Code Style

Theo `room-service`. Riêng module này: tiền `int` VND; hóa đơn chỉ tính trong `build_bill`; đóng stay chỉ qua `close_stay`.

## Testing Strategy

| Mức | Nội dung bắt buộc |
|---|---|
| Unit | `build_bill`: chỉ cộng đơn `COMPLETED`, đơn hủy không tính, phụ phí/giảm giá đã xóa không tính, tổng âm → lỗi; bảng `TRANSITIONS` 16 cặp × 4 actor |
| Integration — tạo | Thiếu `guest_confirmed` → `400`; body có `room_id`/`total_vnd` → `400`; tạo xong stay `CHECKOUT_PENDING`, tạo đơn đồ ăn/dọn phòng → `409`; gửi lần hai → `409` |
| Integration — **C5.4** | `COMPLETED` thẳng từ `CHECKOUT_REQUESTED` → `409`; chốt khi còn đơn mở → `409 OPEN_ORDERS_EXIST`; sửa phụ phí sau khi chốt → `409 BILL_LOCKED`; hai Lễ tân bấm cùng lúc → một `409 CONFLICT`; hoàn tất thiếu `payment_method` → `400`; từ chối thiếu lý do → `400` |
| Integration — **C4.2 / C5.1** | Token hợp lệ trước `COMPLETED` → `401` ngay sau đó (mọi thiết bị của stay), body có `reason=STAY_CLOSED`; mã phòng → `401`; phòng `CLEANING`; có đúng một `TURNOVER`; yêu cầu dọn phòng đang chờ bị hủy; `chat_message` bị xóa; lời cảm ơn được gửi một lần |
| Integration | `REJECTED` → stay `ACTIVE`, khách tạo đơn được và gửi yêu cầu trả phòng mới được; `bill_snapshot` không đổi khi tiền phòng/giá món đổi sau đó |
| Integration — RBAC | `KITCHEN`/`HOUSEKEEPING` → `403` mọi endpoint; khách stay B đọc yêu cầu stay A → `403`; check-out tại quầy khi có yêu cầu mở → `409 CHECKOUT_REQUEST_OPEN` |
| Integration | Push đúng bảng Thông báo (không gửi cho `CHECKOUT_REQUESTED`, `COMPLETED`); payload không có số tiền; nhắc quá hạn một lần |
| admin-web | Nút "Chốt hóa đơn" khóa khi còn đơn mở; tổng hiển thị khớp API; hộp thoại xác nhận hoàn tất |
| mobile-app | Tạm tính có nhãn; nút đặt món khóa khi `CHECKOUT_PENDING`; `401 STAY_CLOSED` → màn chào có lời cảm ơn |

Coverage `app/modules/express_checkout` ≥ 85% (đụng tới thu hồi phiên).

## Boundaries

- **Always:** đóng stay qua `close_stay`; tính tiền qua `build_bill`; chụp `bill_snapshot` khi chốt; cập nhật `domain-rules.md` cho bước `BILLING_VERIFIED → REJECTED` trong PR triển khai.
- **Ask first:** tích hợp thanh toán online/QR ngân hàng; tự động hoàn tất không cần Lễ tân; cho khách rút lại yêu cầu; tính VAT/phí dịch vụ.
- **Never:** để khách tự hoàn tất trả phòng; nhận số tiền từ client; giữ phiên khách sau `COMPLETED`; tạo đường đóng stay thứ hai.

## Success Criteria

1. Khách phòng 101 đã có 1 đơn đồ ăn hoàn tất bấm "Trả phòng nhanh" → thấy tạm tính, xác nhận; Lễ tân thấy yêu cầu trong ≤ 1 s kèm âm báo.
2. Khách thử đặt món sau khi gửi → app khóa nút, API trả `409`.
3. Lễ tân thêm "Minibar 60.000đ", chốt hóa đơn → khách nhận push ≤ 5 s và xem đúng từng dòng; tổng trên app, Web và bản in trùng nhau.
4. Lễ tân chọn "Tiền mặt", hoàn tất → mọi điện thoại của phòng 101 về màn chào kèm lời cảm ơn; phòng 101 `CLEANING`; Buồng phòng có việc "Dọn phòng trả".
5. Khi còn đơn đang giao, Lễ tân không chốt được hóa đơn và thấy link tới đơn đó.
6. Từ chối kèm lý do → khách thấy lý do, dùng app bình thường và gửi lại được.
7. Toàn bộ test trong Testing Strategy xanh; coverage `express_checkout` ≥ 85%, toàn backend ≥ 70%.

## Out of Scope (Deferred)

- Thanh toán online / VietQR / cổng thẻ: giả định 2; cân nhắc sau chạy thử.
- Hóa đơn VAT điện tử, xuất PDF gửi email: cần tích hợp nhà cung cấp hóa đơn.
- Khách rút lại yêu cầu trả phòng: hiếm gặp; khách gọi Lễ tân để từ chối hộ.
- Tự động hoàn tất khi đã thanh toán trước: chưa có thanh toán trong hệ thống.
- Báo cáo doanh thu, thống kê đánh giá: sau chạy thử.

## Open Questions

1. Có cho gửi yêu cầu trả phòng **bất kỳ lúc nào** không, hay chỉ trong khoảng (VD) 12 giờ trước `expected_checkout_at`? Spec hiện cho bất kỳ lúc nào.
2. Có chấp nhận bổ sung bước `BILLING_VERIFIED → REJECTED` vào `domain-rules.md` không?
3. Khách sạn mini có thu tiền đặt cọc khi check-in không? Nếu có, hóa đơn cần thêm dòng "Đã cọc" (trừ vào tổng).
4. Đánh giá 1–5 sao có cần hiện cho quản lý/thống kê ngay ở V1 không, hay chỉ lưu lại?
