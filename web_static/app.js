const state = {
  products: [],
  events: [],
  status: {
    dify_configured: false,
    market_provider: "local_openai",
    real_market_search_configured: false,
    run_mode: "local_demo",
    demo_single_source_proposals: false,
    demo_reset_on_start: false,
    demo_auto_apply_on_run: false,
    demo_force_visible_changes: false,
    demo_proposal_change_percent: 0.15,
  },
  filter: "all",
  search: "",
  sort: "sku",
  activeSku: "",
  running: false,
  loading: true,
  toasts: [],
  toastId: 0,
  confirmResolver: null,
};

const els = {
  agentStatus: document.querySelector("#agentStatus"),
  afterValue: document.querySelector("#afterValue"),
  avgMargin: document.querySelector("#avgMargin"),
  beforeValue: document.querySelector("#beforeValue"),
  catalogValue: document.querySelector("#catalogValue"),
  catalogSubtitle: document.querySelector("#catalogSubtitle"),
  closeDetailButton: document.querySelector("#closeDetailButton"),
  confirmActionButton: document.querySelector("#confirmActionButton"),
  confirmBackdrop: document.querySelector("#confirmBackdrop"),
  confirmCancelButton: document.querySelector("#confirmCancelButton"),
  confirmMessage: document.querySelector("#confirmMessage"),
  confirmTitle: document.querySelector("#confirmTitle"),
  detailBackdrop: document.querySelector("#detailBackdrop"),
  detailContent: document.querySelector("#detailContent"),
  detailSku: document.querySelector("#detailSku"),
  detailSubtitle: document.querySelector("#detailSubtitle"),
  detailTitle: document.querySelector("#detailTitle"),
  eventCount: document.querySelector("#eventCount"),
  impactDelta: document.querySelector("#impactDelta"),
  impactDeltaPct: document.querySelector("#impactDeltaPct"),
  impactProgressFill: document.querySelector("#impactProgressFill"),
  lastSource: document.querySelector("#lastSource"),
  lastUpdate: document.querySelector("#lastUpdate"),
  pendingCount: document.querySelector("#pendingCount"),
  productForm: document.querySelector("#productForm"),
  productList: document.querySelector("#productList"),
  refreshButton: document.querySelector("#refreshButton"),
  resetFormButton: document.querySelector("#resetFormButton"),
  runMode: document.querySelector("#runMode"),
  runAllButton: document.querySelector("#runAllButton"),
  searchInput: document.querySelector("#searchInput"),
  sortSelect: document.querySelector("#sortSelect"),
  skuCount: document.querySelector("#skuCount"),
  timeline: document.querySelector("#timeline"),
  toastRoot: document.querySelector("#toastRoot"),
};

const money = new Intl.NumberFormat("vi-VN", {
  maximumFractionDigits: 0,
  style: "currency",
  currency: "VND",
});

const actionLabels = {
  increase: "Increase ↑",
  decrease: "Decrease ↓",
  hold: "Hold →",
  new: "New",
  none: "No change",
};

const statusLabels = {
  applied: "Applied ✓",
  pending: "Pending",
  rejected: "Rejected",
  none: "No proposal",
};

function formatMoney(value) {
  return money.format(numericValue(value)).replace(/\s?₫$/, "đ");
}

function formatPercent(value) {
  if (!Number.isFinite(value)) return "0%";
  return `${value.toFixed(1)}%`;
}

function marginPercent(product, priceOverride = null) {
  const price = Number(priceOverride ?? product.current_price ?? 0);
  const cost = Number(product.base_cost || 0);
  if (price <= 0) return 0;
  return ((price - cost) / price) * 100;
}

function changePercent(event) {
  if (!event || !event.old_price) return 0;
  return ((Number(event.new_price) - Number(event.old_price)) / Number(event.old_price)) * 100;
}

function pendingEvent(product) {
  return product.last_event?.status === "pending" ? product.last_event : null;
}

function setStatus(text, mode = "ready") {
  els.agentStatus.textContent = text;
  els.agentStatus.classList.toggle("busy", mode === "busy");
  els.agentStatus.classList.toggle("error", mode === "error");
}

function setText(el, text, animate = true) {
  if (!el) return;
  const next = String(text);
  if (el.textContent === next) return;
  el.textContent = next;
  if (!animate) return;
  el.classList.remove("metric-bump");
  void el.offsetWidth;
  el.classList.add("metric-bump");
}

function setRunAllLabel() {
  const label = state.status.dify_configured
    ? state.status.demo_auto_apply_on_run
      ? "Run & Apply"
      : "Run Dify"
    : state.status.real_market_search_configured
      ? "Run real"
      : "Run demo";
  els.runAllButton.innerHTML = `<span aria-hidden="true">▶</span>${label}`;
}

function runModeLabel() {
  if (state.status.dify_configured) {
    if (state.status.demo_auto_apply_on_run) return "Dify demo apply";
    return state.status.market_provider === "dify_tavily" ? "Dify Tavily" : "Dify connected";
  }
  if (state.status.real_market_search_configured) return "Real search";
  return "Local demo";
}

async function api(path, options = {}) {
  const response = await fetch(path, {
    ...options,
    headers: {
      "Content-Type": "application/json",
      ...(options.headers || {}),
    },
  });
  const payload = await response.json().catch(() => ({}));
  if (!response.ok) {
    throw new Error(payload.error || `HTTP ${response.status}`);
  }
  return payload;
}

