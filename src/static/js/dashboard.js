/**
 * SME Dashboard — Frontend Logic
 * ──────────────────────────────
 * Fetches data from /api/dashboard/* and renders KPIs, charts, and tables.
 */

// ── Tenant isolation ──
// Each client's dashboard URL contains ?tenant_id=<uuid> so queries are scoped.
const TENANT_ID = new URLSearchParams(window.location.search).get('tenant_id') || '';

function apiUrl(path, params = {}) {
    const p = new URLSearchParams(params);
    if (TENANT_ID) p.set('tenant_id', TENANT_ID);
    return `${path}?${p.toString()}`;
}

// ── State ──
let currentDays = 0; // 0 = today, 7 = week, 30 = month
let currentPage = 1;
let charts = {};
let autoRefreshTimer = null;
const AUTO_REFRESH_MS = 60_000; // 60 seconds

// ── Helpers ──
function fmt(n) {
    return new Intl.NumberFormat('en-BD', { maximumFractionDigits: 2 }).format(n);
}

function fmtTaka(n) {
    return `৳${fmt(n)}`;
}

function trendHTML(value) {
    if (value === 0) return `<span class="kpi-trend subtle">0%</span>`;
    const cls = value > 0 ? 'up' : 'down';
    const arrow = value > 0 ? '↑' : '↓';
    return `<span class="kpi-trend ${cls}">${arrow} ${Math.abs(value).toFixed(1)}%</span>`;
}

async function fetchJSON(url) {
    try {
        const res = await fetch(url);
        if (!res.ok) throw new Error(`HTTP ${res.status}`);
        return await res.json();
    } catch (e) {
        console.error(`Failed to fetch ${url}:`, e);
        return null;
    }
}

// ── ApexCharts Theme Defaults ──
const chartDefaults = {
    chart: {
        background: 'transparent',
        toolbar: { show: false },
        fontFamily: 'Inter, sans-serif',
    },
    theme: { mode: 'dark' },
    grid: {
        borderColor: 'rgba(31, 41, 55, 0.6)',
        strokeDashArray: 3,
    },
    xaxis: {
        labels: { style: { colors: '#64748b', fontSize: '11px' } },
        axisBorder: { color: '#1f2937' },
        axisTicks: { color: '#1f2937' },
    },
    yaxis: {
        labels: { style: { colors: '#64748b', fontSize: '11px' } },
    },
    tooltip: {
        theme: 'dark',
        style: { fontSize: '12px' },
    },
    dataLabels: { enabled: false },
};


// ═══════════════════════════════════════════
// 1. KPI SUMMARY
// ═══════════════════════════════════════════
async function loadSummary() {
    const data = await fetchJSON(apiUrl('/api/dashboard/summary', { days: currentDays }));
    if (!data) return;

    document.getElementById('kpi-sales-value').textContent = fmtTaka(data.total_sales);
    document.getElementById('kpi-sales-trend').innerHTML = trendHTML(data.sales_growth);

    document.getElementById('kpi-orders-value').textContent = data.total_orders;
    document.getElementById('kpi-orders-trend').innerHTML = trendHTML(data.orders_growth);

    document.getElementById('kpi-avg-value').textContent = fmtTaka(data.avg_order_value);

    document.getElementById('kpi-paid-value').textContent = data.paid_orders;
    document.getElementById('kpi-paid-trend').textContent = `৳${fmt(data.paid_amount)}`;

    document.getElementById('kpi-pending-value').textContent = data.pending_orders;
    document.getElementById('kpi-pending-trend').textContent = `৳${fmt(data.pending_amount)}`;

    document.getElementById('kpi-products-value').textContent = data.active_products;
}


// ═══════════════════════════════════════════
// 2. SALES TREND CHART
// ═══════════════════════════════════════════
async function loadSalesTrend() {
    const days = currentDays === 0 ? 14 : currentDays;
    const data = await fetchJSON(apiUrl('/api/dashboard/sales-trend', { days }));
    if (!data) return;

    const trend = data.trend;
    const categories = trend.map(d => {
        const dt = new Date(d.date);
        return dt.toLocaleDateString('en-US', { month: 'short', day: 'numeric' });
    });
    const salesSeries = trend.map(d => d.sales);
    const ordersSeries = trend.map(d => d.orders);

    const opts = {
        ...chartDefaults,
        chart: {
            ...chartDefaults.chart,
            type: 'area',
            height: 280,
            sparkline: { enabled: false },
        },
        series: [
            { name: 'Sales (৳)', type: 'area', data: salesSeries },
            { name: 'Orders', type: 'line', data: ordersSeries }
        ],
        xaxis: {
            ...chartDefaults.xaxis,
            categories,
        },
        yaxis: [
            {
                title: { text: 'Sales (৳)', style: { color: '#64748b', fontSize: '11px' } },
                labels: {
                    style: { colors: '#64748b', fontSize: '11px' },
                    formatter: v => `৳${fmt(v)}`
                }
            },
            {
                opposite: true,
                title: { text: 'Orders', style: { color: '#64748b', fontSize: '11px' } },
                labels: { style: { colors: '#64748b', fontSize: '11px' } }
            }
        ],
        stroke: { width: [0, 3], curve: 'smooth' },
        fill: {
            type: ['gradient', 'solid'],
            gradient: {
                shadeIntensity: 1,
                opacityFrom: 0.4,
                opacityTo: 0.05,
                stops: [0, 100]
            }
        },
        colors: ['#00d4aa', '#8b5cf6'],
        legend: { show: false },
    };

    if (charts.salesTrend) {
        charts.salesTrend.updateOptions(opts, true, true);
    } else {
        charts.salesTrend = new ApexCharts(document.getElementById('sales-trend-chart'), opts);
        charts.salesTrend.render();
    }
}


