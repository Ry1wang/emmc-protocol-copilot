import { marked } from 'https://cdn.jsdelivr.net/npm/marked/lib/marked.esm.js';

const appState = {
    allChunks: [],
    filteredChunks: [],
    currentType: 'all',
    searchText: '',
    resultsPerPage: 50,
    visibleCount: 50
};

const dom = {
    main: document.querySelector('main'),
    search: document.querySelector('.search-box'),
    filterGroup: document.querySelector('.filter-group'),
    stats: document.querySelector('.stats-content'),
    versionSelect: document.querySelector('#doc-version')
};

// Debounce helper to prevent UI lag during typing
function debounce(fn, wait) {
    let timeout;
    return (...args) => {
        clearTimeout(timeout);
        timeout = setTimeout(() => fn.apply(this, args), wait);
    };
}

async function loadData(filename = 'JESD84-B51_chunks.jsonl') {
    dom.main.innerHTML = '<div style="display: flex; justify-content: center; align-items: center; height: 100%; color: var(--text-muted)">Loading document...</div>';
    try {
        const response = await fetch(`../../data/processed/${filename}`);
        if (!response.ok) throw new Error(`HTTP ${response.status} - ${response.statusText}`);
        const text = await response.text();

        const lines = text.trim().split('\n');
        const chunks = [];
        for (const [idx, line] of lines.entries()) {
            try {
                if (line.trim()) {
                    chunks.push(JSON.parse(line));
                }
            } catch (e) {
                console.error(`Error parsing line ${idx + 1} of ${filename}:`, e);
            }
        }

        appState.allChunks = chunks;
        appState.visibleCount = appState.resultsPerPage;
        refreshView();
    } catch (err) {
        console.error("Failed to load chunks:", err);
        dom.main.innerHTML = `<div class="error-msg">Error loading ${filename}.<br>Make sure the file exists and the server is running.<br>${err.message}</div>`;
    }
}

function refreshView() {
    renderStats();
    renderChunks();
    dom.main.scrollTop = 0;
}

function renderStats() {
    const total = appState.allChunks.length;
    const bodyChunks = appState.allChunks.filter(c => !c.is_front_matter);
    const bodyCount = bodyChunks.length;
    const frontCount = total - bodyCount;

    // Type breakdown for non-front-matter
    const typeCounts = bodyChunks.reduce((acc, curr) => {
        acc[curr.content_type] = (acc[curr.content_type] || 0) + 1;
        return acc;
    }, {});

    let html = `
        <div style="border-bottom: 1px solid var(--border); padding-bottom: 0.8rem; margin-bottom: 0.8rem">
            <div style="display:flex; justify-content:space-between; margin-bottom: 0.4rem">
                <span>Total Chunks:</span> <span style="font-weight:700">${total}</span>
            </div>
            <div style="display:flex; justify-content:space-between; margin-bottom: 0.4rem; color: #60a5fa">
                <span>Body:</span> <span style="font-weight:700">${bodyCount}</span>
            </div>
            <div style="display:flex; justify-content:space-between; color: var(--text-muted)">
                <span>Front Matter:</span> <span style="font-weight:700">${frontCount}</span>
            </div>
        </div>
    `;

    html += Object.entries(typeCounts).map(([type, count]) => `
        <div style="display:flex; justify-content:space-between; margin-bottom: 0.4rem; font-size: 0.85rem">
          <span style="text-transform: capitalize; color: #94a3b8">${type}:</span>
          <span style="font-weight:600">${count}</span>
        </div>
    `).join('');

    dom.stats.innerHTML = html;
}

