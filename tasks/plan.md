# Implementation Plan: Room Service & Housekeeping App + AI Concierge — V1

Status: **draft — chờ Tech Lead duyệt**
Source spec: [spec/capability-map.md](../spec/capability-map.md) và 9 spec module trong `spec/` (đều đã approved 2026-11-19).
Lịch: [docs/roadmap-d01-d27.md](../docs/roadmap-d01-d27.md). Danh sách task chi tiết: [tasks/todo.md](todo.md).

## Overview

Xây 9 module theo thứ tự của capability map, mỗi module là một lát dọc qua `backend-api` / `ai-service` / `admin-web` / `mobile-app`.
Kế hoạch có **60 task** (T01–T60), mỗi task cỡ S hoặc M, một task = một issue Jira `HMA-<n>` = một nhánh
`feature/HMA-<n>-<mo-ta>` = một PR vào `develop`. 6 checkpoint trùng với các mốc của roadmap; Tech Lead duyệt tại mỗi checkpoint trước khi đi tiếp.

## Architecture Decisions (tóm tắt từ spec, không quyết định mới)

- **Backend là nguồn sự thật duy nhất.** Quyền, state machine, giá tiền và hóa đơn đều ở `backend-api`; web/app/chatbot chỉ phản ánh.
- **Một dependency cho phòng của khách:** `current_stay` / `current_active_stay` (stay-access). Không module nào đọc `room_id` từ request.
- **Một hàm đổi trạng thái cho mỗi loại yêu cầu** (`transition`), một hàm đóng stay (`close_stay`), một hàm tính hóa đơn (`build_bill`).
- **Sự kiện:** `emit_status_changed` trong transaction → outbox (push FCM) + `pg_notify` (SSE web). Rollback thì không có sự kiện.
- **ai-service không có DB, không có quyền nhân viên:** gọi backend bằng chính token khách; cổng xác nhận đặt món/trả phòng do server cưỡng chế.
- **Hợp đồng trước, giao diện sau:** endpoint backend của mỗi module xong trước, web/app làm song song dựa trên schema trong spec.

## Lanes (luồng làm việc song song)

| Lane | Phạm vi | Ghi chú |
|---|---|---|
| **BE** | `backend-api` | Đường găng (critical path) — mọi lane khác chờ hợp đồng API từ đây |
| **WEB** | `admin-web` | Bắt đầu thật sự sau T09 (có RBAC) |
| **APP** | `mobile-app` | Bắt đầu thật sự sau T15 (có đăng nhập khách) |
| **AI** | `ai-service` + phần backend của concierge | Rảnh ở Sprint 1 → làm T03, T06, rồi hỗ trợ BE (T19–T21) |
| **LEAD** | Tech Lead | Review PR, checkpoint, branch protection, release, merge `main` |

Kế hoạch giả định **4 người + Tech Lead** (một người một lane, Tech Lead có thể kiêm một lane). Nhóm khác cỡ thì xem Open Questions.

## Phases & Checkpoints

| Phase | Ngày | Task | Checkpoint (mốc) |
|---|---|---|---|
| 1. Foundation | D01 | T01–T06 | **CP-A:** CI xanh trên PR đầu tiên, 4 package chạy local |
| 2. Staff auth | D02–D03 | T07–T11 | **CP-B:** 3 vai trò đăng nhập Web, RBAC `403`, route-guard xanh |
| 3. Stay access | D03–D05 | T12–T18 | **CP-C = M1 (D05):** khách đăng nhập bằng mã/QR trên điện thoại thật, check-out → `401` |
| 4. MVP | D06–D14 | T19–T43 | **CP-D (D10):** đặt món + dọn phòng end-to-end có push/SSE · **CP-E = M2 (D14):** đủ 6 chức năng MVP trên staging, `/eval-bot` S1 PASS |
| 5. Mức Tốt | D15–D21 | T44–T53 | **CP-F = M3 (D21):** trả phòng nhanh + chatbot tool calling, `/eval-bot` S1–S4 PASS 3 lần |
| 6. Release & trial | D22–D27 | T54–T60 | **CP-G = M4 (D27):** APK + Web + Backend đã deploy, `main` tag `v1.0.0`, chạy thử tại đơn vị |

## Đường găng (critical path)

```
T01 → T02 → T07 → T08 → T09 → T12 → T13 → T15 → T19 → T24 → T25 → T26 → (T44 → T45) → (T49 → T50) → T53 → T54 → T56
```

