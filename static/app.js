// State Management
let currentTab = 'dashboard';
let stats = {};
let feeds = [];
let logs = [];
let activeEditFeedId = null;
let currentSourceFilter = 'all';

// Initialize App
document.addEventListener('DOMContentLoaded', () => {
    initClock();
    initTabs();
    initPasswordToggles();
    initSettingsForm();
    initFeedForm();
    initGlobalEventListeners();
    initTradingViewCharts();
    
    // Initial data fetch
    loadDashboardData();
    
    // Timeframe selector event
    const tfSelect = document.getElementById('sentiment-timeframe');
    if(tfSelect) tfSelect.addEventListener('change', loadStats);
    
    // Poll data every 7 seconds to keep dashboard alive
    setInterval(() => {
        if (currentTab === 'dashboard') {
            loadStats();
        } else if (currentTab === 'logs') {
            loadLogs();
        }
    }, 7000);
});

// 1. Clock Display
function initClock() {
    const clockEl = document.getElementById('current-time');
    setInterval(() => {
        const now = new Date();
        clockEl.textContent = now.toLocaleTimeString('th-TH');
    }, 1000);
}

// 2. Tab Navigation
function initTabs() {
    const navItems = document.querySelectorAll('.nav-item');
    const tabContents = document.querySelectorAll('.tab-content');
    
    navItems.forEach(item => {
        item.addEventListener('click', (e) => {
            e.preventDefault();
            const tab = item.getAttribute('data-tab');
            
            navItems.forEach(i => i.classList.remove('active'));
            tabContents.forEach(c => c.classList.remove('active'));
            
            item.classList.add('active');
            document.getElementById(`tab-${tab}`).classList.add('active');
            
            currentTab = tab;
            handleTabChange(tab);
        });
    });
}

function handleTabChange(tab) {
    const titleEl = document.getElementById('page-title');
    const subtitleEl = document.getElementById('page-subtitle');
    
    if (tab === 'dashboard') {
        titleEl.textContent = 'แดชบอร์ดสรุปผลการเงิน';
        subtitleEl.textContent = 'ภาพรวมความเคลื่อนไหวตลาดการเงินและการกรองข่าวจาก AI';
        loadDashboardData();
    } else if (tab === 'news') {
        titleEl.textContent = 'ข่าวการเงินทั้งหมด';
        subtitleEl.textContent = 'รายการข้อมูลดิบและการวิเคราะห์สินทรัพย์โดยละเอียด';
        loadSourcesFilter();
        loadNewsList();
    } else if (tab === 'calendar') {
        titleEl.textContent = 'ปฏิทินเศรษฐกิจ';
        subtitleEl.textContent = 'ข้อมูลดัชนีชี้วัดเศรษฐกิจจาก Forex Factory Calendar';
        loadCalendarEvents();
    } else if (tab === 'feeds') {
        titleEl.textContent = 'จัดการแหล่งข่าวสาร';
        subtitleEl.textContent = 'เปิด-ปิดและกำหนดความถี่ข้อมูลจาก RSS และปฏิทินเศรษฐกิจ';
        loadFeeds();
    } else if (tab === 'settings') {
        titleEl.textContent = 'การตั้งค่าเชื่อมต่อ';
        subtitleEl.textContent = 'ปรับแต่งกุญแจความปลอดภัยสำหรับระบบวิเคราะห์และห้องแจ้งเตือน Telegram';
        loadSettings();
    } else if (tab === 'logs') {
        titleEl.textContent = 'ประวัติบันทึกระบบ';
        subtitleEl.textContent = 'บันทึกการประมวลผลและการรันเซิร์ฟเวอร์แบบเรียลไทม์';
        loadLogs();
    } else if (tab === 'history') {
        titleEl.textContent = 'ประวัติการส่งข้อความ';
        subtitleEl.textContent = 'บันทึกการส่งการแจ้งเตือนไปยัง Telegram ทั้งหมด';
        loadHistoryList();
    }
    
    // Re-render Lucide icons
    lucide.createIcons();
}

// 3. Loaders for API Data
async function loadDashboardData() {
    await loadStats();
    await loadHighlights();
    checkAPIKeys();
}

async function loadStats() {
    try {
        const timeframe = document.getElementById('sentiment-timeframe')?.value || '48h';
        const response = await fetch(`/api/stats?timeframe=${timeframe}`);
        stats = await response.json();
        
        // Populate DOM counters
        document.getElementById('stat-total-fetched').textContent = stats.total_fetched;
        document.getElementById('stat-important-count').textContent = stats.important_count;
        document.getElementById('stat-noise-count').textContent = stats.noise_count;
        document.getElementById('stat-telegram-sent').textContent = stats.telegram_sent;
        
        // Render Sentiment bars
        renderSentimentBars(stats.sentiment);
    } catch (error) {
        console.error("Error loading stats:", error);
    }
}

// 3.1 TradingView Charts
function initTradingViewCharts() {
    const container = document.getElementById('tv-charts-container');
    if (!container) return;
    
    const assets = [
        { id: 'tv_usd', symbol: 'FX_IDC:USDTHB', title: 'USD/THB' },
        { id: 'tv_gold', symbol: 'OANDA:XAUUSD', title: 'Gold (XAU/USD)' },
        { id: 'tv_nasdaq', symbol: 'NASDAQ:NDX', title: 'Nasdaq 100' },
        { id: 'tv_sp500', symbol: 'SP:SPX', title: 'S&P 500' }
    ];
    
    container.innerHTML = '';
    
    assets.forEach(asset => {
        // Create container for widget
        const chartWrapper = document.createElement('div');
        chartWrapper.className = 'chart-container';
        chartWrapper.id = asset.id;
        container.appendChild(chartWrapper);
        
        // Inject script
        const script = document.createElement('script');
        script.type = 'text/javascript';
        script.src = 'https://s3.tradingview.com/tv.js';
        script.onload = () => {
            new TradingView.widget({
                "autosize": true,
                "symbol": asset.symbol,
                "interval": "D",
                "timezone": "Asia/Bangkok",
                "theme": "dark",
                "style": "3", // Area chart
                "locale": "th_TH",
                "enable_publishing": false,
                "hide_top_toolbar": true,
                "hide_legend": false,
                "save_image": false,
                "container_id": asset.id,
                "backgroundColor": "rgba(17, 22, 34, 1)",
                "gridColor": "rgba(42, 46, 57, 0.5)"
            });
        };
        document.body.appendChild(script);
    });
}

