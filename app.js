/* ============================================================
   SOC TERMINAL — APPLICATION LOGIC
   Krajowy Rejestr Operacji Sieciowych
   ============================================================ */

'use strict';

// ── Konfiguracja ─────────────────────────────────────────────
const CONFIG = {
    apiUrl: 'https://api.github.com/events?per_page=100',
    fetchInterval: 30,      // Sekundy między skanami API
    streamInterval: 1800,   // Ms między emisją kolejnego wiersza z bufora
};

// ── Stan aplikacji ───────────────────────────────────────────
const state = {
    seenIds: new Set(),
    buffer: [],
    totalItems: 0,
    countdown: CONFIG.fetchInterval,
    streamTimer: null,
    fetchTimer: null,
};

// ── Elementy DOM ─────────────────────────────────────────────
const DOM = {
    clock:          () => document.getElementById('clock'),
    countdown:      () => document.getElementById('countdown'),
    totalCount:     () => document.getElementById('totalCount'),
    bufferCount:    () => document.getElementById('bufferCount'),
    streamBody:     () => document.getElementById('streamBody'),
    searchInput:    () => document.getElementById('mainSearch'),
    emptyState:     () => document.getElementById('emptyState'),
    initialState:   () => document.getElementById('initialState'),
    syncDot:        () => document.getElementById('syncDot'),
    syncLabel:      () => document.getElementById('syncLabel'),
    lastActionLog:  () => document.getElementById('lastActionLog'),
};

// ── Zegar systemowy ──────────────────────────────────────────
function startClock() {
    function tick() {
        DOM.clock().textContent = new Date().toLocaleTimeString('pl-PL', { hour12: false });
    }
    tick();
    setInterval(tick, 1000);
}

// ── Odliczanie do następnego skanu ───────────────────────────
function startCountdown() {
    state.countdown = CONFIG.fetchInterval;

    setInterval(() => {
        state.countdown--;
        if (state.countdown < 0) {
            state.countdown = CONFIG.fetchInterval;
            fetchToBuffer();
        }
        DOM.countdown().textContent = state.countdown + 's';
    }, 1000);
}

// ── Status synchronizacji ────────────────────────────────────
function setSyncStatus(status) {
    const dot = DOM.syncDot();
    const label = DOM.syncLabel();
    dot.className = 'sync-dot';

    switch (status) {
        case 'scanning':
            dot.classList.add('sync-scanning');
            label.textContent = 'Synchronizacja...';
            label.style.color = '#f59e0b';
            break;
        case 'error':
            dot.classList.add('sync-error');
            label.textContent = 'Błąd połączenia';
            label.style.color = '#ef4444';
            break;
        default:
            dot.classList.add('sync-ok');
            label.textContent = 'Monitorowanie';
            label.style.color = '';
    }
}

function setLastAction(msg) {
    DOM.lastActionLog().textContent = msg;
}

// ── Pobieranie danych do bufora ──────────────────────────────
async function fetchToBuffer() {
    setSyncStatus('scanning');

    try {
        const response = await fetch(CONFIG.apiUrl);

        if (!response.ok) {
            throw new Error(`HTTP ${response.status}`);
        }

        const data = await response.json();

        // Odwróć kolejność, by najstarsze z paczki trafiły do bufora pierwsze
        const reversed = [...data].reverse();

        let added = 0;
        reversed.forEach(event => {
            if (!state.seenIds.has(event.id)) {
                state.buffer.push(event);
                state.seenIds.add(event.id);
                added++;
            }
        });

        setLastAction(
            added > 0
                ? `[${new Date().toLocaleTimeString('pl-PL')}] Zbuforowano ${added} nowych zdarzeń`
                : `[${new Date().toLocaleTimeString('pl-PL')}] Brak nowych zdarzeń — baza aktualna`
        );

        setSyncStatus('ok');
        updateBufferCount();

        // Schowaj stan inicjalizacyjny
        if (DOM.initialState()) {
            DOM.initialState().classList.add('hidden');
        }
    } catch (err) {
        setSyncStatus('error');
        setLastAction(`[${new Date().toLocaleTimeString('pl-PL')}] Błąd połączenia z węzłem: ${err.message}`);
        console.error('[SOC] Błąd pobierania danych:', err);
    }
}