Trễ ở bất kỳ task nào trong chuỗi trên làm trễ mốc. Các task khác có độ trễ cho phép 1–2 ngày.

## Lịch theo lane (tóm tắt — chi tiết ngày ở `todo.md`)

| Ngày | BE | WEB | APP | AI |
|---|---|---|---|---|
| D01 | T01, T02 | T04 | T05 | T03, T06 |
| D02–D03 | T07, T08, T09, T10 | T11 | (T05 tiếp, chuẩn bị UI) | T12 (hỗ trợ BE) |
| D03–D05 | T13, T14, T15 | T16, T17 | T18 | review/test C5.1 |
| D06–D07 | T24, T25 | T22 | T23 (cấu hình Firebase) | T19, T20, T21 |
| D07–D08 | T26, T27 | T28 | T30 | T37 |
| D08–D10 | T32, T33, T34 | T29, T35 | T31, T36 | T38, T39 |
| D11–D13 | sửa lỗi, hỗ trợ | T41 | T42 | T40, T43 |
| D14 | Kiểm thử tích hợp MVP — cả nhóm | | | |
| D15–D17 | T44, T45, T48 | T46 | T47 | T49 |
| D17–D20 | hỗ trợ AI, sửa lỗi | hoàn thiện UI | T52 | T50, T51, T53 |
| D21 | Đa ngôn ngữ/hoàn thiện, demo Sprint 3 — cả nhóm | | | |
| D22–D27 | T54, T56 | T55 | T57 | T54 (chatbot), T59 |

## Quy ước thực thi mỗi task

1. `git switch develop && git pull` → `git switch -c feature/HMA-<n>-<mo-ta>`.
2. Viết test trước cho logic (TDD), code tới khi xanh; chạy lint + test của package (lệnh trong `CLAUDE.md`).
3. PR vào `develop`, mô tả link tới mục spec tương ứng; CI xanh + ≥ 1 review.
4. Task đổi nghiệp vụ (T34, T45) sửa `docs/domain-rules.md` trong cùng PR.
5. Đánh dấu `[x]` trong `tasks/todo.md` và cập nhật Jira.

Mọi task đều phải qua Definition of Done chung: test mới xanh, không `skip`/hạ ngưỡng (C5.7–C5.9), coverage không giảm, không lộ secret.

## Risks and Mitigations

| Rủi ro | Mức | Giảm thiểu |
|---|---|---|
| BE là đường găng, một người khó theo kịp D02–D10 | Cao | Lane AI hỗ trợ BE ở D02–D07 (T12, T19–T21); WEB/APP dùng mock theo schema spec để không phải chờ |
| Cấu hình Firebase/FCM mất thời gian | Trung bình | T23 cấu hình Firebase từ D06; dev dùng `FCM_SENDER=log` nên BE không bị chặn |
| LLM free tier giới hạn tốc độ làm eval live chậm/đứt | Trung bình | CI chỉ dùng `FakeLLMClient`; eval live chạy theo lô nhỏ; chốt nguồn trả phí trước D17 |
| Cổng xác nhận chatbot phân loại sai câu trả lời | Trung bình | Có nút "Xác nhận" làm đường chính; bộ phân loại chỉ là đường phụ; eval S2 chạy 3 lần |
| Tích hợp cuối sprint vỡ vì mỗi lane làm theo cách hiểu riêng | Trung bình | Checkpoint CP-D giữa Sprint 2; hợp đồng API đúng như spec, đổi thì sửa spec trước |
| Trễ Mức Tốt | Trung bình | Thứ tự cắt theo roadmap: T50 (đặt món qua bot) → T44–T47 (trả phòng) → T49/T51 còn lại |
| Deploy/HTTPS gặp sự cố sát hạn | Trung bình | T56 dựng staging từ CP-D (D10) bằng cùng Dockerfile, D24 chỉ còn đổi biến môi trường |

## Open Questions

1. **Nhóm có mấy người và ai giữ lane nào?** Lịch trên giả định 4 người + Tech Lead. Nhóm 3 người thì gộp AI vào BE và Mức Tốt có nguy cơ trễ.
2. **Task theo dõi ở đâu là nguồn chính:** `tasks/todo.md` (cho Claude Code và `/build`) hay Jira? Đề xuất: Jira là nguồn chính cho nhóm, `todo.md` đồng bộ trạng thái, ID task = số Jira (`T07` ↔ `HMA-7`).
3. **Môi trường staging** (CP-D) đặt ở đâu? Cần chốt trước D10 để T56 dựng sớm.
