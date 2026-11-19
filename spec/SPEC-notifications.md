# Spec: notifications — V1

Status: **approved** (2026-11-19, Tech Lead) — Open Questions giữ mặc định: Firebase project chốt khi tạo, không commit `google-services.json`, một âm báo chung; duyệt dependency `google-auth`, `firebase_core`, `firebase_messaging`, `flutter_local_notifications`
Module id: `notifications` · Phụ thuộc: `stay-access` · Mức: MVP · Sprint 2 (D10–D11, trước mốc M2 D14) · Map: [capability-map.md](capability-map.md)
Nguồn quy tắc: `docs/domain-rules.md` §7, `CONSTRAINTS.md` C4.5, C6.

## Objective

Mỗi khi trạng thái một yêu cầu thay đổi, **khách nhận thông báo đẩy (FCM) trên điện thoại** trong ≤ 5 giây
và **nhân viên thấy cập nhật trên Web ngay** mà không phải tải lại trang. Các module nghiệp vụ chỉ gọi một hàm
`emit_status_changed(...)`, không phải biết gì về FCM hay SSE.

**Người dùng:** khách lưu trú (nhận push), nhân viên 3 bộ phận (nhận realtime trên Web), dev các module sau (dùng hàm emit).

**User stories**
- Là khách, khi Bếp chuyển đơn sang "Đang giao", điện thoại tôi hiện thông báo bằng ngôn ngữ tôi đã chọn; chạm vào thì mở đúng đơn đó.
- Là nhân viên Bếp, đơn mới hiện ngay trên màn hàng đợi kèm thông báo nhỏ (và âm báo nếu tôi bật).
- Là Lễ tân, tôi thấy mọi thay đổi của cả Bếp và Buồng phòng theo thời gian thực.
- Là dev, nếu transaction đổi trạng thái bị rollback thì **không** có thông báo nào được gửi.
- Là khách đã trả phòng, tôi nhận một lời cảm ơn cuối cùng, sau đó không nhận thêm thông báo nào nữa.

**Không thuộc module này:** nội dung nghiệp vụ của từng trạng thái (do module phát sự kiện quyết định), nhắc đơn quá hạn (`room-service`),
gửi email/SMS.

## Tech Stack

Kế thừa các module trước. Dependency mới (cần duyệt):

| Package | Dependency | Lý do |
|---|---|---|
| backend-api | `google-auth` | Lấy OAuth token cho FCM HTTP v1 API (gửi qua `httpx` có sẵn), nhẹ hơn `firebase-admin` |
| mobile-app | `firebase_core`, `firebase_messaging` | Nhận FCM |
| mobile-app | `flutter_local_notifications` | Hiển thị thông báo khi app đang mở (foreground) và tạo notification channel |

admin-web **không** thêm dependency: SSE đọc bằng `fetch` + `ReadableStream` (gửi được header `Authorization`, điều mà `EventSource` không làm được).

## Thiết kế

### Hợp đồng cho module khác

```python
# backend-api/app/modules/notifications/api.py
class EntityType(StrEnum):
    FOOD_ORDER = "FOOD_ORDER"
    HOUSEKEEPING = "HOUSEKEEPING"
    CHECKOUT = "CHECKOUT"
    STAY = "STAY"

async def emit_status_changed(
    db: AsyncSession, *, entity_type: EntityType, entity_id: UUID, stay_id: UUID,
    status: str, room_number: str, actor: str,          # actor: "GUEST" | "STAFF:<id>" | "SYSTEM"
) -> None:
    """Gọi BÊN TRONG transaction đổi trạng thái. Ghi outbox + pg_notify; chỉ có hiệu lực khi transaction commit."""
```

- Hàm này làm 2 việc trong **cùng transaction** với thay đổi nghiệp vụ:
  1. Thêm một dòng vào `notification_outbox` (cho push tới khách).
  2. `SELECT pg_notify('staff_events', <json>)`: PostgreSQL chỉ phát NOTIFY khi transaction commit, nên rollback thì không có sự kiện.
- Đóng stay: `stay-access` gọi `emit_status_changed(entity_type=STAY, status="CLOSED", ...)` thông qua hook `on_stay_closed`.
  Với sự kiện này, outbox **chụp lại danh sách `fcm_token`** vào payload *trước khi* các session bị xóa token, để vẫn gửi được lời cảm ơn cuối.

### Dữ liệu (migration Alembic)

