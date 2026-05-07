# AI Pricing Agent

AI Pricing Agent là project demo định giá động cho catalog BESTON. Project gồm hai phần:

- Backend agent CLI theo vòng lặp OODA: observe thị trường, orient dữ liệu, decide giá, apply guardrails, act qua API/approval.
- Website demo local: dashboard BESTON AI Pricing Agent để quản lý SKU, chạy local agent hoặc Dify Workflow, duyệt proposal và xem activity.

Mô tả chi tiết website nằm trong [WEBSITE_README.md](/opt/work/AI%20Agent/ai-pricing-agent/WEBSITE_README.md).

## Yêu cầu môi trường

- Python 3.10 trở lên.
- `pip`.
- Node.js chỉ cần nếu muốn kiểm tra cú pháp frontend bằng `node --check`.
- API key OpenAI nếu chạy agent CLI thật.
- API key Dify nếu muốn nút `Run Dify` trên website gọi workflow Dify.

## Cài đặt

```bash
cd "/opt/work/AI Agent/ai-pricing-agent"
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

Nếu repo có file `.env.example`, có thể tạo `.env` từ file đó:

```bash
cp .env.example .env
```

Nếu không có `.env.example`, tạo file `.env` thủ công theo các biến ở phần cấu hình bên dưới.

## Cấu hình `.env`

Các biến thường dùng:

```env
# OpenAI agent CLI
OPENAI_API_KEY=sk-your_openai_api_key
MODEL_NAME=gpt-4.1-mini

# Safety defaults
REQUIRE_APPROVAL=true
DRY_RUN=true

# SQLite
DB_PATH=pricing.db
WEB_DEMO_DB_PATH=pricing.db

# Website API auth, chỉ cần khi agent ngoài gọi website API
DEMO_API_KEY=demo-secret
WEBSITE_API_BASE_URL=http://127.0.0.1:8000
WEBSITE_API_KEY=demo-secret

# Dify Workflow API cho website demo
DIFY_API_KEY=app-your_dify_workflow_api_key
DIFY_API_BASE_URL=https://api.dify.ai/v1
DIFY_USER=pricing-web-demo
DIFY_INPUT_NAME=products_json
DIFY_INPUT_FORMAT=json_string
DIFY_TIMEOUT=100