function renderSentimentBars(sentiment) {
    const assets = ['USD', 'Gold', 'Nasdaq', 'SP500'];
    
    assets.forEach(asset => {
        const data = sentiment[asset] || { pos: 0, neg: 0, neu: 0 };
        const total = data.pos + data.neg + data.neu;
        
        const posPercent = total > 0 ? (data.pos / total) * 100 : 0;
        const negPercent = total > 0 ? (data.neg / total) * 100 : 0;
        
        const barPos = document.getElementById(`bar-${asset.toLowerCase()}-pos`);
        const barNeg = document.getElementById(`bar-${asset.toLowerCase()}-neg`);
        const labelEl = document.getElementById(`sentiment-val-${asset.toLowerCase()}`);
        
        barPos.style.width = `${posPercent}%`;
        barNeg.style.width = `${negPercent}%`;
        
        labelEl.textContent = `บวก: ${data.pos} | ลบ: ${data.neg} | ปกติ: ${data.neu} (ทั้งหมด ${total})`;
    });
}

async function loadHighlights() {
    try {
        const response = await fetch('/api/news?is_important=true&limit=5');
        const data = await response.json();
        const listEl = document.getElementById('dashboard-highlights');
        
        if (data.items.length === 0) {
            listEl.innerHTML = `
                <div class="empty-state">
                    <i data-lucide="inbox"></i>
                    <p>ไม่มีข่าวความสำคัญระดับวิกฤตในช่วงนี้</p>
                </div>
            `;
            lucide.createIcons();
            return;
        }
        
        listEl.innerHTML = '';
        data.items.forEach(item => {
            listEl.appendChild(createNewsCard(item));
        });
        
        lucide.createIcons();
    } catch (error) {
        console.error("Error loading highlights:", error);
    }
}

async function checkAPIKeys() {
    try {
        const response = await fetch('/api/settings');
        const data = await response.json();
        
        const warningEl = document.getElementById('connection-warning');
        if (!data.gemini_api_key || !data.telegram_bot_token || !data.telegram_chat_id) {
            warningEl.classList.remove('hidden');
        } else {
            warningEl.classList.add('hidden');
        }
        
        // Check rate limit status
        const rateLimitBanner = document.getElementById('ai-rate-limit-banner');
        if (data.ai_rate_limit_error === 'true') {
            rateLimitBanner.classList.remove('hidden');
        } else {
            rateLimitBanner.classList.add('hidden');
        }
    } catch (error) {
        console.error("Error checking settings:", error);
    }
}

// 4. News List View
async function loadSourcesFilter() {
    try {
        const response = await fetch('/api/feeds');
        const data = await response.json();
        const select = document.getElementById('filter-news-source');
        
        select.innerHTML = '<option value="all">ทั้งหมด</option>';
        data.forEach(feed => {
            select.innerHTML += `<option value="${feed.name}">${feed.name}</option>`;
        });
    } catch (error) {
        console.error("Error loading sources filter:", error);
    }
}

async function loadNewsList() {
    const listEl = document.getElementById('all-news-list');
    listEl.innerHTML = '<div class="empty-state"><p>กำลังโหลดข่าวสาร...</p></div>';
    
    const importance = document.getElementById('filter-news-importance').value;
    const source = document.getElementById('filter-news-source').value;
    const search = document.getElementById('filter-news-search').value;
    
    let url = '/api/news?limit=80';
    if (importance === 'important') url += '&is_important=true';
    if (importance === 'noise') url += '&is_important=false';
    if (importance === 'pending') url += '&is_important=null';  // Wait, backend supports checking is_important=None via python side, we can handle it
    
    if (source !== 'all') url += `&source=${encodeURIComponent(source)}`;
    if (search) url += `&search=${encodeURIComponent(search)}`;
    
    try {
        const response = await fetch(url);
        const data = await response.json();
        
        if (data.items.length === 0) {
            listEl.innerHTML = `
                <div class="empty-state">
                    <i data-lucide="inbox"></i>
                    <p>ไม่พบข่าวสารตามการตั้งค่าตัวกรองของคุณ</p>
                </div>
            `;
            lucide.createIcons();
            return;
        }
        
        listEl.innerHTML = '';
        data.items.forEach(item => {
            listEl.appendChild(createNewsCard(item));
        });
        
        lucide.createIcons();
    } catch (error) {
        console.error("Error loading news list:", error);
        listEl.innerHTML = '<div class="empty-state"><p>เกิดข้อผิดพลาดในการโหลดข่าวสาร</p></div>';
    }
}