async function refresh(options = {}) {
  if (options.skeleton) renderLoading();
  const [productsPayload, eventsPayload, statusPayload] = await Promise.all([
    api("/api/products"),
    api("/api/events"),
    api("/api/status"),
  ]);
  state.products = productsPayload.products || [];
  state.events = eventsPayload.events || [];
  state.status = statusPayload || state.status;
  state.loading = false;
  render();
}

function renderLoading() {
  state.loading = true;
  [
    els.skuCount,
    els.catalogValue,
    els.avgMargin,
    els.lastUpdate,
    els.beforeValue,
    els.afterValue,
    els.impactDelta,
    els.pendingCount,
  ].forEach((el) => {
    el.innerHTML = `<span class="skeleton-line medium"></span>`;
  });
  els.impactDeltaPct.innerHTML = `<span class="skeleton-line short"></span>`;
  els.lastSource.innerHTML = `<span class="skeleton-line short"></span>`;
  els.catalogSubtitle.textContent = "Đang tải catalog";
  els.eventCount.textContent = "Đang tải activity";
  els.impactProgressFill.style.width = "0";
  els.productList.innerHTML = [0, 1, 2].map((index) => productSkeletonTemplate(index)).join("");
  els.timeline.innerHTML = [0, 1, 2].map(() => timelineSkeletonTemplate()).join("");
}

function render() {
  renderSummary();
  renderProducts();
  renderTimeline();
  if (state.activeSku) renderDetail(state.activeSku);
}

function renderSummary() {
  const totalValue = state.products.reduce((sum, product) => {
    const event = product.last_event;
    const price = event ? Number(event.old_price || product.current_price || 0) : Number(product.current_price || 0);
    return sum + price * Number(product.inventory || 0);
  }, 0);
  const projectedValue = state.products.reduce((sum, product) => {
    const event = product.last_event;
    const price =
      event && event.status !== "rejected"
        ? Number(event.new_price || product.current_price || 0)
        : Number(product.current_price || 0);
    return sum + price * Number(product.inventory || 0);
  }, 0);
  const pendingCount = state.products.filter((product) => pendingEvent(product)).length;
  const delta = projectedValue - totalValue;
  const deltaPct = totalValue > 0 ? (delta / totalValue) * 100 : 0;
  const avgMargin =
    state.products.length === 0
      ? 0
      : state.products.reduce((sum, product) => sum + marginPercent(product), 0) / state.products.length;
  const lastEvent = state.events[0];
  const maxImpact = Math.max(totalValue, projectedValue, 1);
  const impactWidth = totalValue || projectedValue ? Math.max(4, (projectedValue / maxImpact) * 100) : 0;

  setText(els.skuCount, state.products.length.toString());
  setText(els.catalogValue, formatMoney(totalValue));
  setText(els.beforeValue, formatMoney(totalValue));
  setText(els.afterValue, formatMoney(projectedValue));
  setText(els.impactDelta, `${delta >= 0 ? "+" : ""}${formatMoney(delta)}`);
  setText(els.impactDeltaPct, `${delta >= 0 ? "+" : ""}${formatPercent(deltaPct)}`);
  setText(els.pendingCount, pendingCount.toString());
  setText(els.avgMargin, formatPercent(avgMargin));
  setText(els.lastUpdate, lastEvent ? relativeTime(lastEvent.created_at) : "Chưa có");
  setText(els.lastSource, lastEvent ? lastEvent.source : "-", false);
  setText(els.eventCount, `${state.events.length} events`, false);
  setRunAllLabel();
  setText(els.runMode, runModeLabel(), false);
  setText(els.catalogSubtitle, `${state.products.length} sản phẩm`, false);

  els.impactDelta.classList.toggle("is-positive", delta > 0);
  els.impactDelta.classList.toggle("is-negative", delta < 0);
  els.pendingCount.classList.toggle("has-pending", pendingCount > 0);
  els.impactProgressFill.classList.toggle("is-negative", delta < 0);
  els.impactProgressFill.style.width = `${impactWidth}%`;
}

function renderProducts() {
  const filtered = state.products
    .filter((product) => {
      const action = product.last_event?.action || "none";
      const searchText = [product.sku, product.name, product.description, product.keywords, action]
        .join(" ")
        .toLowerCase();
      if (state.search && !searchText.includes(state.search)) return false;
      if (state.filter === "pending") return product.last_event?.status === "pending";
      if (state.filter === "changed") return action === "increase" || action === "decrease";
      if (state.filter === "increase") return action === "increase";
      if (state.filter === "hold") return action === "hold";
      return true;
    })
    .sort(compareProducts);

  setText(els.catalogSubtitle, `${filtered.length}/${state.products.length} sản phẩm`, false);

  if (filtered.length === 0) {
    els.productList.innerHTML = emptyStateTemplate();
    return;
  }

  els.productList.innerHTML = filtered.map((product, index) => productTemplate(product, index)).join("");
}