```
stay_session  (+ cột mới)
  fcm_token        text NULL
  fcm_updated_at   timestamptz NULL

notification_outbox
  id               uuid PK
  stay_id          uuid FK → stay NOT NULL
  entity_type      text NOT NULL
  entity_id        uuid NOT NULL
  status           text NOT NULL            -- trạng thái nghiệp vụ mới, VD "PREPARING"
  target_tokens    jsonb NULL               -- chỉ dùng cho STAY/CLOSED (danh sách token đã chụp)
  delivery_status  text NOT NULL DEFAULT 'PENDING'   -- PENDING | SENT | FAILED | SKIPPED
  attempts         smallint NOT NULL DEFAULT 0
  next_attempt_at  timestamptz NOT NULL DEFAULT now()
  last_error       text NULL
  created_at, sent_at timestamptz
  INDEX (delivery_status, next_attempt_at)
```

`SKIPPED` = stay không có session nào còn `fcm_token`.

### Push tới khách (FCM HTTP v1)

**Worker:** một task asyncio chạy cùng tiến trình backend-api (khởi động trong `lifespan`). Cứ 1 giây lấy tối đa 50 dòng
`PENDING` có `next_attempt_at ≤ now()` bằng `SELECT ... FOR UPDATE SKIP LOCKED` (an toàn nếu sau này chạy nhiều instance).

**Gửi:** với mỗi dòng outbox, tìm các `stay_session` chưa revoke có `fcm_token` (hoặc dùng `target_tokens` với STAY/CLOSED),
gửi một message cho mỗi token:

```json
{
  "message": {
    "token": "<fcm_token>",
    "notification": { "title": "Đơn đồ ăn đang được giao", "body": "Món của quý khách sẽ tới trong ít phút." },
    "data": {
      "type": "FOOD_ORDER", "entity_id": "uuid", "status": "DELIVERING",
      "title_key": "food_order.DELIVERING", "occurred_at": "2026-11-19T07:30:00Z"
    },
    "android": { "priority": "HIGH", "notification": { "channel_id": "requests" } }
  }
}
```

- `title`/`body` lấy từ file mẫu `notifications/templates/{vi,en}.json` theo khóa `<entity_type>.<status>` và `stay_session.lang`.
  Thiếu khóa → dùng bản `vi`; thiếu cả bản `vi` → test CI đỏ (có test kiểm tra mọi trạng thái trong `domain-rules.md` đều có mẫu).
- Payload **không** chứa mã phòng, tên khách, giá tiền hay token.

**Xử lý lỗi FCM:**

| Phản hồi | Hành động |
|---|---|
| `200` | Dòng outbox → `SENT` khi mọi token đã xử lý xong |
| `404 UNREGISTERED`, `400 INVALID_ARGUMENT` (token) | Xóa `fcm_token` khỏi session đó; không retry token này |
| `429`, `5xx`, lỗi mạng | Retry sau 2 s → 10 s → 30 s; quá 3 lần → `FAILED` + log `notification_failed` |
| `401/403` (credential sai) | `FAILED` ngay + log mức `error` (lỗi cấu hình) |

**Cấu hình:** `FCM_PROJECT_ID`, `FCM_CREDENTIALS_FILE` (đường dẫn service-account JSON, **không commit**), `FCM_SENDER=fcm|log`.
`log` (mặc định khi `APP_ENV=dev`) ghi payload ra log thay vì gọi Google. Đây là một implementation thật của interface `PushSender`, không phải stub.
Test dùng `FakePushSender` để ghi nhận các message đã gửi.

### API phía khách

| Method | Path | Quyền | Mô tả |
|---|---|---|---|
| PUT | `/api/v1/guest/me/fcm-token` | `current_stay` | `{fcm_token}` → `204`. Gọi sau đăng nhập và mỗi khi Firebase làm mới token |
| DELETE | `/api/v1/guest/me/fcm-token` | `current_stay` | → `204` (khi khách tắt thông báo) |

- Logout, cấp lại mã, check-out: `stay-access` xóa `fcm_token` của các session bị revoke (riêng check-out thì token đã được chụp lại cho lời cảm ơn).

### Realtime cho Web nhân viên (SSE)

| Method | Path | Quyền |
|---|---|---|
| GET | `/api/v1/staff/events` | `current_staff` (mọi vai trò), `Accept: text/event-stream` |

- Mỗi kết nối SSE giữ một listener `LISTEN staff_events` dùng chung trong tiến trình. Sự kiện được **lọc theo vai trò**:

  | Vai trò | Nhận `entity_type` |
  |---|---|
  | `KITCHEN` | `FOOD_ORDER` |
  | `HOUSEKEEPING` | `HOUSEKEEPING` |
  | `RECEPTION` | tất cả (`FOOD_ORDER`, `HOUSEKEEPING`, `CHECKOUT`, `STAY`) |

