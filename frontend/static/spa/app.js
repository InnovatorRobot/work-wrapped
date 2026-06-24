// Work Wrapped — React 18 SPA (no build step; uses vendored React + htm).
// Talks to the existing JSON APIs with the session cookie. Reuses app.css.

const html = htm.bind(React.createElement);
const { useState, useEffect, useCallback, useRef } = React;

/* ----------------------------- API helpers ----------------------------- */
async function api(path, opts = {}) {
    const res = await fetch(path, {
        credentials: 'same-origin',
        headers: opts.body ? { 'Content-Type': 'application/json' } : undefined,
        ...opts,
    });
    if (res.status === 401 || res.status === 307) {
        window.location.href = '/login';
        throw new Error('unauthorized');
    }
    const text = await res.text();
    try { return { ok: res.ok, status: res.status, data: text ? JSON.parse(text) : null }; }
    catch (e) { return { ok: res.ok, status: res.status, data: null }; }
}
const getJSON = (p) => api(p).then(r => r.data);
const postJSON = (p, body) => api(p, { method: 'POST', body: JSON.stringify(body || {}) }).then(r => r.data);
const delJSON = (p) => api(p, { method: 'DELETE' }).then(r => r.data);

/* ----------------------------- small utils ----------------------------- */
const trendPct = (cur, prev) => prev === 0 ? (cur > 0 ? '+' : '') : (((cur - prev) / prev) * 100).toFixed(0);
function fetchedAt(iso) {
    if (!iso) return '—';
    const d = new Date(iso); if (isNaN(d.getTime())) return iso;
    const min = Math.floor((Date.now() - d) / 60000);
    if (min < 1) return 'just now'; if (min < 60) return min + ' min ago';
    const h = Math.floor(min / 60); if (h < 24) return h + ' h ago';
    return d.toLocaleString(undefined, { dateStyle: 'short', timeStyle: 'short' });
}

