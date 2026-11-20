# Domain Rules — Quy tắc nghiệp vụ

Nguồn sự thật cho trạng thái, quyền chuyển trạng thái và thông báo. Backend enforce toàn bộ; frontend chỉ phản ánh.
Chuyển trạng thái không hợp lệ → `409 Conflict`. Sai vai trò → `403 Forbidden`.

---

## 1. Thực thể chính

| Thực thể | Ghi chú |
|---|---|
| `room` | Phòng vật lý. Trạng thái: `VACANT` → `OCCUPIED` → `CLEANING` → `VACANT`. |
| `stay` | Một kỳ lưu trú gắn với `room`. Giữ `room_code_hash`, `checkin_at`, `expected_checkout_at`, `status` (`ACTIVE`, `CHECKOUT_PENDING`, `CLOSED`). |
| `stay_session` | Phiên đăng nhập của thiết bị khách: `jti`, `stay_id`, `fcm_token`, `revoked_at`. |
| `food_order` / `order_item` | Đơn đồ ăn, giá chốt tại thời điểm đặt. |
| `housekeeping_request` | Yêu cầu dọn phòng / thêm đồ dùng (`type`: `CLEANING`, `AMENITY`). |
| `checkout_request` | Yêu cầu trả phòng nhanh. |
| `status_history` | Lịch sử chuyển trạng thái (ai, khi nào, từ → đến, lý do) cho mọi yêu cầu. |

## 2. Vòng đời mã phòng & phiên lưu trú

```mermaid
stateDiagram-v2
    [*] --> VACANT
    VACANT --> OCCUPIED: RECEPTION check-in\n(sinh mã phiên/QR, tạo stay ACTIVE)
    OCCUPIED --> OCCUPIED: Khách đổi mã → stay_session_token
    OCCUPIED --> CLEANING: RECEPTION check-out / duyệt Express Checkout\n(revoke mọi stay_session)
    CLEANING --> VACANT: HOUSEKEEPING hoàn tất việc TURNOVER
(hoặc RECEPTION "Đánh dấu đã dọn")
```

- Mã phiên dùng được khi `stay.status` là `ACTIVE` hoặc `CHECKOUT_PENDING` (lúc chờ trả phòng chỉ xem, không tạo yêu cầu mới), tới `expected_checkout_at` + 6 giờ. Nhiều thiết bị cùng stay được phép (mỗi thiết bị một `jti`, tối đa 6).
- Lễ tân có thể **cấp lại mã** (revoke mã cũ + mọi session cũ) khi nghi lộ.
- Khi stay `CLOSED`: mọi token → `401`; đơn đồ ăn `PENDING`/`CONFIRMED` và yêu cầu buồng phòng `REQUESTED`/`ASSIGNED` chuyển `CANCELLED` (lý do `STAY_CLOSED`); đơn đang nấu/giao và việc dọn đang làm được giữ nguyên; hệ thống mở một việc `TURNOVER` cho phòng.
- Lễ tân "Đánh dấu đã dọn" (`CLEANING → VACANT`) thì việc `TURNOVER` chưa bắt đầu của phòng bị hủy (lý do `MARKED_VACANT_BY_RECEPTION`).

## 3. Đặt đồ ăn (Room Service)

```mermaid
stateDiagram-v2
    [*] --> PENDING: GUEST tạo đơn (app/chatbot)
    PENDING --> CONFIRMED: KITCHEN
    PENDING --> CANCELLED: GUEST / KITCHEN / RECEPTION
    CONFIRMED --> PREPARING: KITCHEN
    CONFIRMED --> CANCELLED: KITCHEN / RECEPTION (bắt buộc lý do)
    PREPARING --> DELIVERING: KITCHEN
    DELIVERING --> COMPLETED: KITCHEN
    COMPLETED --> [*]
    CANCELLED --> [*]
```