// 4.5. Dispatch History View
async function loadHistoryList() {
    const tbody = document.getElementById('history-table-body');
    tbody.innerHTML = '<tr><td colspan="5" class="text-center text-muted py-20"><i data-lucide="loader-2" class="icon-spin-hover" style="display:inline-block; margin-bottom:10px;"></i><br>กำลังโหลดประวัติการส่งข้อความ...</td></tr>';
    lucide.createIcons();
    
    try {
        const response = await fetch('/api/message_history?limit=100');
        const data = await response.json();
        
        if (data.length === 0) {
            tbody.innerHTML = '<tr><td colspan="5" class="text-center text-muted py-20"><i data-lucide="inbox" style="display:inline-block; margin-bottom:10px;"></i><br>ยังไม่มีประวัติการส่งข้อความ</td></tr>';
            lucide.createIcons();
            return;
        }
        
        tbody.innerHTML = '';
        data.forEach(hist => {
            const dateStr = new Date(hist.timestamp).toLocaleString('th-TH');
            
            // Format Trigger Type
            let triggerBadge = '';
            if (hist.trigger_type === 'auto') triggerBadge = '<span class="badge badge-primary">Auto (AI)</span>';
            else if (hist.trigger_type === 'pre_event') triggerBadge = '<span class="badge badge-info">Pre-Event (30m)</span>';
            else if (hist.trigger_type === 'manual_dashboard') triggerBadge = '<span class="badge badge-warning">Manual (Admin)</span>';
            else triggerBadge = `<span class="badge">${hist.trigger_type}</span>`;
            
            // Format Status
            let statusBadge = '';
            if (hist.status === 'success') statusBadge = '<span class="status-indicator"><span class="status-dot green"></span> สำเร็จ</span>';
            else statusBadge = '<span class="status-indicator"><span class="status-dot red"></span> ล้มเหลว</span>';
            
            const tr = document.createElement('tr');
            tr.innerHTML = `
                <td>${dateStr}</td>
                <td><strong>${hist.title || '-'}</strong></td>
                <td>${triggerBadge}</td>
                <td>${hist.reason || '-'}</td>
                <td>${statusBadge}</td>
            `;
            tbody.appendChild(tr);
        });
        
        lucide.createIcons();
    } catch (error) {
        console.error("Error loading message history:", error);
        tbody.innerHTML = '<tr><td colspan="5" class="text-center text-danger py-20">เกิดข้อผิดพลาดในการโหลดประวัติ</td></tr>';
    }
}

// 5. Economic Calendar Events View
async function loadCalendarEvents() {
    const listEl = document.getElementById('calendar-events-list');
    listEl.innerHTML = '<div class="empty-state"><p>กำลังโหลดรายการตารางเศรษฐกิจ...</p></div>';
    
    try {
        const response = await fetch('/api/news?is_calendar=true&limit=100');
        const data = await response.json();
        
        if (data.items.length === 0) {
            listEl.innerHTML = `
                <div class="empty-state">
                    <i data-lucide="calendar"></i>
                    <p>ไม่มีตารางเศรษฐกิจในช่วงสัปดาห์นี้</p>
                </div>
            `;
            lucide.createIcons();
            return;
        }
        
        listEl.innerHTML = '';
        data.items.forEach(item => {
            listEl.appendChild(createCalendarCard(item));
        });
        
        lucide.createIcons();
    } catch (error) {
        console.error("Error loading calendar events:", error);
        listEl.innerHTML = '<div class="empty-state"><p>เกิดข้อผิดพลาดในการโหลดปฏิทิน</p></div>';
    }
}

// 6. Feeds Config View
async function loadFeeds() {
    const listEl = document.getElementById('feeds-config-list');
    listEl.innerHTML = '';
    
    try {
        const response = await fetch('/api/feeds');
        feeds = await response.json();
        
        feeds.forEach(feed => {
            listEl.appendChild(createFeedCard(feed));
        });
        
        lucide.createIcons();
    } catch (error) {
        console.error("Error loading feeds:", error);
    }
}

// AI Provider & Model dynamic selection logic
const aiModelsData = {
    "gemini": [
        { id: "gemini-2.5-flash-lite", name: "Gemini 2.5 Flash Lite (ฟรี / เร็ว)", price: "ฟรี (หรือ ~10-20 บาท)" },
        { id: "gemini-2.5-flash", name: "Gemini 2.5 Flash (ฟรี / มาตรฐาน)", price: "ฟรี (หรือ ~15-30 บาท)" },
        { id: "gemini-2.5-pro", name: "Gemini 2.5 Pro (ฉลาดสุด)", price: "~200-400 บาท/เดือน" }
    ],
    "openai": [
        { id: "gpt-4o-mini", name: "GPT-4o-mini (ถูกสุด / เร็ว)", price: "~5-20 บาท/เดือน" },
        { id: "gpt-4o", name: "GPT-4o (ฉลาดสุด)", price: "~150-350 บาท/เดือน" }
    ],
    "openrouter": [
        { id: "openai/gpt-4o-mini", name: "GPT-4o-mini (ผ่าน OpenRouter)", price: "~5-20 บาท/เดือน" },
        { id: "openai/gpt-4o", name: "GPT-4o (ผ่าน OpenRouter)", price: "~150-350 บาท/เดือน" },
        { id: "anthropic/claude-3-5-haiku-20241022", name: "Claude 3.5 Haiku", price: "~20-40 บาท/เดือน" },
        { id: "anthropic/claude-3-5-sonnet-20241022", name: "Claude 3.5 Sonnet", price: "~300-450 บาท/เดือน" }
    ]
};

function updateModelDropdown() {
    const provider = document.getElementById('setting-ai-provider').value;
    const modelSelect = document.getElementById('setting-model-name');
    const priceText = document.getElementById('model-price-estimate');
    
    // Save current selection to dataset to restore later if it exists in the new provider
    const currentModel = modelSelect.dataset.savedModel || modelSelect.value;
    
    // Toggle UI keys
    document.getElementById('group-gemini-key').style.display = provider === 'gemini' ? 'block' : 'none';
    document.getElementById('group-openai-key').style.display = provider === 'openai' ? 'block' : 'none';
    document.getElementById('group-openrouter-key').style.display = provider === 'openrouter' ? 'block' : 'none';
    
    // Update options
    modelSelect.innerHTML = '';
    const models = aiModelsData[provider] || [];
    models.forEach(m => {
        const opt = document.createElement('option');
        opt.value = m.id;
        opt.textContent = m.name;
        modelSelect.appendChild(opt);
    });
    
    // Try to restore previous selection if it belongs to this provider
    if (models.find(m => m.id === currentModel)) {
        modelSelect.value = currentModel;
    }
    modelSelect.dataset.savedModel = modelSelect.value;
    
    // Update price estimate
    updatePriceEstimate();
}