/* ----------------------------- routing --------------------------------- */
function useHashRoute() {
    const [route, setRoute] = useState(window.location.hash.replace(/^#/, '') || '/');
    useEffect(() => {
        const on = () => setRoute(window.location.hash.replace(/^#/, '') || '/');
        window.addEventListener('hashchange', on);
        return () => window.removeEventListener('hashchange', on);
    }, []);
    return route;
}

/* ----------------------------- shared UI ------------------------------- */
function Spinner({ label }) {
    return html`<p style=${{ color: 'var(--text-muted)' }}>${label || 'Loading…'}</p>`;
}
function RangeSelect({ value, options, onChange }) {
    return html`
        <div style=${{ display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
            <label style=${{ color: 'var(--text-muted)', fontSize: '0.85rem' }}>Range</label>
            <select value=${value} onChange=${e => onChange(parseInt(e.target.value, 10))}>
                ${(options || []).map(([m, label]) => html`<option key=${m} value=${m}>${label}</option>`)}
            </select>
        </div>`;
}

function usePersonal() {
    const [data, setData] = useState(null);
    const [months, setMonths] = useState(null);
    const load = useCallback(async (m, refresh) => {
        let url = '/api/personal';
        const qs = [];
        if (m != null) qs.push('months=' + m);
        if (refresh) qs.push('refresh=1');
        if (qs.length) url += '?' + qs.join('&');
        const d = await getJSON(url);
        setData(d); if (d && d.months != null) setMonths(d.months);
    }, []);
    useEffect(() => { load(); }, [load]);
    return { data, months, load };
}

/* ----------------------------- Sidebar --------------------------------- */
const NAV = [
    ['#/', '▤', 'Overview'],
    ['__group', '', 'Sources'],
    ['#/gerrit', '◆', 'Gerrit'],
    ['#/jira', '▦', 'Jira'],
    ['#/confluence', '❏', 'Confluence'],
    ['#/slack', '✦', 'Slack'],
    ['__group', '', 'Reflect'],
    ['#/insights', '✧', 'Insights'],
    ['#/goals', '◎', 'Goals'],
    ['#/meetings', '☷', '1:1s'],
    ['__group', '', 'Team'],
    ['#/team', '⚇', 'Team'],
    ['#/manager', '⚐', 'Manager'],
    ['__group', '', 'Setup'],
    ['#/connections', '⚏', 'Connections'],
    ['#/settings', '⚙', 'Settings'],
];

function Sidebar({ route, open, onClose }) {
    const link = ([href, icon, label]) => {
        if (href === '__group') return html`<div key=${label} class="nav-group-label">${label}</div>`;
        const path = href.slice(1);
        const active = route === path || (href === '#/' && route === '/');
        return html`<a key=${href} href=${href} class=${active ? 'active' : ''} onClick=${onClose}>
            <span class="ni">${icon}</span> ${label}</a>`;
    };
    return html`
        <aside class=${'sidebar' + (open ? ' open' : '')}>
            <div class="sidebar-brand">
                <img src="/static/logo.png" alt="Zenseact" class="sidebar-logo" onError=${e => e.target.style.display = 'none'} />
                <div><div class="sidebar-title">Work Wrapped</div><div class="sidebar-version">React UI</div></div>
            </div>
            <nav class="sidebar-nav">
                ${NAV.map(link)}
            </nav>
            <div class="sidebar-footer">
                <button class="theme-toggle" onClick=${toggleTheme}><span class="ni">◐</span> Theme</button>
                <a href="/logout" class="nav-logout"><span class="ni">⏻</span> Log out</a>
            </div>
        </aside>`;
}
function toggleTheme() {
    const isLight = document.documentElement.getAttribute('data-theme') === 'light';
    const next = isLight ? 'dark' : 'light';
    document.documentElement.setAttribute('data-theme', next);
    try { localStorage.setItem('ww-theme', next); } catch (e) { }
}

/* ----------------------------- Overview -------------------------------- */
function Overview() {
    const { data, months, load } = usePersonal();
    if (!data) return html`<${Spinner} label="Loading your activity…" />`;
    const t = data.totals || {}, user = data.user || {};
    const bm = data.busiest_month_cross, bw = data.busiest_week;
    const stats = [['Jira', 'jira', t.jira || 0, 'tickets'], ['Gerrit', 'gerrit', t.gerrit || 0, 'changes'],
    ['Confluence', 'confluence', t.confluence || 0, 'pages'], ['Slack', 'slack', t.slack || 0, 'messages']];
    const cards = [
        ['#/insights', '✧ Insights', 'AI summary, ask your data & trends'],
        ['#/goals', '◎ Goals', 'Objectives, targets & snapshots'],
        ['#/meetings', '☷ 1:1s', 'Agendas, notes & action items'],
        ['#/gerrit', '◆ Gerrit', (t.gerrit || 0) + ' changes'],
        ['#/jira', '▦ Jira', (t.jira || 0) + ' tickets'],
        ['#/confluence', '❏ Confluence', (t.confluence || 0) + ' pages'],
        ['#/slack', '✦ Slack', (t.slack || 0) + ' messages'],
        ['#/team', '⚇ Team', 'Aggregated team view'],
    ];
    return html`
        <div style=${{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-end', gap: '1rem', flexWrap: 'wrap', marginBottom: '1.25rem' }}>
            <div>
                <h1 class="hero-greeting">Hi, ${user.name || 'there'} 👋</h1>
                <p style=${{ color: 'var(--text-muted)', margin: 0 }}>Here's your work at a glance — for reflection, not ranking.</p>
            </div>
            <${RangeSelect} value=${months || 12} options=${data.time_range_options} onChange=${m => load(m)} />
        </div>
        <div class="stat-grid" style=${{ marginBottom: '1.25rem' }}>
            ${stats.map(([name, cls, num, unit]) => html`
                <div key=${cls} class="card stat-card">
                    <div class="stat-num">${num}</div>
                    <div class="stat-label"><span class=${'badge badge-' + cls}>${name}</span> ${unit}</div>
                </div>`)}
        </div>
        ${(bm || bw || data.focus_score_pct != null || data.trend_label) && html`
            <div class="card" style=${{ marginBottom: '1.25rem' }}><p style=${{ margin: 0, fontSize: '0.92rem' }}>
                ${bm && html`Busiest month: <strong>${bm.label || bm.month}</strong> (${bm.count}). `}
                ${bw && html`Busiest week: <strong>${bw.label}</strong> (${bw.count}). `}
                ${data.focus_score_pct != null && html`Focus: <strong>${data.focus_score_pct}%</strong> in top 2 areas. `}
                ${data.trend_label && html`Trend: <strong>${data.trend_label}</strong>.`}
            </p></div>`}
        ${(data.nudges || []).length > 0 && html`
            <div class="card nudge-card" style=${{ marginBottom: '1.25rem' }}>
                <h3 style=${{ fontSize: '0.95rem', margin: '0 0 0.5rem' }}>Reminders</h3>
                <ul style=${{ margin: 0, paddingLeft: '1.25rem', fontSize: '0.9rem', color: 'var(--text-muted)' }}>
                    ${data.nudges.map((n, i) => html`<li key=${i}>${n.message || n}</li>`)}
                </ul>
            </div>`}
        <h3 class="chart-section-title">Explore</h3>
        <div class="nav-card-grid" style=${{ marginBottom: '1.5rem' }}>
            ${cards.map(([href, title, desc]) => html`
                <a key=${href} class="card nav-card" href=${href}>
                    <div class="nav-card-title">${title}</div><div class="nav-card-desc">${desc}</div>
                </a>`)}
        </div>
        <p style=${{ fontSize: '0.83rem', color: 'var(--text-muted)' }}>
            Data as of ${fetchedAt(data.fetched_at)} · <a href="#" onClick=${e => { e.preventDefault(); load(months, true); }} style=${{ color: 'var(--accent)' }}>Refresh</a>
        </p>`;
}

/* ----------------------------- Insights -------------------------------- */
function AiSummary({ months }) {
    const [state, setState] = useState({ status: 'idle', text: '', error: '', cached: false });
    const gen = async () => {
        setState({ status: 'loading', text: '', error: '', cached: false });
        try {
            const d = await getJSON('/api/ai-summary?months=' + (months || 12));
            if (d.ok) setState({ status: 'done', text: d.narrative, cached: !!d.cached });
            else if (d.configured === false) setState({ status: 'error', error: 'No local LLM configured. Set OPENAI_BASE_URL to your Ollama server in .env and restart.' });
            else setState({ status: 'error', error: d.error || 'Could not generate a summary.' });
        } catch (e) { setState({ status: 'error', error: 'Could not reach the server.' }); }
    };
    return html`
        <div class="card" style=${{ marginBottom: '1rem' }}>
            <div style=${{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', gap: '0.75rem', flexWrap: 'wrap' }}>
                <div>
                    <h3 style=${{ fontSize: '0.95rem', margin: '0 0 0.2rem' }}>AI summary</h3>
                    <p style=${{ fontSize: '0.82rem', color: 'var(--text-muted)', margin: 0 }}>A short narrative written locally by an LLM from your activity.</p>
                </div>
                <button class="btn btn-primary btn-sm" disabled=${state.status === 'loading'} onClick=${gen}>${state.status === 'loading' ? 'Generating…' : 'Generate'}</button>
            </div>
            ${state.status === 'loading' && html`<p style=${{ fontSize: '0.85rem', color: 'var(--text-muted)', marginTop: '0.85rem' }}>Asking the model… this can take a moment.</p>`}
            ${state.status === 'done' && html`<div style=${{ marginTop: '0.85rem' }}>
                <div style=${{ fontSize: '0.9rem', lineHeight: 1.55, whiteSpace: 'pre-wrap' }}>${state.text}</div>
                ${state.cached && html`<span style=${{ fontSize: '0.75rem', color: 'var(--text-faint)' }}>cached</span>`}
            </div>`}
            ${state.status === 'error' && html`<p style=${{ fontSize: '0.85rem', color: 'var(--text-muted)', marginTop: '0.85rem' }}>${state.error}</p>`}
        </div>`;
}
function AskData() {
    const [hist, setHist] = useState([]);
    const [q, setQ] = useState('');
    const [busy, setBusy] = useState(false);
    const threadRef = useRef(null);
    useEffect(() => { if (threadRef.current) threadRef.current.scrollTop = threadRef.current.scrollHeight; }, [hist]);
    const ask = async (preset) => {
        const question = (preset || q || '').trim(); if (!question) return;
        setQ('');
        const prior = hist.filter(m => !m.pending);
        const next = [...prior, { role: 'user', content: question }, { role: 'assistant', content: '…thinking (local model)…', pending: true }];
        setHist(next); setBusy(true);
        try {
            const d = await postJSON('/api/ask', { question, history: prior });
            const ans = d.ok ? d.answer : (d.configured === false ? 'No local LLM configured. Set OPENAI_BASE_URL in .env and restart.' : (d.error || 'Could not answer.'));
            setHist([...prior, { role: 'user', content: question }, { role: 'assistant', content: ans }]);
        } catch (e) {
            setHist([...prior, { role: 'user', content: question }, { role: 'assistant', content: 'Could not reach the server.' }]);
        }
        setBusy(false);
    };
    const presets = ['What did I focus on most this period?', 'Which projects stalled or went quiet?', 'Summarize my code reviews.', 'How does this period compare to before?'];
    return html`
        <div class="card" style=${{ marginBottom: '1rem' }}>
            <h3 style=${{ fontSize: '0.95rem', margin: '0 0 0.2rem' }}>Ask your data</h3>
            <p style=${{ fontSize: '0.82rem', color: 'var(--text-muted)', margin: '0 0 0.6rem' }}>Answered locally from your own data — nothing leaves your machine.</p>
            ${hist.length > 0 && html`<div ref=${threadRef} style=${{ marginBottom: '0.6rem', maxHeight: '340px', overflowY: 'auto' }}>
                ${hist.map((m, i) => html`<div key=${i} style=${{ marginBottom: '0.5rem' }}>
                    <div style=${{ fontSize: '0.7rem', color: 'var(--text-faint)', marginBottom: '0.15rem' }}>${m.role === 'user' ? 'You' : 'AI'}</div>
                    <div style=${{ fontSize: '0.9rem', lineHeight: 1.5, whiteSpace: 'pre-wrap', background: m.role === 'user' ? 'var(--accent-soft)' : 'var(--bg-elevated)', border: '1px solid var(--line)', borderRadius: 'var(--radius-sm)', padding: '0.5rem 0.7rem' }}>${m.content}</div>
                </div>`)}
            </div>`}
            <div style=${{ display: 'flex', gap: '0.5rem', flexWrap: 'wrap', alignItems: 'center' }}>
                <input type="text" value=${q} placeholder="e.g. What did I focus on most this period?" style=${{ flex: 1, minWidth: '220px' }}
                    onInput=${e => setQ(e.target.value)} onKeyDown=${e => { if (e.key === 'Enter') ask(); }} />
                <button class="btn btn-primary btn-sm" disabled=${busy} onClick=${() => ask()}>Ask</button>
            </div>
            <div style=${{ marginTop: '0.5rem', display: 'flex', gap: '0.4rem', flexWrap: 'wrap' }}>
                ${presets.map(p => html`<button key=${p} class="btn btn-ghost btn-sm" onClick=${() => ask(p)}>${p}</button>`)}
            </div>
        </div>`;
}
function Trends({ data }) {
    const blocks = [];
    const pc = data.period_comparison;
    if (pc) { const c = pc.current_6m, p = pc.previous_6m; blocks.push(['Last 6 months vs previous 6',
        `Tickets: ${c.jira} vs ${p.jira} (${trendPct(c.jira, p.jira)}%). Changes: ${c.gerrit} vs ${p.gerrit} (${trendPct(c.gerrit, p.gerrit)}%). Messages: ${c.slack} vs ${p.slack} (${trendPct(c.slack, p.slack)}%).`]); }
    const mom = data.month_over_month;
    if (mom) { const l = mom.last, p = mom.previous; blocks.push(['Vs last month',
        `${mom.last_month}: Tickets ${l.jira} (${trendPct(l.jira, p.jira)}%), Changes ${l.gerrit} (${trendPct(l.gerrit, p.gerrit)}%), Messages ${l.slack} (${trendPct(l.slack, p.slack)}%) vs ${mom.previous_month}.`]); }
    const sm = data.same_month_last_year;
    if (sm) { const c = sm.current, p = sm.previous; blocks.push(['Same month last year',
        `${sm.current_label} vs ${sm.previous_label} — Tickets ${c.jira} (${trendPct(c.jira, p.jira)}%), Changes ${c.gerrit} (${trendPct(c.gerrit, p.gerrit)}%), Pages ${c.confluence} (${trendPct(c.confluence, p.confluence)}%), Messages ${c.slack} (${trendPct(c.slack, p.slack)}%).`]); }
    return html`${blocks.map(([title, text]) => html`
        <h3 key=${title} class="chart-section-title">${title}</h3>
        <div class="card" style=${{ marginBottom: '1rem' }}><p style=${{ fontSize: '0.9rem', margin: 0 }}>${text}</p></div>`)}`;
}
function Insights() {
    const { data, months, load } = usePersonal();
    return html`
        <div style=${{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-end', gap: '1rem', flexWrap: 'wrap', marginBottom: '1.25rem' }}>
            <div><h2 class="page-title" style=${{ margin: '0 0 0.2rem' }}>Insights</h2>
                <p class="page-subtitle" style=${{ margin: 0 }}>AI summaries, ask your data, and how this period compares.</p></div>
            ${data && html`<${RangeSelect} value=${months || 12} options=${data.time_range_options} onChange=${m => load(m)} />`}
        </div>
        <${AiSummary} months=${months} />
        <${AskData} />
        ${data ? html`
            ${(data.highlights || []).length > 0 && html`
                <h3 class="chart-section-title">Talking points</h3>
                <div class="card" style=${{ marginBottom: '1rem' }}>
                    <ul style=${{ margin: 0, paddingLeft: '1.25rem', fontSize: '0.9rem' }}>${data.highlights.map((h, i) => html`<li key=${i}>${h}</li>`)}</ul>
                </div>`}
            <${Trends} data=${data} />
            <h3 class="chart-section-title">Export & share</h3>
            <div class="card"><p style=${{ fontSize: '0.9rem', margin: 0 }}>
                <span style=${{ color: 'var(--text-muted)' }}>Download:</span> ${' '}
                <a href=${'/export/pdf?months=' + (months || 12)} style=${{ color: 'var(--accent)' }}>PDF</a> · ${' '}
                <a href=${'/export/onepager?months=' + (months || 12)} style=${{ color: 'var(--accent)' }}>One-pager</a> · ${' '}
                <a href=${'/api/export/json?months=' + (months || 12)} style=${{ color: 'var(--accent)' }}>JSON</a> · ${' '}
                <a href=${'/api/export/csv?months=' + (months || 12)} style=${{ color: 'var(--accent)' }}>CSV</a>
            </p></div>` : html`<${Spinner} />`}`;
}

/* ----------------------------- Goals ----------------------------------- */
const CAT = { delivery: 'Delivery', learning: 'Learning', collaboration: 'Collaboration', other: 'Other' };
const STAT = { not_started: 'Not started', in_progress: 'In progress', done: 'Done' };
const METRIC = { tickets_done: 'Tickets done', reviews: 'Reviews (changes)', messages: 'Messages' };

function ObjectiveForm({ initial, totals, themes, onSaved, onCancel }) {
    const [f, setF] = useState(initial || { title: '', description: '', category: 'delivery', status: 'not_started', target_date: '', metric: '', target: '', progress: 0, evidence: [] });
    const [err, setErr] = useState('');
    const up = (k, v) => setF(s => ({ ...s, [k]: v }));
    const addEv = (label, value, source) => setF(s => ({ ...s, evidence: [...(s.evidence || []), { label: label || '', value: value ?? '', source: source || 'manual' }] }));
    const chips = [['Jira tickets', totals.jira, 'jira'], ['Gerrit changes', totals.gerrit, 'gerrit'], ['Confluence pages', totals.confluence, 'confluence'], ['Slack messages', totals.slack, 'slack']]
        .filter(c => c[1]).concat((themes || []).slice(0, 6).map(t => [t.name, t.count, 'theme']));
    const save = async () => {
        if (!f.title.trim()) { setErr('Title is required.'); return; }
        const payload = { ...f, target: f.metric && f.target ? parseInt(f.target, 10) : null, progress: f.metric ? 0 : parseInt(f.progress || 0, 10),
            evidence: (f.evidence || []).filter(e => (e.label || '').trim()).map(e => ({ label: e.label, value: e.value === '' ? null : parseInt(e.value, 10), source: e.source || 'manual' })) };
        const url = initial && initial.id ? '/api/objectives/' + initial.id : '/api/objectives';
        const d = await postJSON(url, payload);
        if (d && d.ok) onSaved(); else setErr((d && d.error) || 'Could not save objective.');
    };
    return html`
        <div class="objective-form">
            <div class="objective-form-head">${initial && initial.id ? 'Edit objective' : 'New objective'}</div>
            <div class="obj-field"><label>Title</label><input type="text" maxLength=${140} value=${f.title} onInput=${e => up('title', e.target.value)} placeholder="e.g. Improve review turnaround" /></div>
            <div class="obj-field"><label>Description <span class="obj-opt">(optional)</span></label><textarea rows=${2} maxLength=${600} value=${f.description} onInput=${e => up('description', e.target.value)}></textarea></div>
            <div class="obj-row">
                <div class="obj-field"><label>Category</label><select value=${f.category} onChange=${e => up('category', e.target.value)}>${Object.entries(CAT).map(([k, v]) => html`<option key=${k} value=${k}>${v}</option>`)}</select></div>
                <div class="obj-field"><label>Status</label><select value=${f.status} onChange=${e => up('status', e.target.value)}>${Object.entries(STAT).map(([k, v]) => html`<option key=${k} value=${k}>${v}</option>`)}</select></div>
                <div class="obj-field"><label>Target date</label><input type="date" value=${f.target_date} onInput=${e => up('target_date', e.target.value)} /></div>
            </div>
            <div class="obj-row">
                <div class="obj-field"><label>Track by</label><select value=${f.metric} onChange=${e => up('metric', e.target.value)}><option value="">Manual</option>${Object.entries(METRIC).map(([k, v]) => html`<option key=${k} value=${k}>${v}</option>`)}</select></div>
                ${f.metric ? html`<div class="obj-field"><label>Target</label><input type="number" min=${0} value=${f.target} onInput=${e => up('target', e.target.value)} /></div>`
                    : html`<div class="obj-field"><label>Progress %</label><input type="number" min=${0} max=${100} value=${f.progress} onInput=${e => up('progress', e.target.value)} /></div>`}
            </div>
            <div class="obj-field">
                <label>Evidence <span class="obj-opt">(attach real numbers / themes)</span></label>
                <div style=${{ display: 'flex', gap: '0.3rem', flexWrap: 'wrap', margin: '0.1rem 0 0.4rem' }}>
                    ${chips.map((c, i) => html`<button key=${i} type="button" class="btn btn-ghost btn-sm" style=${{ fontSize: '0.75rem', padding: '0.2rem 0.5rem' }} onClick=${() => addEv(c[0], c[1], c[2])}>+ ${c[0]} (${c[1]})</button>`)}
                </div>
                <div style=${{ display: 'flex', flexDirection: 'column', gap: '0.35rem' }}>
                    ${(f.evidence || []).map((e, i) => html`<div key=${i} style=${{ display: 'flex', gap: '0.35rem', alignItems: 'center' }}>
                        <input type="text" style=${{ flex: 1, minWidth: '120px' }} value=${e.label} onInput=${ev => setF(s => { const cp = [...s.evidence]; cp[i] = { ...cp[i], label: ev.target.value }; return { ...s, evidence: cp }; })} />
                        <input type="number" style=${{ width: '5rem' }} value=${e.value} onInput=${ev => setF(s => { const cp = [...s.evidence]; cp[i] = { ...cp[i], value: ev.target.value }; return { ...s, evidence: cp }; })} />
                        <button type="button" class="btn btn-ghost btn-sm" onClick=${() => setF(s => ({ ...s, evidence: s.evidence.filter((_, j) => j !== i) }))}>×</button>
                    </div>`)}
                </div>
                <button type="button" class="btn btn-ghost btn-sm" style=${{ marginTop: '0.35rem' }} onClick=${() => addEv('', '', 'manual')}>+ Add evidence</button>
            </div>
            ${err && html`<div class="objective-form-error">${err}</div>`}
            <div class="objective-form-actions"><button class="btn btn-primary btn-sm" onClick=${save}>Save objective</button><button class="btn btn-ghost btn-sm" onClick=${onCancel}>Cancel</button></div>
        </div>`;
}

function Goals() {
    const { data, months, load } = usePersonal();
    const [editing, setEditing] = useState(null); // null | {} | objective
    const [goalForm, setGoalForm] = useState(null);
    const [snapLabel, setSnapLabel] = useState('');
    if (!data) return html`<${Spinner} />`;
    const objectives = data.objectives || [], goals = data.goals || {}, gp = data.goals_progress || {}, snapshots = data.snapshots || [];
    const g = goalForm || { tickets_done: goals.tickets_done ?? '', reviews: goals.reviews ?? '', messages: goals.messages ?? '' };
    const saveGoals = async () => {
        await postJSON('/api/goals', { tickets_done: g.tickets_done === '' ? null : parseInt(g.tickets_done, 10), reviews: g.reviews === '' ? null : parseInt(g.reviews, 10), messages: g.messages === '' ? null : parseInt(g.messages, 10) });
        setGoalForm(null); load(months);
    };
    const del = async (id) => { if (confirm('Delete this objective?')) { await delJSON('/api/objectives/' + id); load(months); } };
    const saveSnap = async () => { await postJSON('/api/snapshots', { label: snapLabel.trim() || 'Snapshot' }); setSnapLabel(''); load(months); };
    const optin = async (v) => { await postJSON('/api/team-comparison', { include: v }); load(months); };
    const tc = data.team_comparison;
    return html`
        <div style=${{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-end', gap: '1rem', flexWrap: 'wrap', marginBottom: '1.25rem' }}>
            <div><h2 class="page-title" style=${{ margin: '0 0 0.2rem' }}>Goals</h2>
                <p class="page-subtitle" style=${{ margin: 0 }}>Objectives, quick targets, snapshots, and team comparison.</p></div>
            <${RangeSelect} value=${months || 12} options=${data.time_range_options} onChange=${m => load(m)} />
        </div>

        <h3 class="chart-section-title">Objectives</h3>
        <div class="card" style=${{ marginBottom: '1rem' }}>
            <div style=${{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', gap: '0.75rem', flexWrap: 'wrap', marginBottom: '0.75rem' }}>
                <p style=${{ fontSize: '0.85rem', color: 'var(--text-muted)', margin: 0 }}>Set objectives with a status, target date and progress.</p>
                <button class="btn btn-primary btn-sm" onClick=${() => setEditing({})}>+ Add objective</button>
            </div>
            ${editing && html`<${ObjectiveForm} initial=${editing.id ? editing : null} totals=${data.totals || {}} themes=${data.themes || []}
                onSaved=${() => { setEditing(null); load(months); }} onCancel=${() => setEditing(null)} />`}
            ${objectives.length ? html`<div class="objective-list">
                ${objectives.map(o => {
                    const pct = o.computed_progress != null ? o.computed_progress : (o.progress || 0);
                    const note = o.metric ? (METRIC[o.metric] || o.metric) + (o.target != null ? ' · target ' + o.target : '') : '';
                    return html`<div key=${o.id} class="objective-item">
                        <div class="objective-item-head"><div class="objective-item-title">${o.title}</div>
                            <div class="objective-item-actions"><button class="btn btn-ghost btn-sm" onClick=${() => setEditing(o)}>Edit</button><button class="btn btn-ghost btn-sm" onClick=${() => del(o.id)}>Delete</button></div></div>
                        ${o.description && html`<p class="objective-item-desc">${o.description}</p>`}
                        <div class="objective-meta"><span class="obj-badge obj-cat">${CAT[o.category] || 'Other'}</span><span class=${'obj-badge status-' + (o.status || 'not_started')}>${STAT[o.status] || 'Not started'}</span>
                            ${o.target_date && html`<span class="obj-meta-text">Due ${o.target_date}</span>`}${note && html`<span class="obj-meta-text">${note}</span>`}</div>
                        <div class="objective-progress"><div class="objective-progress-track"><div class="objective-progress-fill" style=${{ width: pct + '%' }}></div></div><span class="objective-progress-pct">${pct}%</span></div>
                        ${(o.evidence || []).length > 0 && html`<div style=${{ display: 'flex', gap: '0.3rem', flexWrap: 'wrap', marginTop: '0.5rem' }}>
                            ${o.evidence.map((e, i) => html`<span key=${i} class="obj-badge" style=${{ background: 'var(--accent-soft)', color: 'var(--accent)' }}>${e.label}${e.value != null ? ': ' + e.value : ''}</span>`)}</div>`}
                    </div>`;
                })}
            </div>` : html`<p style=${{ fontSize: '0.85rem', color: 'var(--text-faint)', margin: 0 }}>No objectives yet.</p>`}
        </div>

        <h3 class="chart-section-title">Quick targets</h3>
        <div class="card" style=${{ marginBottom: '1rem' }}>
            <div style=${{ display: 'flex', flexWrap: 'wrap', gap: '0.75rem', alignItems: 'center', marginBottom: '0.75rem' }}>
                ${[['tickets_done', 'Tickets done'], ['reviews', 'Reviews'], ['messages', 'Messages']].map(([k, lbl]) => html`
                    <label key=${k}>${lbl} <input type="number" min=${0} style=${{ width: '4.5rem', marginLeft: '0.25rem' }} value=${g[k]}
                        onInput=${e => setGoalForm({ ...g, [k]: e.target.value })} /></label>`)}
                <button class="btn btn-primary btn-sm" onClick=${saveGoals}>Save targets</button>
            </div>
            ${Object.keys(gp).map(k => { const x = gp[k]; if (x.goal == null) return null; const pct = Math.min(100, Math.round((x.current / x.goal) * 100));
                return html`<div key=${k} style=${{ marginBottom: '0.5rem' }}><span style=${{ fontSize: '0.9rem' }}>${x.label}: ${x.current} / ${x.goal}</span>
                    <div style=${{ background: 'rgba(148,163,184,0.18)', borderRadius: '6px', height: '8px', overflow: 'hidden' }}><div style=${{ background: 'var(--accent)', height: '100%', width: pct + '%' }}></div></div></div>`; })}
        </div>

        <h3 class="chart-section-title">Snapshots</h3>
        <div class="card" style=${{ marginBottom: '1rem' }}>
            <div style=${{ display: 'flex', flexWrap: 'wrap', gap: '0.5rem', alignItems: 'center', marginBottom: '0.6rem' }}>
                <input type="text" placeholder="e.g. Q1 check-in" style=${{ width: '12rem' }} value=${snapLabel} onInput=${e => setSnapLabel(e.target.value)} />
                <button class="btn btn-primary btn-sm" onClick=${saveSnap}>Save snapshot</button>
            </div>
            ${snapshots.length ? html`<ul style=${{ margin: 0, paddingLeft: '1.25rem', fontSize: '0.9rem' }}>
                ${snapshots.map((s, i) => { const t = s.totals || {}; return html`<li key=${i}><strong>${s.label}</strong> <span style=${{ color: 'var(--text-faint)' }}>${s.date || ''}</span> — Jira ${t.jira || 0}, Gerrit ${t.gerrit || 0}, Confluence ${t.confluence || 0}, Slack ${t.slack || 0}</li>`; })}
            </ul>` : html`<p style=${{ fontSize: '0.85rem', color: 'var(--text-faint)', margin: 0 }}>No snapshots yet.</p>`}
        </div>

        <h3 class="chart-section-title">Team comparison</h3>
        <div class="card">
            <label style=${{ display: 'flex', gap: '0.6rem', alignItems: 'flex-start', cursor: 'pointer' }}>
                <input type="checkbox" checked=${!!data.team_optin} onChange=${e => optin(e.target.checked)} style=${{ marginTop: '0.2rem', accentColor: 'var(--accent)' }} />
                <span><strong>Include me in the team average</strong><span style=${{ display: 'block', fontSize: '0.82rem', color: 'var(--text-faint)' }}>Adds only your totals (no name) to an aggregate.</span></span>
            </label>
            ${tc && html`<p style=${{ fontSize: '0.9rem', margin: '0.75rem 0 0' }}>You vs team average (${tc.participant_count}): Jira <strong>${(tc.your_totals || {}).jira || 0}</strong> vs ${(tc.team_average || {}).jira}, Gerrit <strong>${(tc.your_totals || {}).gerrit || 0}</strong> vs ${(tc.team_average || {}).gerrit}, Slack <strong>${(tc.your_totals || {}).slack || 0}</strong> vs ${(tc.team_average || {}).slack}.</p>`}
        </div>`;
}

/* ----------------------------- Meetings -------------------------------- */
function Meetings() {
    const [list, setList] = useState(null);
    const [sel, setSel] = useState(null);
    const [creating, setCreating] = useState(false);
    const load = useCallback(async (selectId) => {
        const d = await getJSON('/api/meetings');
        const meetings = (d && d.meetings) || [];
        setList(meetings);
        setSel(prev => { const id = selectId || (prev && prev.id) || (meetings[0] && meetings[0].id); return meetings.find(m => m.id === id) || meetings[0] || null; });
    }, []);
    useEffect(() => { load(); }, [load]);
    if (list == null) return html`<${Spinner} />`;
    const create = async (date, title, seed) => { const d = await postJSON('/api/meetings', { date, title, seed }); setCreating(false); if (d && d.meeting) load(d.meeting.id); };
    return html`
        <div style=${{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-end', gap: '1rem', flexWrap: 'wrap', marginBottom: '1.25rem' }}>
            <div><h2 class="page-title" style=${{ margin: '0 0 0.2rem' }}>1:1 meetings</h2>
                <p class="page-subtitle" style=${{ margin: 0 }}>Agenda, notes & action items that carry forward.</p></div>
            <button class="btn btn-primary" onClick=${() => setCreating(true)}>+ New 1:1</button>
        </div>
        ${creating && html`<${NewMeeting} onCreate=${create} onCancel=${() => setCreating(false)} />`}
        <div style=${{ display: 'grid', gridTemplateColumns: '280px 1fr', gap: '1.2rem', alignItems: 'start' }} class="mtg-grid-react">
            <aside style=${{ display: 'flex', flexDirection: 'column', gap: '0.5rem' }}>
                ${list.length === 0 ? html`<p class="field-hint">No 1:1s yet.</p>` : list.map(m => html`
                    <button key=${m.id} class=${'card'} style=${{ textAlign: 'left', cursor: 'pointer', borderColor: sel && sel.id === m.id ? 'var(--accent)' : 'var(--line)', background: sel && sel.id === m.id ? 'var(--accent-soft)' : 'var(--card)' }} onClick=${() => setSel(m)}>
                        <div style=${{ fontSize: '0.78rem', color: 'var(--text-faint)' }}>${m.date}</div>
                        <div style=${{ fontWeight: 600 }}>${m.title}</div>
                        <div style=${{ fontSize: '0.72rem', color: m.status === 'completed' ? 'var(--success)' : 'var(--accent)' }}>${m.status === 'completed' ? 'Completed' : 'Scheduled'}</div>
                    </button>`)}
            </aside>
            <div>${sel ? html`<${MeetingDetail} meeting=${sel} onChange=${(id) => load(id)} />` : html`<div class="card"><p class="field-hint">Select or create a 1:1.</p></div>`}</div>
        </div>`;
}
function NewMeeting({ onCreate, onCancel }) {
    const today = new Date().toISOString().slice(0, 10);
    const [date, setDate] = useState(today); const [title, setTitle] = useState(''); const [seed, setSeed] = useState(true); const [busy, setBusy] = useState(false);
    return html`<div class="card" style=${{ marginBottom: '1.2rem', display: 'flex', flexDirection: 'column', gap: '0.8rem', maxWidth: '760px' }}>
        <div class="section-label">New 1:1</div>
        <div style=${{ display: 'flex', gap: '0.8rem', flexWrap: 'wrap', alignItems: 'flex-end' }}>
            <div><label style=${{ display: 'block', fontSize: '0.82rem', color: 'var(--text-muted)', marginBottom: '0.35rem' }}>Date</label><input type="date" value=${date} onInput=${e => setDate(e.target.value)} /></div>
            <div style=${{ flex: 1, minWidth: '200px' }}><label style=${{ display: 'block', fontSize: '0.82rem', color: 'var(--text-muted)', marginBottom: '0.35rem' }}>Title (optional)</label><input type="text" value=${title} placeholder="e.g. 1:1 with Alex" style=${{ width: '100%' }} onInput=${e => setTitle(e.target.value)} /></div>
        </div>
        <label style=${{ display: 'flex', gap: '0.6rem', alignItems: 'flex-start', fontSize: '0.86rem', color: 'var(--text-muted)' }}><input type="checkbox" checked=${seed} onChange=${e => setSeed(e.target.checked)} /> Seed agenda from my latest activity & nudges</label>
        <div style=${{ display: 'flex', gap: '0.6rem' }}>
            <button class="btn btn-primary" disabled=${busy} onClick=${async () => { setBusy(true); await onCreate(date, title, seed); }}>Create 1:1</button>
            <button class="btn btn-ghost" onClick=${onCancel}>Cancel</button>
        </div>
    </div>`;
}
function MeetingDetail({ meeting, onChange }) {
    const [m, setM] = useState(meeting);
    useEffect(() => { setM(meeting); }, [meeting]);
    const save = async (extra) => {
        const payload = { title: m.title, date: m.date, notes: m.notes || '', agenda: m.agenda || [], action_items: m.action_items || [], ...(extra || {}) };
        const d = await postJSON('/api/meetings/' + m.id, payload);
        if (d && d.meeting) onChange(d.meeting.id);
    };
    const del = async () => { if (confirm('Delete this 1:1 and its notes?')) { await delJSON('/api/meetings/' + m.id); onChange(); } };
    const setAgenda = (i, patch) => setM(s => { const a = [...(s.agenda || [])]; a[i] = { ...a[i], ...patch }; return { ...s, agenda: a }; });
    const setAction = (i, patch) => setM(s => { const a = [...(s.action_items || [])]; a[i] = { ...a[i], ...patch }; return { ...s, action_items: a }; });
    return html`<div class="card">
        <div style=${{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', gap: '1rem', marginBottom: '1rem' }}>
            <div style=${{ flex: 1 }}>
                <input value=${m.title} onInput=${e => setM({ ...m, title: e.target.value })} style=${{ fontSize: '1.1rem', fontWeight: 700, width: '100%', background: 'transparent', border: '1px solid transparent' }} />
                <div style=${{ display: 'flex', gap: '0.7rem', alignItems: 'center' }}><input type="date" value=${m.date} onInput=${e => setM({ ...m, date: e.target.value })} />${m.manager_name && html`<span class="field-hint">with ${m.manager_name}</span>`}</div>
            </div>
            <span class="obj-badge" style=${{ color: m.status === 'completed' ? 'var(--success)' : 'var(--accent)' }}>${m.status === 'completed' ? 'Completed' : 'Scheduled'}</span>
        </div>

        <div class="section-label">Agenda</div>
        ${(m.agenda || []).map((it, i) => html`<div key=${i} style=${{ display: 'flex', gap: '0.5rem', alignItems: 'center', marginBottom: '0.5rem' }}>
            <input type="checkbox" checked=${!!it.done} onChange=${e => setAgenda(i, { done: e.target.checked })} />
            <input type="text" style=${{ flex: 1 }} value=${it.text} onInput=${e => setAgenda(i, { text: e.target.value })} />
            ${it.source === 'seed' && html`<span class="obj-badge" style=${{ color: 'var(--accent)', background: 'var(--accent-soft)' }}>seeded</span>`}
            <button class="btn btn-ghost btn-sm" onClick=${() => setM(s => ({ ...s, agenda: s.agenda.filter((_, j) => j !== i) }))}>×</button>
        </div>`)}
        <button class="btn btn-ghost btn-sm" onClick=${() => setM(s => ({ ...s, agenda: [...(s.agenda || []), { text: '', source: 'manual', done: false }] }))}>+ Add item</button>

        <div class="section-label" style=${{ marginTop: '1.4rem' }}>Notes</div>
        <textarea rows=${5} style=${{ width: '100%' }} value=${m.notes || ''} onInput=${e => setM({ ...m, notes: e.target.value })}></textarea>

        <div class="section-label" style=${{ marginTop: '1.4rem' }}>Action items</div>
        ${(m.action_items || []).map((it, i) => html`<div key=${i} style=${{ display: 'flex', gap: '0.5rem', alignItems: 'center', marginBottom: '0.5rem', flexWrap: 'wrap' }}>
            <input type="checkbox" checked=${it.status === 'done'} onChange=${e => setAction(i, { status: e.target.checked ? 'done' : 'open' })} />
            <input type="text" style=${{ flex: 1, minWidth: '120px' }} value=${it.text} onInput=${e => setAction(i, { text: e.target.value })} />
            <select value=${it.owner || 'me'} onChange=${e => setAction(i, { owner: e.target.value })}><option value="me">Me</option><option value="manager">Manager</option></select>
            <input type="date" value=${it.due_date || ''} onInput=${e => setAction(i, { due_date: e.target.value })} />
            ${it.carried_over && html`<span class="obj-badge" style=${{ color: 'var(--warning)', background: 'rgba(227,160,8,0.12)' }}>carried</span>`}
            <button class="btn btn-ghost btn-sm" onClick=${() => setM(s => ({ ...s, action_items: s.action_items.filter((_, j) => j !== i) }))}>×</button>
        </div>`)}
        <button class="btn btn-ghost btn-sm" onClick=${() => setM(s => ({ ...s, action_items: [...(s.action_items || []), { text: '', owner: 'me', status: 'open', due_date: '' }] }))}>+ Add action</button>

        <div style=${{ display: 'flex', gap: '0.6rem', alignItems: 'center', marginTop: '1.5rem', paddingTop: '1.1rem', borderTop: '1px solid var(--line)' }}>
            <button class="btn btn-primary" onClick=${() => save()}>Save</button>
            <button class="btn btn-ghost" onClick=${() => save({ status: m.status === 'completed' ? 'scheduled' : 'completed' })}>${m.status === 'completed' ? 'Reopen' : 'Mark completed'}</button>
            <button class="btn btn-ghost" style=${{ marginLeft: 'auto', color: 'var(--error)' }} onClick=${del}>Delete</button>
        </div>
    </div>`;
}

/* ----------------------------- Team ------------------------------------ */
function Team() {
    const [t, setT] = useState(null);
    useEffect(() => { getJSON('/api/team').then(setT); }, []);
    if (!t) return html`<${Spinner} />`;
    const totals = t.totals || {}, avg = t.average || {};
    return html`
        <div style=${{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-end', gap: '1rem', flexWrap: 'wrap', marginBottom: '1.25rem' }}>
            <div><h2 class="page-title" style=${{ margin: '0 0 0.2rem' }}>Team view</h2>
                <p class="page-subtitle" style=${{ margin: 0 }}>Aggregated across opted-in users — totals & themes, no names.</p></div>
            <div style=${{ display: 'flex', gap: '0.5rem' }}>
                <a class="btn btn-secondary btn-sm" href="/api/team/export/csv">Export CSV</a>
                <a class="btn btn-secondary btn-sm" href="/team/export/pdf">Export PDF</a>
            </div>
        </div>
        <div class="card" style=${{ marginBottom: '1rem' }}><div class="section-label">Participants</div><p style=${{ fontSize: '1.4rem', fontWeight: 700, margin: 0 }}>${t.participant_count}</p></div>
        <div class="stat-grid" style=${{ marginBottom: '1rem' }}>
            ${[['Jira', 'jira', 'tickets'], ['Gerrit', 'gerrit', 'changes'], ['Confluence', 'confluence', 'pages'], ['Slack', 'slack', 'messages']].map(([name, k, unit]) => html`
                <div key=${k} class="card stat-card"><div class="stat-num">${totals[k] || 0}</div><div class="stat-label"><span class=${'badge badge-' + k}>${name}</span> ${unit} <span class="field-hint">(avg ${avg[k]})</span></div></div>`)}
        </div>
        ${(t.themes || []).length > 0 && html`<h3 class="chart-section-title">Top team areas</h3>
            <div class="card"><ul style=${{ margin: 0, paddingLeft: '1.25rem', fontSize: '0.9rem', columns: 2 }}>${t.themes.map((th, i) => html`<li key=${i}>${th.name} <span class="field-hint">(${th.count})</span></li>`)}</ul></div>`}`;
}

/* ----------------------------- Source pages ---------------------------- */
function StatTiles({ items }) {
    const shown = items.filter(([, v]) => v != null && v !== '');
    if (!shown.length) return null;
    return html`<div class="stat-grid" style=${{ marginBottom: '1rem' }}>
        ${shown.map(([label, val], i) => html`<div key=${i} class="card stat-card"><div class="stat-num">${val}</div><div class="stat-label">${label}</div></div>`)}
    </div>`;
}
function TopList({ title, rows }) {
    if (!rows || !rows.length) return null;
    return html`<h3 class="chart-section-title">${title}</h3>
        <div class="card" style=${{ marginBottom: '1rem' }}>
            <ul style=${{ margin: 0, paddingLeft: '1.25rem', fontSize: '0.9rem', columns: 2 }}>
                ${rows.map((r, i) => html`<li key=${i}>${r[0]} <span class="field-hint">(${r[1]})</span></li>`)}
            </ul></div>`;
}
function SourcePage({ kind }) {
    const { data, months, load } = usePersonal();
    const [q, setQ] = useState('');
    if (!data) return html`<${Spinner} />`;
    const badge = { gerrit: 'Gerrit', jira: 'Jira', confluence: 'Confluence', slack: 'Slack' }[kind];
    const gm = data.gerrit_metrics || {}, jm = data.jira_metrics || {}, cm = data.confluence_metrics || {}, sm = data.slack_metrics || {}, tot = data.totals || {};
    const items = data[kind] || [];
    let tiles = [], tops = [], cols = () => [];
    if (kind === 'gerrit') {
        tiles = [['Changes', gm.total_changes], ['Merged', gm.merged_count], ['Open', gm.open_count], ['Abandoned', gm.abandoned_count], ['Merge rate', gm.merge_rate_pct != null ? gm.merge_rate_pct + '%' : null], ['Avg days to merge', gm.avg_merge_days], ['Lines +/−', (gm.lines_added || 0) + ' / ' + (gm.lines_removed || 0)], ['Rework (>1 PS)', gm.changes_with_rework]];
        tops = [['By topic', gm.top_topics], ['Top branches', gm.top_branches], ['Top reviewers', gm.top_reviewers]];
        cols = it => [it.message, it.project, it.status, it.month];
    } else if (kind === 'jira') {
        tiles = [['Tickets', jm.total_tickets], ['Done', jm.done_count], ['Open', jm.open_count], ['In review', jm.in_review_count], ['Blocked', jm.blocked_count], ['Reopened', jm.reopened_count], ['Comments/ticket', jm.comments_per_ticket_avg], ['Story points', jm.story_points_done]];
        tops = [['Top status', jm.top_statuses], ['Top projects', jm.top_projects], ['Top epics', jm.top_epics]];
        cols = it => [(it.key ? it.key + ' ' : '') + (it.title || ''), it.project, it.status, it.month];
    } else if (kind === 'confluence') {
        tiles = [['Pages', tot.confluence], ['Created', cm.created_count], ['Updated', cm.updated_count]];
        tops = [['Top spaces', cm.top_spaces]];
        cols = it => [it.title, it.space, '', it.updated];
    } else {
        tiles = [['Messages', tot.slack], ['Peak hour', sm.peak_hour != null ? sm.peak_hour + ':00' : null], ['Reactions', sm.total_reactions], ['Thread replies', sm.thread_reply_count]];
        if (sm.peak_weekday_hour_one_liner) tiles.push(['Most active', sm.peak_weekday_hour_one_liner]);
        tops = [['Top channels', sm.top_channels]];
        cols = it => [it.text || it.message || '', it.channel_name || it.channel_id || '', '', it.month];
    }
    const ql = q.toLowerCase();
    const filtered = items.filter(it => cols(it).join(' ').toLowerCase().includes(ql));
    return html`
        <div style=${{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-end', gap: '1rem', flexWrap: 'wrap', marginBottom: '1.25rem' }}>
            <div><h2 class="page-title" style=${{ margin: '0 0 0.3rem' }}><span class=${'badge badge-' + kind}>${badge}</span></h2>
                <p class="page-subtitle" style=${{ margin: 0 }}>Your ${badge} activity and metrics.</p></div>
            <${RangeSelect} value=${months || 12} options=${data.time_range_options} onChange=${m => load(m)} />
        </div>
        ${data[kind + '_error'] && html`<div class="card" style=${{ marginBottom: '1rem', color: 'var(--error)' }}>${data[kind + '_error']}</div>`}
        <${StatTiles} items=${tiles} />
        ${tops.map(([t, rows]) => html`<${TopList} key=${t} title=${t} rows=${rows} />`)}
        <h3 class="chart-section-title">Items (${filtered.length})</h3>
        <div class="card">
            <input type="text" placeholder="Search…" value=${q} onInput=${e => setQ(e.target.value)} style=${{ width: '100%', marginBottom: '0.6rem' }} />
            <div style=${{ maxHeight: '520px', overflowY: 'auto' }}>
                ${filtered.length === 0 ? html`<p class="field-hint">No items${items.length ? ' match your search' : ' yet — connect ' + badge + ' and refresh'}.</p>`
            : filtered.slice(0, 300).map((it, i) => { const c = cols(it); return html`
                    <div key=${i} style=${{ display: 'flex', gap: '0.6rem', padding: '0.45rem 0', borderBottom: '1px solid var(--line)', fontSize: '0.88rem' }}>
                        <span style=${{ flex: 1, minWidth: 0, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>${c[0]}</span>
                        ${c[1] && html`<span class="field-hint" style=${{ flexShrink: 0 }}>${c[1]}</span>`}
                        ${c[2] && html`<span class="field-hint" style=${{ flexShrink: 0 }}>${c[2]}</span>`}
                        ${c[3] && html`<span class="field-hint" style=${{ flexShrink: 0 }}>${c[3]}</span>`}
                    </div>`; })}
            </div>
        </div>`;
}

/* ----------------------------- Connections ----------------------------- */
const CONN_DEFS = {
    gerrit: { label: 'Gerrit', fields: [['username', 'Username'], ['password', 'HTTP password']], path: '/api/connect/gerrit' },
    jira: { label: 'Jira', fields: [['email', 'Email'], ['api_token', 'API token']], path: '/api/connect/jira' },
    confluence: { label: 'Confluence', fields: [['email', 'Email'], ['api_token', 'API token']], path: '/api/connect/confluence' },
    slack: { label: 'Slack', fields: [['token', 'User OAuth token']], path: '/api/connect/slack' },
};
function Connections() {
    const [conn, setConn] = useState(null);
    const [forms, setForms] = useState({});
    const [msg, setMsg] = useState({});
    const load = useCallback(() => getJSON('/api/connections').then(setConn), []);
    useEffect(() => { load(); }, [load]);
    if (!conn) return html`<${Spinner} />`;
    const setF = (svc, k, v) => setForms(s => ({ ...s, [svc]: { ...(s[svc] || {}), [k]: v } }));
    const connect = async (svc) => {
        const d = await postJSON(CONN_DEFS[svc].path, forms[svc] || {});
        setMsg(m => ({ ...m, [svc]: d.ok ? 'Connected.' : (d.error || 'Failed.') }));
        if (d.ok) { setForms(s => ({ ...s, [svc]: {} })); load(); }
    };
    const disconnect = async (svc) => { await postJSON('/api/disconnect/' + svc, {}); load(); };
    return html`
        <h2 class="page-title" style=${{ margin: '0 0 0.2rem' }}>Connections</h2>
        <p class="page-subtitle" style=${{ marginBottom: '1.25rem' }}>Connect each service. Credentials are stored encrypted on the server.</p>
        ${Object.entries(CONN_DEFS).map(([svc, d]) => { const c = conn[svc] || {}; const unconfigured = !c.configured && svc !== 'slack'; return html`
            <div key=${svc} class="card" style=${{ marginBottom: '1rem', maxWidth: '660px' }}>
                <div style=${{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', gap: '0.75rem', flexWrap: 'wrap' }}>
                    <div><strong>${d.label}</strong> ${c.connected ? html`<span class="obj-badge" style=${{ color: 'var(--success)', background: 'rgba(63,178,127,0.12)' }}>Connected${c.identifier ? ' · ' + c.identifier : ''}</span>` : html`<span class="field-hint">Not connected</span>`}</div>
                    ${c.connected && html`<button class="btn btn-ghost btn-sm" onClick=${() => disconnect(svc)}>Disconnect</button>`}
                </div>
                ${unconfigured ? html`<p class="field-hint" style=${{ marginTop: '0.5rem' }}>${d.label} URL is not configured on the server.</p>` : html`
                    <div style=${{ display: 'flex', gap: '0.5rem', flexWrap: 'wrap', marginTop: '0.6rem' }}>
                        ${d.fields.map(([k, lbl]) => html`<input key=${k} type=${(k.includes('password') || k.includes('token')) ? 'password' : 'text'} placeholder=${lbl} value=${(forms[svc] || {})[k] || ''} onInput=${e => setF(svc, k, e.target.value)} style=${{ flex: 1, minWidth: '150px' }} />`)}
                        <button class="btn btn-primary btn-sm" onClick=${() => connect(svc)}>${c.connected ? 'Reconnect' : 'Connect'}</button>
                    </div>`}
                ${msg[svc] && html`<p class="field-hint" style=${{ marginTop: '0.5rem' }}>${msg[svc]}</p>`}
            </div>`; })}`;
}

/* ----------------------------- Settings -------------------------------- */
function Settings() {
    const [s, setS] = useState(null);
    const [optin, setOptin] = useState(false);
    const [toast, setToast] = useState('');
    const opts = [[3, 'Last 3 months'], [6, 'Last 6 months'], [12, 'Last 12 months'], [24, 'Last 2 years'], [36, 'Last 3 years']];
    useEffect(() => { getJSON('/api/settings').then(setS); getJSON('/api/team-comparison').then(d => setOptin(!!(d && d.include))); }, []);
    if (!s) return html`<${Spinner} />`;
    const up = (k, v) => setS(x => ({ ...x, [k]: v }));
    const flash = (m) => { setToast(m); setTimeout(() => setToast(''), 2400); };
    const save = async () => {
        await postJSON('/api/settings', { default_months: parseInt(s.default_months, 10), manager_name: s.manager_name, manager_email: s.manager_email, share_with_manager: !!s.share_with_manager, digest_frequency: s.digest_frequency });
        await postJSON('/api/team-comparison', { include: optin });
        flash('Settings saved');
    };
    const testDigest = async () => { const d = await postJSON('/api/digest/test', {}); flash(d.ok ? ('Test digest sent to ' + (d.sent_to || 'you')) : (d.error || 'Could not send digest')); };
    const field = (label, node) => html`<div style=${{ marginBottom: '1.1rem' }}><label style=${{ display: 'block', marginBottom: '0.4rem' }}>${label}</label>${node}</div>`;
    return html`
        <h2 class="page-title" style=${{ margin: '0 0 0.2rem' }}>Settings</h2>
        <p class="page-subtitle" style=${{ marginBottom: '1.25rem' }}>Your defaults, manager, sharing and email digest.</p>
        <div class="card" style=${{ maxWidth: '640px', marginBottom: '1rem' }}>
            <div class="section-label">Dashboard</div>
            ${field('Default time range', html`<select value=${s.default_months} onChange=${e => up('default_months', e.target.value)} style=${{ maxWidth: '360px' }}>${opts.map(([m, l]) => html`<option key=${m} value=${m}>${l}</option>`)}</select>`)}
        </div>
        <div class="card" style=${{ maxWidth: '640px', marginBottom: '1rem' }}>
            <div class="section-label">Your manager</div>
            ${field('Manager name', html`<input type="text" value=${s.manager_name || ''} placeholder="e.g. Alex Johnson" style=${{ maxWidth: '360px' }} onInput=${e => up('manager_name', e.target.value)} />`)}
            ${field('Manager email', html`<input type="email" value=${s.manager_email || ''} placeholder="e.g. alex@example.com" style=${{ maxWidth: '360px' }} onInput=${e => up('manager_email', e.target.value)} />`)}
            <label style=${{ display: 'flex', gap: '0.6rem', alignItems: 'flex-start', cursor: 'pointer' }}>
                <input type="checkbox" checked=${!!s.share_with_manager} onChange=${e => up('share_with_manager', e.target.checked)} style=${{ marginTop: '0.2rem', accentColor: 'var(--accent)' }} />
                <span><strong>Share my goals &amp; 1:1s with my manager</strong><span style=${{ display: 'block', fontSize: '0.82rem', color: 'var(--text-faint)' }}>Off by default.</span></span>
            </label>
        </div>
        <div class="card" style=${{ maxWidth: '640px', marginBottom: '1rem' }}>
            <div class="section-label">Privacy &amp; digest</div>
            <label style=${{ display: 'flex', gap: '0.6rem', alignItems: 'flex-start', cursor: 'pointer', marginBottom: '1rem' }}>
                <input type="checkbox" checked=${optin} onChange=${e => setOptin(e.target.checked)} style=${{ marginTop: '0.2rem', accentColor: 'var(--accent)' }} />
                <span><strong>Include me in the team average</strong><span style=${{ display: 'block', fontSize: '0.82rem', color: 'var(--text-faint)' }}>Adds only your totals (no name).</span></span>
            </label>
            ${field('Email digest', html`<select value=${s.digest_frequency || 'off'} onChange=${e => up('digest_frequency', e.target.value)} style=${{ maxWidth: '360px' }}><option value="off">Off</option><option value="weekly">Weekly (Mondays)</option><option value="monthly">Monthly (1st)</option></select>`)}
            <button class="btn btn-secondary btn-sm" onClick=${testDigest}>Send me a test digest now</button>
        </div>
        <div style=${{ display: 'flex', gap: '0.75rem', alignItems: 'center' }}>
            <button class="btn btn-primary" onClick=${save}>Save changes</button>
            ${toast && html`<span class="field-hint">${toast}</span>`}
        </div>`;
}

/* ----------------------------- Manager --------------------------------- */
function CommentBox({ ownerId, kind, targetId, onAdded }) {
    const [text, setText] = useState('');
    const send = async () => { if (!text.trim()) return; const d = await postJSON('/api/comments', { owner_id: ownerId, kind, target_id: targetId, text }); if (d && d.ok) { setText(''); onAdded(); } };
    return html`<div style=${{ display: 'flex', gap: '0.4rem', marginTop: '0.35rem' }}>
        <input type="text" placeholder="Add a comment…" value=${text} style=${{ flex: 1 }} onInput=${e => setText(e.target.value)} onKeyDown=${e => { if (e.key === 'Enter') send(); }} />
        <button class="btn btn-ghost btn-sm" onClick=${send}>Comment</button></div>`;
}
function Manager() {
    const [reports, setReports] = useState(null);
    const load = useCallback(() => getJSON('/api/manager/reports').then(d => setReports((d && d.reports) || [])), []);
    useEffect(() => { load(); }, [load]);
    if (reports == null) return html`<${Spinner} />`;
    const block = (r, kind, it, headline) => html`
        <div key=${it.id} style=${{ border: '1px solid var(--line)', borderRadius: 'var(--radius-sm)', padding: '0.6rem 0.75rem', marginBottom: '0.5rem' }}>
            <div style=${{ fontWeight: 600, fontSize: '0.9rem' }}>${headline}</div>
            ${(it.comments || []).map((c, i) => html`<div key=${i} style=${{ fontSize: '0.85rem', background: 'var(--bg-elevated)', borderRadius: 'var(--radius-sm)', padding: '0.3rem 0.5rem', marginTop: '0.25rem' }}><strong>${c.author_name}:</strong> ${c.text} <span class="field-hint">${(c.date || '').slice(0, 10)}</span></div>`)}
            <${CommentBox} ownerId=${r.user_id} kind=${kind} targetId=${it.id} onAdded=${load} />
        </div>`;
    return html`
        <h2 class="page-title" style=${{ margin: '0 0 0.2rem' }}>Manager view</h2>
        <p class="page-subtitle" style=${{ marginBottom: '1.25rem' }}>People sharing their goals &amp; 1:1s with you. Comments are visible to both.</p>
        ${reports.length === 0 ? html`<div class="card"><p class="field-hint" style=${{ margin: 0 }}>No one is sharing with you yet. A teammate shares by setting your email as their manager and enabling "Share my goals &amp; 1:1s" in their Settings.</p></div>`
            : reports.map(r => html`<div key=${r.user_id} class="card" style=${{ marginBottom: '1.2rem' }}>
                <div class="section-label">${r.name} <span class="field-hint">&lt;${r.email}&gt;</span></div>
                <h4 style=${{ margin: '0.8rem 0 0.4rem', fontSize: '0.9rem' }}>Objectives</h4>
                ${(r.objectives || []).length === 0 ? html`<p class="field-hint">No objectives.</p>` : r.objectives.map(o => block(r, 'objective', o, html`${o.title} <span class="field-hint">[${o.status} · ${o.progress}%]</span>`))}
                <h4 style=${{ margin: '1rem 0 0.4rem', fontSize: '0.9rem' }}>1:1 meetings</h4>
                ${(r.meetings || []).length === 0 ? html`<p class="field-hint">No 1:1s.</p>` : r.meetings.map(m => block(r, 'meeting', m, html`${m.date} — ${m.title} <span class="field-hint">[${m.status}]</span>`))}
            </div>`)}`;
}

/* ----------------------------- App shell ------------------------------- */
function App() {
    const route = useHashRoute();
    const [navOpen, setNavOpen] = useState(false);
    useEffect(() => { setNavOpen(false); window.scrollTo(0, 0); }, [route]);
    let Page = Overview, title = 'Overview';
    if (route.startsWith('/insights')) { Page = Insights; title = 'Insights'; }
    else if (route.startsWith('/goals')) { Page = Goals; title = 'Goals'; }
    else if (route.startsWith('/meetings')) { Page = Meetings; title = '1:1s'; }
    else if (route.startsWith('/team')) { Page = Team; title = 'Team'; }
    else if (route.startsWith('/manager')) { Page = Manager; title = 'Manager'; }
    else if (route.startsWith('/connections')) { Page = Connections; title = 'Connections'; }
    else if (route.startsWith('/settings')) { Page = Settings; title = 'Settings'; }
    else if (route.startsWith('/gerrit')) { Page = () => html`<${SourcePage} kind="gerrit" />`; title = 'Gerrit'; }
    else if (route.startsWith('/jira')) { Page = () => html`<${SourcePage} kind="jira" />`; title = 'Jira'; }
    else if (route.startsWith('/confluence')) { Page = () => html`<${SourcePage} kind="confluence" />`; title = 'Confluence'; }
    else if (route.startsWith('/slack')) { Page = () => html`<${SourcePage} kind="slack" />`; title = 'Slack'; }
    return html`
        <div class="app-shell">
            <${Sidebar} route=${route} open=${navOpen} onClose=${() => setNavOpen(false)} />
            ${navOpen && html`<div class="sidebar-overlay show" onClick=${() => setNavOpen(false)}></div>`}
            <div class="app-main">
                <header class="app-topbar">
                    <button class="menu-toggle" onClick=${() => setNavOpen(true)}>☰</button>
                    <div class="topbar-title">${title}</div>
                    <button class="theme-toggle topbar-theme" onClick=${toggleTheme}>◐</button>
                </header>
                <main class="app-content"><${Page} /></main>
            </div>
        </div>`;
}

ReactDOM.createRoot(document.getElementById('root')).render(html`<${App} />`);
