# Biên bản chạy thử tại đơn vị — v1.0.0 (T59)

> Mẫu biên bản. Điền trong 2 ngày chạy thử (D25–D26); đại diện đơn vị ký xác nhận ở mục 6.

## 1. Thông tin chung

| Mục | Nội dung |
|---|---|
| Đơn vị | |
| Địa chỉ | |
| Thời gian chạy thử | từ ……/……/…… đến ……/……/…… |
| Phiên bản | backend/ai-service/web: `v1.0.0` · APK: `v1.0.0` (SHA-256 chữ ký: ………) |
| Địa chỉ hệ thống | `https://api.……` · `https://admin.……` |
| Nhóm thực hiện | |
| Đại diện đơn vị | |

## 2. Chuẩn bị dữ liệu (checklist)

- [ ] Phòng: `seed-rooms --from-file rooms.csv` (…… phòng) — đối chiếu sơ đồ phòng với thực tế
- [ ] Thực đơn: `seed-menu --from-file menu.csv` (…… món, giá đã được đơn vị duyệt)
- [ ] Thông tin khách sạn + Knowledge Base + địa điểm: `seed-kb --from-file kb.yaml`; Lễ tân rà lại tab **Thông tin Concierge**
- [ ] Giờ phục vụ, tên khách sạn, số điện thoại Lễ tân (**Cài đặt**)
- [ ] Tài khoản: Lễ tân …… · Bếp …… · Buồng phòng …… (mỗi người một tài khoản, `create-staff`)
- [ ] Máy in K80 quầy Lễ tân in được phiếu nhận phòng và hóa đơn
- [ ] Đào tạo theo `docs/user-guide-{reception,kitchen,housekeeping}.md` (…… người, …… phút); in `user-guide-guest.md` kèm phiếu

## 3. Kịch bản chạy thử

| # | Kịch bản | Số lần | Đạt | Ghi chú |
|---|---|---|---|---|
| 1 | Check-in, khách đăng nhập bằng QR / mã | | | |
| 2 | Khách đặt món trên app; Bếp xử lý trọn vòng đời; khách nhận thông báo | | | |
| 3 | Khách gọi dọn phòng / đồ dùng; Buồng phòng xử lý | | | |
| 4 | Khách hỏi Concierge (giờ ăn sáng, Wi-Fi, tham quan); câu không có thông tin | | | |
| 5 | Đặt món qua Concierge có bước xác nhận | | | |
| 6 | Trả phòng nhanh: phụ phí, chốt hóa đơn, in, hoàn tất; khách bị đăng xuất | | | |
| 7 | Trả phòng tại quầy | | | |
| 8 | Cấp lại mã khi nghi lộ | | | |

## 4. Số liệu

| Chỉ số | Giá trị |
|---|---|
| Số kỳ lưu trú dùng app / tổng số | |
| Số đơn đồ ăn (app / Concierge) | |
| Số yêu cầu buồng phòng | |
| Số lượt hỏi Concierge; số câu "chưa có thông tin" | |
| Thời gian trung bình đơn: đặt → giao | |
| Số yêu cầu trả phòng nhanh / hoàn tất / từ chối | |
| Sự cố (mất kết nối, lỗi app, thông báo không tới…) | |

## 5. Phản hồi

| # | Người phản hồi (vai trò) | Nội dung | Mức (Cao/TB/Thấp) | Xử lý (hotfix / bản sau / không làm) |
|---|---|---|---|---|
| 1 | | | | |
| 2 | | | | |

Lỗi mức Cao sửa qua `hotfix/*` → `main` (Tech Lead), ghi phiên bản vá vào đây.

## 6. Xác nhận

Đơn vị xác nhận đã chạy thử hệ thống theo các nội dung trên.

| Đại diện đơn vị | Đại diện nhóm dự án |
|---|---|
| (ký, ghi rõ họ tên, ngày) | (ký, ghi rõ họ tên, ngày) |
