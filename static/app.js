/* Zhia Lian Quest Browser: front end.
   One JSON model from /api/event drives four views. Quest progress lives in
   localStorage under STORE_KEY as a list of quest InternalNames, which stay
   stable from one data version to the next. Quests in the player's journal,
   from a player file (character export), live under JOURNAL_KEY. */
'use strict';
(() => {
  const STORE_KEY = 'zhiaLian.completed.v1';
  const JOURNAL_KEY = 'zhiaLian.journal.v1';
  const PREFS_KEY = 'zhiaLian.prefs.v1';
  const $ = (s, el = document) => el.querySelector(s);
  const $$ = (s, el = document) => [...el.querySelectorAll(s)];
  const esc = (s) => String(s ?? '').replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
  const fmt = (n) => Number(n || 0).toLocaleString('en-US');
  const avg = (a) => a.reduce((s, x) => s + x, 0) / a.length;
  const clamp = (v, lo, hi) => Math.max(lo, Math.min(hi, v));
  const plural = (n, one, many) => `${fmt(n)} ${n === 1 ? one : (many || one + 's')}`;

  const STATUS_LABEL = { done: 'Done', active: 'In journal', available: 'Available', locked: 'Locked' };
  const GATE_KINDS = ['followup', 'requires', 'offered'];
  const QUALITY = ['Rough', 'Crude', 'Decent', 'Nice', 'Quality', 'Great', 'Amazing', 'Astounding', 'Awesome', 'Incredible', 'Marvelous'];
  const CHECK_SVG = '<svg viewBox="0 0 16 16" aria-hidden="true"><path d="M3 8.5l3.2 3L13 4.5"/></svg>';
  const ZHIA = 'NPC_ZhiaLian';

  const S = {
    model: null,
    q: new Map(), npc: new Map(), region: new Map(), chain: new Map(),
    parents: new Map(), children: new Map(), chainOf: new Map(),
    done: new Set(), status: new Map(), journal: new Set(), importInfo: null, pendingImport: null,
    prefs: { followups: true }, player: null, playerAt: 0,
    tab: 'questline', npcSel: ZHIA, regionSel: null, chainSel: null,
    filters: { status: 'all', category: 'all', size: 'any' },
    search: '', drawerId: null, drawerReturn: null,
    graph: null, selectedNode: null, nextOnly: false,
  };

  // ------------------------------------------------------------ storage
  function loadDone() {
    try {
      const a = JSON.parse(localStorage.getItem(STORE_KEY) || '[]');
      if (Array.isArray(a)) a.forEach((x) => typeof x === 'string' && S.done.add(x));
    } catch { /* storage blocked: progress just won't persist */ }
  }
  function saveDone() {
    try { localStorage.setItem(STORE_KEY, JSON.stringify([...S.done])); } catch { /* ignore */ }
  }
  function loadJournal() {
    try {
      const j = JSON.parse(localStorage.getItem(JOURNAL_KEY) || 'null');
      if (j && Array.isArray(j.active)) {
        S.journal = new Set(j.active.filter((x) => typeof x === 'string'));
        S.importInfo = j.info || null;
      }
    } catch { /* ignore */ }
  }
  function loadPrefs() {
    try { Object.assign(S.prefs, JSON.parse(localStorage.getItem(PREFS_KEY) || '{}')); } catch { /* ignore */ }
  }
  function savePrefs() {
    try { localStorage.setItem(PREFS_KEY, JSON.stringify(S.prefs)); } catch { /* ignore */ }
  }
  function saveJournal() {
    try { localStorage.setItem(JOURNAL_KEY, JSON.stringify({ active: [...S.journal], info: S.importInfo })); } catch { /* ignore */ }
  }

  // ------------------------------------------------------------ model
  function push(map, k, v) { (map.get(k) || map.set(k, []).get(k)).push(v); }

  function indexModel(m) {
    S.model = m;
    S.q = new Map(); S.npc = new Map(); S.region = new Map(); S.chain = new Map();
    S.parents = new Map(); S.children = new Map(); S.chainOf = new Map();
    m.quests.forEach((q) => { q.label = q.short; S.q.set(q.id, q); });
    m.npcs.forEach((n) => S.npc.set(n.key, n));
    m.regions.forEach((r) => S.region.set(r.name, r));
    m.chains.forEach((c) => { S.chain.set(c.id, c); c.quests.forEach((id) => S.chainOf.set(id, c.id)); });
    m.edges.forEach((e) => { push(S.parents, e.to, e); push(S.children, e.from, e); });

    // Tell apart quests that share a name ("Delivering The Beer", repeated challenges).
    const byShort = new Map();
    m.quests.forEach((q) => push(byShort, q.short, q));
    byShort.forEach((list) => {
      if (list.length < 2) return;
      const nums = list.map((q) => ((q.objectives[0] || {}).text || '').match(/\d[\d,]*/));
      const distinct = nums.every(Boolean) && new Set(nums.map((n) => n[0])).size === list.length;
      list.forEach((q, i) => { q.label = distinct ? `${q.short} (goal ${nums[i][0]})` : `${q.short} (part ${i + 1})`; });
    });

    m.quests.forEach((q) => {
      const r = q.rewards;
      q._search = [
        q.name, npcName(q.giver),
        q.regions.map((x) => x.region + ' ' + x.spots.join(' ')).join(' '),
        q.objectives.map((o) => o.text + ' ' + (o.item ? o.item.name : '')).join(' '),
        r.items.map((i) => i.name).join(' '), r.recipes.map((i) => i.name).join(' '),
        r.titles.map((t) => t.text).join(' '), r.abilities.map((a) => a.name).join(' '),
        q.tags.join(' '),
      ].join(' ').toLowerCase();
    });
    // keep what was selected when the data is reloaded, if it still exists
    if (!S.npc.has(S.npcSel)) S.npcSel = m.npcs.length ? m.npcs[0].key : null;
    if (!S.region.has(S.regionSel)) S.regionSel = m.regions.length ? m.regions[0].name : null;
    if (!S.chain.has(S.chainSel)) S.chainSel = m.chains.length ? m.chains[0].id : null;
  }

  function npcName(key) {
    if (!key) return '';
    const n = S.npc.get(key);
    return n ? n.name : key;
  }

  // A quest is available when one of its unlocking parents is done (or, for
  // "offered" links, merely reached) and every hard prerequisite is done.
  function computeStatus() {
    const st = new Map();
    const visit = (id) => {
      if (st.has(id)) return st.get(id);
      st.set(id, 'locked'); // guards against any cycle in the data
      let s;
      if (S.done.has(id)) s = 'done';
      else if (S.journal.has(id)) s = 'active';
      else {
        const ps = (S.parents.get(id) || []).filter((e) => e.kinds.some((k) => GATE_KINDS.includes(k)));
        const unlockers = ps.filter((e) => e.kinds.includes('followup') || e.kinds.includes('offered'));
        const required = ps.filter((e) => e.kinds.includes('requires'));
        let open = unlockers.length === 0 || unlockers.some((e) =>
          S.done.has(e.from) || (e.kinds.includes('offered') && visit(e.from) !== 'locked'));
        if (required.length) open = open && required.every((e) => S.done.has(e.from));
        s = open ? 'available' : 'locked';
      }
      st.set(id, s);
      return s;
    };
    S.model.quests.forEach((q) => visit(q.id));
    S.status = st;
  }

  function lockedReason(q) {
    const ps = (S.parents.get(q.id) || []).filter((e) => e.kinds.some((k) => GATE_KINDS.includes(k)));
    const names = ps.filter((e) => !S.done.has(e.from)).map((e) => S.q.get(e.from).label);
    return names.length ? 'Finish ' + names.join(' or ') + ' first' : '';
  }

  // ------------------------------------------------------------ shared bits
  function sealBtn(q) {
    const d = S.done.has(q.id);
    return `<button type="button" class="seal" role="checkbox" aria-checked="${d}" aria-label="${esc(q.label)} done" data-toggle="${esc(q.id)}">${CHECK_SVG}</button>`;
  }
  function pill(id) {
    const st = S.status.get(id);
    return `<span class="pill ${st}">${STATUS_LABEL[st]}</span>`;
  }
  function img(src, cls, alt = '') {
    return src
      ? `<img class="${cls}" src="${esc(src)}" alt="${esc(alt)}" loading="lazy" width="32" height="32" onerror="this.style.visibility='hidden'">`
      : `<span class="${cls} ico-blank" aria-hidden="true"></span>`;
  }
  function questLink(id) {
    const q = S.q.get(id);
    return q ? `<button type="button" class="linkbtn" data-open="${esc(id)}">${esc(q.label)}</button>` : esc(id);
  }
  // Every event title shares the game's green, so the color says nothing here.
  function titleSpan(t) { return `<span class="t-text">${esc(t.text)}</span>`; }

  function rewardBits(q) {
    const r = q.rewards, bits = [];
    if (r.councils) bits.push(`<span>${fmt(r.councils)} councils</span>`);
    r.currencies.forEach((c) => bits.push(`<span class="reward-lec">${plural(c.amount, c.name.replace(/s$/, ''), c.name)}</span>`));
    const items = r.items.filter((i) => i.given === 'reward');
    if (items.length) bits.push(`<span>${items.length === 1 ? `${items[0].qty > 1 ? items[0].qty + '× ' : ''}${esc(items[0].name)}` : plural(items.length, 'item')}</span>`);
    if (r.titles.length) bits.push(`<span>Title: ${titleSpan(r.titles[0])}</span>`);
    if (r.abilities.some((a) => a.given === 'reward')) bits.push('<span>New ability</span>');
    if (r.recipes.some((a) => a.given === 'reward')) bits.push('<span>New recipe</span>');
    return bits.join('');
  }

  function questRow(q, regionName) {
    const st = S.status.get(q.id);
    let place = '';
    if (regionName) {
      const reg = q.regions.find((x) => x.region === regionName);
      place = reg && reg.spots.length ? reg.spots.join(', ') : '';
    } else {
      place = q.regions.map((x) => x.region).join(', ');
    }
    const tags = q.tags.map((t) => `<span class="tag">${esc(t)}</span>`).join('');
    return `<li class="qrow is-${st}" data-row="${esc(q.id)}">
      ${sealBtn(q)}
      <div class="q-main">
        <button type="button" class="q-title" data-open="${esc(q.id)}">${esc(q.label)}</button>
        <div class="q-sub">${place ? `<span class="place">${esc(place)}</span>` : ''}${rewardBits(q)}${tags}</div>
      </div>
      ${pill(q.id)}
    </li>`;
  }

  function filterQuests(list) {
    const f = S.filters, term = S.search;
    return list.filter((q) => {
      if (f.status !== 'all' && S.status.get(q.id) !== f.status) return false;
      if (f.category !== 'all' && q.category !== f.category) return false;
      const group = q.tags.includes('Group recommended');
      if (f.size === 'group' && !group) return false;
      if (f.size === 'solo' && group) return false;
      if (term && !q._search.includes(term)) return false;
      return true;
    });
  }

  function filtersBar(shown, total) {
    const seg = [['all', 'All'], ['available', 'Available'], ['active', 'In journal'], ['done', 'Done'], ['locked', 'Locked']]
      .map(([v, l]) => `<button type="button" data-fstatus="${v}" aria-pressed="${S.filters.status === v}">${l}</button>`).join('');
    const cats = [['all', 'Every type'], ...S.model.categories.map((c) => [c.id, c.label])]
      .map(([v, l]) => `<option value="${v}"${S.filters.category === v ? ' selected' : ''}>${esc(l)}</option>`).join('');
    const sizes = [['any', 'Solo or group'], ['solo', 'Solo-friendly'], ['group', 'Group recommended']]
      .map(([v, l]) => `<option value="${v}"${S.filters.size === v ? ' selected' : ''}>${l}</option>`).join('');
    return `<div class="filters">
      <div class="seg" role="group" aria-label="Status">${seg}</div>
      <label><span class="visually-hidden">Quest type</span><select data-fcat>${cats}</select></label>
      <label><span class="visually-hidden">Group size</span><select data-fsize>${sizes}</select></label>
      <span class="count">${shown === total ? plural(total, 'quest') : `${fmt(shown)} of ${plural(total, 'quest')}`}</span>
    </div>`;
  }

  // Long lists read better split by quest type.
  function questListHtml(list, regionName) {
    if (!list.length) return `<p class="empty">No quests match these filters. Try <button type="button" class="linkbtn" data-clear-filters>clearing the filters</button>.</p>`;
    if (list.length < 16) return `<ul class="qlist">${list.map((q) => questRow(q, regionName)).join('')}</ul>`;
    return S.model.categories.map((c) => {
      const part = list.filter((q) => q.category === c.id);
      if (!part.length) return '';
      const d = part.filter((q) => S.done.has(q.id)).length;
      return `<h3 class="group-title">${esc(c.label)}<small>${d} of ${part.length} done</small></h3>
        <ul class="qlist">${part.map((q) => questRow(q, regionName)).join('')}</ul>`;
    }).join('');
  }

  function countBadge(ids) {
    const d = ids.filter((id) => S.done.has(id)).length;
    return `<span class="s-count"><b>${d}</b>/${ids.length}</span>`;
  }

  // ------------------------------------------------------------ NPC view
  function renderNpcView() {
    const list = S.model.npcs;
    $('#npc-list').innerHTML = list.map((n) => {
      const ids = [...n.gives, ...n.involved];
      const meta = n.key === ZHIA ? 'Speaks into your mind' : (n.regions.join(', ') || 'In your inventory');
      return `<li><button type="button" data-npc="${esc(n.key)}" aria-current="${S.npcSel === n.key}">
        <span class="s-name">${esc(n.name)}</span><span class="s-meta">${esc(meta)}</span>${countBadge(ids)}</button></li>`;
    }).join('');
    const n = S.npc.get(S.npcSel) || list[0];
    if (!n) return;
    const gives = n.gives.map((id) => S.q.get(id));
    const involved = n.involved.map((id) => S.q.get(id));
    const fg = filterQuests(gives), fi = filterQuests(involved);
    const where = n.key === ZHIA ? 'Anywhere: she talks straight into your head' : n.areas.join(', ');
    $('#npc-pane').innerHTML = `
      <div class="pane-head">
        <h2>${esc(n.name)}</h2>
        ${where ? `<p class="where">${esc(where)}</p>` : ''}
        ${n.role ? `<p class="role">${esc(n.role)}</p>` : ''}
        ${n.desc ? `<p class="flavor">${esc(n.desc)}</p>` : ''}
      </div>
      ${filtersBar(fg.length + fi.length, gives.length + involved.length)}
      ${gives.length ? `${involved.length ? '<h3 class="group-title">Gives these quests</h3>' : ''}${questListHtml(fg)}` : ''}
      ${involved.length ? `<h3 class="group-title">Also appears in</h3>${questListHtml(fi)}` : ''}`;
  }

  // ------------------------------------------------------------ region view
  function renderRegionView() {
    const regs = S.model.regions;
    $('#region-list').innerHTML = regs.map((r) => `<li><button type="button" data-region="${esc(r.name)}" aria-current="${S.regionSel === r.name}">
      <span class="s-name">${esc(r.name)}</span>${countBadge(r.quests)}</button></li>`).join('');
    const r = S.region.get(S.regionSel) || regs[0];
    if (!r) return;
    const all = r.quests.map((id) => S.q.get(id));
    const shown = filterQuests(all);
    const npcs = r.npcs.filter((k) => k !== ZHIA).map((k) => S.npc.get(k));
    const anywhere = r.name === 'Anywhere';
    $('#region-pane').innerHTML = `
      <div class="pane-head">
        <h2>${esc(r.name)}</h2>
        ${anywhere
          ? '<p class="role">These quests don\'t point to one place. Do them wherever you find the right monsters, crafting station or moment.</p>'
          : (r.areas.length ? `<p class="where">Also covers ${esc(r.areas.join(', '))}</p>` : '')}
        ${npcs.length ? `<p class="npc-here">Event NPCs here: ${npcs.map((n) => `<button type="button" class="linkbtn" data-goto-npc="${esc(n.key)}">${esc(n.name)}</button>`).join(', ')}</p>` : ''}
      </div>
      ${filtersBar(shown.length, all.length)}
      ${questListHtml(shown, anywhere ? null : r.name)}`;
  }

  // ------------------------------------------------------------ drawer
  const PARENT_PHRASE = { requires: 'Needs', followup: 'Unlocked by finishing', offered: 'Offered while you have', completes: 'Completed by finishing' };
  const CHILD_PHRASE = { requires: 'Required for', followup: 'Finishing this unlocks', offered: 'While you have this, you\'re offered', completes: 'Finishing this counts toward' };
  const KIND_ORDER = ['requires', 'followup', 'offered', 'completes'];

  function linkGroups(edges, side, phrases) {
    const groups = new Map();
    edges.forEach((e) => {
      const kind = KIND_ORDER.find((k) => e.kinds.includes(k));
      push(groups, kind, e);
    });
    return KIND_ORDER.filter((k) => groups.has(k)).map((k) => `
      <li><span class="kind">${phrases[k]}</span><br>${groups.get(k).map((e) => `${questLink(e[side])} ${pill(e[side])}`).join('<br>')}
      ${groups.get(k).flatMap((e) => e.notes).map((n) => `<br><small class="kind">${esc(n)}</small>`).join('')}</li>`).join('');
  }

  function rewardsList(r) {
    const li = [];
    const row = (icon, html) => li.push(`<li>${icon}<span>${html}</span></li>`);
    if (r.councils) row(img(null, 'ico'), `<span class="qty">${fmt(r.councils)}</span> councils`);
    r.currencies.forEach((c) => row(img(null, 'ico'), `<span class="qty">${fmt(c.amount)}</span> ${esc(c.name)}`));
    r.items.forEach((i) => row(img(i.icon, 'ico', i.name), `<span class="qty">${fmt(i.qty)}×</span> ${esc(i.name)}${i.given === 'start' ? ' <small>(given when the quest starts)</small>' : ''}`));
    r.recipes.forEach((x) => row(img(x.icon, 'ico', x.name), `Recipe: ${esc(x.name)} <small>${esc(x.skill || '')}${x.level ? ' ' + x.level : ''}${x.given === 'start' ? ', taught when the quest starts' : ''}</small>`));
    r.abilities.forEach((a) => row(img(a.icon, 'ico', a.name), `Ability: ${esc(a.name)} <small>${esc(a.skill || '')}${a.given === 'start' ? ', taught when the quest starts' : ''}</small>`));
    r.titles.forEach((t) => row(img(null, 'ico'), `Title: ${titleSpan(t)}`));
    r.skillLevels.forEach((s) => row(img(null, 'ico'), `<span class="qty">+${s.levels}</span> ${esc(s.skill)} ${s.levels === 1 ? 'level' : 'levels'}`));
    r.xp.forEach((x) => row(img(null, 'ico'), `<span class="qty">${fmt(x.xp)}</span> ${esc(x.skill)} XP`));
    r.favor.forEach((f) => row(img(null, 'ico'), `<span class="qty">+${fmt(f.amount)}</span> favour with ${esc(f.name)}`));
    r.blessings.forEach(() => row(img(null, 'ico'), `Zhia's Blessing for an hour <small>(see <button type="button" class="linkbtn" data-tab-go="rewards">Rewards &amp; items</button>)</small>`));
    if (r.loot) row(img(null, 'ico'), `${esc(r.loot)}${r.lootLevel ? ` <small>(level ${r.lootLevel})</small>` : ''}`);
    r.other.forEach((o) => row(img(null, 'ico'), esc(o)));
    return li.length ? `<ul class="rlist">${li.join('')}</ul>` : '<p class="empty">No rewards listed.</p>';
  }

  function drawerHtml(q) {
    const done = S.done.has(q.id), st = S.status.get(q.id);
    const giver = q.giver ? S.npc.get(q.giver) : null;
    let from = '';
    if (q.giver === ZHIA) from = 'From Zhia Lian, straight into your mind';
    else if (giver) from = `From <button type="button" class="linkbtn" data-goto-npc="${esc(giver.key)}">${esc(giver.name)}</button>`;
    const where = q.regions.map((r) => r.region === 'Anywhere'
      ? '<li>Anywhere you can find what the quest asks for</li>'
      : `<li><button type="button" class="linkbtn" data-goto-region="${esc(r.region)}"><b>${esc(r.region)}</b></button>${r.spots.length ? ': ' + esc(r.spots.join(', ')) : ''}</li>`).join('');
    const notes = [
      ...q.requirements.map((t) => `<div class="callout">${esc(t)}</div>`),
      ...q.notes.map((t) => `<div class="callout quiet">${esc(t)}</div>`),
      st === 'locked' ? `<div class="callout">${esc(lockedReason(q))}</div>` : '',
      st === 'active' ? `<div class="callout quiet">In your journal${S.importInfo && S.importInfo.character ? `, from ${esc(S.importInfo.character)}'s player file` : ''}.</div>` : '',
    ].join('');
    const objs = q.objectives.map((o) => `<li><span class="n${o.count ? '' : ' dot'}">${o.count ? o.count + '×' : '•'}</span>
      <span>${esc(o.text)}${o.notes.map((n) => `<small>${esc(n)}</small>`).join('')}</span></li>`).join('');
    const parents = linkGroups(S.parents.get(q.id) || [], 'from', PARENT_PHRASE);
    const kids = linkGroups(S.children.get(q.id) || [], 'to', CHILD_PHRASE);
    const chainId = S.chainOf.get(q.id);
    return `
      <p class="d-giver">${from}</p>
      <h2 class="d-title" id="drawer-title">${esc(q.label)}</h2>
      <div class="d-actions">
        <button type="button" class="btn${done ? ' done' : ''}" data-toggle="${esc(q.id)}" aria-pressed="${done}">${done ? CHECK_SVG.replace('aria-hidden', 'width="14" height="14" stroke="currentColor" stroke-width="2.5" fill="none" aria-hidden') + ' Done' : 'Mark done'}</button>
        ${pill(q.id)}
        ${chainId ? `<button type="button" class="btn ghost" data-show-in-map="${esc(q.id)}">Show in questline</button>` : ''}
        <a class="btn ghost" href="${esc(q.wiki)}" target="_blank" rel="noopener">Open on the wiki</a>
      </div>
      <div class="d-sec"><h3>Where</h3><ul class="links d-where">${where}</ul></div>
      ${notes ? `<div class="d-sec">${notes}</div>` : ''}
      <div class="d-sec"><h3>What to do</h3><ul class="objs">${objs}</ul></div>
      <div class="d-sec"><h3>Rewards</h3>${rewardsList(q.rewards)}</div>
      ${parents || kids ? `<div class="d-sec"><h3>In the questline</h3><ul class="links">${parents}${kids}</ul></div>` : ''}
      <div class="d-sec"><h3>The quest text</h3><div class="story">${q.descHtml}</div>
        ${q.prefaceHtml ? `<div class="story-sub"><p><b>When the quest starts</b></p>${q.prefaceHtml}</div>` : ''}
        ${q.successHtml ? `<div class="story-sub"><p><b>When you finish</b></p>${q.successHtml}</div>` : ''}
      </div>
      <p class="d-meta">${q.repeat ? `<span>${esc(q.repeat)}</span>` : ''}<span>Quest ${q.num}</span><span>${esc(q.id)}</span></p>`;
  }

  function openDrawer(id, opener) {
    const q = S.q.get(id);
    if (!q) return;
    if (!S.drawerId) S.drawerReturn = opener || document.activeElement;
    S.drawerId = id;
    const d = $('#drawer');
    $('#drawer-body').innerHTML = drawerHtml(q);
    d.classList.add('open');
    d.setAttribute('aria-hidden', 'false');
    d.setAttribute('aria-labelledby', 'drawer-title');
    $('#scrim').hidden = false;
    d.scrollTop = 0;
    d.focus({ preventScroll: true });
  }
  function closeDrawer() {
    if (!S.drawerId) return;
    S.drawerId = null;
    const d = $('#drawer');
    d.classList.remove('open');
    d.setAttribute('aria-hidden', 'true');
    $('#scrim').hidden = true;
    if (S.drawerReturn && document.contains(S.drawerReturn)) S.drawerReturn.focus({ preventScroll: true });
  }
  function refreshDrawer() {
    if (!S.drawerId) return;
    const d = $('#drawer'), top = d.scrollTop;
    $('#drawer-body').innerHTML = drawerHtml(S.q.get(S.drawerId));
    d.scrollTop = top;
  }

  // ------------------------------------------------------------ questline map
  const NW = 232, NH = 54, GX = 74, GY = 16, STEP = NH + GY;
  const layouts = new Map();
  const view = { k: 1, x: 0, y: 0 };

  function gateParentsIn(id, set) {
    return (S.parents.get(id) || []).filter((e) => set.has(e.from) && e.kinds.some((k) => GATE_KINDS.includes(k))).map((e) => e.from);
  }
  function gateChildrenIn(id, set) {
    return (S.children.get(id) || []).filter((e) => set.has(e.to) && e.kinds.some((k) => GATE_KINDS.includes(k))).map((e) => e.to);
  }

  // Layered layout: columns by longest unlock path, rows nudged toward parents
  // then children so branches stay together.
  function layoutChain(chain) {
    if (layouts.has(chain.id)) return layouts.get(chain.id);
    const ids = chain.quests, set = new Set(ids), pos = new Map();
    const hasEdges = S.model.edges.some((e) => set.has(e.from) && set.has(e.to));
    if (!hasEdges) {
      const cols = Math.min(4, ids.length);
      ids.forEach((id, i) => pos.set(id, { x: (i % cols) * (NW + GX), y: Math.floor(i / cols) * STEP }));
    } else {
      const layer = new Map();
      const L = (id) => {
        if (layer.has(id)) return layer.get(id);
        layer.set(id, 0);
        const ps = gateParentsIn(id, set);
        const v = ps.length ? 1 + Math.max(...ps.map(L)) : 0;
        layer.set(id, v);
        return v;
      };
      ids.forEach(L);
      const layers = [];
      ids.forEach((id) => (layers[layer.get(id)] ||= []).push(id));
      layers.forEach((l) => l.sort((a, b) => S.q.get(a).num - S.q.get(b).num));
      const y = new Map();
      const place = (l, want) => {
        l.sort((a, b) => want.get(a) - want.get(b) || S.q.get(a).num - S.q.get(b).num);
        let prev = -Infinity;
        l.forEach((id) => { const v = Math.max(want.get(id), prev + STEP); y.set(id, v); prev = v; });
        const off = avg(l.map((id) => want.get(id) - y.get(id)));
        l.forEach((id) => y.set(id, y.get(id) + off));
      };
      layers[0].forEach((id, i) => y.set(id, i * STEP * 2));
      const forward = () => {
        for (let li = 1; li < layers.length; li++) {
          const want = new Map();
          layers[li].forEach((id, i) => {
            const ps = gateParentsIn(id, set).filter((p) => y.has(p));
            want.set(id, ps.length ? avg(ps.map((p) => y.get(p))) : (y.get(id) ?? i * STEP));
          });
          place(layers[li], want);
        }
      };
      const backward = () => {
        for (let li = layers.length - 2; li >= 0; li--) {
          const want = new Map();
          layers[li].forEach((id) => {
            const ks = gateChildrenIn(id, set).filter((k) => layer.get(k) === li + 1);
            want.set(id, ks.length ? (avg(ks.map((k) => y.get(k))) + y.get(id)) / 2 : y.get(id));
          });
          place(layers[li], want);
        }
      };
      forward(); backward(); forward();
      const minY = Math.min(...y.values());
      ids.forEach((id) => pos.set(id, { x: layer.get(id) * (NW + GX), y: y.get(id) - minY }));
    }
    let w = 0, h = 0;
    pos.forEach((p) => { w = Math.max(w, p.x + NW); h = Math.max(h, p.y + NH); });
    const out = { pos, w, h: h + 70, set };
    layouts.set(chain.id, out);
    return out;
  }

  function edgePath(a, b) {
    const sx = a.x + NW, sy = a.y + NH / 2, tx = b.x, ty = b.y + NH / 2;
    if (tx > sx + 10) {
      const dx = Math.max(30, (tx - sx) / 2);
      return `M${sx},${sy} C${sx + dx},${sy} ${tx - dx},${ty} ${tx - 2},${ty}`;
    }
    const x1 = a.x + NW / 2, y1 = a.y + NH, x2 = b.x + NW / 2 + 18, y2 = b.y + NH;
    const drop = Math.max(y1, y2) + 46;
    return `M${x1},${y1} C${x1},${drop} ${x2},${drop} ${x2},${y2 + 2}`;
  }

  const TAG_PATH = `M14,0 H${NW - 7} Q${NW},0 ${NW},7 V${NH - 7} Q${NW},${NH} ${NW - 7},${NH} H14 L0,${NH - 14} V14 Z`;
  function truncate(s, n) { return s.length > n ? s.slice(0, n - 1).trimEnd() + '…' : s; }

  function nodeSub(q) {
    const r = q.regions[0];
    if (!r) return '';
    return r.region === 'Anywhere' ? 'Anywhere' : (r.spots[0] && r.spots[0] !== npcName(q.giver) ? `${r.region}, ${r.spots[0]}` : r.region);
  }

  function renderChainPicker() {
    $('#chain-picker').innerHTML = S.model.chains.map((c) => {
      const d = c.quests.filter((id) => S.done.has(id)).length;
      return `<button type="button" role="radio" aria-checked="${S.chainSel === c.id}" data-chain="${esc(c.id)}">${esc(c.name)}<b>${d}/${c.quests.length}</b></button>`;
    }).join('');
    const c = S.chain.get(S.chainSel);
    $('#chain-blurb').textContent = c ? c.blurb : '';
  }

  function renderQuestline(keepView) {
    renderChainPicker();
    const c = S.chain.get(S.chainSel);
    if (!c) return;
    const g = layoutChain(c);
    S.graph = g;
    S.graphChain = c.id;
    const edges = S.model.edges.filter((e) => g.set.has(e.from) && g.set.has(e.to));
    $('#ql-edges').innerHTML = edges.map((e) => {
      const kind = KIND_ORDER.find((k) => e.kinds.includes(k));
      const marker = kind === 'offered' ? 'arrow-offered' : kind === 'completes' ? 'arrow-completes' : 'arrow';
      return `<path class="edge ${kind}" data-from="${esc(e.from)}" data-to="${esc(e.to)}" d="${edgePath(g.pos.get(e.from), g.pos.get(e.to))}" marker-end="url(#${marker})"/>`;
    }).join('');
    $('#ql-nodes').innerHTML = c.quests.map((id) => {
      const q = S.q.get(id), p = g.pos.get(id), st = S.status.get(id);
      return `<g class="node ${st}" data-node="${esc(id)}" transform="translate(${p.x},${p.y})" tabindex="0" role="button" aria-label="${esc(q.label)}, ${STATUS_LABEL[st]}">
        <title>${esc(q.name)}</title>
        <path class="tag-body" d="${TAG_PATH}"/>
        <circle class="n-seal" cx="24" cy="${NH / 2}" r="10"/>
        <path class="n-check" d="M19,${NH / 2} l3.5,3.6 l6.5,-7.2"/>
        <circle class="n-seal-hit" cx="24" cy="${NH / 2}" r="17" data-seal="${esc(id)}"/>
        <text class="n-title" x="44" y="23">${esc(truncate(q.label, 25))}</text>
        <text class="n-sub" x="44" y="41">${esc(truncate(nodeSub(q), 30))}</text>
      </g>`;
    }).join('');
    applyHighlights();
    if (!keepView) initialView();
  }

  function updateQuestlineStatus() {
    renderChainPicker();
    $$('#ql-nodes .node').forEach((n) => {
      const id = n.dataset.node, st = S.status.get(id);
      n.classList.remove('done', 'active', 'available', 'locked');
      n.classList.add(st);
      n.setAttribute('aria-label', `${S.q.get(id).label}, ${STATUS_LABEL[st]}`);
    });
    applyHighlights();
  }

  function lineage(id) {
    const keep = new Set([id]);
    const walk = (start, map, side) => {
      const stack = [start];
      while (stack.length) {
        const x = stack.pop();
        (map.get(x) || []).forEach((e) => { const y = e[side]; if (!keep.has(y)) { keep.add(y); stack.push(y); } });
      }
    };
    walk(id, S.parents, 'from');
    walk(id, S.children, 'to');
    return keep;
  }

  function applyHighlights() {
    const term = S.search;
    let keep = null;
    if (S.selectedNode && S.graph && S.graph.set.has(S.selectedNode)) keep = lineage(S.selectedNode);
    $$('#ql-nodes .node').forEach((n) => {
      const id = n.dataset.node, q = S.q.get(id);
      const match = term && q._search.includes(term);
      let dim = false;
      if (keep && !keep.has(id)) dim = true;
      if (term && !match) dim = true;
      if (S.nextOnly && !['available', 'active'].includes(S.status.get(id))) dim = true;
      n.classList.toggle('dim', dim);
      n.classList.toggle('match', !!match);
      n.classList.toggle('selected', id === S.selectedNode);
    });
    $$('#ql-edges .edge').forEach((p) => {
      const a = p.dataset.from, b = p.dataset.to;
      const lit = keep && keep.has(a) && keep.has(b);
      p.classList.toggle('lit', !!lit);
      p.classList.toggle('dim', !!(keep && !lit) || !!term || S.nextOnly);
    });
  }

  function applyView() {
    $('#ql-world').setAttribute('transform', `translate(${view.x},${view.y}) scale(${view.k})`);
  }
  function stageSize() { const r = $('#ql-svg').getBoundingClientRect(); return { w: r.width, h: r.height }; }
  function fitView() {
    const g = S.graph; if (!g) return;
    const { w, h } = stageSize(); const pad = 30;
    view.k = clamp(Math.min((w - pad * 2) / g.w, (h - pad * 2 - 30) / g.h), 0.15, 1.1);
    view.x = (w - g.w * view.k) / 2;
    view.y = Math.max(pad, (h - 40 - g.h * view.k) / 2);
    applyView();
  }
  // Big trees open readable at the roots; small ones fit to the stage.
  function initialView() {
    const g = S.graph; if (!g) return;
    const { w, h } = stageSize();
    const fitK = Math.min((w - 60) / g.w, (h - 90) / g.h);
    if (fitK >= 0.62) { fitView(); return; }
    view.k = w < 700 ? 0.7 : 0.85;
    const roots = [...g.pos.entries()].filter(([, p]) => p.x === 0).map(([, p]) => p.y + NH / 2);
    const cy = roots.length ? avg(roots) : g.h / 2;
    view.x = 24;
    view.y = h / 2 - cy * view.k;
    applyView();
  }
  function zoomAt(px, py, f) {
    const k2 = clamp(view.k * f, 0.15, 2.5), f2 = k2 / view.k;
    view.x = px - (px - view.x) * f2;
    view.y = py - (py - view.y) * f2;
    view.k = k2;
    applyView();
  }
  function centerOn(id) {
    const g = S.graph, p = g && g.pos.get(id);
    if (!p) return;
    const { w, h } = stageSize();
    view.k = Math.max(view.k, 0.8);
    view.x = w / 2 - (p.x + NW / 2) * view.k;
    view.y = h / 2 - (p.y + NH / 2) * view.k;
    applyView();
  }

  function setupPanZoom() {
    const svg = $('#ql-svg');
    const pointers = new Map();
    let start = null, moved = false, pinch = null;
    svg.addEventListener('wheel', (e) => {
      e.preventDefault();
      const r = svg.getBoundingClientRect();
      zoomAt(e.clientX - r.left, e.clientY - r.top, Math.exp(-e.deltaY * 0.0016));
    }, { passive: false });
    svg.addEventListener('pointerdown', (e) => {
      pointers.set(e.pointerId, { x: e.clientX, y: e.clientY });
      if (pointers.size === 1) { start = { x: e.clientX, y: e.clientY, vx: view.x, vy: view.y }; moved = false; }
      if (pointers.size === 2) {
        const [a, b] = [...pointers.values()];
        pinch = { d: Math.hypot(a.x - b.x, a.y - b.y), k: view.k };
      }
    });
    svg.addEventListener('pointermove', (e) => {
      if (!pointers.has(e.pointerId)) return;
      pointers.set(e.pointerId, { x: e.clientX, y: e.clientY });
      if (pointers.size === 2 && pinch) {
        const [a, b] = [...pointers.values()];
        const r = svg.getBoundingClientRect();
        const d = Math.hypot(a.x - b.x, a.y - b.y);
        zoomAt((a.x + b.x) / 2 - r.left, (a.y + b.y) / 2 - r.top, (pinch.k * d / pinch.d) / view.k);
        moved = true;
        return;
      }
      if (!start) return;
      const dx = e.clientX - start.x, dy = e.clientY - start.y;
      if (!moved && Math.hypot(dx, dy) < 5) return;
      if (!moved) { moved = true; svg.classList.add('panning'); try { svg.setPointerCapture(e.pointerId); } catch { /* ignore */ } }
      view.x = start.vx + dx; view.y = start.vy + dy;
      applyView();
    });
    const end = (e) => {
      pointers.delete(e.pointerId);
      if (pointers.size < 2) pinch = null;
      if (pointers.size === 0) { start = null; svg.classList.remove('panning'); }
    };
    svg.addEventListener('pointerup', end);
    svg.addEventListener('pointercancel', end);
    svg.addEventListener('click', (e) => {
      if (moved) { moved = false; return; }
      const seal = e.target.closest('[data-seal]');
      if (seal) { toggleDone(seal.dataset.seal); return; }
      const node = e.target.closest('[data-node]');
      if (node) {
        S.selectedNode = node.dataset.node;
        applyHighlights();
        openDrawer(node.dataset.node, node);
      } else if (S.selectedNode) {
        S.selectedNode = null;
        applyHighlights();
      }
    });
    svg.addEventListener('keydown', (e) => {
      const node = e.target.closest && e.target.closest('[data-node]');
      if (!node) return;
      if (e.key === 'Enter') { e.preventDefault(); S.selectedNode = node.dataset.node; applyHighlights(); openDrawer(node.dataset.node, node); }
      if (e.key === ' ') { e.preventDefault(); toggleDone(node.dataset.node); }
    });
    svg.addEventListener('focusin', (e) => {
      const node = e.target.closest && e.target.closest('[data-node]');
      if (!node) return;
      const p = S.graph.pos.get(node.dataset.node), { w, h } = stageSize();
      const sx = view.x + p.x * view.k, sy = view.y + p.y * view.k;
      if (sx < 0 || sy < 0 || sx + NW * view.k > w || sy + NH * view.k > h) centerOn(node.dataset.node);
    });
    $('#ql-zoom-in').addEventListener('click', () => { const s = stageSize(); zoomAt(s.w / 2, s.h / 2, 1.25); });
    $('#ql-zoom-out').addEventListener('click', () => { const s = stageSize(); zoomAt(s.w / 2, s.h / 2, 0.8); });
    $('#ql-fit').addEventListener('click', fitView);
    $('#ql-next').addEventListener('change', (e) => { S.nextOnly = e.target.checked; applyHighlights(); });
  }

  // ------------------------------------------------------------ rewards view
  function familyName(n) {
    const m = n.match(/^(\w+: )?(\w+) (.*)$/);
    return m && QUALITY.includes(m[2]) ? (m[1] || '') + m[3] : n;
  }
  function families(items) {
    const fam = new Map();
    items.forEach((it) => push(fam, familyName(it.name), it));
    return [...fam.entries()].map(([name, list]) => ({ name, list }));
  }
  function itemMatches(it) {
    const t = S.search;
    return !t || (it.name + ' ' + it.desc + ' ' + it.sources.join(' ')).toLowerCase().includes(t);
  }

  function familyHtml(f) {
    const first = f.list[0];
    const levels = f.list.map((i) => i.level).filter((x) => x != null);
    const sources = [...new Set(f.list.flatMap((i) => i.sources))];
    const qs = [...new Set(f.list.flatMap((i) => i.quests))];
    const metaParts = [];
    if (f.list.length > 1) {
      const range = familyQualities(f.list);
      metaParts.push(range ? `${f.list.length} qualities, ${range}` : `${f.list.length} versions`);
    }
    if (first.slot) metaParts.push(first.slot);
    if (levels.length) metaParts.push(levels.length > 1 ? `Levels ${Math.min(...levels)} to ${Math.max(...levels)}` : `Level ${levels[0]}`);
    if (first.food) metaParts.push(first.food);
    const how = qs.length ? 'Quest reward' : (sources.length ? sources[0].replace(/:.*$/, '') : '');
    const single = f.list.length === 1;
    const body = single
      ? `<p>${esc(first.desc)}</p>
         ${first.stats.length ? `<ul class="stats">${first.stats.map((s) => `<li>${esc(s)}</li>`).join('')}</ul>` : ''}
         ${first.skillReqs.length ? `<p class="src">Needs ${esc(first.skillReqs.join(', '))}</p>` : ''}
         ${sourcesHtml(first)}`
      : `<p>${esc(first.desc)}</p>
         <div class="tbl-wrap"><table class="variants"><colgroup><col style="width:24%"><col style="width:7%"><col style="width:42%"><col></colgroup>
         <thead><tr><th>Item</th><th>Level</th><th>Stats</th><th>How to get it</th></tr></thead><tbody>
         ${f.list.map((i) => `<tr><td>${esc(i.name)}</td><td class="num">${i.level ?? ''}</td>
           <td><ul class="stats">${i.stats.map((s) => `<li>${esc(s)}</li>`).join('')}</ul></td>
           <td>${esc(i.sources.join('; ') || (i.quests.length ? '' : 'No recorded source'))}${i.quests.map((id) => ' ' + questLink(id)).join('')}</td></tr>`).join('')}
         </tbody></table></div>`;
    return `<li><details class="family">
      <summary>${img(first.icon, 'f-ico', f.name)}
        <span><span class="f-name">${esc(f.name)}</span><br><span class="f-meta">${esc(metaParts.join(', ') || how)}</span></span>
        <span class="f-more">${esc(how || 'Details')}</span></summary>
      <div class="family-body">${body}</div></details></li>`;
  }
  function familyQualities(list) {
    const qs = list.map((i) => i.name.split(' ').find((w) => QUALITY.includes(w))).filter(Boolean);
    return qs.length > 1 ? `${qs[0]} to ${qs[qs.length - 1]}` : '';
  }
  function sourcesHtml(it) {
    const parts = [];
    if (it.quests.length) parts.push(`Quest reward: ${it.quests.map(questLink).join(', ')}`);
    const other = it.sources.filter((s) => !s.startsWith('Quest:'));
    if (other.length) parts.push(esc(other.join('; ')));
    if (!parts.length) parts.push('No recorded source in the game data. Event items like this usually drop from undead during the event.');
    return `<p class="src">${parts.join('<br>')}</p>`;
  }

  function renderRewards() {
    const R = S.model.rewards, T = R.totals;
    const doneQ = S.model.quests.filter((q) => S.done.has(q.id) && q.kind !== 'book');
    const earned = {
      councils: doneQ.reduce((s, q) => s + q.rewards.councils, 0),
      lec: doneQ.reduce((s, q) => s + q.rewards.currencies.filter((c) => c.id === 'LiveEventCredits').reduce((a, c) => a + c.amount, 0), 0),
      favor: doneQ.reduce((s, q) => s + q.rewards.favor.filter((f) => f.npc === ZHIA).reduce((a, f) => a + f.amount, 0), 0),
      titles: new Set(S.model.quests.filter((q) => S.done.has(q.id)).flatMap((q) => q.rewards.titles.map((t) => t.key))).size,
    };
    const questTitles = R.titles.filter((t) => t.quests.length).length;
    const sec = (title, lede, inner) => (inner ? `<section class="r-sec"><h2>${title}</h2>${lede ? `<p class="lede">${lede}</p>` : ''}${inner}</section>` : '');

    const titlesLive = R.titles.filter((t) => !t.retired && (!S.search || t.text.toLowerCase().includes(S.search)));
    const titlesOld = R.titles.filter((t) => t.retired && (!S.search || t.text.toLowerCase().includes(S.search)));
    const titleLi = (t) => {
      const how = [];
      if (t.quests.length) how.push('From ' + t.quests.map(questLink).join(', '));
      t.how.filter((h) => h !== 'quest').forEach((h) => how.push(h === 'trick-or-treating' ? 'Earned by trick-or-treating' : 'Found in the party prize chest'));
      if (t.books.length) how.push('Counts toward ' + t.books.map(questLink).join(', '));
      return `<li>${titleSpan(t)}<div class="t-how">${how.join('. ') || esc(t.tooltip)}</div></li>`;
    };

    const items = R.items.map((g) => ({ ...g, items: g.items.filter(itemMatches) }));
    const group = (id) => items.find((g) => g.id === id);
    const famList = (g) => (g && g.items.length ? `<ul class="families">${families(g.items).map(familyHtml).join('')}</ul>` : '');

    const abilities = R.abilities.filter((a) => !S.search || a.name.toLowerCase().includes(S.search));
    const recipes = R.recipes.filter((a) => !S.search || a.name.toLowerCase().includes(S.search));
    const needs = R.craftNeeds.filter((a) => !S.search || a.name.toLowerCase().includes(S.search));
    const rewardItems = R.rewardItems.filter((a) => !S.search || a.name.toLowerCase().includes(S.search));

    const abilitiesHtml = abilities.length ? `<h3>Abilities</h3><div class="tbl-wrap"><table class="tbl"><thead><tr><th>Ability</th><th>Skill</th><th>From</th></tr></thead><tbody>
      ${abilities.map((a) => `<tr><td><div class="item-cell">${img(a.icon, '', a.name)}<span>${esc(a.name)}<br><small class="src">${esc(a.desc || '')}</small></span></div></td>
        <td>${esc(a.skill || '')}</td><td>${a.quests.map((x) => questLink(x.id) + (x.given === 'start' ? ' <small class="src">(at the start)</small>' : '')).join('<br>')}</td></tr>`).join('')}</tbody></table></div>` : '';
    const recipesHtml = recipes.length ? `<h3>Recipes taught by quests</h3><div class="tbl-wrap"><table class="tbl"><thead><tr><th>Recipe</th><th>Skill</th><th>From</th></tr></thead><tbody>
      ${recipes.map((r) => `<tr><td><div class="item-cell">${img(r.icon, '', r.name)}<span>${esc(r.name)}</span></div></td>
        <td>${esc(r.skill || '')} ${r.level || ''}</td><td>${r.quests.map((x) => questLink(x.id) + (x.given === 'start' ? ' <small class="src">(at the start)</small>' : '')).join('<br>')}</td></tr>`).join('')}</tbody></table></div>` : '';
    const blessingsHtml = !S.search && R.blessings.length ? `<h3>Zhia's blessings and wrath</h3>
      <p class="lede">Her Whimsical Challenges hand out one of these blessings when the server meets the goal, and one of the wraths when it doesn't. The data doesn't say which challenge gives which.</p>
      <ul class="blessings">${R.blessings.map((b) => `<li class="${b.kind}">${img(b.icon, '', b.name)}<span><span class="b-name">${esc(b.name.replace(/^Zhia's (Blessing|Wrath): /, ''))}</span><small>${esc(b.desc)}</small><small>${esc(b.kind === 'blessing' ? 'Blessing, ' : 'Wrath, ')}${esc(b.duration.toLowerCase())}</small></span></li>`).join('')}</ul>` : '';

    const rewardTable = rewardItems.length ? `<div class="tbl-wrap"><table class="tbl"><thead><tr><th>Item</th><th>Total</th><th>Quests</th></tr></thead><tbody>
      ${rewardItems.map((a) => `<tr><td><div class="item-cell">${img(a.icon, '', a.name)}<span>${esc(a.name)}</span></div></td><td class="num">${fmt(a.total)}</td>
        <td><div class="qlinks">${a.quests.map((x) => `<span>${questLink(x.id)}${x.qty > 1 ? ` <small class="src">×${x.qty}</small>` : ''}${x.given === 'start' ? ' <small class="src">(at the start)</small>' : ''}</span>`).join('')}</div></td></tr>`).join('')}
      </tbody></table></div>` : '';
    const needsTable = needs.length ? `<div class="tbl-wrap"><table class="tbl"><thead><tr><th>Recipe</th><th>Skill</th><th>How to learn it</th><th>Needed for</th></tr></thead><tbody>
      ${needs.map((r) => `<tr><td><div class="item-cell">${img(r.icon, '', r.name)}<span>${esc(r.name)}</span></div></td><td>${esc(r.skill || '')} ${r.level || ''}</td>
        <td>${esc((r.learn || []).join('; ') || 'Not recorded')}</td><td>${r.quests.map(questLink).join('<br>')}</td></tr>`).join('')}
      </tbody></table></div>` : '';

    const anything = titlesLive.length + titlesOld.length + items.reduce((s, g) => s + g.items.length, 0) + abilities.length + recipes.length + needs.length + rewardItems.length;

    $('#rewards').innerHTML = `
      <div class="tally">
        <div><div class="v">${fmt(earned.councils)} <small>of ${fmt(T.councils)}</small></div><div class="l">Councils</div></div>
        <div><div class="v">${fmt(earned.lec)} <small>of ${fmt(T.liveEventCredits)}</small></div><div class="l">Live Event Credits, from ${T.liveEventCreditQuests.length} quests</div></div>
        <div><div class="v">${fmt(earned.favor)} <small>of ${fmt(T.zhiaFavor)}</small></div><div class="l">Favour with Zhia Lian, from quests</div></div>
        <div><div class="v">${fmt(earned.titles)} <small>of ${fmt(questTitles)}</small></div><div class="l">Quest titles, plus ${T.titles - questTitles} more to find</div></div>
      </div>
      <p class="tally-note">Totals are for one run of all ${T.quests} event quests. The first number counts the quests you've marked done.</p>
      ${S.search && !anything ? `<p class="empty">Nothing here matches “${esc(S.search)}”.</p>` : ''}
      ${sec('Titles', 'Titles you can earn this year. Several also count toward the three title-collection books, each worth a bonus skill level.',
        titlesLive.length ? `<ul class="titles">${titlesLive.map(titleLi).join('')}</ul>` : '')}
      ${sec('Hats and masks', 'Event headwear. Masquerade masks also get you into Zhia Lian\'s party.', famList(group('wearable')))}
      ${sec('Abilities, recipes and blessings', '', abilitiesHtml + recipesHtml + blessingsHtml)}
      ${sec('Candy', 'Seasonal candy, found on undead during the event.', famList(group('candy')))}
      ${sec('Food, drink and keys', 'Event loot keys open the special chests behind the Serbule Keep inn. The jade Weird Key opens the prize chest at the party.',
        famList({ items: [...(group('food') || { items: [] }).items, ...(group('key') || { items: [] }).items] }))}
      ${sec('Recipe and skill scrolls', '', famList(group('scroll')))}
      ${sec('Other event items', '', famList(group('other')))}
      ${sec('Everything the quests hand out', 'Every item a quest gives, with the total if you finish them all.', rewardTable)}
      ${sec('Recipes the quests ask you to craft', '', needsTable)}
      ${titlesOld.length ? sec('Past party titles', 'Earned at earlier years\' parties. They can no longer be earned.', `<ul class="titles">${titlesOld.map(titleLi).join('')}</ul>`) : ''}`;
  }

  // ------------------------------------------------------------ character export
  // The game's character export lists the quests in your journal (ActiveQuests)
  // but not finished repeatable quests, so finished event quests are worked out
  // from the quest chain.
  function inferFromExport(activeIds, completedIds) {
    const active = new Set(activeIds.filter((id) => S.q.has(id)));
    const gate = (id) => (S.parents.get(id) || []).filter((e) => e.kinds.some((k) => GATE_KINDS.includes(k)));

    // Everything that must have been reached (in the journal or finished) before `id` could be.
    const memo = new Map();
    const reach = (id) => {
      if (memo.has(id)) return memo.get(id);
      memo.set(id, new Set()); // cycle guard
      const R = new Set();
      const alts = [];
      gate(id).forEach((e) => {
        if (e.kinds.includes('requires')) { R.add(e.from); reach(e.from).forEach((x) => R.add(x)); }
        else alts.push(e.from); // "finishing unlocks" or "offered": any one of these was enough
      });
      if (alts.length) { // only what every alternative has in common is certain
        const sets = alts.map((a) => new Set([a, ...reach(a)]));
        sets[0].forEach((x) => { if (sets.every((set) => set.has(x))) R.add(x); });
      }
      memo.set(id, R);
      return R;
    };

    // 1. A quest that was reached but isn't in the journal any more is finished.
    const reached = new Set(active);
    for (let grew = true; grew;) {
      grew = false;
      [...reached].forEach((id) => reach(id).forEach((x) => { if (!reached.has(x)) { reached.add(x); grew = true; } }));
      [...reached].filter((id) => !active.has(id)).forEach((id) => (S.parents.get(id) || []).forEach((e) => {
        // whatever a finished quest needed to "count toward" it is finished too
        if (e.kinds.includes('completes') && !reached.has(e.from)) { reached.add(e.from); grew = true; }
      }));
    }
    const proven = new Set([...reached].filter((id) => !active.has(id)));
    completedIds.forEach((id) => { if (S.q.has(id) && !active.has(id)) proven.add(id); }); // e.g. title books

    // 2. Zhia hands out follow-ups by herself and they can't be abandoned, so a
    //    follow-up of a finished quest that isn't in the journal is finished too.
    const done = new Set(proven);
    if ([...active].some((id) => S.q.get(id).kind === 'zhia')) {
      const granted = new Set(S.model.quests.filter((q) => q.kind === 'zhia' && !gate(q.id).length).map((q) => q.id));
      const gateOk = (id) => {
        const ps = (S.parents.get(id) || []).filter((e) => e.kinds.includes('followup') || e.kinds.includes('requires'));
        const fu = ps.filter((e) => e.kinds.includes('followup'));
        const rq = ps.filter((e) => e.kinds.includes('requires'));
        return (!fu.length || fu.some((e) => done.has(e.from))) && rq.every((e) => done.has(e.from));
      };
      for (let grew = true; grew;) {
        grew = false;
        granted.forEach((id) => { if (!active.has(id) && !done.has(id)) { done.add(id); grew = true; } });
        [...done].forEach((id) => (S.children.get(id) || []).forEach((e) => {
          if (e.kinds.includes('followup') && !granted.has(e.to) && gateOk(e.to)) { granted.add(e.to); grew = true; }
        }));
      }
    }
    const byNum = (a, b) => S.q.get(a).num - S.q.get(b).num;
    const unresolved = [...active].map((id) => {
      const alts = gate(id).filter((e) => !e.kinds.includes('requires')).map((e) => e.from);
      return alts.length > 1 && !alts.some((a) => done.has(a) || active.has(a)) ? { id, alts } : null;
    }).filter(Boolean);
    return {
      active: [...active].sort(byNum),
      proven: [...proven].sort(byNum),
      followups: [...done].filter((id) => !proven.has(id)).sort(byNum),
      unresolved,
    };
  }

  function exportWhen(ts) {
    if (!ts) return '';
    const d = new Date(String(ts).trim().replace(' ', 'T'));
    return Number.isNaN(d.getTime()) ? String(ts) : d.toLocaleString(undefined, { dateStyle: 'medium', timeStyle: 'short' });
  }

  // What the page keeps about an export: who, when, favour. Quest lists are applied, not kept.
  function exportInfo(data, fileName) {
    const npcs = data.NPCs && typeof data.NPCs === 'object' ? data.NPCs : null;
    const zhia = npcs && npcs.NPC_ZhiaLian && typeof npcs.NPC_ZhiaLian === 'object' ? npcs.NPC_ZhiaLian : null;
    const favor = zhia && typeof zhia.Favor === 'number' ? zhia.Favor : (npcs ? 0 : null);
    return {
      character: String(data.Character || ''), server: String(data.ServerName || ''),
      timestamp: String(data.Timestamp || ''), when: exportWhen(data.Timestamp), file: fileName || '',
      favor, favorLevel: zhia ? String(zhia.FavorLevel || '') : '',
    };
  }
  function infoFromSummary(exp) {
    return {
      character: exp.character || '', server: exp.server || '', timestamp: exp.timestamp || '',
      when: exportWhen(exp.timestamp), file: exp.file || '', favor: exp.favor, favorLevel: exp.favorLevel || '',
    };
  }
  const exportTime = (ts) => new Date(String(ts || '').trim().replace(' ', 'T')).getTime();
  const sameExport = (a, b) => !!(a && b && a.character === b.character && a.server === b.server && a.timestamp === b.timestamp);

  async function postJSON(url, body) {
    const r = await fetch(url, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body || {}) });
    const data = await r.json().catch(() => ({ error: `The app answered ${r.status} without details.` }));
    if (!r.ok || data.error) throw new Error(data.error || `The app answered ${r.status}.`);
    return data;
  }

  function readExport(file) {
    if (!file) return;
    if (!S.model) { toast('Wait for the quests to finish loading, then import the file again.', { kind: 'bad' }); return; }
    const reader = new FileReader();
    reader.onload = async () => {
      let data = null;
      try { data = JSON.parse(String(reader.result).replace(/^\uFEFF/, '')); } catch { /* handled below */ }
      if (!data || !Array.isArray(data.ActiveQuests)) {
        toast(`${file.name} isn't a player file. Choose the Character_….json file the game saved.`, { kind: 'bad' });
        return;
      }
      const result = inferFromExport(
        data.ActiveQuests.filter((x) => typeof x === 'string'),
        Array.isArray(data.CompletedQuests) ? data.CompletedQuests.filter((x) => typeof x === 'string') : [],
      );
      const info = exportInfo(data, file.name);
      let watch = null;
      try {
        watch = await postJSON('/api/player/locate', { file: file.name, character: info.character, server: info.server });
      } catch { /* the app can't watch right now; the import still works */ }
      S.pendingImport = { ...result, info, watch };
      showImportDialog();
    };
    reader.onerror = () => toast(`Couldn't read ${file.name}.`, { kind: 'bad' });
    reader.readAsText(file);
  }

  function namesList(ids) {
    return `<ul class="imp-names">${ids.map((id) => `<li>${esc(S.q.get(id).label)}</li>`).join('')}</ul>`;
  }

  const VIP_NOTE = '<p class="watch-note">“Automatically export on logout” checkbox should be ticked (Settings → VIP)</p>';

  // Asks whether to keep this file watched. Ticked by default the first time.
  function watchSection(w, info) {
    if (!w) return '';
    const file = esc(w.file || info.file);
    const first = !(S.player && S.player.configured);
    if (w.watchingThis) {
      return `<div class="imp-watch"><p>You're already watching <b>${file}</b>, so each new save updates your ticks and favour by itself.</p></div>`;
    }
    const explain = `<p class="imp-note">The app checks it every 15 seconds and updates your ticks and favour each time the game saves it.</p>${VIP_NOTE}`;
    if (w.found) {
      const label = w.watchingOther ? `Watch <b>${file}</b> instead of ${esc(w.watchingOther)}` : `Watch <b>${file}</b> for updates`;
      return `<div class="imp-watch">
        <label class="imp-check"><input type="checkbox" id="imp-watch"${first ? ' checked' : ''}>${label}</label>
        ${explain}${w.path ? `<p class="imp-path">${esc(w.path)}</p>` : ''}</div>`;
    }
    if (w.canSetPath) {
      return `<div class="imp-watch">
        <label class="imp-check"><input type="checkbox" id="imp-watch">Watch <b>${file}</b> for updates</label>
        <p class="imp-note">The app couldn't find this file in Project Gorgon's Reports folder. To watch it, paste where it is:</p>
        <label class="visually-hidden" for="imp-path">Where the file is</label>
        <input type="text" id="imp-path" class="imp-path-input" spellcheck="false" autocomplete="off"
          placeholder="${esc((w.folder || 'C:\\Users\\you\\AppData\\LocalLow\\Elder Game\\Project Gorgon\\Reports') + (w.folder && w.folder.includes('/') ? '/' : '\\') + (w.file || info.file))}">
        ${explain}</div>`;
    }
    return `<div class="imp-watch"><p class="imp-note">To watch <b>${file}</b> for updates, import it on the computer that runs the app.</p></div>`;
  }

  function showImportDialog() {
    const p = S.pendingImport, info = p.info;
    const who = info.character ? `<b>${esc(info.character)}</b>${info.server ? ` on ${esc(info.server)}` : ''}` : 'This character';
    const favour = typeof info.favor === 'number' ? ` Zhia Lian favour: <b>${fmt(info.favor)}</b>${info.favorLevel ? ` (${esc(levelName(info.favorLevel))})` : ''}.` : '';
    const parts = [`<p class="imp-who">${who}, exported ${esc(info.when || 'at an unknown time')}.${favour}</p>`];
    if (!p.active.length) {
      parts.push('<p>This file has no Zhia Lian quests in the journal. Either the event hasn\'t reached this character yet, or every quest Zhia offered is finished. Nothing can be worked out from it, so importing it only clears your journal list.</p>');
    } else {
      const n = p.followups.length;
      parts.push(`<ul class="imp-sum">
        <li><b>${p.active.length}</b> event ${p.active.length === 1 ? 'quest is' : 'quests are'} in your journal. ${p.active.length === 1 ? 'It' : 'They'}'ll show as In journal.
          <details><summary>Show them</summary>${namesList(p.active)}</details></li>
        <li><b>${p.proven.length}</b> finished ${p.proven.length === 1 ? 'quest' : 'quests'}, worked out from what had to come before the quests in your journal.
          ${p.proven.length ? `<details><summary>Show them</summary>${namesList(p.proven)}</details>` : ''}</li>
        ${n ? `<li><label class="imp-check"><input type="checkbox" id="imp-follow"${S.prefs.followups ? ' checked' : ''}>Also mark <b>${n}</b> ${n === 1 ? 'follow-up' : 'follow-ups'} as finished.</label>
          Zhia gave you ${n === 1 ? 'this' : 'these'} after quests you finished, and ${n === 1 ? 'it isn\'t' : 'they aren\'t'} in your journal any more.
          <details><summary>Show them</summary>${namesList(p.followups)}</details></li>` : ''}
      </ul>`);
      if (p.unresolved.length) {
        parts.push(`<p class="imp-warn">Couldn't tell which of these you finished, so none is marked: ${p.unresolved
          .map((u) => u.alts.map((a) => esc(S.q.get(a).label)).join(' or ')).join('; ')}.</p>`);
      }
    }
    parts.push(`<label class="imp-check"><input type="checkbox" id="imp-replace">Clear my other ticks first</label>
      <p class="imp-note">Otherwise your other ticks stay as they are, except quests that are back in your journal.</p>`);
    parts.push(watchSection(p.watch, info));
    $('#import-body').innerHTML = parts.join('');
    $('#import-apply').textContent = p.active.length ? 'Mark these quests' : 'Clear my journal list';
    const path = $('#imp-path');
    if (path) path.addEventListener('input', () => { $('#imp-watch').checked = path.value.trim().length > 0; });
    const dlg = $('#import-dialog');
    if (typeof dlg.showModal === 'function') dlg.showModal(); else dlg.setAttribute('open', '');
    $('#import-apply').focus();
  }

  // Shared by the dialog and by watched-file updates.
  function applyResult(r, info, { followups, replace }) {
    const finished = [...r.proven, ...(followups ? r.followups : [])];
    const done = replace ? new Set() : new Set(S.done);
    r.active.forEach((id) => done.delete(id)); // in the journal again, so not finished this time round
    finished.forEach((id) => done.add(id));
    S.done = done;
    S.journal = new Set(r.active);
    S.importInfo = info;
    saveDone(); saveJournal(); rerenderAll();
    return finished.length;
  }

  async function applyImport() {
    const p = S.pendingImport;
    if (!p) return;
    S.pendingImport = null;
    if ($('#imp-follow')) { S.prefs.followups = $('#imp-follow').checked; savePrefs(); }
    const n = applyResult(p, p.info, { followups: S.prefs.followups, replace: $('#imp-replace').checked });
    const whose = p.info.character ? `${p.info.character}'s` : 'the';
    toast(`Marked ${plural(n, 'quest')} done and ${p.active.length} in your journal from ${whose} player file.`, { kind: 'ok' });
    const wantWatch = $('#imp-watch') && $('#imp-watch').checked;
    if (!wantWatch) return;
    const typed = $('#imp-path') ? $('#imp-path').value.trim() : '';
    try {
      const st = await postJSON('/api/player/watch', typed
        ? { path: typed }
        : { file: p.info.file, character: p.info.character, server: p.info.server });
      handlePlayerStatus(st, { quiet: true });
      toast(`Watching ${st.file}. New saves will update this page by themselves.`, { kind: 'ok' });
    } catch (err) {
      toast(`Couldn't start watching: ${err.message}`, { kind: 'bad' });
    }
  }

  // ------------------------------------------------------------ watching the player file
  // The app checks the file every 15 seconds; the page asks just after each check.
  let playerTimer = null;
  async function pollPlayer() {
    clearTimeout(playerTimer);
    let next = 15;
    try {
      const st = await (await fetch('/api/player', { cache: 'no-store' })).json();
      handlePlayerStatus(st);
      if (st.enabled && typeof st.nextCheckIn === 'number') next = clamp(st.nextCheckIn + 1, 2, 16);
    } catch { /* app closed or restarting: try again later */ }
    playerTimer = setTimeout(pollPlayer, next * 1000);
  }

  function handlePlayerStatus(st, opts = {}) {
    S.player = st;
    S.playerAt = Date.now();
    let applied = false;
    if (st.enabled && st.export && S.model) applied = applyWatched(st.export, opts);
    renderWatch();
    return applied;
  }

  // A newer save of the watched file: apply it the way the last import was applied.
  function applyWatched(exp, opts) {
    const info = infoFromSummary(exp);
    const prev = S.importInfo;
    if (sameExport(info, prev)) {
      if (prev && typeof prev.favor !== 'number' && typeof info.favor === 'number') { // imported before favour was shown
        S.importInfo = { ...prev, favor: info.favor, favorLevel: info.favorLevel };
        saveJournal(); renderProgress();
      }
      return false;
    }
    const tNew = exportTime(info.timestamp), tOld = prev ? exportTime(prev.timestamp) : NaN;
    if (prev && prev.character === info.character && tNew < tOld) return false; // this page already shows a newer save
    const before = new Set(S.done);
    const favourBefore = prev && typeof prev.favor === 'number' ? prev.favor : null;
    applyResult(inferFromExport(exp.active, exp.completed), info, { followups: S.prefs.followups, replace: false });
    if (opts.quiet) return true;
    const more = [...S.done].filter((id) => !before.has(id)).length;
    const bits = [];
    if (!prev) bits.push(`${plural(S.done.size, 'quest')} done`);
    else if (more) bits.push(`${more} more ${more === 1 ? 'quest' : 'quests'} done`);
    bits.push(`${S.journal.size} in your journal`);
    if (typeof info.favor === 'number' && info.favor !== favourBefore) {
      const d = favourBefore === null ? '' : ` (${info.favor > favourBefore ? '+' : ''}${fmt(info.favor - favourBefore)})`;
      bits.push(`favour ${fmt(info.favor)}${d}`);
    }
    toast(prev
      ? `${info.file} was saved${info.when ? ' ' + info.when : ''}: ${bits.join(', ')}.`
      : `Loaded the watched file ${info.file}${info.when ? ', saved ' + info.when : ''}: ${bits.join(', ')}.`, { kind: 'ok' });
    return true;
  }

  function checkedText() {
    const st = S.player;
    if (!st || st.checkedAgo == null) return 'Checking…';
    const ago = st.checkedAgo + (Date.now() - S.playerAt) / 1000;
    if (ago < 5) return 'Checked just now';
    if (ago < 90) return `Checked ${Math.round(ago)} seconds ago`;
    return `Checked ${Math.round(ago / 60)} minutes ago`;
  }

  function renderWatch() {
    const st = S.player, box = $('#watch');
    const show = !!(st && st.configured);
    if (box.hidden === show) {
      box.hidden = !show;
      document.documentElement.style.setProperty('--header-h', $('.top').offsetHeight + 'px');
    }
    if (!show) return;
    $('#watch-toggle').checked = st.enabled;
    $('#watch-label').textContent = st.enabled ? `Watching ${st.file}` : `Watch ${st.file} for updates`;
    const state = $('#watch-state');
    state.textContent = st.enabled ? (st.error || checkedText()) : '';
    state.classList.toggle('bad', !!(st.enabled && st.error));
    $('#watch-recheck').hidden = !st.enabled;
    $('#watch-note').hidden = !st.enabled;
    box.title = st.path ? st.path : '';
  }

  async function recheckNow() {
    const btn = $('#watch-recheck');
    btn.disabled = true;
    try {
      const st = await postJSON('/api/player/recheck', {});
      const applied = handlePlayerStatus(st);
      if (st.error) toast(st.error, { kind: 'bad' });
      else if (!applied) {
        const when = st.export ? exportWhen(st.export.timestamp) : '';
        toast(`Checked ${st.file}: no new save${when ? ' since ' + when : ''}.`);
      }
    } catch (err) {
      toast(err.message.includes('fetch') ? NOT_RESPONDING : err.message, { kind: 'bad' });
    } finally {
      btn.disabled = false;
      pollPlayer(); // line the next poll up with the app's next check
    }
  }

  async function setWatching(on) {
    try {
      handlePlayerStatus(await postJSON('/api/player/watch', { enabled: on }));
      if (on) pollPlayer();
    } catch (err) {
      $('#watch-toggle').checked = !on;
      toast(`Couldn't ${on ? 'start' : 'stop'} watching: ${err.message}`, { kind: 'bad' });
    }
  }

  // ------------------------------------------------------------ messages and data updates
  function toast(text, opts = {}) {
    const el = document.createElement('div');
    el.className = 'toast' + (opts.kind ? ' ' + opts.kind : '');
    el.setAttribute('role', opts.kind === 'bad' ? 'alert' : 'status');
    el.textContent = text;
    $('#toasts').appendChild(el);
    let timer = null;
    const remove = () => { el.classList.add('out'); setTimeout(() => el.remove(), 300); };
    const later = (ms) => { clearTimeout(timer); timer = setTimeout(remove, ms); };
    el.addEventListener('click', remove);
    if (!opts.sticky) later(opts.kind === 'bad' ? 10000 : 6000);
    return {
      update(t) { el.textContent = t; },
      done(t) { el.textContent = t; el.className = 'toast ok'; later(6000); },
      fail(t) { el.textContent = t; el.className = 'toast bad'; el.setAttribute('role', 'alert'); later(12000); },
    };
  }

  async function runRefresh(force) {
    const t = toast(force ? 'Downloading all game data files again.' : 'Checking for new game data.', { sticky: true });
    const stop = watchDownload((text) => t.update(text));
    try {
      const r = await fetch('/api/refresh', {
        method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ force }),
      });
      const res = await r.json().catch(() => ({ error: `The app answered ${r.status} without details.` }));
      if (!r.ok || res.error) throw new Error(res.error || `The app answered ${r.status}.`);
      if (res.updated) await reloadModel();
      t.done(res.message);
    } catch (err) {
      t.fail(err.message.includes('fetch') ? NOT_RESPONDING : err.message);
    } finally {
      stop();
    }
  }

  async function reloadModel() {
    const r = await fetch('/api/event', { cache: 'no-cache' });
    const model = await r.json();
    if (!r.ok || model.error) throw new Error(model.error || `The app answered ${r.status}.`);
    layouts.clear();
    S.graph = null;
    S.graphChain = null;
    indexModel(model);
    renderDataline(model.event);
    if (S.drawerId && !S.q.has(S.drawerId)) closeDrawer();
    computeStatus();
    renderProgress();
    if (S.tab === 'questline') renderQuestline(false); else renderTab();
    refreshDrawer();
  }

  // ------------------------------------------------------------ app shell
  function renderProgress() {
    const total = S.model.quests.length;
    const d = S.model.quests.filter((q) => S.done.has(q.id)).length;
    const inJournal = S.model.quests.filter((q) => S.status.get(q.id) === 'active').length;
    $('#done-count').textContent = d;
    $('#total-count').textContent = total;
    $('#journal-note').textContent = inJournal ? `, ${inJournal} in your journal` : '';
    const pct = total ? Math.round((d / total) * 100) : 0;
    $('#progress-fill').style.width = pct + '%';
    $('.progress-bar').setAttribute('aria-valuenow', pct);
    const note = $('#import-note');
    const info = S.importInfo;
    note.hidden = !info;
    if (info) note.textContent = `From ${info.character || 'your character'}'s player file${info.when ? ', ' + info.when : ''}`;
    renderFavour();
  }

  function levelName(level) { return String(level || '').replace(/([a-z])([A-Z])/g, '$1 $2'); }

  function renderFavour() {
    const info = S.importInfo;
    const has = !!(info && typeof info.favor === 'number');
    $('#favour').classList.toggle('empty', !has);
    $('#favour-num').hidden = !has;
    if (has) {
      $('#favour-value').textContent = fmt(info.favor);
      $('#favour-level').textContent = info.favorLevel ? levelName(info.favorLevel) : '';
      $('#favour-label').textContent = 'Zhia Lian favour';
    } else {
      $('#favour-label').textContent = 'Import a player file to see your Zhia Lian favour';
    }
  }

  function renderDataline(ev) {
    const where = ev.source === 'snapshot' ? ' (built-in copy, offline)' : (!ev.live ? ' (saved copy, offline)' : '');
    $('#dataline').textContent = `Project Gorgon's Halloween event. Game data v${ev.version}${where}.`;
  }

  function rerenderAll() {
    computeStatus();
    renderProgress();
    if (S.tab === 'questline') updateQuestlineStatus(); else renderTab();
    refreshDrawer();
  }

  function renderTab() {
    if (S.tab === 'npc') renderNpcView();
    else if (S.tab === 'region') renderRegionView();
    else if (S.tab === 'questline') renderQuestline(true);
    else if (S.tab === 'rewards') renderRewards();
  }

  function setTab(tab, opts = {}) {
    if (!['questline', 'npc', 'region', 'rewards'].includes(tab)) tab = 'questline';
    const changed = S.tab !== tab;
    if (!changed && tab !== 'questline') { renderTab(); if (!opts.noHash) writeHash(); return; }
    S.tab = tab;
    $$('.tabs [role="tab"]').forEach((b) => {
      const on = b.dataset.tab === tab;
      b.setAttribute('aria-selected', on);
      b.tabIndex = on ? 0 : -1;
    });
    $$('.view').forEach((v) => { v.hidden = v.id !== 'view-' + tab; });
    if (tab === 'questline') renderQuestline(!opts.resetView && S.graphChain === S.chainSel);
    else renderTab();
    if (!opts.noHash) writeHash();
    if (changed && !opts.keepScroll) window.scrollTo({ top: 0 });
  }

  function writeHash() {
    let h = S.tab;
    if (S.tab === 'npc' && S.npcSel) h += '/' + encodeURIComponent(S.npcSel);
    if (S.tab === 'region' && S.regionSel) h += '/' + encodeURIComponent(S.regionSel);
    if (S.tab === 'questline' && S.chainSel) h += '/' + encodeURIComponent(S.chainSel);
    if (location.hash.slice(1) !== h) history.replaceState(null, '', '#' + h);
  }
  function readHash() {
    const [tab, sel] = location.hash.slice(1).split('/');
    const val = sel ? decodeURIComponent(sel) : null;
    if (tab === 'npc' && val && S.npc.has(val)) S.npcSel = val;
    if (tab === 'region' && val && S.region.has(val)) S.regionSel = val;
    if (tab === 'questline' && val && S.chain.has(val)) S.chainSel = val;
    return tab || 'questline';
  }

  function toggleDone(id) {
    if (!S.q.has(id)) return;
    const focused = document.activeElement;
    const focusKey = focused && focused.dataset ? (focused.dataset.toggle || focused.dataset.node) : null;
    if (S.done.has(id)) S.done.delete(id); else S.done.add(id);
    saveDone();
    computeStatus();
    renderProgress();
    if (S.tab === 'questline') updateQuestlineStatus(); else renderTab();
    refreshDrawer();
    // keep keyboard focus where it was and stamp the seal
    if (focusKey) {
      const again = $(`[data-toggle="${CSS.escape(focusKey)}"]`, focused.closest('#drawer') ? $('#drawer') : document) || $(`[data-node="${CSS.escape(focusKey)}"]`);
      if (again) again.focus({ preventScroll: true });
    }
    if (S.done.has(id)) $$(`.seal[data-toggle="${CSS.escape(id)}"]`).forEach((el) => el.classList.add('stamp'));
  }

  function resetFilters() { S.filters = { status: 'all', category: 'all', size: 'any' }; }

  function bindEvents() {
    document.addEventListener('click', (e) => {
      const t = e.target.closest('button, a, [data-row], [data-tab-go]');
      if (!t) return;
      const d = t.dataset;
      if (d.toggle) { e.stopPropagation(); toggleDone(d.toggle); return; }
      if (d.open) { openDrawer(d.open, t); return; }
      if (d.tab) { setTab(d.tab); return; }
      if (d.tabGo) { closeDrawer(); setTab(d.tabGo); return; }
      if (d.npc) { S.npcSel = d.npc; renderNpcView(); writeHash(); return; }
      if (d.region) { S.regionSel = d.region; renderRegionView(); writeHash(); return; }
      if (d.chain) { S.chainSel = d.chain; S.selectedNode = null; renderQuestline(false); writeHash(); return; }
      if (d.gotoNpc) { closeDrawer(); S.npcSel = d.gotoNpc; setTab('npc'); return; }
      if (d.gotoRegion) { closeDrawer(); S.regionSel = d.gotoRegion; setTab('region'); return; }
      if (d.showInMap) {
        const id = d.showInMap;
        closeDrawer();
        S.chainSel = S.chainOf.get(id);
        S.selectedNode = id;
        setTab('questline', { resetView: true });
        centerOn(id);
        const node = $(`[data-node="${CSS.escape(id)}"]`);
        if (node) node.focus({ preventScroll: true });
        return;
      }
      if (d.fstatus) { S.filters.status = d.fstatus; renderTab(); return; }
      if ('clearFilters' in d) { resetFilters(); S.search = ''; $('#search').value = ''; renderTab(); return; }
      if (d.row && !e.target.closest('button')) openDrawer(d.row, t);
    });
    document.addEventListener('change', (e) => {
      if (e.target.matches('[data-fcat]')) { S.filters.category = e.target.value; renderTab(); }
      if (e.target.matches('[data-fsize]')) { S.filters.size = e.target.value; renderTab(); }
    });
    let timer = null;
    $('#search').addEventListener('input', (e) => {
      clearTimeout(timer);
      timer = setTimeout(() => {
        S.search = e.target.value.trim().toLowerCase();
        if (S.tab === 'questline') applyHighlights(); else renderTab();
      }, 120);
    });
    $('#drawer-close').addEventListener('click', closeDrawer);
    $('#scrim').addEventListener('click', closeDrawer);
    document.addEventListener('keydown', (e) => {
      if (e.key === 'Escape') {
        if (S.drawerId) closeDrawer();
        const menu = $('.menu[open]');
        if (menu) menu.open = false;
      }
      // trap focus in the drawer while it's open
      if (e.key === 'Tab' && S.drawerId) {
        const f = $$('#drawer button, #drawer a[href]').filter((el) => el.offsetParent !== null);
        if (!f.length) return;
        if (e.shiftKey && (document.activeElement === f[0] || document.activeElement === $('#drawer'))) { e.preventDefault(); f[f.length - 1].focus(); }
        else if (!e.shiftKey && document.activeElement === f[f.length - 1]) { e.preventDefault(); f[0].focus(); }
      }
    });
    // arrow keys move between tabs
    $('.tabs').addEventListener('keydown', (e) => {
      if (!['ArrowLeft', 'ArrowRight'].includes(e.key)) return;
      const tabs = $$('.tabs [role="tab"]');
      const i = tabs.findIndex((b) => b.dataset.tab === S.tab);
      const next = tabs[(i + (e.key === 'ArrowRight' ? 1 : tabs.length - 1)) % tabs.length];
      setTab(next.dataset.tab);
      next.focus();
    });
    window.addEventListener('hashchange', () => { closeDrawer(); setTab(readHash(), { noHash: true }); });
    window.addEventListener('resize', () => {
      document.documentElement.style.setProperty('--header-h', $('.top').offsetHeight + 'px');
    });
    document.addEventListener('click', (e) => {
      const menu = $('.menu[open]');
      if (menu && !menu.contains(e.target)) menu.open = false;
    });

    $('#reset-progress').addEventListener('click', () => {
      $('.menu').open = false;
      if (!S.done.size && !S.journal.size) return;
      const watching = !!(S.player && S.player.enabled && S.importInfo);
      const after = watching ? ` The watched ${S.player.file} fills them in again the next time the game saves it.` : '';
      if (!confirm(`Clear all ${S.done.size} done marks and your journal list? Use this when a new year's event starts.${after}`)) return;
      S.done.clear(); S.journal.clear();
      if (!watching) S.importInfo = null; // keep which save is applied, so watching doesn't undo the reset
      saveDone(); saveJournal(); rerenderAll();
    });
    $('#export-progress').addEventListener('click', async () => {
      $('.menu').open = false;
      const text = JSON.stringify([...S.done]);
      try { await navigator.clipboard.writeText(text); alert(`Copied ${S.done.size} done quests. Paste them into this app in another browser.`); }
      catch { prompt('Copy this text:', text); }
    });
    $('#import-progress').addEventListener('click', () => {
      $('.menu').open = false;
      const text = prompt('Paste progress copied from this app. It replaces your current marks.');
      if (!text) return;
      try {
        const a = JSON.parse(text);
        if (!Array.isArray(a)) throw new Error('not a list');
        S.done = new Set(a.filter((x) => typeof x === 'string'));
        saveDone(); rerenderAll();
      } catch { alert('That text isn\'t progress from this app. Copy it again with "Copy my progress".'); }
    });

    // character export: button, menu item, or drop the file anywhere on the page
    const pickExport = () => { $('.menu').open = false; $('#import-file').value = ''; $('#import-file').click(); };
    $('#load-export').addEventListener('click', pickExport);
    $('#menu-load-export').addEventListener('click', pickExport);
    $('#import-file').addEventListener('change', (e) => readExport(e.target.files[0]));
    $('#import-cancel').addEventListener('click', () => { S.pendingImport = null; $('#import-dialog').close(); });
    $('#watch-toggle').addEventListener('change', (e) => setWatching(e.target.checked));
    $('#watch-recheck').addEventListener('click', recheckNow);
    setInterval(() => { if (S.player && S.player.enabled && !S.player.error) $('#watch-state').textContent = checkedText(); }, 1000);
    $('#import-dialog').addEventListener('cancel', () => { S.pendingImport = null; });
    $('#import-form').addEventListener('submit', () => applyImport()); // method="dialog" closes it
    let dragDepth = 0;
    const hasFiles = (e) => [...((e.dataTransfer && e.dataTransfer.types) || [])].includes('Files');
    window.addEventListener('dragenter', (e) => { if (hasFiles(e)) { dragDepth += 1; $('#drop-zone').hidden = false; } });
    window.addEventListener('dragleave', (e) => {
      if (!hasFiles(e)) return;
      dragDepth = Math.max(0, dragDepth - 1);
      if (!dragDepth) $('#drop-zone').hidden = true;
    });
    window.addEventListener('dragover', (e) => { if (hasFiles(e)) e.preventDefault(); });
    window.addEventListener('drop', (e) => {
      if (!hasFiles(e)) return;
      e.preventDefault();
      dragDepth = 0;
      $('#drop-zone').hidden = true;
      readExport(e.dataTransfer.files[0]);
    });

    $('#check-updates').addEventListener('click', () => { $('.menu').open = false; runRefresh(false); });
    $('#redownload').addEventListener('click', () => { $('.menu').open = false; runRefresh(true); });
  }

  function showError(msg) {
    $('#status-msg').hidden = false;
    $('#status-msg').innerHTML = `<h2>Couldn't load the quests</h2><p>${esc(msg)}</p><button type="button" class="btn" id="retry">Try again</button>`;
    $('#retry').addEventListener('click', () => { $('#status-msg').innerHTML = '<p>Loading game data…</p>'; load(); });
  }

  const NOT_RESPONDING = 'The app isn\'t responding. Make sure the Zhia Lian Quest Browser window is still open, then try again.';

  // Polls /api/status while the server downloads game data files.
  function watchDownload(onProgress) {
    const id = setInterval(async () => {
      try {
        const s = await (await fetch('/api/status', { cache: 'no-store' })).json();
        const dl = s.download || {};
        if (dl.active) onProgress(`Downloading game data v${dl.version}: ${dl.done} of ${dl.total} files.`);
      } catch { /* ignore; the main request reports errors */ }
    }, 600);
    return () => clearInterval(id);
  }

  async function load() {
    const stop = watchDownload((text) => { $('#status-msg').innerHTML = `<p>${esc(text)}</p>`; });
    try {
      const r = await fetch('/api/event', { cache: 'no-cache' });
      const data = await r.json().catch(() => ({ error: `The server answered ${r.status} without data.` }));
      if (!r.ok || data.error) throw new Error(data.error || `The server answered ${r.status}.`);
      stop();
      start(data);
    } catch (err) {
      stop();
      showError(err.message.includes('fetch') ? NOT_RESPONDING : err.message);
    }
  }

  function start(model) {
    indexModel(model);
    loadDone();
    loadJournal();
    loadPrefs();
    computeStatus();
    const ev = model.event;
    renderDataline(ev);
    $('#credit').textContent = ev.credit;
    $('#status-msg').hidden = true;
    document.documentElement.style.setProperty('--header-h', $('.top').offsetHeight + 'px');
    renderProgress();
    setupPanZoom();
    S.tab = null; // so the first setTab always shows a view
    setTab(readHash(), { keepScroll: true });
    pollPlayer();
  }

  bindEvents();
  load();
})();