| Chuyển | GUEST | KITCHEN | RECEPTION | HOUSEKEEPING |
|---|:-:|:-:|:-:|:-:|
| tạo → `PENDING` | ✅ | | | |
| `PENDING → CONFIRMED` | | ✅ | | |
| `PENDING → CANCELLED` | ✅ | ✅ | ✅ | |
| `CONFIRMED → PREPARING → DELIVERING → COMPLETED` | | ✅ | | |
| `CONFIRMED → CANCELLED` | | ✅ | ✅ | |

- Khách chỉ được hủy khi đơn còn `PENDING`.
- Món phải `available = true` lúc tạo đơn; tổng tiền do backend tính từ giá trong DB.
- Đơn `PENDING` quá 10 phút chưa xác nhận → nhắc Lễ tân trên Web.

## 4. Dọn phòng / thêm đồ dùng (Housekeeping)

```mermaid
stateDiagram-v2
    [*] --> REQUESTED: GUEST tạo yêu cầu
    REQUESTED --> ASSIGNED: HOUSEKEEPING nhận việc (gán nhân viên)
    ASSIGNED --> IN_PROGRESS: HOUSEKEEPING
    IN_PROGRESS --> DONE: HOUSEKEEPING
    ASSIGNED --> REQUESTED: HOUSEKEEPING trả lại việc (chỉ người được gán)
    REQUESTED --> CANCELLED: GUEST / RECEPTION / SYSTEM
    ASSIGNED --> CANCELLED: SYSTEM (stay đóng, phòng được đánh dấu đã dọn)
    DONE --> [*]
    CANCELLED --> [*]
```

| Chuyển | GUEST | HOUSEKEEPING | RECEPTION | KITCHEN |
|---|:-:|:-:|:-:|:-:|
| tạo → `REQUESTED` | ✅ | | | |
| `REQUESTED → ASSIGNED → IN_PROGRESS → DONE` | | ✅ | | |
| `ASSIGNED → REQUESTED` (trả lại việc) | | ✅ | | |
| `REQUESTED → CANCELLED` | ✅ | | ✅ | |

- Khách có thể chọn khung giờ mong muốn (`preferred_time`) hoặc "Không làm phiền".
- Một stay chỉ có tối đa 1 yêu cầu `CLEANING` đang mở cùng lúc (tránh spam), tối đa 3 yêu cầu `AMENITY` đang mở.
- Loại yêu cầu: `CLEANING`, `AMENITY` (khách tạo) và `TURNOVER` (hệ thống tạo khi trả phòng, không gắn stay, khách không thấy). Mỗi phòng tối đa 1 `TURNOVER` đang mở; `TURNOVER → DONE` đưa phòng từ `CLEANING` về `VACANT`.
- Chỉ nhân viên được gán mới chuyển `IN_PROGRESS`, `DONE` hoặc trả lại việc.

## 5. Trả phòng nhanh (Express Checkout)

```mermaid
stateDiagram-v2
    [*] --> CHECKOUT_REQUESTED: GUEST gửi yêu cầu (app/chatbot, guest_confirmed=true)
    CHECKOUT_REQUESTED --> BILLING_VERIFIED: RECEPTION chốt hóa đơn (phòng + đồ ăn + phụ phí − giảm giá)
    BILLING_VERIFIED --> COMPLETED: RECEPTION duyệt hoàn tất (bắt buộc hình thức thanh toán)
    CHECKOUT_REQUESTED --> REJECTED: RECEPTION (bắt buộc lý do, VD còn nợ)
    BILLING_VERIFIED --> REJECTED: RECEPTION (bắt buộc lý do, VD khách không đồng ý hóa đơn)
    COMPLETED --> [*]
    REJECTED --> [*]
```

| Chuyển | GUEST | RECEPTION | KITCHEN | HOUSEKEEPING |
|---|:-:|:-:|:-:|:-:|
| tạo → `CHECKOUT_REQUESTED` | ✅ | | | |
| `CHECKOUT_REQUESTED → BILLING_VERIFIED → COMPLETED` | | ✅ | | |
| `CHECKOUT_REQUESTED → REJECTED`, `BILLING_VERIFIED → REJECTED` | | ✅ | | |