// ── Strumień emisji (bufor → tabela) ─────────────────────────
function startStreamEmitter() {
    state.streamTimer = setInterval(() => {
        if (state.buffer.length === 0) return;

        const event = state.buffer.shift();
        renderRow(event);
        updateBufferCount();
    }, CONFIG.streamInterval);
}

// ── Renderowanie wiersza ─────────────────────────────────────
function renderRow(event) {
    const body = DOM.streamBody();
    const row = document.createElement('tr');
    row.className = 'stream-row';

    const type = event.type.replace('Event', '');
    const time = new Date(event.created_at).toLocaleTimeString('pl-PL', { hour12: false });
    const repoName = event.repo.name;

    row.innerHTML = `
        <td class="cell-operator">@${escapeHtml(event.actor.login)}</td>
        <td class="cell-type"><span class="badge ${getBadgeClass(type)}">${escapeHtml(type)}</span></td>
        <td class="cell-repo"><span>${escapeHtml(repoName)}</span></td>
        <td class="cell-time">${time}</td>
    `;

    body.prepend(row);
    state.totalItems++;

    updateTotalCount();
    applyCurrentFilter(row);
}

// ── Escape HTML (zabezpieczenie przed XSS) ───────────────────
function escapeHtml(str) {
    if (!str) return '';
    return String(str)
        .replace(/&/g, '&amp;')
        .replace(/</g, '&lt;')
        .replace(/>/g, '&gt;')
        .replace(/"/g, '&quot;')
        .replace(/'/g, '&#039;');
}

// ── Badge CSS na podstawie typu ──────────────────────────────
function getBadgeClass(type) {
    const map = {
        'Push':               'badge-push',
        'Create':             'badge-create',
        'Delete':             'badge-delete',
        'Watch':              'badge-watch',
        'Fork':               'badge-fork',
        'Issues':             'badge-issues',
        'IssueComment':       'badge-issues',
        'PullRequest':        'badge-pullreq',
        'PullRequestReview':  'badge-pullreq',
    };
    return map[type] || 'badge-default';
}

// ── Aktualizacje liczników ────────────────────────────────────
function updateTotalCount() {
    DOM.totalCount().textContent = state.totalItems.toLocaleString('pl-PL');
}

function updateBufferCount() {
    DOM.bufferCount().textContent = state.buffer.length.toLocaleString('pl-PL');
}

// ── Wyszukiwarka ─────────────────────────────────────────────
function initSearch() {
    DOM.searchInput().addEventListener('input', function () {
        const term = this.value.toLowerCase().trim();
        filterTable(term);
    });
}

function filterTable(term) {
    const rows = DOM.streamBody().querySelectorAll('tr');
    let visibleCount = 0;

    rows.forEach(row => {
        const text = row.textContent.toLowerCase();
        const match = !term || text.includes(term);
        row.style.display = match ? '' : 'none';
        if (match) visibleCount++;
    });

    const hasRows = DOM.streamBody().childElementCount > 0;
    const empty = DOM.emptyState();

    if (hasRows && visibleCount === 0) {
        empty.classList.remove('hidden');
    } else {
        empty.classList.add('hidden');
    }
}

// Zastosuj bieżący filtr do nowo dodanego wiersza
function applyCurrentFilter(row) {
    const term = DOM.searchInput().value.toLowerCase().trim();
    if (!term) return;

    const text = row.textContent.toLowerCase();
    if (!text.includes(term)) {
        row.style.display = 'none';
    }

    // Odśwież komunikat "brak wyników"
    filterTable(term);
}

// ── Uruchomienie aplikacji ────────────────────────────────────
function init() {
    startClock();
    initSearch();
    startCountdown();
    startStreamEmitter();
    fetchToBuffer(); // Pierwsze pobranie od razu
}

document.addEventListener('DOMContentLoaded', init);