function productTemplate(product, index) {
  const event = product.last_event;
  const action = safeToken(event?.action || "new");
  const status = safeToken(event?.status || "none");
  const isPending = status === "pending";
  const isApplied = status === "applied";
  const currentPrice = Number(product.current_price || 0);
  const proposedPrice = event ? Number(event.new_price || currentPrice) : currentPrice;
  const referencePrice = event && isApplied ? Number(event.old_price || currentPrice) : proposedPrice;
  const margin = marginPercent(product);
  const proposedMargin = marginPercent(product, proposedPrice);
  const fill = Math.max(4, Math.min(100, margin * 2.2));
  const delta = event ? proposedPrice - Number(event.old_price || currentPrice) : 0;
  const deltaClass = delta > 0 ? "positive" : delta < 0 ? "negative" : "";
  const deltaText = event
    ? `${delta >= 0 ? "+" : ""}${formatMoney(delta)} (${formatPercent(changePercent(event))})`
    : "Chưa chạy agent";
  const actionLabel = actionLabels[action] || titleCase(action);
  const statusLabel = statusLabels[status] || titleCase(status);
  const runLabel = state.status.dify_configured
    ? state.status.demo_auto_apply_on_run
      ? "Run & Apply"
      : "Run Dify"
    : "Run demo";
  const guardrail = event?.guardrail_note || "Chưa có guardrail";
  const eventText = event?.reason || "Chưa chạy agent để nhận đề xuất giá.";
  const marketSignal = marketSignalText(event);
  const policy = marketPolicy(event);
  const policyPill = policy
    ? `<span class="pill market-policy ${escapeHtml(policy.kind)}">${escapeHtml(policy.label)}</span>`
    : "";
  const pendingControls = isPending
    ? `
        <button class="primary-button icon-text" type="button" data-action="approve">
          <span aria-hidden="true">✓</span>
          Approve
        </button>
        <button class="secondary-button icon-text" type="button" data-action="reject">
          <span aria-hidden="true">×</span>
          Reject
        </button>
      `
    : "";

  return `
    <article
      class="product-card is-${action} is-${status}"
      data-sku="${escapeHtml(product.sku)}"
      tabindex="0"
      style="--row-stagger: ${index * 60}ms"
    >
      <header class="product-card-header">
        <div class="product-identity">
          <span class="sku">${escapeHtml(product.sku)}</span>
          <h3 class="product-title">${escapeHtml(product.name)}</h3>
          <p class="description">${escapeHtml(product.description || "Chưa có mô tả.")}</p>
        </div>
        <div class="status-cluster">
          <span class="pill ${action}">${escapeHtml(actionLabel)}</span>
          <span class="pill ${status}">${escapeHtml(statusLabel)}</span>
          ${policyPill}
          <button class="icon-button run-chip" type="button" data-action="run" title="${escapeHtml(runLabel)}" aria-label="${escapeHtml(runLabel)} ${escapeHtml(product.sku)}">
            <span aria-hidden="true">▶</span>
          </button>
        </div>
      </header>

      <div class="product-card-body">
        <div class="product-stats">
          <div class="product-stat">
            <span class="row-label">Giá hiện tại</span>
            <strong class="price-value">${formatMoney(currentPrice)}</strong>
          </div>
          <div class="product-stat">
            <span class="row-label">${escapeHtml(isApplied ? "Giá trước" : isPending ? "Giá đề xuất" : "Giá agent")}</span>
            <strong class="price-value ${deltaClass}">${event ? formatMoney(referencePrice) : "N/A"}</strong>
          </div>
          <div class="product-stat">
            <span class="row-label">Margin</span>
            <strong class="price-value">${formatPercent(isPending ? proposedMargin : margin)}</strong>
          </div>
          <div class="product-stat">
            <span class="row-label">Tồn kho</span>
            <strong class="price-value">${Number(product.inventory || 0)}</strong>
          </div>
        </div>

        <div class="margin-bar" aria-hidden="true">
          <div class="margin-fill" style="--margin-width: ${fill}%"></div>
        </div>
        <p class="event-note"><span>Delta:</span> ${escapeHtml(deltaText)}</p>
        ${marketSignal ? `<p class="event-note market-signal"><span>Market:</span> ${escapeHtml(marketSignal)}</p>` : ""}
        <p class="event-note"><span>AI:</span> ${escapeHtml(eventText)}</p>
        <p class="event-note"><span>Guardrail:</span> ${escapeHtml(guardrail)}</p>

        <div class="product-actions">
          <button class="secondary-button" type="button" data-action="details">Details</button>
          ${pendingControls}
          <button class="secondary-button" type="button" data-action="edit">Edit</button>
          <button class="danger-button" type="button" data-action="delete">Delete</button>
        </div>
      </div>
    </article>
  `;
}

function productSkeletonTemplate(index) {
  return `
    <article class="product-card skeleton" style="--row-stagger: ${index * 60}ms">
      <div class="skeleton-layout">
        <div class="skeleton-header">
          <div class="skeleton-line medium"></div>
          <div class="skeleton-pill"></div>
        </div>
        <div class="skeleton-line"></div>
        <div class="skeleton-stats">
          <div class="skeleton-line"></div>
          <div class="skeleton-line"></div>
          <div class="skeleton-line"></div>
          <div class="skeleton-line"></div>
        </div>
        <div class="skeleton-line"></div>
        <div class="skeleton-line medium"></div>
      </div>
    </article>
  `;
}

function timelineSkeletonTemplate() {
  return `
    <article class="timeline-item">
      <div class="skeleton-line medium"></div>
      <div class="skeleton-line"></div>
      <div class="skeleton-line short"></div>
    </article>
  `;
}

function emptyStateTemplate() {
  return `
    <div class="empty-state">
      <svg viewBox="0 0 72 72" aria-hidden="true">
        <rect x="12" y="18" width="48" height="34" rx="7" fill="none" stroke="currentColor" stroke-width="3"/>
        <path d="M22 43h28M22 33h14m8 0h6" fill="none" stroke="currentColor" stroke-linecap="round" stroke-width="3"/>
        <path d="M52 28h4a4 4 0 0 1 4 4v6a4 4 0 0 1-4 4h-4z" fill="currentColor"/>
      </svg>
      <strong>Không có sản phẩm phù hợp</strong>
      <p>Thử đổi bộ lọc, tìm SKU khác hoặc tạo sản phẩm mới để agent có dữ liệu định giá.</p>
      <button class="secondary-button icon-text" type="button" data-empty-action="new">
        <span aria-hidden="true">＋</span>
        New product
      </button>
    </div>
  `;
}