function updatePriceEstimate() {
    const provider = document.getElementById('setting-ai-provider').value;
    const modelSelect = document.getElementById('setting-model-name');
    const priceText = document.getElementById('model-price-estimate');
    
    const models = aiModelsData[provider] || [];
    const selectedModel = models.find(m => m.id === modelSelect.value);
    if (selectedModel) {
        priceText.textContent = `💰 ราคาประเมิน: ${selectedModel.price}`;
    }
}

// Bind events for AI providers
document.addEventListener('DOMContentLoaded', () => {
    const providerSelect = document.getElementById('setting-ai-provider');
    const modelSelect = document.getElementById('setting-model-name');
    if (providerSelect && modelSelect) {
        providerSelect.addEventListener('change', () => {
            modelSelect.dataset.savedModel = ''; // Reset on provider change
            updateModelDropdown();
        });
        modelSelect.addEventListener('change', () => {
            modelSelect.dataset.savedModel = modelSelect.value;
            updatePriceEstimate();
        });
    }
});

// 7. Settings View
async function loadSettings() {
    try {
        const response = await fetch('/api/settings');
        const settings = await response.json();
        
        document.getElementById('setting-ai-provider').value = settings.ai_provider || 'gemini';
        document.getElementById('setting-gemini-api-key').value = settings.gemini_api_key || '';
        document.getElementById('setting-openai-api-key').value = settings.openai_api_key || '';
        document.getElementById('setting-openrouter-api-key').value = settings.openrouter_api_key || '';
        
        // Setup dropdown and trigger change event to populate models correctly
        if (typeof updateModelDropdown === 'function') {
            // Wait to ensure DOM elements exist
            setTimeout(() => {
                const modelSelect = document.getElementById('setting-model-name');
                if (settings.model_name) modelSelect.dataset.savedModel = settings.model_name;
                updateModelDropdown();
            }, 100);
        } else {
            document.getElementById('setting-model-name').value = settings.model_name || 'gemini-2.5-flash-lite';
        }

        document.getElementById('setting-telegram-bot-token').value = settings.telegram_bot_token || '';
        document.getElementById('setting-telegram-chat-id').value = settings.telegram_chat_id || '';
        document.getElementById('setting-fetch-interval').value = settings.fetch_interval_minutes || 5;
        document.getElementById('setting-worker-active').checked = String(settings.worker_active).toLowerCase() === 'true';
        document.getElementById('setting-pre-event-alert-active').checked = String(settings.pre_event_alert_active).toLowerCase() === 'true';
    } catch (error) {
        console.error("Error loading settings:", error);
    }
}

// 8. System Logs View
async function loadLogs() {
    const terminalEl = document.getElementById('logs-terminal');
    
    try {
        const response = await fetch('/api/logs?limit=150');
        const rawLogs = await response.json();
        
        terminalEl.innerHTML = '';
        
        if (rawLogs.length === 0) {
            terminalEl.innerHTML = '<div class="log-line text-muted">No logs available in database. System idle.</div>';
            return;
        }
        
        rawLogs.reverse().forEach(log => {
            const row = document.createElement('div');
            row.className = 'log-line';
            
            // Format timestamp local
            const timeStr = new Date(log.timestamp + 'Z').toLocaleTimeString();
            const levelClass = `log-level-${log.level.toLowerCase()}`;
            
            row.innerHTML = `
                <span class="log-time">[${timeStr}]</span> 
                <span class="badge ${levelClass}">${log.level}</span> 
                <span class="log-module">[${log.module || 'System'}]</span> 
                <span>${escapeHtml(log.message)}</span>
            `;
            
            terminalEl.appendChild(row);
        });
        
        // Auto scroll to bottom
        terminalEl.scrollTop = terminalEl.scrollHeight;
    } catch (error) {
        console.error("Error loading logs:", error);
    }
}

// --- Card Creators ---

function createNewsCard(item) {
    const wrapper = document.createElement('div');
    const impactClass = item.is_important ? 'high-impact' : 'normal';
    wrapper.className = `news-card-wrapper ${impactClass}`;
    
    // Header
    const formattedDate = new Date(item.published_at + 'Z').toLocaleString('th-TH');
    
    // Badge based on importance status
    let importanceBadge = '';
    if (item.is_important === null) {
        importanceBadge = '<span class="badge badge-warning">รอวิเคราะห์ (Pending)</span>';
    } else if (item.is_important) {
        const score = item.ai_analysis?.importance_score || 8;
        importanceBadge = `<span class="badge badge-danger">High Impact (${score}/10)</span>`;
    } else {
        importanceBadge = '<span class="badge badge-gray">Noise</span>';
    }
    
    // HTML Header Structure
    wrapper.innerHTML = `
        <div class="news-card-header">
            <div class="news-meta-left">
                <div class="news-source-date">
                    <span>📰 <b>${escapeHtml(item.source)}</b></span>
                    <span>•</span>
                    <span>${formattedDate}</span>
                </div>
                <div class="news-title-text">${escapeHtml(item.title)}</div>
            </div>
            <div class="news-badges-right">
                ${importanceBadge}
                <i data-lucide="chevron-down" class="chevron-icon"></i>
            </div>
        </div>
    `;
    
    // Click header to toggle expanding details
    const header = wrapper.querySelector('.news-card-header');
    header.addEventListener('click', () => {
        // Close other expanded cards
        const currentlyExpanded = document.querySelector('.news-analysis-body');
        const icon = header.querySelector('.chevron-icon');
        
        const existingBody = wrapper.querySelector('.news-analysis-body');
        if (existingBody) {
            existingBody.remove();
            icon.style.transform = 'rotate(0deg)';
        } else {
            // Expand card
            const body = renderAnalysisBody(item);
            wrapper.appendChild(body);
            icon.style.transform = 'rotate(180deg)';
            lucide.createIcons();
        }
    });
    
    return wrapper;
}