function renderChunks() {
    const query = appState.searchText.toLowerCase();

    // 1. Filter
    appState.filteredChunks = appState.allChunks.filter(c => {
        let typeMatch = false;
        if (appState.currentType === 'all') {
            typeMatch = true;
        } else if (appState.currentType === 'front_matter') {
            typeMatch = c.is_front_matter === true;
        } else {
            typeMatch = c.content_type === appState.currentType && !c.is_front_matter;
        }

        const textMatch = !query ||
            c.text.toLowerCase().includes(query) ||
            c.section_title.toLowerCase().includes(query) ||
            (c.chunk_id && c.chunk_id.toLowerCase().includes(query));

        return typeMatch && textMatch;
    });

    // 2. Clear and Render
    dom.main.innerHTML = '';

    if (appState.filteredChunks.length === 0) {
        dom.main.innerHTML = '<div style="display: flex; justify-content: center; align-items: center; height: 100%; color: var(--text-muted)">No matching chunks found.</div>';
        return;
    }

    const itemsToShow = appState.filteredChunks.slice(0, appState.visibleCount);
    const fragment = document.createDocumentFragment();

    itemsToShow.forEach(chunk => {
        fragment.appendChild(createChunkCard(chunk));
    });
    dom.main.appendChild(fragment);

    // 3. Load More Trigger
    if (appState.allChunks.length > 0 && appState.filteredChunks.length > appState.visibleCount) {
        const moreWrapper = document.createElement('div');
        moreWrapper.style.padding = '2rem';
        moreWrapper.style.textAlign = 'center';

        const moreBtn = document.createElement('button');
        moreBtn.className = 'filter-btn active';
        moreBtn.style.padding = '0.75rem 2rem';
        moreBtn.style.cursor = 'pointer';
        moreBtn.textContent = `Load More Content (+${Math.min(appState.resultsPerPage, appState.filteredChunks.length - appState.visibleCount)})`;

        moreBtn.onclick = () => {
            appState.visibleCount += appState.resultsPerPage;
            renderChunks();
        };

        const countInfo = document.createElement('p');
        countInfo.style.marginTop = '1rem';
        countInfo.style.fontSize = '0.8rem';
        countInfo.style.color = 'var(--text-muted)';
        countInfo.textContent = `Showing ${appState.visibleCount} of ${appState.filteredChunks.length} results`;

        moreWrapper.appendChild(moreBtn);
        moreWrapper.appendChild(countInfo);
        dom.main.appendChild(moreWrapper);
    }
}

function createChunkCard(chunk) {
    const pathStr = chunk.section_path.join(' > ');
    let text = chunk.text;

    // Highlight the Register Context if present (custom feature)
    text = text.replace("**Register Context: ", "<span style='color: #fbbf24; font-weight: 600'>Register Context: ");
    text = text.replace(" (cont’d)**", " (cont'd)</span>");

    const card = document.createElement('div');
    card.className = 'chunk-card';

    const isReg = chunk.content_type === 'register';

    card.innerHTML = `
    <div class="chunk-header">
      <div style="display: flex; align-items: center; gap: 0.5rem">
        ${chunk.is_front_matter ? '<span class="chunk-badge" style="background: rgba(148, 163, 184, 0.2); color: #94a3b8">FRONT MATTER</span>' : ''}
        <span class="chunk-badge badge-${chunk.content_type}">${chunk.content_type}</span>
        <span style="font-size: 0.8rem; color: #94a3b8">Page ${chunk.page_start}</span>
      </div>
      <div class="chunk-path">${pathStr || 'Root'}</div>
    </div>
    <div class="chunk-body">
      <h3 style="font-size: 1.1rem; margin-bottom: 1rem; color: ${isReg ? '#fbbf24' : '#3b82f6'}">
        ${chunk.section_title || 'Untitled Section'}
      </h3>
      <div class="markdown-content">
        ${marked.parse(text)}
      </div>
    </div>
    <div style="margin-top: 1.5rem; display: flex; gap: 0.5rem; border-top: 1px solid rgba(255,255,255,0.05); padding-top: 1rem">
       <button class="footer-action-btn" onclick="copyToClipboard('${chunk.chunk_id}')">Copy ID</button>
       <button class="footer-action-btn" onclick="copyToClipboard('${chunk.text.replace(/'/g, "\\'")}')">Copy Text</button>
    </div>
  `;
    return card;
}

// Global actions
window.copyToClipboard = (text) => {
    navigator.clipboard.writeText(text).then(() => {
        // Notification could go here
    });
};

// Event Listeners
dom.search.addEventListener('input', debounce((e) => {
    appState.searchText = e.target.value;
    appState.visibleCount = appState.resultsPerPage; // Reset scroll on search
    renderChunks();
}, 250));

dom.filterGroup.addEventListener('click', (e) => {
    if (e.target.classList.contains('filter-btn')) {
        document.querySelectorAll('.filter-btn').forEach(b => b.classList.remove('active'));
        e.target.classList.add('active');
        appState.currentType = e.target.dataset.type;
        appState.visibleCount = appState.resultsPerPage; // Reset scroll on filter
        renderChunks();
        dom.main.scrollTop = 0;
    }
});

dom.versionSelect.addEventListener('change', (e) => {
    loadData(e.target.value);
});

// Initialization
loadData();
