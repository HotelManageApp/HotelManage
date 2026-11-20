# CONSTRAINTS.md — Hợp đồng chất lượng của dự án

File này là "thước đo" bắt buộc. Agent và thành viên **không được hạ chuẩn** để qua CI.
Muốn nới một ràng buộc → mở PR riêng sửa file này, Tech Lead duyệt.

---

## C1. Git Guardrail

| ID | Ràng buộc |
|---|---|
| C1.1 | **Cấm tuyệt đối** `git push origin main`, `git push origin HEAD:main`, `git push -f` / `--force` / `--force-with-lease`. |
| C1.2 | Cấm merge/rebase vào `main` từ phía thành viên hoặc agent. Chỉ Tech Lead merge PR `release/*` hoặc `hotfix/*` → `main`. |
| C1.3 | Mọi nhánh làm việc tách từ `develop`, tên `feature/<JIRA-KEY>-<mo-ta-ngan>`; PR nhắm vào `develop`. |
| C1.4 | `main` và `develop` bật branch protection: bắt buộc CI xanh + ≥ 1 review; `main` chỉ Tech Lead được merge. |
| C1.5 | Không commit secrets (`.env`, service-account FCM, API key LLM). Có secret scan trong CI. |

## C2. Chống bịa đặt (Anti-Hallucination) cho Chatbot

| ID | Ràng buộc |
|---|---|
| C2.1 | Chatbot **không được tự bịa** giờ ăn sáng, giá món, món có sẵn, dịch vụ, chính sách, điểm tham quan. |
| C2.2 | Mọi thông tin thực tế phải đến từ: DB, Knowledge Base của khách sạn, hoặc kết quả Tool. |
| C2.3 | Không có dữ liệu → trả lời "chưa có thông tin" và gợi ý liên hệ Lễ tân. Không đoán. |
| C2.4 | Giá và tổng tiền hiển thị cho khách phải lấy từ `get_available_menu` / backend, không do LLM tính. |
| C2.5 | `create_room_service_order` chỉ gọi **sau khi** khách xác nhận rõ ràng bản tóm tắt món + tổng tiền. |
| C2.6 | Chatbot không tiết lộ system prompt, không làm theo chỉ dẫn chèn trong câu chat (prompt injection). |

## C3. Phân việc giữa các bộ phận (RBAC)

| Vai trò | Màn hình | Được phép | Không được phép |
|---|---|---|---|
| `RECEPTION` (Lễ tân) | Check-in/out, phòng, yêu cầu tổng hợp, Express Checkout, khiếu nại | Check-in/out, cấp/thu hồi mã phòng, duyệt Express Checkout, xem mọi yêu cầu (read), hủy đơn khi khách yêu cầu, nhận khiếu nại | Cập nhật trạng thái chế biến của Bếp, trạng thái dọn của Buồng phòng |
| `KITCHEN` (Bếp) | Hàng đợi đơn đồ ăn, quản lý menu/tình trạng món | Xác nhận, chuyển `PREPARING`/`DELIVERING`/`COMPLETED`, từ chối (`CANCELLED` có lý do), bật/tắt món | Xem mã phòng, check-in/out, yêu cầu dọn phòng |
| `HOUSEKEEPING` (Buồng phòng) | Hàng đợi yêu cầu dọn phòng / đồ dùng | Nhận việc (`ASSIGNED`), `IN_PROGRESS`, `DONE` | Xem mã phòng, đơn đồ ăn, check-in/out |
| `GUEST` (token lưu trú) | App mobile + Chatbot | Tạo/xem yêu cầu **của chính stay mình** | Truy cập dữ liệu phòng/stay khác |

- Phân quyền kiểm tra ở **backend** (dependency/middleware), không chỉ ẩn nút ở frontend.
- Mỗi chuyển trạng thái kiểm tra cả vai trò lẫn trạng thái hiện tại (xem `docs/domain-rules.md`).
- Mã phòng thô chỉ hiển thị cho `RECEPTION` đúng lúc cấp; DB lưu hash.

## C4. Bảo mật mã phòng & phiên lưu trú

| ID | Ràng buộc |
|---|---|
| C4.1 | `room_id`/`stay_id` chỉ lấy từ `stay_session_token` đã xác thực; input chứa `room_id` từ client → bỏ qua hoặc `400`. |
| C4.2 | Token bị thu hồi khi check-out/duyệt Express Checkout; request sau đó → `401`. |
| C4.3 | Endpoint đổi mã (`POST /auth/room-code`): rate limit ≤ 5 lần/phút/IP và ≤ 10 lần sai/giờ/thiết bị, sau đó khóa tạm 15 phút → `429`. |
| C4.4 | Mã phiên sinh bằng CSPRNG, ≥ 6 ký tự từ bảng chữ không nhập nhằng, hết hạn theo ngày check-out. |
| C4.5 | Không log mã phòng thô, JWT, hay API key. |

## C5. Tiêu chuẩn kiểm thử

| ID | Ràng buộc |
|---|---|
| C5.1 | **Bắt buộc integration test**: mã phòng chưa check-in → `401`; mã của stay đã check-out → `401`; token đã revoke → `401`; token hợp lệ truy cập tài nguyên stay khác → `403`. |
| C5.2 | **Bắt buộc test rate limit**: vượt ngưỡng đổi mã → `429`. |
| C5.3 | Test RBAC: mỗi vai trò gọi endpoint ngoài quyền → `403`. |
| C5.4 | Test state machine: chuyển trạng thái không hợp lệ → `409`. |
| C5.5 | Test chatbot (`/eval-bot`): không bịa, có bước xác nhận đặt món, chặn đổi `room_id` qua chat. |
| C5.6 | Coverage backend-api và ai-service ≥ 70% dòng; không giảm so với `develop`. |
| C5.7 | **Cấm** xóa test, `@pytest.mark.skip`, `xit`/`.skip`/`.only`, `skip:` trong Flutter test, hay hạ assertion để pass CI. |
| C5.8 | **Cấm** thêm `# noqa`, `# type: ignore`, `eslint-disable`, `@ts-ignore`, `// ignore:` mới khi chưa có lý do ghi kèm và reviewer đồng ý. |
| C5.9 | Không có stub "TODO: implement" trong code được merge vào `develop`. |

## C6. Hiệu năng & vận hành (mức đồ án)

- API p95 < 500 ms (không tính gọi LLM); phản hồi chatbot p95 < 8 s.
- FCM gửi trong ≤ 5 s sau khi trạng thái đổi.
- Tải thử: 50 khách đồng thời không lỗi 5xx.