function renderAnalysisBody(item) {
    const body = document.createElement('div');
    body.className = 'news-analysis-body';
    
    if (item.is_important === null) {
        body.innerHTML = `
            <div class="empty-state">
                <p class="text-muted">ข่าวนี้ยังไม่ได้ประมวลผลการวิเคราะห์ด้วย AI</p>
                <button class="btn btn-primary btn-sm mt-10 btn-analyze-now">
                    <i data-lucide="cpu"></i> เริ่มวิเคราะห์เดี๋ยวนี้
                </button>
            </div>
        `;
        
        body.querySelector('.btn-analyze-now').addEventListener('click', async (e) => {
            e.stopPropagation();
            await runManualAnalysis(item.id, body);
        });
        
        return body;
    }
    
    if (!item.is_important) {
        body.innerHTML = `
            <div class="pb-15">
                <h4 class="analysis-headline"><i data-lucide="info"></i> เหตุผลการคัดออกโดย AI:</h4>
                <p style="font-size:0.9rem;">${escapeHtml(item.filter_reason)}</p>
            </div>
            <div class="pb-15" style="font-size:0.85rem; border-top:1px solid var(--card-border); padding-top:15px;">
                <span class="text-muted">เนื้อหาตั้งต้น:</span>
                <p class="text-muted mt-10">${escapeHtml(item.raw_content || 'ไม่มีรายละเอียด')}</p>
            </div>
            <div class="analysis-actions-footer">
                <button class="btn btn-secondary btn-sm btn-analyze-now">
                    <i data-lucide="cpu"></i> บังคับวิเคราะห์ใหม่เป็น High Impact
                </button>
            </div>
        `;
        
        body.querySelector('.btn-analyze-now').addEventListener('click', async (e) => {
            e.stopPropagation();
            await runManualAnalysis(item.id, body);
        });
        
        return body;
    }
    
    // Formulate variables for important news
    const analysis = item.ai_analysis || {};
    const assets = analysis.assets || {};
    const summary = analysis.summary || {};
    const reasoning = analysis.reasoning_chain || "";
    const score = analysis.importance_score || 5;
    const confidence = analysis.confidence_score || 50;
    
    const usd = assets.USD || { impact: '0', reason: 'ไม่มีข้อมูลวิเคราะห์' };
    const gold = assets.Gold || { impact: '0', reason: 'ไม่มีข้อมูลวิเคราะห์' };
    const nasdaq = assets.Nasdaq || { impact: '0', reason: 'ไม่มีข้อมูลวิเคราะห์' };
    const sp500 = assets.SP500 || { impact: '0', reason: 'ไม่มีข้อมูลวิเคราะห์' };
    
    const getImpactClass = (imp) => imp === '+' ? 'pos' : (imp === '-' ? 'neg' : 'neu');
    const getImpactText = (imp) => imp === '+' ? '🟢 บูลลิช (Bullish)' : (imp === '-' ? '🔴 แบร์ริช (Bearish)' : '⚪ นิวทรัล (Neutral)');
    
    body.innerHTML = `
        <div class="pb-15">
            <h4 class="analysis-headline"><i data-lucide="bar-chart-2"></i> ดัชนีผลกระทบสินทรัพย์ (Asset Impacts):</h4>
            <div class="market-impact-grid">
                <div class="asset-impact-box ${getImpactClass(usd.impact)}">
                    <div class="asset-impact-title">ดอลลาร์สหรัฐ (USD)</div>
                    <div class="asset-impact-direction ${getImpactClass(usd.impact)}">${usd.impact === '+' ? '↑' : (usd.impact === '-' ? '↓' : '→')}</div>
                    <div class="asset-impact-desc">${escapeHtml(usd.reason)}</div>
                </div>
                <div class="asset-impact-box ${getImpactClass(gold.impact)}">
                    <div class="asset-impact-title">ทองคำ (Gold)</div>
                    <div class="asset-impact-direction ${getImpactClass(gold.impact)}">${gold.impact === '+' ? '↑' : (gold.impact === '-' ? '↓' : '→')}</div>
                    <div class="asset-impact-desc">${escapeHtml(gold.reason)}</div>
                </div>
                <div class="asset-impact-box ${getImpactClass(nasdaq.impact)}">
                    <div class="asset-impact-title">ดัชนี Nasdaq</div>
                    <div class="asset-impact-direction ${getImpactClass(nasdaq.impact)}">${nasdaq.impact === '+' ? '↑' : (nasdaq.impact === '-' ? '↓' : '→')}</div>
                    <div class="asset-impact-desc">${escapeHtml(nasdaq.reason)}</div>
                </div>
                <div class="asset-impact-box ${getImpactClass(sp500.impact)}">
                    <div class="asset-impact-title">ดัชนี S&P 500</div>
                    <div class="asset-impact-direction ${getImpactClass(sp500.impact)}">${sp500.impact === '+' ? '↑' : (sp500.impact === '-' ? '↓' : '→')}</div>
                    <div class="asset-impact-desc">${escapeHtml(sp500.reason)}</div>
                </div>
            </div>
        </div>

        <div class="thai-summary-box">
            <h4>📌 สรุปภาษาไทยจาก AI (3 บรรทัด):</h4>
            <div class="thai-summary-list">
                <div><span class="bullet">•</span> <b>เหตุการณ์คืออะไร:</b> ${escapeHtml(summary.what_happened || '-')}</div>
                <div><span class="bullet">•</span> <b>ส่งผลกระทบอะไร:</b> ${escapeHtml(summary.what_it_affects || '-')}</div>
                <div><span class="bullet">•</span> <b>ควรจับตาดูอะไรต่อ:</b> ${escapeHtml(summary.what_to_watch_next || '-')}</div>
            </div>
        </div>
        
        ${reasoning ? `
        <div class="reasoning-chain-box">
            <h4>🧠 ขั้นตอนวิเคราะห์เชิงเหตุและผล (Reasoning Chain):</h4>
            <div class="reasoning-code">${escapeHtml(reasoning)}</div>
        </div>
        ` : ''}

        <div class="pb-15" style="font-size:0.85rem; border-top:1px solid var(--card-border); padding-top:15px; margin-bottom:15px;">
            <span class="text-muted">เนื้อหาตั้งต้น (Raw News Content):</span>
            <p class="text-muted mt-10" style="max-height: 120px; overflow-y: auto;">${escapeHtml(item.raw_content || 'ไม่มีรายละเอียดเนื้อหา')}</p>
        </div>

        <div class="analysis-actions-footer">
            <div class="analysis-score-meta">
                <span>ความมั่นใจ: <strong>${confidence}%</strong></span>
                <span>ระดับความสำคัญ: <strong>${score}/10</strong></span>
                <span>สถานะ Telegram: <strong>${item.telegram_sent ? 'ส่งแล้ว ✅' : 'ยังไม่ส่ง ❌'}</strong></span>
            </div>
            <div class="analysis-buttons">
                <button class="btn btn-secondary btn-sm btn-reanalyze"><i data-lucide="rotate-cw"></i> วิเคราะห์ใหม่</button>
                <button class="btn btn-primary btn-sm btn-telegram"><i data-lucide="send"></i> ส่งเข้า Telegram</button>
            </div>
        </div>
    `;
    
    // Add Event Listeners to actions inside expanded card
    body.querySelector('.btn-reanalyze').addEventListener('click', async (e) => {
        e.stopPropagation();
        await runManualAnalysis(item.id, body);
    });
    
    body.querySelector('.btn-telegram').addEventListener('click', async (e) => {
        e.stopPropagation();
        await sendToTelegramManual(item.id, body);
    });
    
    return body;
}