// ═══════════════════════════════════════════
// 3. PLATFORM SPLIT (Donut)
// ═══════════════════════════════════════════
async function loadPlatformSplit() {
    const data = await fetchJSON(apiUrl('/api/dashboard/platform-split', { days: currentDays }));
    if (!data) return;

    const platforms = data.platforms;
    const labels = platforms.map(p => p.name);
    const series = platforms.map(p => p.orders);

    const colorMap = {
        'FACEBOOK': '#3b82f6',
        'WHATSAPP': '#22c55e',
        'TELEGRAM': '#8b5cf6',
    };
    const colors = labels.map(l => colorMap[l] || '#64748b');

    const opts = {
        ...chartDefaults,
        chart: {
            ...chartDefaults.chart,
            type: 'donut',
            height: 300,
        },
        series,
        labels,
        colors,
        plotOptions: {
            pie: {
                donut: {
                    size: '65%',
                    labels: {
                        show: true,
                        name: {
                            show: true,
                            color: '#f1f5f9',
                            fontSize: '14px',
                            fontWeight: 600,
                        },
                        value: {
                            show: true,
                            color: '#94a3b8',
                            fontSize: '22px',
                            fontWeight: 700,
                            formatter: val => val
                        },
                        total: {
                            show: true,
                            label: 'Total Orders',
                            color: '#64748b',
                            fontSize: '12px',
                            formatter: w => w.globals.spieSeries.reduce((a, b) => a + b, 0)
                        }
                    }
                }
            }
        },
        legend: {
            position: 'bottom',
            labels: { colors: '#94a3b8' },
        },
        stroke: { width: 0 },
    };

    if (charts.platformSplit) {
        charts.platformSplit.updateOptions(opts, true, true);
    } else {
        charts.platformSplit = new ApexCharts(document.getElementById('platform-split-chart'), opts);
        charts.platformSplit.render();
    }
}


// ═══════════════════════════════════════════
// 4. TOP PRODUCTS (Horizontal Bar)
// ═══════════════════════════════════════════
async function loadTopProducts() {
    const data = await fetchJSON(apiUrl('/api/dashboard/top-products', { days: currentDays, limit: 8 }));
    if (!data) return;

    const products = data.products;
    const categories = products.map(p => p.name);
    const series = products.map(p => p.revenue);

    const opts = {
        ...chartDefaults,
        chart: {
            ...chartDefaults.chart,
            type: 'bar',
            height: 300,
        },
        series: [{ name: 'Revenue', data: series }],
        xaxis: {
            ...chartDefaults.xaxis,
            categories,
        },
        yaxis: {
            labels: {
                style: { colors: '#64748b', fontSize: '11px' },
                formatter: v => `৳${fmt(v)}`
            }
        },
        plotOptions: {
            bar: {
                horizontal: true,
                borderRadius: 6,
                barHeight: '65%',
                distributed: true,
            }
        },
        colors: ['#00d4aa', '#3b82f6', '#8b5cf6', '#f59e0b', '#ec4899', '#22c55e', '#ef4444', '#06b6d4'],
        legend: { show: false },
        tooltip: {
            theme: 'dark',
            y: { formatter: v => fmtTaka(v) }
        },
    };

    if (charts.topProducts) {
        charts.topProducts.updateOptions(opts, true, true);
    } else {
        charts.topProducts = new ApexCharts(document.getElementById('top-products-chart'), opts);
        charts.topProducts.render();
    }
}


