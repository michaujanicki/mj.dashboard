/* ============================================================
   SOC TERMINAL — APPLICATION LOGIC
   Krajowy Rejestr Operacji Sieciowych
   ============================================================ */

'use strict';

// ── Konfiguracja ─────────────────────────────────────────────
const CONFIG = {
    apiUrl: 'https://api.github.com/events?per_page=300',
    fetchInterval: 10,       // Sekundy między skanami API
    maxStoredEvents: 10000, // Maksimalna liczba zdarzeń w pamięci
    pagesPerFetch: 3,       // Pobieraj 3 strony × 300 = 900 eventów
    githubToken: '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',
};

// ── Stan aplikacji ───────────────────────────────────────────
const state = {
    seenIds: new Map(),  // Map: id -> timestamp (aby śledzić wiek wpisu)
    totalItems: 0,
    countdown: CONFIG.fetchInterval,
    fetchTimer: null,
    lastFetchSize: 0,   // Ile nowych eventów w ostatnim pobraniu
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

// ── Pobieranie danych i emisja natychmiast ──────────────────
async function fetchToBuffer() {
    setSyncStatus('scanning');

    try {
        // Wymuś limit 10000 zdarzeń — usuń najstarsze jeśli przekroczony
        enforceMaxEvents();

        // Pobierz wiele stron naraz (1-3 = 900 eventów)
        const pageRequests = [];
        for (let page = 1; page <= CONFIG.pagesPerFetch; page++) {
            const url = `${CONFIG.apiUrl}&page=${page}`;
            pageRequests.push(
                fetch(url, {
                    headers: {
                        'Authorization': `Bearer ${CONFIG.githubToken}`
                    }
                })
                    .then(r => r.ok ? r.json() : [])
                    .catch(() => [])  // Jeśli błąd, zwróć pustą tablicę
            );
        }

        const allPages = await Promise.all(pageRequests);
        let allEvents = [];
        allPages.forEach(page => {
            if (Array.isArray(page)) {
                allEvents = allEvents.concat(page);
            }
        });

        // Deduplikuj po ID i odwróć kolejność (najstarsze z paczki pierwsze)
        const uniqueIds = new Set();
        const dedupedEvents = [];
        for (let event of allEvents.reverse()) {
            if (!uniqueIds.has(event.id)) {
                uniqueIds.add(event.id);
                dedupedEvents.push(event);
            }
        }

        let added = 0;
        dedupedEvents.forEach(event => {
            if (!state.seenIds.has(event.id)) {
                state.seenIds.set(event.id, Date.now());  // Pamiętaj czas pobrania
                renderRow(event);  // Renderuj od razu, bez bufora
                added++;
            }
        });

        state.lastFetchSize = added;

        setLastAction(
            added > 0
                ? `[${new Date().toLocaleTimeString('pl-PL')}] Dodano ${added} nowych zdarzeń (${state.seenIds.size} w cache)`
                : `[${new Date().toLocaleTimeString('pl-PL')}] Brak nowych zdarzeń — baza aktualna (${state.seenIds.size} w cache)`
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

// ── [Usunięto] Strumień emisji — teraz renderowanie natychmiast ──

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
    DOM.bufferCount().textContent = state.seenIds.size.toLocaleString('pl-PL');
}

// ── Czyszczenie starych ID — limit do 10000 zdarzeń ──────────
function enforceMaxEvents() {
    // Jeśli przekroczyliśmy 10000, usuń najstarsze zdarzenia
    if (state.seenIds.size > CONFIG.maxStoredEvents) {
        // Konwertuj Map na Array, sortuj po timestamp, usuń najstarsze
        const entries = Array.from(state.seenIds.entries());
        entries.sort((a, b) => a[1] - b[1]);
        
        const toDelete = entries.length - CONFIG.maxStoredEvents;
        const rows = DOM.streamBody().querySelectorAll('tr');
        let rowsToRemove = 0;

        // Usuń ze starej części tabeli (od tyłu)
        for (let i = rows.length - 1; i >= 0 && rowsToRemove < toDelete; i--) {
            rows[i].remove();
            rowsToRemove++;
        }

        // Usuń ze seenIds
        for (let i = 0; i < toDelete; i++) {
            state.seenIds.delete(entries[i][0]);
        }

        // Zsynchronizuj totalItems
        state.totalItems = DOM.streamBody().querySelectorAll('tr').length;
        updateTotalCount();
    }
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
    fetchToBuffer(); // Pierwsze pobranie od razu
}

document.addEventListener('DOMContentLoaded', init);