function createCalendarCard(item) {
    const card = document.createElement('div');
    const cal = item.calendar_details || {};
    const impact = cal.impact ? cal.impact.toLowerCase() : 'low';
    
    card.className = `calendar-card ${impact}`;
    
    const formattedDate = new Date(item.published_at + 'Z').toLocaleDateString('th-TH', { month: 'short', day: 'numeric' });
    const formattedTime = cal.event_time || 'ทั้งวัน';
    
    let badgeClass = 'badge-gray';
    if (impact === 'high') badgeClass = 'badge-danger animate-pulse';
    else if (impact === 'medium') badgeClass = 'badge-warning';
    
    card.innerHTML = `
        <div class="calendar-meta-left">
            <div class="calendar-datetime">
                <span class="calendar-date">${formattedDate}</span>
                <span class="calendar-time">${formattedTime}</span>
            </div>
            <div class="calendar-country-badge">${escapeHtml(cal.country || 'USD')}</div>
            <div>
                <span class="badge ${badgeClass} mb-5" style="display:inline-block;">${escapeHtml(cal.impact || 'Low')} Impact</span>
                <div class="calendar-event-title">${escapeHtml(item.title.replace(`[${cal.country}] `, ''))}</div>
            </div>
        </div>
        <div class="calendar-numbers-right">
            <div class="calendar-num-val forecast">
                <span>Forecast</span>
                <code>${escapeHtml(cal.forecast || '-')}</code>
            </div>
            <div class="calendar-num-val previous">
                <span>Previous</span>
                <code>${escapeHtml(cal.previous || '-')}</code>
            </div>
            <button class="btn btn-secondary btn-sm btn-view-calendar-analysis"><i data-lucide="brain"></i> ดูวิเคราะห์</button>
        </div>
    `;
    
    card.querySelector('.btn-view-calendar-analysis').addEventListener('click', () => {
        // Go to News tab, set search filter to this title, apply filter
        document.getElementById('filter-news-search').value = item.title;
        document.querySelector('[data-tab="news"]').click();
    });
    
    return card;
}

function createFeedCard(feed) {
    const card = document.createElement('div');
    card.className = 'card feed-card';
    
    card.innerHTML = `
        <div class="feed-card-header">
            <h3>${escapeHtml(feed.name)}</h3>
            <span class="badge badge-info">Tier ${feed.tier}</span>
        </div>
        <div class="feed-card-url">${escapeHtml(feed.url)}</div>
        <div class="feed-card-footer">
            <div style="display:flex; align-items:center; gap:8px;">
                <span class="text-muted" style="font-size:0.8rem;">สถานะการใช้งาน</span>
                <div class="toggle-switch">
                    <input type="checkbox" id="feed-toggle-${feed.id}" ${feed.active ? 'checked' : ''}>
                    <label for="feed-toggle-${feed.id}" class="toggle-label"></label>
                </div>
            </div>
            <div style="display:flex; gap:8px;">
                <button class="btn-icon-only btn-edit-feed" title="แก้ไข"><i data-lucide="edit-3"></i></button>
                <button class="btn-icon-only btn-delete-feed" style="color:var(--color-red);" title="ลบ"><i data-lucide="trash-2"></i></button>
            </div>
        </div>
    `;
    
    // Active toggling
    card.querySelector(`#feed-toggle-${feed.id}`).addEventListener('change', async (e) => {
        await updateFeedStatus(feed.id, e.target.checked);
    });
    
    // Edit
    card.querySelector('.btn-edit-feed').addEventListener('click', () => {
        openFeedModal(feed);
    });
    
    // Delete
    card.querySelector('.btn-delete-feed').addEventListener('click', async () => {
        if (confirm(`คุณต้องการลบแหล่งข่าว ${feed.name} ใช่หรือไม่?`)) {
            await deleteFeed(feed.id);
        }
    });
    
    return card;
}

// --- Action Handlers ---

async function runManualAnalysis(itemId, containerEl) {
    containerEl.innerHTML = '<div class="empty-state"><p>กำลังประมวลผลการวิเคราะห์ทางเศรษฐกิจผ่าน Gemini AI...</p></div>';
    
    try {
        const response = await fetch(`/api/news/${itemId}/analyze`, { method: 'POST' });
        const result = await response.json();
        
        if (response.ok) {
            showToast("วิเคราะห์ข่าวด้วย AI สำเร็จ!");
            // Re-render analysis body
            const parent = containerEl.parentElement;
            containerEl.remove();
            parent.appendChild(renderAnalysisBody(result.item));
            lucide.createIcons();
            loadStats(); // Update stats
        } else {
            showToast(`เกิดข้อผิดพลาด: ${result.detail}`, true);
            // Restore btn
            loadNewsList();
        }
    } catch (error) {
        console.error("Error analyzing manually:", error);
        showToast("วิเคราะห์ข่าวล้มเหลว", true);
        loadNewsList();
    }
}