// ═══════════════════════════════════════════
// 5. PAYMENT STATUS (Donut)
// ═══════════════════════════════════════════
async function loadPaymentStatus() {
    const data = await fetchJSON(apiUrl('/api/dashboard/payment-status', { days: currentDays }));
    if (!data) return;

    const statuses = data.statuses;
    const labels = statuses.map(s => s.status);
    const series = statuses.map(s => s.count);

    const colorMap = {
        'PAID': '#22c55e',
        'PENDING': '#f59e0b',
        'CANCELLED': '#ef4444',
    };
    const colors = labels.map(l => colorMap[l] || '#64748b');

    const opts = {
        ...chartDefaults,
        chart: {
            ...chartDefaults.chart,
            type: 'donut',
            height: 300,
        },
        series,
        labels,
        colors,
        plotOptions: {
            pie: {
                donut: {
                    size: '65%',
                    labels: {
                        show: true,
                        name: {
                            show: true,
                            color: '#f1f5f9',
                            fontSize: '14px',
                            fontWeight: 600,
                        },
                        value: {
                            show: true,
                            color: '#94a3b8',
                            fontSize: '22px',
                            fontWeight: 700,
                        },
                        total: {
                            show: true,
                            label: 'Total',
                            color: '#64748b',
                            fontSize: '12px',
                            formatter: w => w.globals.spieSeries.reduce((a, b) => a + b, 0)
                        }
                    }
                }
            }
        },
        legend: {
            position: 'bottom',
            labels: { colors: '#94a3b8' },
        },
        stroke: { width: 0 },
    };

    if (charts.paymentStatus) {
        charts.paymentStatus.updateOptions(opts, true, true);
    } else {
        charts.paymentStatus = new ApexCharts(document.getElementById('payment-status-chart'), opts);
        charts.paymentStatus.render();
    }
}


// ═══════════════════════════════════════════
// 6. MODERATOR TABLE
// ═══════════════════════════════════════════
async function loadModerators() {
    const data = await fetchJSON(apiUrl('/api/dashboard/moderators'));
    if (!data) return;

    const tbody = document.getElementById('moderators-tbody');
    const mods = data.moderators;

    if (!mods.length) {
        tbody.innerHTML = '<tr><td colspan="7" class="empty-state">No moderators found</td></tr>';
        return;
    }

    // Sort by today_sales desc
    mods.sort((a, b) => b.today_sales - a.today_sales);

    const rankBadges = ['🥇', '🥈', '🥉'];

    tbody.innerHTML = mods.map((m, i) => {
        const rank = i < 3 ? `<span class="rank-badge">${rankBadges[i]}</span>` : (i + 1);
        const platClass = `badge badge-${m.platform.toLowerCase()}`;
        return `
            <tr>
                <td>${rank}</td>
                <td style="color:var(--text-primary);font-weight:500">${m.name}</td>
                <td><span class="${platClass}">${m.platform}</span></td>
                <td>${m.today_orders}</td>
                <td>${fmtTaka(m.today_sales)}</td>
                <td>${fmtTaka(m.week_sales)}</td>
                <td>${fmtTaka(m.alltime_sales)}</td>
            </tr>
        `;
    }).join('');
}


// ═══════════════════════════════════════════
// 7. STOCK TABLE
// ═══════════════════════════════════════════
async function loadStock() {
    const data = await fetchJSON(apiUrl('/api/dashboard/stock-alerts'));
    if (!data) return;

    const tbody = document.getElementById('stock-tbody');
    const predictions = data.predictions;

    if (!predictions.length) {
        tbody.innerHTML = '<tr><td colspan="5" class="empty-state">No products in inventory</td></tr>';
        return;
    }

    // Sort by days_remaining asc (most urgent first)
    predictions.sort((a, b) => a.days_remaining - b.days_remaining);

    tbody.innerHTML = predictions.map(p => {
        let statusClass, statusText;
        if (p.days_remaining < 5) {
            statusClass = 'stock-critical';
            statusText = '🔴 Critical';
        } else if (p.days_remaining < 15) {
            statusClass = 'stock-warning';
            statusText = '🟡 Low';
        } else {
            statusClass = 'stock-safe';
            statusText = '🟢 Safe';
        }

        const daysStr = p.days_remaining >= 999 ? '∞' : Math.round(p.days_remaining);

        return `
            <tr>
                <td style="color:var(--text-primary);font-weight:500">${p.product_name}</td>
                <td>${p.current_stock}</td>
                <td>${p.avg_daily_sales.toFixed(1)}</td>
                <td>${daysStr}</td>
                <td><span class="${statusClass}">${statusText}</span></td>
            </tr>
        `;
    }).join('');
}


