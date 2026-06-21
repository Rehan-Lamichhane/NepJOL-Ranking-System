/* static/js/app.js */

// Global state array logs holding background context snapshots
let fullRankingsArray = [];
let scatterChartInstance = null;
let donutChartInstance = null;

// Initialize network system hook when DOM loads completely
window.addEventListener('DOMContentLoaded', async () => {
    if (typeof lucide !== 'undefined') {
        lucide.createIcons();
    }
    await synchronizeSystemEndpoints();
});

async function synchronizeSystemEndpoints() {
    try {
        const response = await fetch('/api/rankings');
        if (!response.ok) throw new Error("HTTP connection synchronization error.");
        
        const data = await response.json();
        if (data.status === "error") throw new Error(data.message);

        // Map global variables to precalculated row frames
        fullRankingsArray = data.journals;

        // Parse metrics directly to scalar cards elements
        document.getElementById('statJournals').innerText = data.metadata.total_journals;
        document.getElementById('statMaxScore').innerText = data.metadata.max_score.toFixed(2);
        document.getElementById('statClusters').innerText = data.metadata.optimal_k;

        // Initialize background graphical canvas components using pickled model metadata boundaries
        renderVisuals(data.metadata.optimal_k);
        filterAndPaintLeaderboard();

    } catch (e) {
        console.error("Infrastructure data sync error: ", e);
        document.getElementById('leaderboardRows').innerHTML = `
            <tr>
                <td colspan="6" class="p-8 text-center font-bold text-rose-500 bg-rose-50/40">
                    Operational Matrix Desync Error: ${e.message}
                </td>
            </tr>
        `;
    }
}

function filterAndPaintLeaderboard() {
    const searchQuery = document.getElementById('masterSearch').value.toLowerCase().trim();
    const jppsFilterValue = document.getElementById('jppsFilter').value;

    // Evaluate filtering rules instantly on client space arrays
    const workingFilteredSet = fullRankingsArray.filter(journal => {
        const matchesSearch = journal['Journal Name'].toLowerCase().includes(searchQuery) || journal['ISSN'].toLowerCase().includes(searchQuery);
        const matchesJPPS = (jppsFilterValue === "ALL") || (journal['JPPS Rating'].trim() === jppsFilterValue.trim());
        return matchesSearch && matchesJPPS;
    });

    const tbody = document.getElementById('leaderboardRows');
    tbody.innerHTML = '';

    if (workingFilteredSet.length === 0) {
        tbody.innerHTML = `<tr><td colspan="6" class="p-12 text-center text-slate-400 font-semibold text-sm">No matched journal properties found within target database lines.</td></tr>`;
        return;
    }

    workingFilteredSet.forEach(journal => {
        const tr = document.createElement('tr');
        tr.className = "hover:bg-slate-50/80 transition-colors cursor-pointer group border-b border-slate-100";
        tr.onclick = () => openJournalDrawer(journal);
        
        // Color palettes tracking array clusters indices dynamically
        const clusterColors = [
            'bg-sky-50 text-sky-700 border-sky-200', 
            'bg-orange-50 text-orange-700 border-orange-200', 
            'bg-emerald-50 text-emerald-700 border-emerald-200', 
            'bg-purple-50 text-purple-700 border-purple-200'
        ];
        const selectedClusterStyle = clusterColors[journal.Cluster % clusterColors.length];

        tr.innerHTML = `
            <td class="px-5 py-4 text-center font-bold text-slate-400 group-hover:text-sky-500 font-mono transition-colors">${journal.Global_Rank}</td>
            <td class="px-5 py-4">
                <div class="font-semibold text-slate-900 group-hover:text-sky-600 transition-colors line-clamp-1">${journal['Journal Name']}</div>
                <div class="text-xs text-slate-400 font-mono mt-0.5 flex items-center gap-2">
                    <span>ISSN: ${journal['ISSN']}</span>
                    <span class="px-1.5 py-0.2 rounded border text-[10px] ${selectedClusterStyle}">Cohort ${journal.Cluster}</span>
                </div>
            </td>
            <td class="px-5 py-4 text-center">
                <span class="px-2 py-1 text-[11px] rounded-md bg-slate-100 text-slate-700 font-bold border border-slate-200/60">${journal['JPPS Rating']}</span>
            </td>
            <td class="px-5 py-4 text-right font-mono text-slate-600 tabular-nums">${Math.round(journal.Average_Views).toLocaleString()}</td>
            <td class="px-5 py-4 text-right font-mono text-slate-600 tabular-nums">${journal.Average_Citations.toFixed(1)}</td>
            <td class="px-5 py-4 text-right pr-6"><span class="font-bold text-sky-600 font-mono bg-sky-50 border border-sky-100 rounded px-2.5 py-1 tabular-nums">${journal.Journal_Score.toFixed(2)}</span></td>
        `;
        tbody.appendChild(tr);
    });
}

// Attach UI inputs observers safely
document.getElementById('masterSearch').addEventListener('input', filterAndPaintLeaderboard);
document.getElementById('jppsFilter').addEventListener('change', filterAndPaintLeaderboard);