async function sendToTelegramManual(itemId, containerEl) {
    const btn = containerEl.querySelector('.btn-telegram');
    const oldText = btn.innerHTML;
    btn.disabled = true;
    btn.innerHTML = '<i class="icon-spin-hover" data-lucide="refresh-cw"></i> กำลังส่ง...';
    lucide.createIcons();
    
    try {
        const response = await fetch(`/api/news/${itemId}/send-telegram`, { method: 'POST' });
        const result = await response.json();
        
        if (response.ok) {
            showToast("ส่งข่าวไปยัง Telegram สำเร็จ!");
            // Update sent badge
            const statusLabel = containerEl.querySelector('.analysis-score-meta span:last-child strong');
            if (statusLabel) statusLabel.textContent = 'ส่งแล้ว ✅';
            loadStats(); // Update stats
        } else {
            showToast(`ส่ง Telegram ล้มเหลว: ${result.detail}`, true);
        }
    } catch (error) {
        console.error("Error dispatching manually:", error);
        showToast("ส่ง Telegram ล้มเหลว", true);
    } finally {
        btn.disabled = false;
        btn.innerHTML = oldText;
        lucide.createIcons();
    }
}

// Settings form save
async function initSettingsForm() {
    const form = document.getElementById('settings-form');
    form.addEventListener('submit', async (e) => {
        e.preventDefault();
        
        const payload = {
            ai_provider: document.getElementById('setting-ai-provider').value,
            gemini_api_key: document.getElementById('setting-gemini-api-key').value,
            openai_api_key: document.getElementById('setting-openai-api-key').value,
            openrouter_api_key: document.getElementById('setting-openrouter-api-key').value,
            model_name: document.getElementById('setting-model-name').value,
            telegram_bot_token: document.getElementById('setting-telegram-bot-token').value,
            telegram_chat_id: document.getElementById('setting-telegram-chat-id').value,
            fetch_interval_minutes: document.getElementById('setting-fetch-interval').value,
            worker_active: document.getElementById('setting-worker-active').checked,
            pre_event_alert_active: document.getElementById('setting-pre-event-alert-active').checked
        };
        
        try {
            const response = await fetch('/api/settings', {
                method: 'PUT',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(payload)
            });
            
            if (response.ok) {
                showToast("บันทึกการตั้งค่าระบบเรียบร้อย!");
                checkAPIKeys();
            } else {
                showToast("บันทึกข้อมูลล้มเหลว", true);
            }
        } catch (error) {
            console.error("Error saving settings:", error);
            showToast("เกิดข้อผิดพลาดในการบันทึกข้อมูล", true);
        }
    });
    
    // Connection test button
    const testBtn = document.getElementById('btn-test-telegram');
    testBtn.addEventListener('click', async () => {
        const oldText = testBtn.innerHTML;
        testBtn.disabled = true;
        testBtn.innerHTML = '<i class="icon-spin-hover" data-lucide="refresh-cw"></i> กำลังส่งข้อความทดสอบ...';
        lucide.createIcons();
        
        try {
            // First save configuration to ensure testing with newest keys
            const payload = {
                gemini_api_key: document.getElementById('setting-gemini-api-key').value,
                telegram_bot_token: document.getElementById('setting-telegram-bot-token').value,
                telegram_chat_id: document.getElementById('setting-telegram-chat-id').value,
                fetch_interval_minutes: document.getElementById('setting-fetch-interval').value,
                worker_active: document.getElementById('setting-worker-active').checked,
                pre_event_alert_active: document.getElementById('setting-pre-event-alert-active').checked
            };
            
            await fetch('/api/settings', {
                method: 'PUT',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(payload)
            });

            const response = await fetch('/api/settings/test-telegram', { method: 'POST' });
            const result = await response.json();
            
            if (response.ok) {
                showToast("ส่งข้อความทดสอบเข้า Telegram สำเร็จ! กรุณาเช็คแอปพลิเคชัน");
            } else {
                showToast(`ทดสอบล้มเหลว: ${result.detail}`, true);
            }
        } catch (error) {
            console.error("Error testing Telegram:", error);
            showToast("ทดสอบส่ง Telegram ล้มเหลว", true);
        } finally {
            testBtn.disabled = false;
            testBtn.innerHTML = oldText;
            lucide.createIcons();
        }
    });
}

// Feeds settings
async function updateFeedStatus(id, active) {
    try {
        await fetch(`/api/feeds/${id}`, {
            method: 'PUT',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ active })
        });
        showToast("ปรับปรุงสถานะการดึงข่าวเรียบร้อย");
    } catch (error) {
        console.error("Error toggling feed status:", error);
    }
}

async function deleteFeed(id) {
    try {
        const response = await fetch(`/api/feeds/${id}`, { method: 'DELETE' });
        if (response.ok) {
            showToast("ลบแหล่งข่าวเรียบร้อย");
            loadFeeds();
        }
    } catch (error) {
        console.error("Error deleting feed:", error);
    }
}