function compareProducts(a, b) {
  if (state.sort === "price_desc") {
    return Number(b.current_price || 0) - Number(a.current_price || 0);
  }
  if (state.sort === "margin_asc") {
    return marginPercent(a) - marginPercent(b);
  }
  if (state.sort === "updated_desc") {
    return timestamp(b.last_event?.created_at || b.updated_at) - timestamp(a.last_event?.created_at || a.updated_at);
  }
  return String(a.sku).localeCompare(String(b.sku), "vi");
}

function renderTimeline() {
  if (state.events.length === 0) {
    els.timeline.innerHTML = `
      <div class="empty-state compact">
        <strong>Chưa có activity</strong>
        <p>Run agent để tạo proposal đầu tiên.</p>
      </div>
    `;
    return;
  }

  els.timeline.innerHTML = state.events.map((event) => timelineTemplate(event)).join("");
}

function timelineTemplate(event) {
  const status = safeToken(event.status || "applied");
  const delta = Number(event.new_price || 0) - Number(event.old_price || 0);
  const deltaClass = delta > 0 ? "positive" : delta < 0 ? "negative" : "";
  return `
    <article class="timeline-item is-${status}">
      <div class="timeline-title">
        <strong>${escapeHtml(event.sku)}${event.name ? ` - ${escapeHtml(event.name)}` : ""}</strong>
        <span class="pill ${status}">${escapeHtml(statusLabels[status] || titleCase(status))}</span>
      </div>
      <div class="timeline-price">
        <span>${formatMoney(event.old_price)}</span>
        <strong class="${deltaClass}">${formatMoney(event.new_price)}</strong>
      </div>
      <p class="event-note">${escapeHtml(event.reason)}</p>
      <div class="timeline-time">${escapeHtml(event.source)} · ${relativeTime(event.created_at)}</div>
    </article>
  `;
}

function renderDetail(sku) {
  const product = state.products.find((item) => item.sku === sku);
  if (!product) {
    closeDetail();
    return;
  }
  const event = product.last_event;
  const status = safeToken(event?.status || "none");
  const proposedPrice = event ? Number(event.new_price || product.current_price || 0) : Number(product.current_price || 0);
  const comparisonPrice = event?.status === "applied" ? Number(event.old_price || product.current_price || 0) : proposedPrice;
  const evidence = evidenceSources(event);
  const marketRows = evidence.map((item) => sourceTemplate(item)).join("");
  const policy = marketPolicy(event);
  const eventControls =
    event?.status === "pending"
      ? `
          <div class="detail-actions">
            <button class="primary-button icon-text" type="button" data-detail-action="approve">
              <span aria-hidden="true">✓</span>
              Approve proposal
            </button>
            <button class="danger-button icon-text" type="button" data-detail-action="reject">
              <span aria-hidden="true">×</span>
              Reject
            </button>
          </div>
        `
      : "";

  els.detailSku.textContent = product.sku;
  els.detailTitle.textContent = product.name;
  els.detailSubtitle.textContent = `${statusLabels[status] || titleCase(status)} · ${policy ? `${policy.label} · ` : ""}${event?.source || "no agent run"}`;
  els.detailContent.innerHTML = `
    <section class="detail-grid">
      <div>
        <span class="row-label">Giá hiện tại</span>
        <strong>${formatMoney(product.current_price)}</strong>
      </div>
      <div>
        <span class="row-label">${event?.status === "applied" ? "Giá trước Run" : "Giá đề xuất"}</span>
        <strong>${event ? formatMoney(comparisonPrice) : "Chưa có"}</strong>
      </div>
      <div>
        <span class="row-label">Thay đổi</span>
        <strong>${event ? formatPercent(changePercent(event)) : "0%"}</strong>
      </div>
      <div>
        <span class="row-label">Confidence</span>
        <strong>${escapeHtml(event?.confidence || "-")}</strong>
      </div>
    </section>
    ${sparklineTemplate(product)}
    <section class="detail-section">
      <h3>Lý do AI</h3>
      <p>${escapeHtml(event?.reason || "Chưa có đề xuất từ agent.")}</p>
    </section>
    <section class="detail-section">
      <h3>Guardrails</h3>
      <p>${escapeHtml(event?.guardrail_note || "Chưa có guardrail note.")}</p>
    </section>
    ${marketSummaryTemplate(event)}
    <section class="detail-section">
      <h3>Evidence & sources</h3>
      <div class="source-list">
        ${marketRows || emptyMarketSourcesTemplate(event)}
      </div>
    </section>
    ${marketNoteTemplate(event)}
    ${eventControls}
  `;
  els.detailBackdrop.hidden = false;
}

function marketPolicy(event) {
  const policy = event?.market_data?.demo_policy || "";
  if (policy === "visible_change_fallback") {
    return { kind: "fallback", label: "Demo fallback" };
  }
  if (policy === "ai_only_no_sources") {
    return { kind: "ai-only", label: "AI-only" };
  }
  if (policy === "single_source_pending_proposal") {
    return { kind: "single-source", label: "1 nguồn thật" };
  }
  if (marketSources(event).length > 0) {
    return { kind: "evidence", label: "Tavily evidence" };
  }
  if (event?.source && String(event.source).startsWith("dify")) {
    return { kind: "fallback", label: "Dify output" };
  }
  return null;
}