function renderVisuals(k) {
    const themeColors = ['#0ea5e9', '#f97316', '#10b981', '#a855f7', '#ec4899'];
    
    const scatterMapSets = Array.from({length: k}, (_, i) => ({
        label: `Cohort ${i}`,
        data: [],
        backgroundColor: themeColors[i % themeColors.length] + 'CC',
        pointRadius: 5,
        hoverRadius: 7
    }));

    const cohortFrequencies = Array(k).fill(0);

    fullRankingsArray.forEach(j => {
        if (j.Cluster < k) {
            scatterMapSets[j.Cluster].data.push({ x: j.Average_Views, y: j.Average_Citations });
            cohortFrequencies[j.Cluster]++;
        }
    });

    const scCtx = document.getElementById('scatterCanvas').getContext('2d');
    if (scatterChartInstance) scatterChartInstance.destroy();
    scatterChartInstance = new Chart(scCtx, {
        type: 'scatter',
        data: { datasets: scatterMapSets },
        options: {
            responsive: true,
            maintainAspectRatio: false,
            plugins: { legend: { labels: { boxWidth: 8, font: { size: 10, weight: 'bold' } } } },
            scales: {
                x: { title: { display: true, text: 'Clean Normalized Views', font: { size: 10, weight: 'bold' } }, grid: { color: '#f1f5f9' } },
                y: { title: { display: true, text: 'Average Citations Metric', font: { size: 10, weight: 'bold' } }, grid: { color: '#f1f5f9' } }
            }
        }
    });

    const dnCtx = document.getElementById('donutCanvas').getContext('2d');
    if (donutChartInstance) donutChartInstance.destroy();
    donutChartInstance = new Chart(dnCtx, {
        type: 'doughnut',
        data: {
            labels: Array.from({length: k}, (_, i) => `Cohort ${i}`),
            datasets: [{
                data: cohortFrequencies,
                backgroundColor: themeColors.slice(0, k),
                borderWidth: 2,
                borderColor: '#ffffff'
            }]
        },
        options: {
            responsive: true,
            maintainAspectRatio: false,
            plugins: { legend: { position: 'bottom', labels: { boxWidth: 10, font: { size: 11 } } } },
            cutout: '70%'
        }
    });
}

// RELATIONAL SLIDEOVER SIDE DRAWER ACTIONS
async function openJournalDrawer(journal) {
    const overlay = document.getElementById('drawerOverlay');
    const container = document.getElementById('drawerContainer');
    const loading = document.getElementById('articlesLoadingState');
    const listContainer = document.getElementById('drawerArticlesList');

    document.getElementById('drawerJournalTitle').innerText = journal['Journal Name'];
    document.getElementById('drawISSN').innerText = journal['ISSN'];
    document.getElementById('drawFreq').innerText = journal['Stated Frequency Num'];
    document.getElementById('drawTotalIssues').innerText = journal['Total_Issues Published'];

    overlay.classList.remove('hidden');
    setTimeout(() => {
        overlay.classList.add('opacity-100');
        container.classList.remove('translate-x-full');
    }, 10);

    loading.classList.remove('hidden');
    listContainer.classList.add('hidden');
    listContainer.innerHTML = '';

    try {
        const response = await fetch(`/api/articles?journal=${encodeURIComponent(journal['Journal Name'])}`);
        if (!response.ok) throw new Error();
        const articles = await response.json();

        loading.classList.add('hidden');
        listContainer.classList.remove('hidden');

        if (articles.length === 0) {
            listContainer.innerHTML = `<p class="text-center py-6 text-slate-400 font-semibold text-xs">No individual paper matrices recorded under this registry title.</p>`;
            return;
        }

        articles.forEach(article => {
            const block = document.createElement('div');
            block.className = "p-4 rounded-xl border border-slate-200/70 bg-white hover:border-sky-300 hover:shadow-md hover:shadow-slate-100/50 transition-all space-y-2";
            block.innerHTML = `
                <div class="font-semibold text-sm text-slate-900 leading-snug">${article['Article Title']}</div>
                <div class="flex flex-wrap items-center justify-between gap-2 text-xs font-medium pt-1">
                    <span class="text-slate-400">Publication Vector: <strong class="text-slate-700">${article['Publication Year'] || '2026'}</strong></span>
                    <div class="flex items-center gap-4 text-slate-500 font-mono">
                        <span class="flex items-center gap-1"><i data-lucide="eye" class="w-3.5 h-3.5"></i> ${article['Views']}</span>
                        <span class="flex items-center gap-1"><i data-lucide="download" class="w-3.5 h-3.5"></i> ${article['Downloads']}</span>
                        <span class="flex items-center gap-1 text-emerald-600 font-bold bg-emerald-50 px-1.5 py-0.5 rounded border border-emerald-100"><i data-lucide="milestone" class="w-3.5 h-3.5"></i> Citations: ${article['Citations']}</span>
                    </div>
                </div>
                <div class="pt-2 border-t border-slate-100 flex items-center justify-between text-xs">
                    <span class="text-slate-400 font-mono text-[10px] bg-slate-50 px-2 py-0.5 rounded border">DOI Status Authenticated</span>
                    <a href="${article['DOI']}" target="_blank" class="text-sky-600 hover:text-sky-700 font-bold flex items-center gap-1 transition-colors">Digital Library Link <i data-lucide="external-link" class="w-3.5 h-3.5"></i></a>
                </div>
            `;
            listContainer.appendChild(block);
        });

        if (typeof lucide !== 'undefined') {
            lucide.createIcons();
        }

    } catch (err) {
        loading.classList.add('hidden');
        listContainer.classList.remove('hidden');
        listContainer.innerHTML = `<p class="text-center text-rose-500 text-xs font-bold py-4">Failed to synchronize dynamic relational publications sub-matrix logs.</p>`;
    }
}

function closeDrawer() {
    const overlay = document.getElementById('drawerOverlay');
    const container = document.getElementById('drawerContainer');

    overlay.classList.remove('opacity-100');
    container.classList.add('translate-x-full');
    setTimeout(() => overlay.classList.add('hidden'), 300);
}