# Quant: nghiên cứu danh mục đầu tư 6–18 tháng (100 triệu VND)

- **Báo cáo chính:** [`BAO_CAO_DAU_TU_2026-10.md`](BAO_CAO_DAU_TU_2026-10.md). Dữ liệu chốt phiên 02/10/2026.
- **Bảng khuyến nghị (mở bằng Excel hoặc Google Sheets):** [`danh_muc_khuyen_nghi_2026-10.csv`](danh_muc_khuyen_nghi_2026-10.csv)
- **Rà soát sâu cơ hội lợi nhuận cao, "đón tin trước", x5–x10 (03/10/2026):** [`BAO_CAO_CO_HOI_2026-10.md`](BAO_CAO_CO_HOI_2026-10.md). Bảng 24 cơ hội: [`co_hoi_2026-10.csv`](co_hoi_2026-10.csv). Dữ liệu gốc và kết quả agent: [`data/opportunity/`](data/opportunity/)

## Dữ liệu và cách cập nhật

| Script | Workflow | Lấy gì | Ghi ra |
|---|---|---|---|
| `scripts/fetch_market_data.py` | `market-data` | Giá OHLCV đối chiếu 3 nguồn (VNDirect, Vietcap, DNSE); thị trường toàn cầu; crypto; vàng; tỷ giá; NAV quỹ mở; tin tức 30 ngày | `data/snapshot/` |
| `scripts/fetch_fundamentals.py` | `fundamentals` | P/E, P/B, cổ tức; BCTC quý (Vietcap IQ); khuyến nghị của các CTCK | `data/snapshot/fundamentals2.json` |
| `scripts/fetch_events.py` | `events` | Lịch sự kiện doanh nghiệp: ngày giao dịch không hưởng quyền, tỷ lệ chia | `data/snapshot/events.json` |

Hai script sau đây chạy cục bộ, sau khi đã có dữ liệu ở trên:
- `scripts/build_fundamentals_table.py`: tạo `fundamentals_compact.csv`.
- `scripts/build_dossiers.py`: tạo hồ sơ cho từng ứng viên.

`data/snapshot/research_results.json` chứa kết quả phân tích và phản biện của 112 agent.

Để cập nhật giá, chạy lại workflow `market-data` (workflow_dispatch) trên GitHub Actions.

Đây là tài liệu nghiên cứu, không phải tư vấn đầu tư được cấp phép.