function emptyMarketSourcesTemplate(event) {
  const policy = event?.market_data?.demo_policy || "";
  if (policy === "visible_change_fallback") {
    return `
      <div class="empty-state compact">
        <strong>Demo fallback</strong>
        <p>Dify chưa trả nguồn giá có cấu trúc. Giá đổi để trình diễn luồng Run và guardrails.</p>
      </div>
    `;
  }
  return `<div class="empty-state compact"><strong>Chưa có market sources</strong><p>Output hiện tại chưa có nguồn thị trường.</p></div>`;
}

function marketSignalText(event) {
  const data = event?.market_data || {};
  const sources = marketSources(event);
  const count = Number(data.valid_source_count || sources.filter((item) => item.url || item.link).length || sources.length || 0);
  if (!count && !data.market_anchor && !data.average_price && !data.demo_policy) {
    return event?.source && String(event.source).startsWith("dify") ? "Dify output · chưa có URL giá" : "";
  }
  if (data.demo_policy === "visible_change_fallback") return "Demo fallback · guardrails";
  if (data.demo_policy === "ai_only_no_sources") return "AI-only · chưa có URL giá";
  const anchor = Number(data.market_anchor || data.average_price || 0);
  const countText = `${count} nguồn`;
  const anchorText = anchor > 0 ? ` · anchor ${formatMoney(anchor)}` : "";
  const demoText = data.demo_policy ? " · demo" : "";
  return `${countText}${anchorText}${demoText}`;
}

function marketSummaryTemplate(event) {
  const data = event?.market_data || {};
  const sources = marketSources(event);
  const hasDifyOutput = event?.source && String(event.source).startsWith("dify");
  if (!sources.length && !data.market_anchor && !data.average_price && !data.demo_policy && !hasDifyOutput) return "";
  const count = Number(data.valid_source_count || sources.filter((item) => item.url || item.link).length || sources.length || 0);
  const anchor = Number(data.market_anchor || 0);
  const low = Number(data.lowest_price || 0);
  const high = Number(data.highest_price || 0);
  const range = low && high ? `${formatMoney(low)} - ${formatMoney(high)}` : "Chưa đủ dữ liệu";
  const policy =
    data.demo_policy === "visible_change_fallback"
      ? "Demo fallback"
      : data.demo_policy === "ai_only_no_sources"
        ? "AI-only"
      : data.demo_policy
        ? "Proposal demo"
        : hasDifyOutput
          ? "Dify output"
          : "Tavily evidence";
  return `
    <section class="market-summary" aria-label="Market signal">
      <div>
        <span class="row-label">Nguồn thật</span>
        <strong>${count}</strong>
      </div>
      <div>
        <span class="row-label">Market anchor</span>
        <strong>${anchor ? formatMoney(anchor) : "Chưa đủ"}</strong>
      </div>
      <div>
        <span class="row-label">Khoảng giá</span>
        <strong>${escapeHtml(range)}</strong>
      </div>
      <div>
        <span class="row-label">Policy</span>
        <strong>${escapeHtml(policy)}</strong>
      </div>
    </section>
  `;
}

function marketNoteTemplate(event) {
  const marketData = event?.market_data || {};
  const note = marketData.note || "";
  const sourceType = marketData.source_type || "";
  if (!note && !sourceType) return "";
  return `
    <section class="detail-section">
      <h3>Market note</h3>
      <p>${sourceType ? `${escapeHtml(sourceType)} · ` : ""}${escapeHtml(note)}</p>
    </section>
  `;
}

function sparklineTemplate(product) {
  const values = priceHistory(product);
  const points = sparklinePoints(values);
  const first = points.split(" ")[0] || "0,84";
  const last = points.split(" ").at(-1) || "300,84";
  const areaPoints = `${first} ${points} ${last.split(",")[0]},88 ${first.split(",")[0]},88`;
  const min = Math.min(...values);
  const max = Math.max(...values);

  return `
    <section class="sparkline-panel">
      <div class="sparkline-top">
        <strong>Price history</strong>
        <span>${formatMoney(min)} → ${formatMoney(max)}</span>
      </div>
      <svg class="sparkline" viewBox="0 0 300 96" preserveAspectRatio="none" aria-hidden="true">
        <defs>
          <linearGradient id="sparkFill-${escapeHtml(product.sku)}" x1="0" x2="0" y1="0" y2="1">
            <stop stop-color="#00e5c3" stop-opacity="0.36"/>
            <stop offset="1" stop-color="#00e5c3" stop-opacity="0"/>
          </linearGradient>
        </defs>
        <polygon points="${areaPoints}" fill="url(#sparkFill-${escapeHtml(product.sku)})"></polygon>
        <polyline points="${points}" fill="none" stroke="#00e5c3" stroke-linecap="round" stroke-linejoin="round" stroke-width="3"></polyline>
      </svg>
    </section>
  `;
}

function priceHistory(product) {
  const skuEvents = state.events
    .filter((event) => event.sku === product.sku)
    .sort((a, b) => timestamp(a.created_at) - timestamp(b.created_at));
  if (skuEvents.length === 0) return [Number(product.current_price || 0), Number(product.current_price || 0)];
  const values = [Number(skuEvents[0].old_price || product.current_price || 0)];
  skuEvents.forEach((event) => values.push(Number(event.new_price || values.at(-1) || 0)));
  return values.filter((value) => Number.isFinite(value));
}