// ═══════════════════════════════════════════
// 8. ORDERS TABLE
// ═══════════════════════════════════════════
async function loadOrders() {
    const search = document.getElementById('order-search').value;
    const platform = document.getElementById('order-platform-filter').value;
    const status = document.getElementById('order-status-filter').value;

    const orderParams = { page: currentPage, limit: 20 };
    if (search) orderParams.search = search;
    if (platform) orderParams.platform = platform;
    if (status) orderParams.payment_status = status;

    const data = await fetchJSON(apiUrl('/api/dashboard/orders', orderParams));
    if (!data) return;

    const tbody = document.getElementById('orders-tbody');
    const orders = data.orders;

    if (!orders.length) {
        tbody.innerHTML = '<tr><td colspan="8" class="empty-state">No orders found</td></tr>';
    } else {
        tbody.innerHTML = orders.map(o => {
            const payClass = `badge badge-${o.payment_status.toLowerCase()}`;
            const platClass = `badge badge-${o.platform.toLowerCase()}`;
            return `
                <tr>
                    <td style="color:var(--accent-cyan);font-weight:500">${o.order_id}</td>
                    <td style="color:var(--text-primary)">${o.product_name}</td>
                    <td>${o.quantity}</td>
                    <td>${fmtTaka(o.price)}</td>
                    <td><span class="${platClass}">${o.platform}</span></td>
                    <td><span class="${payClass}">${o.payment_status}</span></td>
                    <td>${o.phone_number}</td>
                    <td>${o.timestamp}</td>
                </tr>
            `;
        }).join('');
    }

    // Pagination
    const pageInfo = document.getElementById('page-info');
    const prevBtn = document.getElementById('prev-page');
    const nextBtn = document.getElementById('next-page');

    pageInfo.textContent = `Page ${data.page} of ${data.pages || 1}`;
    prevBtn.disabled = data.page <= 1;
    nextBtn.disabled = data.page >= data.pages;
}


// ═══════════════════════════════════════════
// MASTER LOAD
// ═══════════════════════════════════════════
async function loadAll() {
    const refreshBtn = document.getElementById('refresh-btn');
    refreshBtn.classList.add('spinning');

    await Promise.all([
        loadSummary(),
        loadSalesTrend(),
        loadPlatformSplit(),
        loadTopProducts(),
        loadPaymentStatus(),
        loadModerators(),
        loadStock(),
        loadOrders(),
    ]);

    // Update timestamp
    const now = new Date();
    document.getElementById('last-updated').textContent = now.toLocaleString('en-US', {
        hour: '2-digit', minute: '2-digit', second: '2-digit', hour12: true
    });

    refreshBtn.classList.remove('spinning');
}


// ═══════════════════════════════════════════
// EVENT LISTENERS
// ═══════════════════════════════════════════
document.addEventListener('DOMContentLoaded', () => {

    // Guard: show a clear message when tenant_id is missing from the URL
    if (!TENANT_ID) {
        document.querySelector('.dashboard-main').innerHTML = `
            <div style="display:flex;flex-direction:column;align-items:center;justify-content:center;
                        height:60vh;gap:16px;color:var(--text-secondary);text-align:center;padding:2rem;">
                <svg width="52" height="52" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5">
                    <circle cx="12" cy="12" r="10"/>
                    <line x1="12" y1="8" x2="12" y2="12"/>
                    <line x1="12" y1="16" x2="12.01" y2="16"/>
                </svg>
                <h2 style="color:var(--text-primary);margin:0">No Tenant Selected</h2>
                <p style="margin:0;max-width:440px;">
                    Add <code style="background:rgba(255,255,255,0.08);padding:2px 8px;border-radius:4px;
                                     font-size:0.9em;">?tenant_id=YOUR_UUID</code> to the URL to load your dashboard.
                </p>
            </div>`;
        return;
    }

    // Period selector
    document.querySelectorAll('.period-btn').forEach(btn => {
        btn.addEventListener('click', () => {
            document.querySelector('.period-btn.active').classList.remove('active');
            btn.classList.add('active');
            currentDays = parseInt(btn.dataset.days);
            currentPage = 1;
            loadAll();
        });
    });

    // Refresh button
    document.getElementById('refresh-btn').addEventListener('click', loadAll);

    // Order filters
    document.getElementById('order-search').addEventListener('input', debounce(() => {
        currentPage = 1;
        loadOrders();
    }, 400));

    document.getElementById('order-platform-filter').addEventListener('change', () => {
        currentPage = 1;
        loadOrders();
    });

    document.getElementById('order-status-filter').addEventListener('change', () => {
        currentPage = 1;
        loadOrders();
    });

    // Pagination
    document.getElementById('prev-page').addEventListener('click', () => {
        if (currentPage > 1) { currentPage--; loadOrders(); }
    });
    document.getElementById('next-page').addEventListener('click', () => {
        currentPage++;
        loadOrders();
    });

    // Auto refresh
    autoRefreshTimer = setInterval(loadAll, AUTO_REFRESH_MS);

    // Initial load
    loadAll();
});


// ── Debounce utility ──
function debounce(fn, delay) {
    let timer;
    return (...args) => {
        clearTimeout(timer);
        timer = setTimeout(() => fn(...args), delay);
    };
}
