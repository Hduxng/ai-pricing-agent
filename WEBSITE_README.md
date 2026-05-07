# BESTON AI Pricing Agent Website

Tài liệu này mô tả chi tiết chức năng, màn hình và tương tác của website demo BESTON AI Pricing Agent. Nội dung cài đặt và cách chạy nằm trong [README.md](/opt/work/AI%20Agent/ai-pricing-agent/README.md).

## Mục tiêu website

Website là dashboard vận hành định giá động cho catalog sản phẩm BESTON. Người dùng có thể quản lý SKU, chạy pricing agent, xem proposal giá mới, kiểm tra tác động doanh thu trước khi duyệt, và theo dõi lịch sử ra quyết định của agent.

Luồng chính:

```text
Catalog BESTON -> Run Agent/Dify -> Proposal pending -> Review Details -> Approve/Reject -> Activity log
```

## Dữ liệu demo hiện tại

Catalog demo đang dùng sản phẩm thực tế từ BESTON Việt Nam:

| SKU | Sản phẩm | Giá hiện tại |
| --- | --- | ---: |
| `AA1200` | Pin Sạc AA 1.2V Ni-MH 1200mAh | 52.000đ |
| `AA2000` | Pin Sạc AA 1.2V Ni-MH 2000mAh | 80.000đ |
| `BTCSC24-C8022B` | Sạc Pin AA & AAA 1.2V Ni-MH 4 Khe C8022B | 46.000đ |
| `BTCSCA-C9012` | Sạc Pin AA & AAA 1.2V Ni-MH 4 Khe C9012 | 140.000đ |
| `BTCSCA-C9025L` | Sạc Pin AA & AAA 1.2V Ni-MH LCD 12 Khe C9025L | 320.000đ |

`base_cost` và `inventory` là dữ liệu nội bộ giả lập cho demo vì website công khai không công bố giá vốn và tồn kho.

## Tổng quan giao diện

Website dùng theme dark “Command Center” theo nhận diện BESTON:

- Màu nhấn chính: electric teal cho trạng thái active, action chính và biểu đồ.
- Màu amber cho trạng thái pending/cần duyệt.
- Màu green/red cho tăng/giảm hoặc approve/reject.
- Font `Inter` cho giao diện và `JetBrains Mono` cho số liệu giá, SKU, phần trăm.

Giao diện gồm 4 vùng chính:

1. Topbar điều khiển.
2. Summary metrics và impact strip.
3. Workspace 3 cột: Product Editor, Catalog, Activity.
4. Detail panel trượt từ phải khi mở từng SKU.

## Topbar

Topbar hiển thị brand `BESTON AI Pricing Agent`, trạng thái kết nối và các thao tác cấp dashboard.

Thành phần:

- `Local demo` hoặc `Dify connected`: cho biết website đang dùng local demo agent hay Dify Workflow API.
- `Ready`, `Saving`, `Running`, `Error`: trạng thái hiện tại của agent/server.
- `Refresh`: tải lại products, events và status từ backend.
- `Run demo` hoặc `Run Dify`: chạy pricing agent cho toàn bộ catalog.

Tương tác:

- Khi `DIFY_API_KEY` chưa cấu hình, nút chạy toàn bộ hiển thị `Run demo` và dùng agent mô phỏng trong `web_demo.py`.
- Mặc định `DEMO_RESET_ON_START=1`, mỗi lần khởi động website sẽ reset 5 sản phẩm BESTON về giá gốc và xóa activity cũ để demo luôn bắt đầu sạch.
- Mỗi lần Run, backend ưu tiên lấy giá thị trường thật qua OpenAI web search nếu có `OPENAI_API_KEY`.
- Khi chạy Dify, website hiển thị `Dify Tavily`, gửi catalog mới nhất qua `products_json`; workflow Dify chịu trách nhiệm search giá thật bằng Tavily và trả `market_data`.
- Để demo có nhiều tín hiệu hơn, backend mặc định bật `DEMO_SINGLE_SOURCE_PROPOSALS=1`: nếu Dify/Tavily trả 1 URL giá thật, website tạo proposal pending với note rõ là cần người dùng approve, không tự áp giá.
- Có thể tăng độ rõ của demo bằng `DEMO_PROPOSAL_CHANGE_PERCENT=0.15`. Nếu muốn giá hiện tại đổi ngay sau Run trong buổi trình diễn, bật `DEMO_AUTO_APPLY_ON_RUN=1`.
- Nếu Dify không trả được nguồn giá có cấu trúc, `DEMO_FORCE_VISIBLE_CHANGES=1` tạo một biến động demo có guardrails và ghi rõ `demo fallback`; dùng cho buổi trình diễn, không dùng làm quyết định production.
- Nếu thiếu `OPENAI_API_KEY` hoặc tìm giá thật thất bại, backend fallback sang dữ liệu mô phỏng và ghi rõ note trong `market_data`.
- Khi Dify đã cấu hình, nút hiển thị `Run Dify` và backend gọi `/workflows/run`.
- Dot trạng thái có animation pulse để người demo dễ thấy website đang kết nối/đang sẵn sàng.