function sparklinePoints(values) {
  const width = 300;
  const height = 96;
  const pad = 10;
  const min = Math.min(...values);
  const max = Math.max(...values);
  const range = max - min || 1;
  const step = values.length > 1 ? (width - pad * 2) / (values.length - 1) : width - pad * 2;
  return values
    .map((value, index) => {
      const x = pad + index * step;
      const y = height - pad - ((value - min) / range) * (height - pad * 2);
      return `${x.toFixed(1)},${y.toFixed(1)}`;
    })
    .join(" ");
}

function sourceTemplate(item) {
  const name = item.source || item.competitor || sourceHost(item.url) || "Market";
  const title = item.title || item.url || item.note || "Market evidence";
  const price = item.price || item.value || item.current_price || 0;
  const url = item.url || item.link || "";
  const type = safeToken(item.type || "");
  const titleMarkup = url
    ? `<a href="${escapeHtml(url)}" target="_blank" rel="noopener noreferrer">${escapeHtml(title)}</a>`
    : `<span>${escapeHtml(title)}</span>`;
  return `
    <div class="source-row ${type ? `is-${type}` : ""}">
      <div class="source-meta">
        <span class="source-badge">${escapeHtml(sourceAbbrev(name))}</span>
        <div>
          <strong>${escapeHtml(name)}</strong>
          ${titleMarkup}
        </div>
      </div>
      <b>${formatMoney(price)}</b>
    </div>
  `;
}

function evidenceSources(event) {
  const sources = marketSources(event);
  if (sources.length > 0) return sources;
  if (!event) return [];

  const policy = event.market_data?.demo_policy || "";
  if (policy === "visible_change_fallback") {
    return [
      {
        type: "fallback",
        source: "Demo fallback",
        price: event.new_price,
        title: "Không có URL giá đủ cấu trúc; đề xuất được tạo bằng guardrails để trình diễn luồng duyệt giá.",
      },
    ];
  }

  if (policy === "ai_only_no_sources") {
    return [
      {
        type: "ai-only",
        source: "AI-only",
        price: event.new_price,
        title: "Dify đề xuất đổi giá nhưng chưa trả URL nguồn thị trường; cần kiểm tra trước khi approve.",
      },
    ];
  }

  if (event.source && String(event.source).startsWith("dify")) {
    return [
      {
        type: "dify-output",
        source: "Dify output",
        price: event.new_price,
        title: "Dify trả đề xuất giá nhưng chưa trả market_data.prices có URL để hiển thị.",
      },
    ];
  }

  return [];
}

function marketSources(event) {
  const data = event?.market_data || {};
  if (Array.isArray(data)) return data;
  if (Array.isArray(data.prices)) return data.prices;
  if (Array.isArray(data.sources)) return data.sources;
  if (Array.isArray(data.competitors)) return data.competitors;
  return [];
}

function openDetails(sku) {
  state.activeSku = sku;
  renderDetail(sku);
}

function closeDetail() {
  state.activeSku = "";
  els.detailBackdrop.hidden = true;
}

function fillForm(product) {
  els.productForm.sku.value = product.sku;
  els.productForm.name.value = product.name;
  els.productForm.description.value = product.description || "";
  els.productForm.base_cost.value = product.base_cost;
  els.productForm.current_price.value = product.current_price;
  els.productForm.inventory.value = product.inventory || 0;
  els.productForm.keywords.value = product.keywords || "";
  els.productForm.sku.focus();
}

function resetForm() {
  els.productForm.reset();
  els.productForm.sku.focus();
}

function formPayload() {
  const data = new FormData(els.productForm);
  return Object.fromEntries(data.entries());
}

async function saveProduct(event) {
  event.preventDefault();
  const payload = formPayload();
  setStatus("Saving", "busy");
  try {
    await api("/api/products", {
      method: "POST",
      body: JSON.stringify(payload),
    });
    resetForm();
    await refresh();
    setStatus("Saved");
    showToast("Đã lưu sản phẩm", "success", payload.sku ? `${payload.sku.toUpperCase()} đã cập nhật trong catalog.` : "");
  } catch (error) {
    handleError(error, "Không lưu được sản phẩm");
  }
}

async function runAll() {
  setRunning(
    true,
    state.status.dify_configured
      ? "Calling Dify"
      : state.status.real_market_search_configured
        ? "Searching prices"
        : "Running demo",
  );
  try {
    const result = await api("/api/products/run-agent", { method: "POST", body: "{}" });
    await refresh();
    const count = result.proposal_count ?? result.applied_count ?? result.results?.length ?? (result.result ? 1 : 0);
    if (result.mode === "dify" && count === 0) {
      setStatus("Dify ran, no output price", "error");
      showToast("Dify chưa trả giá", "warning", "Workflow chạy xong nhưng không có output price hợp lệ.");
    } else {
      setStatus(result.mode === "dify" ? "Dify proposals ready" : "Proposals ready");
      showToast("Agent đã chạy xong", "success", `${count} proposal/event đã được tạo hoặc cập nhật.`);
    }
  } catch (error) {
    handleError(error, "Agent run lỗi");
  } finally {
    setRunning(false);
  }
}

async function runOne(sku) {
  setRunning(
    true,
    state.status.dify_configured
      ? `Dify ${sku}`
      : state.status.real_market_search_configured
        ? `Searching ${sku}`
        : `Running ${sku}`,
  );
  try {
    const result = await api(`/api/products/${encodeURIComponent(sku)}/run-agent`, {
      method: "POST",
      body: "{}",
    });
    await refresh();
    const count = result.proposal_count ?? result.applied_count ?? result.results?.length ?? (result.result ? 1 : 0);
    if (result.mode === "dify" && count === 0) {
      setStatus("Dify ran, no output price", "error");
      showToast(`${sku}: chưa có output price`, "warning", "Workflow chạy xong nhưng không có giá hợp lệ.");
    } else {
      setStatus(`${sku} proposal ready`);
      showToast(`${sku} proposal ready`, "success", "Kiểm tra card hoặc mở Details để duyệt.");
    }
  } catch (error) {
    handleError(error, `${sku} run lỗi`);
  } finally {
    setRunning(false);
  }
}