# Web demo
WEB_DEMO_PORT=8000
DEMO_RESET_ON_START=1
DEMO_SINGLE_SOURCE_PROPOSALS=1
DEMO_FORCE_VISIBLE_CHANGES=1
DEMO_PROPOSAL_CHANGE_PERCENT=0.15
DEMO_PROPOSAL_MAX_CHANGE_PERCENT=0.20
DEMO_AUTO_APPLY_ON_RUN=0
```

Mặc định an toàn:

- `REQUIRE_APPROVAL=true`: agent chỉ tạo đề xuất, không tự áp dụng giá.
- `DRY_RUN=true`: không gọi website API hoặc Telegram thật.
- `DEMO_RESET_ON_START=1`: mỗi lần khởi động website, catalog BESTON và activity được reset về seed ban đầu.
- `DEMO_SINGLE_SOURCE_PROPOSALS=1`: khi Dify/Tavily tìm được 1 URL giá thật, website tạo proposal pending cho demo nhưng vẫn yêu cầu approve.
- `DEMO_FORCE_VISIBLE_CHANGES=1`: nếu Dify không trả được nguồn giá có cấu trúc, website vẫn tạo biến động có guardrails và ghi rõ `demo fallback` để buổi demo không bị toàn bộ `hold`.
- `DEMO_PROPOSAL_CHANGE_PERCENT=0.15`: làm proposal demo lệch rõ hơn khoảng 15% để dễ thấy trên màn hình.
- `DEMO_AUTO_APPLY_ON_RUN=1`: chỉ dùng khi trình diễn; giá hiện tại sẽ đổi ngay sau Run thay vì chờ Approve.

## Chạy Website Demo

```bash
python web_demo.py --port 8000
```

Mở URL được in ra terminal:

```text
http://127.0.0.1:8000
```

Nếu port `8000` đang bận, server tự thử các port kế tiếp trong giới hạn `--port-attempts`.

Chạy với Dify:

```bash
export DIFY_API_KEY="app-your_dify_workflow_api_key"
python web_demo.py --port 8000
```

Khi chưa có `DIFY_API_KEY`, website dùng local demo agent trong `web_demo.py`. Khi có `DIFY_API_KEY`, topbar hiển thị `Dify connected` và nút run gọi Dify Workflow API.

Khi chạy Dify, website chỉ gửi catalog mới nhất trong `products_json`; workflow Dify chịu trách nhiệm search giá thật bằng Tavily và trả proposal. Nếu Dify trả `market_data.prices` có 1 URL giá thật nhưng action vẫn là `hold`, website có thể tạo proposal pending theo `DEMO_SINGLE_SOURCE_PROPOSALS=1` để demo có tín hiệu giá rõ hơn; giá không được áp dụng cho tới khi người dùng approve. Khi không cấu hình Dify, local demo agent sẽ ưu tiên lấy giá thị trường thật bằng `OPENAI_API_KEY` qua OpenAI web search. Nếu chưa cấu hình `OPENAI_API_KEY`, hoặc web search không tìm đủ nguồn đáng tin cậy, website vẫn tạo proposal bằng dữ liệu fallback mô phỏng và ghi rõ note trong `market_data`.

Chạy website với giá thật:

```bash
export OPENAI_API_KEY="sk-your_openai_api_key"
python web_demo.py --port 8000
```

## Sử Dụng Website

Luồng demo cơ bản:

1. Mở website.
2. Kiểm tra topbar đang là `Local demo` hoặc `Dify connected`.
3. Thêm hoặc chỉnh sản phẩm ở Product Editor.
4. Bấm `Save product`.
5. Bấm `Run demo`/`Run Dify` trên topbar để chạy toàn catalog, hoặc bấm icon run trên từng product card.
6. Xem proposal `pending`, delta và impact before/after.
7. Bấm `Details` để xem lý do AI, guardrails, confidence, market sources và sparkline.
8. Bấm `Approve` để áp dụng giá mới hoặc `Reject` để giữ giá cũ.
9. Xem lịch sử ở Activity timeline.

Phím tắt:

| Phím | Hành động |
| --- | --- |
| `R` | Refresh |
| `N` | Tạo sản phẩm mới/focus form |
| `Esc` | Đóng detail panel hoặc confirm dialog |
| `Enter` trên product card | Mở details |

## Chạy Agent CLI

Chạy một chu kỳ:

```bash
python main.py --once
```

Chạy ngay rồi lên lịch theo `CHECK_INTERVAL_HOURS`:

```bash
python main.py --schedule
```

Các SKU mặc định nằm trong `config.py`. Có thể override bằng `TRACKED_SKUS_JSON`:

```env
TRACKED_SKUS_JSON=[
  {"sku":"AA2000","name":"Pin Sạc AA 1.2V Ni-MH 2000mAh","base_cost":51000,"current_price":80000}
]
```

## Kết Nối Agent CLI Với Website API

Để `PriceUpdater` gọi website local:

```env
WEB_DEMO_DB_PATH=pricing.db
DEMO_API_KEY=demo-secret
WEBSITE_API_BASE_URL=http://127.0.0.1:8000
WEBSITE_API_KEY=demo-secret
REQUIRE_APPROVAL=false
DRY_RUN=false
```

Sau đó chạy:

```bash
python main.py --once
```

`PriceUpdater` sẽ gọi:

```text
PUT /api/products/<SKU>/price
```

Header xác thực:

```text
X-API-Key: demo-secret
```

## Kết Nối Dify Workflow

Website gọi Dify qua backend `web_demo.py`, không đưa Dify API key vào frontend.

Biến cấu hình quan trọng:

```env
DIFY_API_KEY=app-your_dify_workflow_api_key
DIFY_API_BASE_URL=https://api.dify.ai/v1
DIFY_INPUT_NAME=products_json
DIFY_INPUT_FORMAT=json_string
```

Workflow Dify cần được Publish trước khi gọi `/workflows/run`.

Website luôn gửi Start node variable `products_json` dưới dạng chuỗi JSON chứa danh sách products mới nhất mỗi lần Run. Backend cũng gửi thêm `products_count` và `first_sku` để debug nhanh trong Dify.

Khi Dify đã cấu hình, topbar website hiển thị `Dify Tavily`. Điều đó nghĩa là Tavily search nằm trong workflow Dify, còn website chỉ nhận `results` và `market_data.prices`.

Trong Dify, tạo Start node variables:

```text
products_json  Text / Paragraph
products_count Number hoặc Text
first_sku      Text
```

Code node ngay sau Start node nên đọc trực tiếp `products_json`:

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

Output node nên trả về ít nhất `sku` và `new_price`. Ví dụ:

```json
{
  "results": [
    "{\"sku\":\"AA2000\",\"old_price\":80000,\"new_price\":84000,\"action\":\"increase\",\"reason\":\"Giá tham chiếu cao hơn.\",\"confidence\":\"medium\",\"guardrail_note\":\"OK\"}"
  ]
}
```

Nếu muốn Dify chủ động gọi ngược về website, thêm HTTP Request node gửi:

```json
{
  "sku": "{{sku}}",
  "name": "{{name}}",
  "old_price": "{{old_price}}",
  "new_price": "{{new_price}}",
  "action": "{{action}}",
  "reason": "{{reason}}",
  "confidence": "{{confidence}}",
  "guardrail_note": "{{guardrail_note}}"
}
```

Endpoint:

```text
POST https://<public-demo-url>/api/agent-results
```

Khi chạy local, dùng tunnel như ngrok hoặc cloudflared để Dify gọi được máy của bạn.

## API Nội Bộ Website

Các endpoint frontend dùng:

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

Endpoint tích hợp:

```text
POST   /api/agent-results
PUT    /api/products/<SKU>/price
```

## Database

Website dùng SQLite file `pricing.db` theo mặc định.

Bảng chính:

- `demo_products`: catalog sản phẩm demo.
- `demo_price_events`: lịch sử proposal/applied/rejected event.

Khi database rỗng, `web_demo.py` seed catalog BESTON mặc định. Với mặc định demo `DEMO_RESET_ON_START=1`, mỗi lần khởi động website sẽ reset catalog và activity về seed ban đầu. Nếu muốn giữ dữ liệu hiện tại qua nhiều lần chạy, đặt `DEMO_RESET_ON_START=0`.

Reset database demo về seed mặc định:

```bash
python - <<'PY'
from web_demo import DEFAULT_DEMO_PRODUCTS, DemoStore