## Summary Metrics

Khu vực summary gồm 4 metric card:

| Card | Ý nghĩa |
| --- | --- |
| SKU | Số sản phẩm đang theo dõi trong catalog |
| Revenue | Tổng giá trị catalog theo `current_price * inventory` |
| Avg margin | Margin trung bình ước tính từ `base_cost` và `current_price` |
| Last update | Activity mới nhất từ local agent, Dify hoặc Website API |

Tương tác và trạng thái:

- Số liệu có animation nhẹ khi thay đổi sau refresh/run/approve.
- Khi website đang tải lần đầu, card hiển thị skeleton loading.
- Card cuối có accent glow để nhấn mạnh activity mới nhất.

## Impact Strip

Impact strip cho thấy tác động nếu approve toàn bộ proposal đang pending.

Chỉ số:

- `Before`: tổng giá trị catalog hiện tại.
- `After approval`: tổng giá trị nếu dùng `new_price` của các proposal pending.
- `Delta`: chênh lệch tuyệt đối và phần trăm.
- `Pending`: số proposal cần duyệt.

Tương tác:

- Progress bar đổi màu theo hướng tác động.
- Delta dương hiển thị màu green, delta âm hiển thị màu red.
- Pending lớn hơn 0 sẽ có dot amber pulse cạnh số.

## Product Editor

Cột trái dùng để thêm mới hoặc chỉnh sửa sản phẩm.

Trường nhập:

- `SKU`: mã sản phẩm, backend tự chuẩn hóa thành chữ hoa.
- `Tên`: tên hiển thị trong catalog.
- `Mô tả`: thông tin agent dùng để suy luận bối cảnh sản phẩm.
- `Giá vốn`: dùng cho guardrails margin.
- `Giá hiện tại`: giá đang niêm yết.
- `Tồn kho`: ảnh hưởng tới đề xuất tăng/giảm của local demo agent.
- `Từ khóa`: dùng làm tín hiệu thị trường và tìm kiếm.

Tương tác:

- `Save product`: tạo mới hoặc cập nhật SKU.
- `New`: reset form và focus về ô SKU.
- `Edit` trên product card sẽ nạp dữ liệu SKU đó vào editor.
- Sau khi lưu thành công, website refresh catalog và hiện toast.

Validation chính ở backend:

- `sku` bắt buộc và chỉ nhận chữ, số, dấu `.`, `_`, `-`.
- `name`, `base_cost`, `current_price` bắt buộc.
- `base_cost` và `current_price` phải là số dương.
- `inventory` không được âm.

## Catalog

Cột giữa là danh sách product cards và bộ công cụ tìm/lọc/sắp xếp.

### Search

Ô search tìm theo:

- SKU.
- Tên sản phẩm.
- Mô tả.
- Từ khóa.
- Action gần nhất.

Search chạy realtime khi nhập.

### Sort

Các chế độ sort:

| Option | Ý nghĩa |
| --- | --- |
| `SKU` | Sắp xếp theo mã SKU |
| `Giá cao` | Giá hiện tại giảm dần |
| `Margin thấp` | Margin thấp lên trước |
| `Mới cập nhật` | Event hoặc cập nhật mới nhất lên trước |

### Filter Tabs

Các tab lọc:

| Tab | Hiển thị |
| --- | --- |
| `All` | Tất cả sản phẩm |
| `Pending` | SKU có proposal pending |
| `Changed` | SKU có action tăng hoặc giảm |
| `Up` | SKU có action increase |
| `Hold` | SKU agent đề xuất giữ giá |