async function approveProposal(product) {
  const event = pendingEvent(product);
  if (!event) return;
  setStatus("Approving", "busy");
  try {
    await api(`/api/events/${event.id}/approve`, { method: "POST", body: "{}" });
    await refresh();
    setStatus(`${product.sku} applied`);
    showToast(`${product.sku} đã áp dụng`, "success", `${formatMoney(event.old_price)} → ${formatMoney(event.new_price)}`);
  } catch (error) {
    handleError(error, `${product.sku} approve lỗi`);
  }
}

async function rejectProposal(product) {
  const event = pendingEvent(product);
  if (!event) return;
  setStatus("Rejecting", "busy");
  try {
    await api(`/api/events/${event.id}/reject`, { method: "POST", body: "{}" });
    await refresh();
    setStatus(`${product.sku} rejected`);
    showToast(`${product.sku} đã reject`, "warning", "Proposal được đánh dấu rejected và không đổi giá hiện tại.");
  } catch (error) {
    handleError(error, `${product.sku} reject lỗi`);
  }
}

async function deleteProduct(sku) {
  setStatus("Deleting", "busy");
  try {
    await api(`/api/products/${encodeURIComponent(sku)}`, { method: "DELETE" });
    await refresh();
    setStatus("Deleted");
    showToast(`${sku} đã xóa`, "warning", "Catalog và timeline đã được refresh.");
  } catch (error) {
    handleError(error, `${sku} delete lỗi`);
  }
}

function setRunning(value, label = "Running") {
  state.running = value;
  els.runAllButton.disabled = value;
  els.refreshButton.disabled = value;
  document.querySelectorAll("[data-action='run']").forEach((button) => {
    button.disabled = value;
  });
  if (value) setStatus(label, "busy");
}

function showToast(title, type = "info", detail = "") {
  const id = ++state.toastId;
  state.toasts = [...state.toasts, { id, title, type, detail }].slice(-4);
  renderToasts();
  window.setTimeout(() => dismissToast(id), 4200);
}

function renderToasts() {
  els.toastRoot.innerHTML = state.toasts
    .map(
      (toast) => `
        <article class="toast ${escapeHtml(toast.type)}" data-toast-id="${toast.id}">
          <strong>${escapeHtml(toast.title)}</strong>
          ${toast.detail ? `<p>${escapeHtml(toast.detail)}</p>` : ""}
          <button type="button" aria-label="Close toast" data-toast-close="${toast.id}">×</button>
        </article>
      `,
    )
    .join("");
}

function dismissToast(id) {
  const next = state.toasts.filter((toast) => toast.id !== Number(id));
  if (next.length === state.toasts.length) return;
  state.toasts = next;
  renderToasts();
}

function handleError(error, title = "Thao tác lỗi") {
  const message = error instanceof Error ? error.message : String(error);
  setStatus(message, "error");
  showToast(title, "error", message);
}

function askConfirm({ title, message, confirmLabel = "Confirm", variant = "danger" }) {
  if (state.confirmResolver) state.confirmResolver(false);
  return new Promise((resolve) => {
    state.confirmResolver = resolve;
    els.confirmTitle.textContent = title;
    els.confirmMessage.textContent = message;
    els.confirmActionButton.textContent = confirmLabel;
    els.confirmActionButton.className = variant === "danger" ? "danger-button" : "primary-button";
    els.confirmBackdrop.hidden = false;
    window.requestAnimationFrame(() => els.confirmActionButton.focus());
  });
}

function closeConfirm(confirmed) {
  if (!state.confirmResolver) return;
  const resolve = state.confirmResolver;
  state.confirmResolver = null;
  els.confirmBackdrop.hidden = true;
  resolve(Boolean(confirmed));
}

function relativeTime(value) {
  if (!value) return "-";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  const diffSeconds = Math.round((Date.now() - date.getTime()) / 1000);
  if (diffSeconds < 60) return "vừa xong";
  const diffMinutes = Math.round(diffSeconds / 60);
  if (diffMinutes < 60) return `${diffMinutes} phút trước`;
  const diffHours = Math.round(diffMinutes / 60);
  if (diffHours < 24) return `${diffHours} giờ trước`;
  return date.toLocaleString("vi-VN");
}

function timestamp(value) {
  const date = new Date(value || 0);
  return Number.isNaN(date.getTime()) ? 0 : date.getTime();
}

function numericValue(value) {
  if (typeof value === "number") return Number.isFinite(value) ? value : 0;
  if (typeof value === "string") {
    const negative = value.trim().startsWith("-");
    const digits = value.replace(/[^\d]/g, "");
    return digits ? Number(`${negative ? "-" : ""}${digits}`) : 0;
  }
  const parsed = Number(value || 0);
  return Number.isFinite(parsed) ? parsed : 0;
}

function safeToken(value, fallback = "none") {
  return String(value || fallback)
    .toLowerCase()
    .replace(/[^a-z0-9_-]+/g, "-")
    .replace(/^-+|-+$/g, "") || fallback;
}

function titleCase(value) {
  return String(value || "")
    .replace(/[-_]+/g, " ")
    .replace(/\b\w/g, (char) => char.toUpperCase());
}