- Mỗi stay tối đa **một** yêu cầu đang mở (`CHECKOUT_REQUESTED` hoặc `BILLING_VERIFIED`).
- Khi `CHECKOUT_REQUESTED`: `stay.status = CHECKOUT_PENDING`; khách vẫn xem được trạng thái và hóa đơn nhưng không tạo đơn/yêu cầu mới (`409`).
- `→ BILLING_VERIFIED` chỉ khi không còn đơn đồ ăn đang mở (`409 OPEN_ORDERS_EXIST` kèm danh sách đơn). Hóa đơn được chụp lại
  (`bill_snapshot`) và **khóa**: không sửa phụ phí/giảm giá hay tiền phòng nữa (`409 BILL_LOCKED`) cho tới khi yêu cầu bị từ chối.
- Khi `COMPLETED`: đóng stay bằng **cùng một hàm** với trả phòng tại quầy — `stay.status = CLOSED`, **revoke ngay** mọi
  `stay_session` (request sau đó → `401`, `reason = STAY_CLOSED`), phòng → `CLEANING`, hủy yêu cầu còn chờ, tạo việc `TURNOVER`
  (mục 2, 4), xóa lịch sử chat, gửi một lời cảm ơn (không gửi thêm push riêng cho `COMPLETED`).
- Khi `REJECTED`: `stay.status = ACTIVE`; khách thấy lý do, dùng app bình thường và gửi yêu cầu mới được.
- Trả phòng tại quầy khi stay đang có yêu cầu mở → `409 CHECKOUT_REQUEST_OPEN` (xử lý yêu cầu đó trước).
- Tổng tiền do backend tính (`build_bill`); số tiền không bao giờ nhận từ client. Chỉ `RECEPTION` thao tác các bước.

## 6. Ma trận phân việc tổng hợp

| Nghiệp vụ | Xử lý chính | Giám sát | Khách thấy |
|---|---|---|---|
| Đặt đồ ăn | KITCHEN | RECEPTION (read + hủy) | Trạng thái realtime + FCM |
| Dọn phòng / đồ dùng | HOUSEKEEPING | RECEPTION (read + hủy) | Trạng thái realtime + FCM |
| Express Checkout | RECEPTION | — | Trạng thái realtime + FCM |
| Check-in / cấp mã | RECEPTION | — | — |
| Khiếu nại / hỏi đáp khác | RECEPTION | — | Phản hồi qua app |

## 7. Quy tắc thông báo đẩy (FCM)

- **Mỗi lần trạng thái đổi** (food_order, housekeeping_request, checkout_request) → gửi FCM tới mọi `stay_session`
  còn hiệu lực của stay đó.
- Gửi **sau khi transaction DB commit** (outbox pattern hoặc background task), không trong transaction.
- Payload `data` (không chứa thông tin nhạy cảm, không chứa mã phòng):
  ```json
  { "type": "FOOD_ORDER|HOUSEKEEPING|CHECKOUT", "entity_id": "uuid", "status": "PREPARING",
    "title_key": "order.preparing", "occurred_at": "ISO-8601" }
  ```
- `notification` title/body theo ngôn ngữ của session (`vi`, `en`, …).
- Token FCM không hợp lệ (`UNREGISTERED`) → xóa khỏi session. Retry tối đa 3 lần với backoff.
- Khi stay `CLOSED`: gửi một thông báo cuối "Cảm ơn quý khách", rồi xóa `fcm_token` của mọi session.
- Web quản trị nhận cập nhật realtime qua WebSocket/SSE (không dùng FCM) — kênh theo vai trò:
  `kitchen`, `housekeeping`, `reception`.
- App khách có fallback: khi mở màn hình theo dõi, poll/WS để đồng bộ nếu FCM trễ.