// Modal Form Feed logic
function initFeedForm() {
    const modal = document.getElementById('feed-modal');
    const form = document.getElementById('feed-modal-form');
    
    // Close modal triggers
    const closeBtn = modal.querySelector('.modal-close');
    const cancelBtn = modal.querySelector('.modal-cancel');
    
    const closeModal = () => {
        modal.classList.add('hidden');
        form.reset();
        activeEditFeedId = null;
    };
    
    closeBtn.addEventListener('click', closeModal);
    cancelBtn.addEventListener('click', closeModal);
    
    form.addEventListener('submit', async (e) => {
        e.preventDefault();
        
        const payload = {
            name: document.getElementById('modal-feed-name').value,
            url: document.getElementById('modal-feed-url').value,
            tier: parseInt(document.getElementById('modal-feed-tier').value),
            is_calendar: document.getElementById('modal-feed-is-calendar').checked
        };
        
        try {
            let response;
            if (activeEditFeedId) {
                // Update
                response = await fetch(`/api/feeds/${activeEditFeedId}`, {
                    method: 'PUT',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify(payload)
                });
            } else {
                // Create
                response = await fetch('/api/feeds', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify(payload)
                });
            }
            
            if (response.ok) {
                showToast("บันทึกแหล่งข้อมูลสำเร็จ!");
                closeModal();
                loadFeeds();
            } else {
                const err = await response.json();
                showToast(`เกิดข้อผิดพลาด: ${err.detail}`, true);
            }
        } catch (error) {
            console.error("Error saving feed:", error);
            showToast("บันทึกแหล่งข่าวล้มเหลว", true);
        }
    });
}

function openFeedModal(feed = null) {
    const modal = document.getElementById('feed-modal');
    const titleEl = document.getElementById('feed-modal-title');
    
    modal.classList.remove('hidden');
    
    if (feed) {
        titleEl.textContent = 'แก้ไขแหล่งข่าว';
        activeEditFeedId = feed.id;
        document.getElementById('modal-feed-name').value = feed.name;
        document.getElementById('modal-feed-url').value = feed.url;
        document.getElementById('modal-feed-tier').value = feed.tier;
        document.getElementById('modal-feed-is-calendar').checked = feed.is_calendar;
    } else {
        titleEl.textContent = 'เพิ่มแหล่งข่าวสารใหม่';
        activeEditFeedId = null;
        document.getElementById('modal-feed-name').value = '';
        document.getElementById('modal-feed-url').value = '';
        document.getElementById('modal-feed-tier').value = '1';
        document.getElementById('modal-feed-is-calendar').checked = false;
    }
    
    lucide.createIcons();
}

// 9. Generic Event Listeners
function initGlobalEventListeners() {
    // Sync buttons / trigger background tasks
    const triggerFetch = (btnId) => {
        const btn = document.getElementById(btnId);
        btn.addEventListener('click', async () => {
            const oldText = btn.innerHTML;
            btn.disabled = true;
            btn.innerHTML = '<i class="icon-spin-hover" data-lucide="refresh-cw"></i> กำลังดึงข่าว...';
            lucide.createIcons();
            
            try {
                const response = await fetch('/api/worker/run', { method: 'POST' });
                if (response.ok) {
                    showToast("เริ่มดึงข้อมูลและคัดกรองเบื้องหลังแล้ว!");
                    // Poll stats and highlights after a short delay
                    setTimeout(() => {
                        loadDashboardData();
                    }, 4000);
                } else {
                    showToast("ไม่สามารถเริ่มการประมวลผลได้", true);
                }
            } catch (error) {
                console.error("Error running worker:", error);
            } finally {
                btn.disabled = false;
                btn.innerHTML = oldText;
                lucide.createIcons();
            }
        });
    };
    
    triggerFetch('btn-trigger-fetch');
    triggerFetch('btn-quick-sync');
    
    // Process pending button on dashboard
    const btnProcessPending = document.getElementById('btn-process-pending');
    btnProcessPending.addEventListener('click', async () => {
        btnProcessPending.disabled = true;
        showToast("กำลังประมวลผลข่าวคงค้างทั้งหมดในพื้นหลัง...");
        try {
            await fetch('/api/worker/run', { method: 'POST' });
            setTimeout(() => {
                loadDashboardData();
                btnProcessPending.disabled = false;
            }, 3000);
        } catch (e) {
            btnProcessPending.disabled = false;
        }
    });

    // Go to settings button in quick ops
    document.getElementById('btn-open-settings').addEventListener('click', () => {
        document.querySelector('[data-tab="settings"]').click();
    });

    // Refresh logs button
    document.getElementById('btn-refresh-logs').addEventListener('click', loadLogs);
    
    // Add feed modal trigger
    document.getElementById('btn-add-feed-modal').addEventListener('click', () => {
        openFeedModal();
    });
    
    // Apply news filters button
    document.getElementById('btn-apply-filters').addEventListener('click', loadNewsList);
    
    // Refresh history button
    document.getElementById('btn-refresh-history').addEventListener('click', loadHistoryList);
}

// 10. Helpers

// Toast Notification
function showToast(message, isError = false) {
    const toast = document.getElementById('toast');
    toast.querySelector('.toast-message').textContent = message;
    
    if (isError) {
        toast.style.borderColor = 'var(--color-red)';
        toast.style.boxShadow = '0 4px 15px var(--color-red-glow)';
    } else {
        toast.style.borderColor = 'var(--color-green)';
        toast.style.boxShadow = '0 4px 15px var(--color-green-glow)';
    }
    
    toast.classList.remove('hidden');
    setTimeout(() => {
        toast.classList.add('hidden');
    }, 4000);
}

// Password eye toggler
function initPasswordToggles() {
    const togglers = document.querySelectorAll('.btn-toggle-password');
    togglers.forEach(btn => {
        btn.addEventListener('click', () => {
            const input = btn.previousElementSibling;
            const icon = btn.querySelector('i');
            
            if (input.type === 'password') {
                input.type = 'text';
                icon.setAttribute('data-lucide', 'eye-off');
            } else {
                input.type = 'password';
                icon.setAttribute('data-lucide', 'eye');
            }
            lucide.createIcons();
        });
    });
}

// Escape html helper to prevent XSS
function escapeHtml(text) {
    if (!text) return "";
    const map = {
        '&': '&amp;',
        '<': '&lt;',
        '>': '&gt;',
        '"': '&quot;',
        "'": '&#039;'
    };
    return text.toString().replace(/[&<>"']/g, function(m) { return map[m]; });
}
