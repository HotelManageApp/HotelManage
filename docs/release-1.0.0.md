# Kế hoạch phát hành v1.0.0 (T58)

Theo `CLAUDE.md` / `CONSTRAINTS.md` C1: chỉ **Tech Lead** merge vào `main`; mọi nhánh làm việc vào `develop` qua PR có CI xanh
và ≥ 1 review. Tài liệu này liệt kê việc cần làm, theo thứ tự.

## 1. Trạng thái nhánh (2026-11-20)

- 61 nhánh `feature/HMA-*` đã push; `develop` mới có commit khởi tạo.
- Các nhánh nối tiếp nhau theo chuỗi; **mọi** nhánh feature nằm trong một trong hai nhánh đầu cuối, và hai nhánh này gộp với
  nhau không xung đột:

| Nhánh đầu cuối | Chứa |
|---|---|
| `feature/HMA-56-prod-deploy` | backend-api, ai-service, admin-web (T01–T56 trừ app), bảo mật T54, tải T55, deploy T56 |
| `feature/HMA-57-release-apk` | mobile-app (T05–T52 phần app), CI T06, ký APK T57 |
| `feature/HMA-58-release-prep` | gộp hai nhánh trên + `CHANGELOG.md`, tài liệu này (= bản ứng viên phát hành) |

Trên `feature/HMA-58-release-prep`: backend 785 test, ai-service 305, admin-web 104, mobile-app 128 đều đạt; lint/analyze sạch.

## 2. Đưa vào `develop`

Hai cách, Tech Lead chọn:

1. **Theo chuỗi (review từng phần):** mở PR lần lượt từ nhánh sớm nhất của mỗi chuỗi vào `develop` (VD `feature/HMA-1-…`,
   rồi `HMA-2`, …). Mỗi PR chỉ còn diff của chính task đó vì nhánh trước đã vào `develop`. Danh sách:
   `git for-each-ref --sort=committerdate --format='%(refname:short)' refs/remotes/origin/feature`.
2. **Một lần:** PR `feature/HMA-58-release-prep → develop` (diff lớn; dùng khi các phần đã được review ở bước demo sprint).

Sau khi merge: CI trên `develop` phải xanh cho cả 4 package và `security`.

## 3. Feature freeze và nhánh release

```bash
git switch develop && git pull
git switch -c release/1.0.0
git push -u origin release/1.0.0
```

Trên `release/1.0.0` chỉ nhận sửa lỗi (PR vào `release/1.0.0`), mỗi bản sửa merge ngược về `develop`.

## 4. Kiểm tra trước khi gắn tag (trên staging — `docs/deploy.md`)

- [ ] Triển khai `release/1.0.0` lên staging; `/health` = 200, HTTPS, header bảo mật (`docs/deploy.md` §2).
- [ ] `/eval-bot` 4 kịch bản × 3 lần với LLM thật (S2–S4 100 %) — đánh dấu xong T43, T53.
- [ ] `loadtest/guest_flow.js` trên staging: không 5xx, p95 < 500 ms.
- [ ] APK ký bằng keystore release (`docs/release-apk.md`), cài trên 3 máy, chạy checklist §4 của tài liệu đó.
- [ ] Rà lại `docs/security-report.md` §5 trên staging (F3: rate limit thấy IP thật).
- [ ] Demo Sprint 3 / Tech Lead review — đóng CP-F.

## 5. Phát hành (Tech Lead)

```bash
# PR release/1.0.0 → main, Tech Lead review và merge (không force-push, không merge trực tiếp)
git switch main && git pull
git tag -a v1.0.0 -m "v1.0.0" && git push origin v1.0.0   # CI build APK release ký từ tag
# Merge ngược main → develop qua PR
```

Sửa `CHANGELOG.md`: đổi "chờ phát hành" thành ngày phát hành. Triển khai production bằng `git checkout v1.0.0`
(`docs/deploy.md` §2); APK lấy ở Artifacts của workflow `mobile-app` cho tag `v1.0.0`.

## 6. Sau phát hành

Lỗi gấp: nhánh `hotfix/HMA-<n>-…` từ `main` → PR vào `main` (Tech Lead) → tag `v1.0.x` → merge ngược `develop`.