function sourceHost(value) {
  if (!value) return "";
  try {
    return new URL(value).hostname.replace(/^www\./, "");
  } catch {
    return "";
  }
}

function sourceAbbrev(value) {
  const cleaned = String(value || "M").replace(/[^a-z0-9 ]/gi, " ");
  const parts = cleaned.trim().split(/\s+/).filter(Boolean);
  if (parts.length === 0) return "M";
  if (parts.length === 1) return parts[0].slice(0, 2).toUpperCase();
  return parts
    .slice(0, 2)
    .map((part) => part[0])
    .join("")
    .toUpperCase();
}

function escapeHtml(value) {
  return String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");
}

els.productForm.addEventListener("submit", saveProduct);
els.resetFormButton.addEventListener("click", resetForm);
els.refreshButton.addEventListener("click", async () => {
  setStatus("Refreshing", "busy");
  try {
    await refresh();
    setStatus("Ready");
    showToast("Đã refresh dữ liệu", "success", "Catalog và activity đã đồng bộ.");
  } catch (error) {
    handleError(error, "Refresh lỗi");
  }
});

els.runAllButton.addEventListener("click", runAll);
els.closeDetailButton.addEventListener("click", closeDetail);
els.detailBackdrop.addEventListener("click", (event) => {
  if (event.target === els.detailBackdrop) closeDetail();
});

els.confirmCancelButton.addEventListener("click", () => closeConfirm(false));
els.confirmActionButton.addEventListener("click", () => closeConfirm(true));
els.confirmBackdrop.addEventListener("click", (event) => {
  if (event.target === els.confirmBackdrop) closeConfirm(false);
});

els.toastRoot.addEventListener("click", (event) => {
  const button = event.target.closest("[data-toast-close]");
  if (!button) return;
  dismissToast(button.dataset.toastClose);
});

els.detailContent.addEventListener("click", async (event) => {
  const button = event.target.closest("[data-detail-action]");
  if (!button || !state.activeSku) return;
  const product = state.products.find((item) => item.sku === state.activeSku);
  if (!product) return;
  if (button.dataset.detailAction === "approve") await approveProposal(product);
  if (button.dataset.detailAction === "reject") {
    const confirmed = await askConfirm({
      title: `Reject ${product.sku}?`,
      message: "Proposal sẽ được đánh dấu rejected và giá hiện tại không thay đổi.",
      confirmLabel: "Reject",
    });
    if (confirmed) await rejectProposal(product);
  }
});

els.searchInput.addEventListener("input", (event) => {
  state.search = event.target.value.trim().toLowerCase();
  renderProducts();
});

els.sortSelect.addEventListener("change", (event) => {
  state.sort = event.target.value;
  renderProducts();
});

document.querySelector(".segmented-control").addEventListener("click", (event) => {
  const button = event.target.closest("button[data-filter]");
  if (!button) return;
  state.filter = button.dataset.filter;
  document.querySelectorAll(".segmented-control button").forEach((item) => {
    item.classList.toggle("active", item === button);
  });
  renderProducts();
});

els.productList.addEventListener("click", async (event) => {
  const emptyButton = event.target.closest("[data-empty-action='new']");
  if (emptyButton) {
    resetForm();
    return;
  }

  const button = event.target.closest("button[data-action]");
  const row = event.target.closest("[data-sku]");
  if (!button || !row) return;
  const sku = row.dataset.sku;
  const product = state.products.find((item) => item.sku === sku);
  if (button.dataset.action === "run") {
    await runOne(sku);
  }
  if (button.dataset.action === "details") {
    openDetails(sku);
  }
  if (button.dataset.action === "approve" && product) {
    await approveProposal(product);
  }
  if (button.dataset.action === "reject" && product) {
    const confirmed = await askConfirm({
      title: `Reject ${product.sku}?`,
      message: "Proposal sẽ được đánh dấu rejected và giá hiện tại không thay đổi.",
      confirmLabel: "Reject",
    });
    if (confirmed) await rejectProposal(product);
  }
  if (button.dataset.action === "edit" && product) {
    fillForm(product);
    showToast(`${sku} đã nạp vào editor`, "info", "Chỉnh thông tin rồi bấm Save product.");
  }
  if (button.dataset.action === "delete") {
    const confirmed = await askConfirm({
      title: `Delete ${sku}?`,
      message: "Sản phẩm sẽ bị xóa khỏi catalog demo. Activity cũ vẫn có thể còn trong timeline.",
      confirmLabel: "Delete",
    });
    if (confirmed) await deleteProduct(sku);
  }
});

els.productList.addEventListener("keydown", (event) => {
  if (event.key !== "Enter") return;
  if (event.target.closest("button")) return;
  const row = event.target.closest("[data-sku]");
  if (!row) return;
  event.preventDefault();
  openDetails(row.dataset.sku);
});

document.addEventListener("keydown", (event) => {
  if (event.key === "Escape") {
    if (!els.confirmBackdrop.hidden) {
      closeConfirm(false);
      return;
    }
    if (!els.detailBackdrop.hidden) closeDetail();
    return;
  }

  const tagName = event.target?.tagName;
  const isTyping = ["INPUT", "TEXTAREA", "SELECT"].includes(tagName) || event.target?.isContentEditable;
  if (isTyping) return;

  if (event.key.toLowerCase() === "r") {
    event.preventDefault();
    els.refreshButton.click();
  }

  if (event.key.toLowerCase() === "n") {
    event.preventDefault();
    resetForm();
  }
});

refresh({ skeleton: true })
  .then(() => setStatus("Ready"))
  .catch((error) => handleError(error, "Không tải được dữ liệu"));
