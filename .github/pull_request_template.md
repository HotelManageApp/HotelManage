## Jira

HMA-<!-- số task, VD 12 -->

## Spec

<!-- Link mục spec mà PR này triển khai, VD spec/SPEC-stay-access.md#token-của-khách -->

## Thay đổi

-

## Cách kiểm tra

<!-- Lệnh đã chạy và kết quả; với UI/app: ảnh chụp hoặc mô tả thao tác -->

## Checklist

- [ ] Nhánh `feature/HMA-<n>-*` tách từ `develop`, PR nhắm vào **`develop`** (không phải `main`)
- [ ] Lint + test của package đã chạy xanh local (lệnh trong `CLAUDE.md`)
- [ ] Có test cho hành vi mới; không xóa/`skip`/nới assertion của test cũ (C5.7)
- [ ] Không thêm `# noqa`, `# type: ignore`, `eslint-disable`, `@ts-ignore`, `// ignore:` mà không ghi lý do (C5.8)
- [ ] Không có `TODO: implement` hay stub (C5.9)
- [ ] Không commit secret; biến môi trường mới đã thêm vào `.env.example` (C1.5)
- [ ] API khách lấy phòng từ `current_stay`, không nhận `room_id` từ client (C4.1) — nếu áp dụng
- [ ] Đổi nghiệp vụ → đã cập nhật `docs/` và spec trong cùng PR — nếu áp dụng
- [ ] Đã đánh dấu task trong `tasks/todo.md`