store = DemoStore("pricing.db")
store.init_db(seed=False)
with store.connect() as conn:
    conn.execute("DELETE FROM demo_price_events")
    conn.execute("DELETE FROM demo_products")

for product in DEFAULT_DEMO_PRODUCTS:
    store.upsert_product(product)
PY
```

## Test Và Kiểm Tra

Chạy toàn bộ test:

```bash
python -m pytest
```

Kiểm tra cú pháp frontend:

```bash
node --check web_static/app.js
```

Kiểm tra compile Python:

```bash
python -m compileall config.py web_demo.py
```

Các test dùng fake client/session nên không cần API key và không gọi mạng ngoài.

## Guardrails

Agent kiểm tra các điều kiện an toàn trước khi tạo/cập nhật giá:

- Không dưới giá tối thiểu theo margin: `base_cost / (1 - MIN_MARGIN_PERCENT)`.
- Không giảm quá `PRICE_FLOOR_PERCENT` so với giá hiện tại.
- Không tăng quá `PRICE_CEILING_PERCENT` so với giá hiện tại.
- Không thay đổi quá `MAX_DAILY_CHANGE_PERCENT` trong một chu kỳ.
- Làm tròn giá theo `PRICE_ROUNDING`.

## Lỗi Thường Gặp

`Address already in use`: port đang bận. Dùng port khác:

```bash
python web_demo.py --port 8001
```

`Dify workflow request failed`: kiểm tra `DIFY_API_KEY`, workflow đã Publish chưa, và máy có mạng ra Dify.

`Dify ran, no output price`: workflow chạy nhưng Output node chưa trả `sku` và `new_price`.

Website vẫn hiện nguồn Shopee/Lazada demo: `OPENAI_API_KEY` chưa cấu hình hoặc web search không tìm được đủ giá thật. Mở detail panel để xem `market_data.note`, hoặc kiểm tra log terminal của `web_demo.py`.

Proposal `pending` nhưng giá chưa đổi: đúng thiết kế. Cần bấm `Approve` để áp dụng `new_price`.

`Invalid or missing API key`: request tới Website API thiếu header `X-API-Key` hoặc `Authorization: Bearer <key>`.

`OPENAI_API_KEY is not configured`: chỉ ảnh hưởng khi chạy agent CLI thật. Website local demo vẫn chạy được nếu không dùng OpenAI.