- Định dạng:
  ```
  event: status_changed
  data: {"entity_type":"FOOD_ORDER","entity_id":"...","status":"PENDING","room_number":"101","actor":"GUEST","occurred_at":"..."}
  ```
- Gửi comment `: ping` mỗi 15 s để giữ kết nối qua proxy. Khi access token hết hạn, server đóng stream; client refresh token rồi kết nối lại.
- V1 **không phát lại** sự kiện bị lỡ (không hỗ trợ `Last-Event-ID`). Mỗi lần kết nối lại, client **tải lại danh sách** của màn hình hiện tại.

### admin-web

- `useStaffEvents(handler)`: hook mở stream bằng `fetch` + `Authorization`, tự kết nối lại với backoff 1 s → 2 s → 5 s → 10 s (tối đa),
  báo trạng thái kết nối (chấm xanh/đỏ ở header). Kết nối lại thành công → gọi callback `onReconnect` để màn hình tải lại dữ liệu.
- Toast khi có yêu cầu mới (`status` ban đầu `PENDING`/`REQUESTED`/`CHECKOUT_REQUESTED`) cho đúng bộ phận.
- Âm báo tùy chọn: nút "Bật âm báo" ở header (trình duyệt chỉ cho phát âm thanh sau khi người dùng tương tác); lựa chọn lưu ở `localStorage`.

### mobile-app

- Khởi tạo Firebase khi app chạy. Sau khi đăng nhập thành công: xin quyền `POST_NOTIFICATIONS` (Android 13+), lấy token,
  gọi `PUT /guest/me/fcm-token`; lắng nghe `onTokenRefresh` để gửi lại.
- Notification channel `requests` (importance high), tên hiển thị theo ngôn ngữ.
- **App đang mở:** hiện thông báo bằng `flutter_local_notifications` và **làm mới provider** tương ứng với `type` để màn hình đang mở cập nhật ngay.
- **Chạm vào thông báo** (app ở nền hoặc đã tắt): điều hướng tới `/requests/<type>/<entity_id>` (màn chi tiết do module nghiệp vụ cung cấp;
  khi chưa có màn chi tiết thì mở trang chủ).
- **Dự phòng khi FCM trễ:** màn theo dõi yêu cầu tự tải lại mỗi 15 s khi đang hiển thị và mỗi khi app quay lại foreground.
  Chính sách này áp dụng cho mọi module nghiệp vụ.
- `google-services.json` không commit. Dev đặt file vào `mobile-app/android/app/`; CI giải mã từ secret `GOOGLE_SERVICES_JSON_B64`.

### Công cụ dev

`POST /api/v1/dev/notify-test` (chỉ khi `APP_ENV=dev`, quyền `RECEPTION`): `{stay_id, status}` → phát một sự kiện `STAY` thử,
để kiểm tra push và SSE trước khi có module nghiệp vụ. Endpoint không được đăng ký khi `APP_ENV≠dev`, có test chứng minh.

## Commands

Kế thừa `foundation`. Bổ sung:

```bash
cd backend-api
FCM_SENDER=log uv run uvicorn app.main:app --reload --port 8000     # dev không cần Firebase
uv run pytest -q tests/integration/notifications
curl -N -H "Authorization: Bearer <staff_access_token>" http://localhost:8000/api/v1/staff/events   # xem SSE
cd ../mobile-app && flutter test test/notifications
```

## Project Structure

```
backend-api/app/modules/notifications/
  api.py (emit_status_changed, EntityType)  models.py  outbox_worker.py  senders.py (PushSender, FcmSender, LogSender)
  templates/vi.json  templates/en.json  sse.py (listener + router /staff/events)  router_guest.py  router_dev.py
backend-api/migrations/versions/xxxx_notifications.py
backend-api/tests/unit/notifications/  tests/integration/notifications/
admin-web/src/lib/realtime/  useStaffEvents.ts  sseParser.ts
admin-web/src/components/layout/ConnectionIndicator.tsx  SoundToggle.tsx
mobile-app/lib/features/notifications/  push_service.dart  notification_router.dart
mobile-app/test/notifications/
```

## Code Style

Theo `foundation`. Riêng module này:
- Module nghiệp vụ **chỉ** import `notifications.api`; không import `senders`, `outbox_worker` hay `sse`.
- Worker không bao giờ để một lỗi làm chết vòng lặp: mỗi dòng outbox xử lý trong `try/except` riêng, có log kèm `outbox_id`.
- Không log `fcm_token` (redact theo C4.5); chỉ log 6 ký tự cuối khi cần debug.

## Testing Strategy