Nếu không có kết quả, website hiển thị empty state kèm nút `New product`.

## Product Card

Mỗi product card hiển thị đầy đủ bối cảnh để ra quyết định nhanh.

Thông tin chính:

- SKU và tên sản phẩm.
- Mô tả ngắn.
- Pill action: `Increase`, `Decrease`, `Hold`, `New`.
- Pill status: `Pending`, `Applied`, `Rejected`, `No proposal`.
- Giá hiện tại.
- Giá agent/proposal.
- Margin.
- Tồn kho.
- Margin bar.
- Delta.
- Lý do AI.
- Guardrail note.

Tương tác:

- Nút icon `Run`: chạy agent cho riêng SKU đó.
- `Details`: mở detail panel.
- `Approve`: chỉ hiện khi SKU có proposal pending.
- `Reject`: chỉ hiện khi SKU có proposal pending và sẽ mở confirm dialog.
- `Edit`: nạp sản phẩm vào Product Editor.
- `Delete`: mở confirm dialog trước khi xóa sản phẩm.
- `Enter` khi focus product card: mở detail panel.

Trạng thái thị giác:

- Action tăng có accent green.
- Action giảm có accent red.
- Hold có accent blue.
- Pending có border amber và pulse glow.
- Hover card dịch nhẹ lên và tăng shadow.

## Activity Timeline

Cột phải hiển thị lịch sử event gần nhất.

Mỗi event gồm:

- SKU và tên sản phẩm.
- Status: pending, applied, rejected.
- Giá cũ và giá mới.
- Lý do agent.
- Source: `local_agent`, `dify_webhook`, `website_api`, hoặc nguồn khác.
- Thời gian tương đối như `vừa xong`, `2 phút trước`.
- Với `local_agent`, market sources là kết quả OpenAI web search nếu `OPENAI_API_KEY` đã cấu hình; nếu không, sources sẽ là fallback mô phỏng có note.

Tương tác và visual:

- Timeline dot nằm bên trái từng event.
- Dot green cho applied, amber cho pending, red cho rejected.
- Pending event có border amber.
- Timeline có scrollbar riêng khi danh sách dài.

## Detail Panel

Detail panel mở từ phải khi bấm `Details` hoặc nhấn `Enter` trên product card.

Nội dung:

- Header: SKU, tên sản phẩm, status và source.
- Detail grid:
  - Giá hiện tại.
  - Giá đề xuất.
  - Phần trăm thay đổi.
  - Confidence.
- Mini sparkline chart từ lịch sử price events của SKU.
- Lý do AI.
- Guardrails.
- Market sources.
- Action buttons approve/reject nếu event đang pending.

Tương tác:

- Bấm `Close`, bấm backdrop, hoặc nhấn `Esc` để đóng.
- `Approve proposal`: áp dụng giá mới.
- `Reject`: mở confirm dialog, sau đó giữ giá hiện tại nếu xác nhận.

## Toast Notification

Toast nằm góc trên phải và tự đóng sau vài giây.

Các loại toast:

- Success: lưu sản phẩm, refresh thành công, approve thành công, agent chạy xong.
- Warning: reject proposal, delete product, Dify chạy nhưng không trả giá.
- Error: lỗi API, lỗi validation, lỗi Dify request.
- Info: nạp SKU vào editor.

Toast có nút đóng thủ công.

## Confirm Dialog

Confirm dialog dùng cho thao tác có rủi ro:

- Delete product.
- Reject proposal.

Người dùng có thể:

- Bấm `Cancel`.
- Bấm action chính như `Delete` hoặc `Reject`.
- Bấm backdrop để hủy.
- Nhấn `Esc` để hủy.

## Keyboard Shortcuts

| Phím | Hành động |
| --- | --- |
| `R` | Refresh dữ liệu |
| `N` | Reset form và focus SKU để tạo sản phẩm mới |
| `Esc` | Đóng confirm dialog hoặc detail panel |
| `Enter` trên product card | Mở detail panel |

Shortcut không kích hoạt khi người dùng đang nhập trong input, textarea hoặc select.

## Loading, Empty Và Error States

Website có các trạng thái UX chính:

- Skeleton loading khi tải dữ liệu lần đầu.
- Empty state khi filter/search không có sản phẩm phù hợp.
- Status pill hiển thị lỗi ngắn ở topbar.
- Toast error hiển thị lỗi chi tiết hơn.
- Button run/refresh bị disabled khi agent đang chạy để tránh double submit.

## Responsive Behavior

Layout tự thay đổi theo viewport:

| Kích thước | Layout |
| --- | --- |
| `> 1400px` | Workspace 3 cột: Editor / Catalog / Activity |
| `1024-1400px` | Editor + Catalog, Activity chuyển xuống dưới |
| `768-1024px` | Một cột, metrics 2x2 |
| `< 768px` | Mobile một cột, controls xếp dọc |

Detail panel chiếm toàn chiều ngang trên mobile để tránh text bị bó hẹp.

## Backend API Website Dùng

Frontend gọi các endpoint nội bộ sau:

```text
GET    /api/status
GET    /api/products
POST   /api/products
DELETE /api/products/<SKU>
POST   /api/products/run-agent
POST   /api/products/<SKU>/run-agent
POST   /api/events/<EVENT_ID>/approve
POST   /api/events/<EVENT_ID>/reject
GET    /api/events
```

Endpoint tích hợp ngoài UI:

```text
POST   /api/agent-results
PUT    /api/products/<SKU>/price
```

`POST /api/agent-results` phù hợp khi Dify hoặc webhook muốn đẩy proposal về website. `PUT /api/products/<SKU>/price` dùng cho backend agent/PriceUpdater cập nhật giá qua Website API.

## Dify Start Node Input

Mỗi lần bấm Run, website luôn gửi Start node variable:

```text
products_json
```

Giá trị là chuỗi JSON chứa catalog mới nhất trên website. Khi chạy Dify, workflow Dify nên tự search giá thật bằng Tavily rồi trả `market_data` trong output. Backend cũng gửi thêm:

```text
products_count
first_sku
```

Code node đầu tiên trong Dify nên đọc trực tiếp:

```javascript
function main({ products_json, products_count, first_sku }) {
  const products = JSON.parse(products_json);

  return {
    products,
    debug_count: products.length,
    debug_first_sku: products[0]?.sku || first_sku,
    received_count: products_count
  };
}
```

Nếu `debug_first_sku` vẫn là `SKU001`, workflow còn đang dùng sample/hardcoded cũ thay vì biến Start node.

## Dify Output Website Có Thể Parse

Website chấp nhận Dify output có `sku` và `new_price`. Output có thể là object, list object, hoặc list chuỗi JSON trong trường `results`.

Ví dụ:

```json
{
  "results": [
    "{\"sku\":\"AA2000\",\"old_price\":80000,\"new_price\":84000,\"action\":\"increase\",\"reason\":\"Giá tham chiếu cao hơn giá hiện tại.\",\"confidence\":\"medium\",\"guardrail_note\":\"OK\"}"
  ]
}
```

Market sources có thể đưa vào `market_data`:

```json
{
  "sku": "AA2000",
  "new_price": 84000,
  "market_data": {
    "prices": [
      {
        "source": "Shopee",
        "price": 82000,
        "title": "Pin Sạc AA BESTON 2000mAh",
        "url": "https://shopee.vn/..."
      }
    ]
  }
}
```

Khi `market_data.prices` có URL thật nhưng Dify giữ `action: hold` vì chưa đủ nhiều nguồn, website demo có thể chuyển thành proposal pending. Proposal này sẽ có:

```json
{
  "source": "dify_tavily_demo",
  "market_data": {
    "demo_policy": "single_source_pending_proposal",
    "valid_source_count": 1
  }
}
```

Người dùng vẫn phải bấm `Approve` để áp giá.

Các tên trường thay thế được hỗ trợ: `market_sources`, `sources`, `prices`, `competitors`.

## File Liên Quan

```text
web_demo.py              HTTP server, SQLite store, local demo agent, Dify client
web_static/index.html    HTML shell của dashboard
web_static/styles.css    Dark command-center theme, layout, animation
web_static/app.js        Frontend state, API calls, render templates, interactions
web_static/market-signal.svg  Logo pin BESTON trong topbar
pricing.db               SQLite database local cho products/events
```