| Mức | Nội dung bắt buộc |
|---|---|
| Unit | Parser SSE phía web (sự kiện cắt ngang giữa hai chunk, comment ping); chọn mẫu theo ngôn ngữ, thiếu khóa thì dùng `vi`; tính lịch retry |
| Unit | Mọi cặp `entity_type.status` trong `docs/domain-rules.md` đều có mẫu `vi` và `en` |
| Integration (Postgres thật, `FakePushSender`) | Emit trong transaction commit → có dòng outbox, worker gửi đúng payload tới mọi session có token; **rollback → không có outbox, không có NOTIFY** |
| Integration | FCM trả `UNREGISTERED` → token bị xóa; `503` hai lần rồi `200` → `SENT`, `attempts=3`; `503` bốn lần → `FAILED` |
| Integration | Check-out: lời cảm ơn được gửi tới token đã chụp; sau đó session không còn token, emit tiếp theo → `SKIPPED` |
| Integration | Payload `data` không chứa mã phòng, tên khách, giá tiền (kiểm tra bằng tập khóa cho phép) |
| Integration — SSE | KITCHEN chỉ nhận `FOOD_ORDER`; HOUSEKEEPING chỉ nhận `HOUSEKEEPING`; RECEPTION nhận tất cả; token khách → `401`; không token → `401` |
| Integration | Khi `APP_ENV=prod`, `/dev/notify-test` trả `404` |
| Integration — hiệu năng (C6) | Từ lúc commit tới lúc `FakePushSender` nhận message < 2 s; từ commit tới sự kiện SSE < 1 s |
| admin-web (Vitest) | `useStaffEvents` kết nối lại theo backoff và gọi `onReconnect`; toast đúng bộ phận |
| mobile-app | Chạm thông báo điều hướng đúng route theo `type`/`entity_id`; token refresh gọi lại API |

Coverage `app/modules/notifications` ≥ 80%.

## Boundaries

- **Always:** gọi `emit_status_changed` trong cùng transaction với thay đổi trạng thái; giữ payload push tối thiểu; thêm mẫu vi/en khi thêm trạng thái mới.
- **Ask first:** thêm kênh mới (email/SMS/Zalo); chạy nhiều instance backend (cần xem lại listener SSE); đổi lịch retry; thêm dependency push khác.
- **Never:** gọi FCM trực tiếp trong request handler hoặc trong transaction; commit service-account JSON hay `google-services.json`;
  đưa dữ liệu cá nhân hoặc mã phòng vào payload; dùng FCM để gửi realtime cho Web nhân viên.

## Success Criteria

1. Trên điện thoại Android thật đã đăng nhập: gọi `/dev/notify-test` → thông báo hiện trong ≤ 5 s, đúng ngôn ngữ của khách (vi rồi đổi sang en).
2. App đang mở thì thông báo vẫn hiện và trang chủ làm mới; chạm thông báo khi app đã tắt thì mở app tới đúng màn.
3. Gỡ app rồi phát sự kiện → FCM trả `UNREGISTERED`, `fcm_token` của session đó bị xóa.
4. Mở Web bằng 3 tài khoản mẫu: sự kiện thử chỉ hiện ở các vai trò có quyền nhận; RECEPTION thấy mọi loại.
5. Tắt mạng máy Web 30 giây rồi bật lại → chấm trạng thái chuyển đỏ rồi xanh, danh sách tự tải lại.
6. Check-out tại quầy → khách nhận "Cảm ơn quý khách"; sự kiện thử sau đó không tới máy khách.
7. Test rollback chứng minh không có push và không có SSE khi transaction thất bại.
8. Toàn bộ test trong Testing Strategy xanh; coverage `notifications` ≥ 80%, toàn backend ≥ 70%.

## Out of Scope (Deferred)

- Phát lại sự kiện SSE đã lỡ (`Last-Event-ID`): V1 tải lại danh sách khi kết nối lại, đủ dùng.
- Push cho nhân viên trên điện thoại (app nhân viên): nhân viên dùng Web trên máy tính/máy tính bảng.
- Email/SMS/Zalo OA: chưa cần ở quy mô đồ án.
- Trang thống kê thông báo gửi lỗi trên Web: V1 xem qua log.
- iOS/APNs: ngoài phạm vi (giả định 6).

## Open Questions

1. Ai sở hữu Firebase project (tài khoản Google của Tech Lead hay của nhóm)? Cần để cấp service-account cho CI/deploy.
2. Có muốn commit `google-services.json` cho tiện build không? File này không phải secret, nhưng spec hiện chọn không commit cho an toàn.
3. Âm báo trên Web: có cần âm khác nhau theo loại yêu cầu không, hay một âm chung là đủ?
