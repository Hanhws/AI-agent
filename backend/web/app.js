/* 가닥 창(로컬 웹 페이지). shared/ui의 노선도 카드 · 목록 · 한마디를 그대로 쓰고,
   여기에는 이 입구만의 것(프로젝트 · 대화 목록, 읽기 전용 대화, 찾은 곳, 백엔드와 주고받기)만 있어요.
   주소에 ?demo 를 붙이거나 백엔드 없이 열면 미리 정리해 둔 예시(data/demo_conversations.json)를 보여 줘요. */
(function () {
  'use strict';
  function many(n, word) { return n + ' ' + word + (n === 1 ? '' : 's'); }   // 1 chat · 2 chats
  var G = window.Gadak, el = G.el, fname = G.fname;
  var params = new URLSearchParams(location.search);
  var S = { demo: params.has('demo'), scen: params.get('scen'), projects: [], project: null, chat: null, reset: true,
    rev: -1, status: null, asked: {}, full: {}, bottom: true, goto: null, sources: null, off: false, usage: null,
    findQ: '', found: null, hiddenCount: 0, hiddenOpen: false, hiddenList: null };
  var POLL = 1500, FILES_SHOWN = 8;
  // Windows에 깐 가닥에서는 몇 마디가 달라요: 키를 두는 곳(키체인 → 자격 증명 관리자) · 폴더 경로를 붙여 넣는 법
  var WIN = /Win/i.test(navigator.platform || '');
  var KEYS_AT = WIN ? 'Credential Manager' : 'Keychain';
  var SITES = { 'claude-code': 'Claude Code', codex: 'Codex', cursor: 'Cursor', chatgpt: 'ChatGPT', claude: 'Claude', gemini: 'Gemini' };
  // 가닥 창은 시스템 설정(밝게 · 어둡게)을 따라가요. 주소에 ?theme=light · dark 를 붙이면 고정돼요
  if (/^(light|dark)$/.test(params.get('theme') || '')) document.documentElement.dataset.theme = params.get('theme');

  var g = G.create({
    render: render, go: go, goPart: goPart, itemState: saveItem, insert: copyOut, insertLabel: 'Copy',
    nudgeClass: 'nudge-web', statusBits: statusBits, sideFold: sideFold, track: track, setAuto: setAuto, handoff: handoff,
    // 앞길 살피기 (README 3-1): 목록의 넷째 칸 ‘앞길’과, 할 일 칸 아래의 ‘저절로 살피기’ 줄
    ahead: ahead, aheadOn: function () { return !S.demo && !!(S.status && S.status.ahead && S.status.ahead.on); },
    aheadAuto: function () { return !!(S.status && S.status.ahead && S.status.ahead.auto); }, setAheadAuto: setAheadAuto,
    // 화면에는 글의 앞부분만 실려 있어서, 찾기는 원문을 가진 백엔드에 맡겨요
    search: function (q) { return api('projects/' + encodeURIComponent(S.project) + '/search?q=' + encodeURIComponent(q)).then(function (d) { return d.hits; }); }
  });
  if (S.demo) { delete g.hooks.search; delete g.hooks.setAuto; delete g.hooks.handoff; }  // 예시는 화면에 실린 글에서 바로 찾고, 가닥이 보낼 곳도 없어요
  var st = g.st, R = g.R;

  /* 사용 기록: 무엇을 눌렀는지만 적어요(글은 안 적어요). 적을 수 있는 이름과 칸은 backend/usage_schema.py에 다 있어요 */
  function track(name, fields) { if (!S.demo && !S.off) api('usage', 'POST', { name: name, fields: fields || {} }).catch(function () {}); }

  function api(path, method, body) {
    var opt = method ? { method: method, headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body || {}) } : undefined;
    return fetch(path, opt).then(function (r) { if (!r.ok && r.status !== 409) throw new Error(String(r.status)); return r.json(); });
  }

  /* ---------- 틀 ---------- */
  function foldBtn(mark, label, onclick, cls) {
    var b = el('button', cls || 'colfold', mark); b.type = 'button'; b.setAttribute('aria-label', label); b.title = label; b.onclick = onclick; return b;
  }
  function store(k, v) { try { if (v === undefined) return localStorage.getItem('gadak.' + k); localStorage.setItem('gadak.' + k, v); } catch (e) { return null; } }
  function setLeft(open, quiet) {
    R.site.classList.toggle('left-shut', !open); R.leftOpen.hidden = open;
    if (!quiet) { store('leftOpen', open ? '1' : '0'); track('ui', { what: open ? 'list_open' : 'list_close' }); }
  }
  function sideFold(open, n) {
    R.sideCol.classList.toggle('shut', !open); R.sideOpen.hidden = open;
    R.sideOpenN.textContent = n ? 'To do ' + n : 'To do';
  }
  function mount() {
    var shell = document.getElementById('shell'); shell.innerHTML = ''; R.root = shell;
    // 맨 위 검은 머리띠: 전체 지도와 같은 지하철 표지판 띠 (심볼 · 가닥 · 전체 지도)
    var brand = el('header', 'brand band'), logo = el('button', 'logo'); shell.appendChild(brand);
    var site = el('div', 'site'); shell.appendChild(site);
    var bar = el('aside', 'sitebar'); site.appendChild(bar); logo.type = 'button'; logo.setAttribute('aria-label', 'Play the Gadak symbol again');
    var mark = G.makeMark(30, 10), word = el('b', null, '가닥'); word.appendChild(el('i', null, 'GADAK')); logo.appendChild(mark.svg); logo.appendChild(word); logo.onclick = function () { G.playMark(mark); };
    brand.appendChild(logo); G.macChrome(brand);
    // 전체 지도: 모든 프로젝트 · 대화를 시간 순서 노선으로 한눈에 (backend/web/map.html). 심볼 옆, 늘 보이는 자리에
    var map = el('button', 'btn sm mapbtn', 'System map'); map.type = 'button'; map.onclick = openMap; brand.appendChild(map);
    // 머리띠 오른쪽: 떠 있는 버튼(가닥 앱에서만 · 앱이 window.gadakFloatState로 알려 줘요) · 밤 · 낮 (shared/ui/mark.js G.makeSwitch)
    var right = el('div', 'bandr'); brand.appendChild(right);
    var fl = G.makeSwitch({ label: 'Gadak button (floating)', off: 'Gadak button', get: function () { return !!S.floatOn; },
      set: function (on) { S.floatOn = on; var n = window.webkit && window.webkit.messageHandlers && window.webkit.messageHandlers.gadak; if (n) n.postMessage({ float: on }); } });
    fl.hidden = S.floatOn === undefined; right.appendChild(fl);
    window.gadakFloatState = function (on) { S.floatOn = !!on; fl.hidden = false; fl.sync(); };
    right.appendChild(G.themeSwitch());
    var fw = el('div', 'findwrap'); R.find = el('input', 'qin'); R.find.type = 'search'; R.find.placeholder = 'Search chats';
    R.find.setAttribute('aria-label', 'Search all chats');
    R.find.addEventListener('input', function () { setFind(R.find.value.trim()); });
    R.find.addEventListener('keydown', function (e) { if (e.key === 'Escape') { R.find.value = ''; setFind(''); } });
    fw.appendChild(R.find); bar.appendChild(fw);
    // 양옆 기둥은 위의 버튼으로 접고 펴요. 접으면 얇은 띠에 펼치는 버튼만 남고, 폭이 부드럽게 줄어요 (app.css)
    var lf = foldBtn('‹', 'Collapse chat list', function () { setLeft(false); }); fw.appendChild(lf);
    R.leftOpen = foldBtn('›', 'Expand chat list', function () { setLeft(true); }, 'colopen'); R.leftOpen.appendChild(el('span', 'vt', 'Chats')); site.appendChild(R.leftOpen);
    R.site = site;
    R.lists = el('div', 'lists'); bar.appendChild(R.lists);
    R.foot = el('div', 'foot'); bar.appendChild(R.foot);
    // 가운데: 왼쪽에 노선도 카드와 그 아래 대화, 오른쪽에 목록(할 일 · 정한 것 · 산출물 · 앞길)을 카드와 떼어 위에서 아래까지.
    // 대화 옆 세로 레일은 위의 노선도와 겹쳐서 가닥 창에서는 그리지 않아요 (10/7 · 구현 담당. shared/ui/rail.js는 대화가 화면에 있는 다른 입구용으로 남아 있어요)
    var main = el('div', 'sitemain'); site.appendChild(main);
    var col = el('div', 'maincol'); main.appendChild(col);
    R.unfold = el('button', 'unfold', 'Expand strip map'); R.unfold.type = 'button'; R.unfold.hidden = true; R.unfold.onclick = function () { g.toggleDrawer(); }; col.appendChild(R.unfold);
    g.mountDrawer(col, null, true);
    var cw = el('div', 'chatwrap'); col.appendChild(cw);
    R.chat = el('div', 'chat'); R.thread = el('div', 'thread'); R.chat.appendChild(R.thread); cw.appendChild(R.chat);
    R.nudgeHost = cw;
    R.sideCol = el('aside', 'sidecol'); R.sideCol.setAttribute('aria-label', 'To do · Decided · Files · Ahead'); main.appendChild(R.sideCol);
    g.mountSide(R.sideCol, true);
    // 오른쪽 아래: 구독 사용 한도 게이지 (5시간 · 이번 주). 읽을 것이 없으면 칸째 숨어요 (backend/limits.py)
    R.limits = el('div', 'limits'); R.limits.hidden = true; R.sideCol.appendChild(R.limits);
    R.sideCol.appendChild(foldBtn('›', 'Collapse to-do list', function () { st.ledgerOpen = false; g.track('ui', { what: 'list_close' }); g.render(); }));
    R.sideOpen = foldBtn('‹', 'Expand to-do list', function () { st.ledgerOpen = true; g.track('ui', { what: 'list_open' }); g.render(); }, 'colopen');
    R.sideOpen.appendChild(R.sideOpenN = el('span', 'vt', 'To do')); R.sideCol.appendChild(R.sideOpen);
    setLeft(store('leftOpen') !== '0', true);
    R.chat.addEventListener('scroll', onChatScroll);
    R.toastEl = el('div', 'toast'); R.toastEl.hidden = true; shell.appendChild(R.toastEl);
    R.src = el('div', 'pop srcpop'); R.src.hidden = true; document.body.appendChild(R.src);
    R.ask = el('div', 'pop srcpop'); R.ask.hidden = true; R.ask.setAttribute('role', 'dialog'); document.body.appendChild(R.ask);
    R.ai = el('div', 'pop srcpop aipop'); R.ai.hidden = true; R.ai.setAttribute('role', 'dialog'); R.ai.setAttribute('aria-label', 'Connect AI'); document.body.appendChild(R.ai);
    R.file = el('input'); R.file.type = 'file'; R.file.accept = '.zip,.json'; R.file.hidden = true; R.file.onchange = importFile; shell.appendChild(R.file);
    document.addEventListener('click', function (e) { if (!R.src.hidden && !R.src.contains(e.target) && !(R.srcBtn && R.srcBtn.contains(e.target))) R.src.hidden = true; });
    // AI 연결 창은 연결하는 동안(브라우저에서 로그인하고 돌아올 때까지)에는 다른 곳을 눌러도 닫지 않아요
    document.addEventListener('click', function (e) {
      if (R.ai.hidden || R.ai.contains(e.target) || !document.body.contains(e.target) || (R.aiBtn && R.aiBtn.contains(e.target))) return;
      if (!(S.engine && S.engine.job.state === 'running')) closeAi();
    });
    setTimeout(function () { G.playMark(mark); }, 250);
  }

  /* ---------- 그리기 ---------- */
  function render() {
    var keep = R.chat.scrollTop;
    renderLists();
    renderThread();
    R.chat.scrollTop = S.bottom ? R.chat.scrollHeight : keep; S.bottom = false;
    var V = g.buildView(st.scope);
    R.drawer.classList.toggle('shut', !st.drawerOpen); R.unfold.hidden = st.drawerOpen;   // 접고 펴기는 높이가 부드럽게 (gadak.css)
    g.renderSide();                    // 목록은 노선도 카드를 접어도 그대로 있어요
    if (st.drawerOpen) { g.renderMapHead(V); g.renderMap(V); }
    g.renderNudge();
    updateViewing(true);
    renderFoot();
    if (S.goto && R.turnEls[S.goto]) { scrollToEl(R.turnEls[S.goto]); S.goto = null; }
    askClassify(V);
  }

  /* x = { title, run }을 주면 줄 오른쪽에 ×가 생겨요 (목록에서 빼기). 줄에 마우스를 올리면 보여요 */
  function citem(host, title, small, on, click, x) {
    var row = el('div', 'crow');
    var d = el('button', 'citem' + (on ? ' on' : '')); d.type = 'button'; d.title = title;
    d.appendChild(el('span', null, title)); if (small) d.appendChild(el('small', null, small));
    d.onclick = click; row.appendChild(d);
    if (x && !S.demo) {
      var b = el('button', 'cx', '×'); b.type = 'button'; b.title = x.title; b.setAttribute('aria-label', x.title);
      b.onclick = function (e) { e.stopPropagation(); x.run(); }; row.appendChild(b);
    }
    host.appendChild(row); return d;
  }
  // 프로젝트 노선 색 동그라미: 왼쪽 목록 · 노선도 · 전체 지도가 같은 색 (store.project_color)
  function pdot(color) { var i = el('i', 'pdot'); i.style.background = color; i.setAttribute('aria-hidden', 'true'); return i; }
  function renderLists() {
    var host = R.lists, keep = host.scrollTop;
    if (S.findQ) { R.listSig = null; host.innerHTML = ''; R.citems = {}; renderFound(host); host.scrollTop = keep; return; }
    if (!S.demo && S.projects.length && S.projects[0].list) {
      // 모든 프로젝트를 머리글로 두고 그 아래 대화를 늘 펼쳐 둬요 (Claude 사이드바처럼).
      // 몇 초마다 새로 그리면 누르는 중인 줄이 바뀌어 클릭이 씹혀요. 바뀐 게 없으면 그대로 둬요
      var sig = JSON.stringify([S.projects, g.ACT && g.ACT.id, S.hiddenCount, S.hiddenOpen, S.hiddenList]);
      if (sig === R.listSig && host.firstChild) return;
      R.listSig = sig; host.innerHTML = ''; R.citems = {};
      S.projects.forEach(function (p) {
        var row = el('div', 'crow'), head = el('h6', 'pgroup', p.name); if (p.color) head.prepend(pdot(p.color));
        row.appendChild(head); host.appendChild(row);
        var x = el('button', 'cx', '×'); x.type = 'button'; x.title = 'Remove all chats in this project from the list'; x.setAttribute('aria-label', x.title);
        x.onclick = function () { hideProject(p); }; row.appendChild(x);
        p.list.forEach(function (c) {
          R.citems[c.id] = citem(host, c.title || '(untitled)', c.date, !!g.ACT && c.id === g.ACT.id, function () { S.project = p.id; openChat(c.id); },
            { title: 'Remove this chat from the list', run: function () { hideChats([c.id], 'Removed the chat from the list.'); } });
        });
      });
      renderHidden(host); host.scrollTop = keep; return;
    }
    host.innerHTML = ''; R.citems = {};
    if (g.SC.chats.length) {
      var head = el('h6', null, g.SC.project ? 'Project · ' + g.SC.project : 'Recent chats'); host.appendChild(head);
      var mine = S.projects.filter(function (p) { return p.id === S.project; })[0];
      if (g.SC.project && mine && mine.color) head.prepend(pdot(mine.color));
      g.SC.chats.slice().reverse().forEach(function (c) {
        R.citems[c.id] = citem(host, c.title, c.date, c === g.ACT, function () { openChat(c.id); },
          { title: 'Remove this chat from the list', run: function () { hideChats([c.id], 'Removed the chat from the list.'); } });
      });
    }
    var others = S.projects.filter(function (p) { return p.id !== S.project; });
    if (others.length) {
      host.appendChild(el('h6', null, S.demo ? 'Other examples' : 'Other projects'));
      others.forEach(function (p) {
        var d = citem(host, p.name, S.demo ? '' : String(p.chats), false, function () { openProject(p.id); },
          { title: 'Remove all chats in this project from the list', run: function () { hideProject(p); } });
        if (p.color) d.firstChild.prepend(pdot(p.color));
      });
    }
    renderHidden(host);
    host.scrollTop = keep;
  }

  /* ---------- 목록에서 빼기: 필요 없는 대화를 목록 · 찾기 · 정리에서 빼요. 읽어 둔 글은 이 PC에 남고, 되돌릴 수 있어요 ---------- */
  function afterHiding(r, msg) {
    S.hiddenList = null;
    if (!r.ids.length) return;
    g.flashToast(msg, { label: 'Undo', run: function () { restore(r.ids); } });
    if (g.ACT && r.ids.indexOf(g.ACT.id) >= 0) { S.chat = null; S.reset = true; S.bottom = true; }
    load();
  }
  function hideChats(ids, msg) { api('chats/hidden', 'POST', { ids: ids, hidden: true }).then(function (r) { afterHiding(r, msg); }); }
  function hideProject(p) {
    api('projects/' + encodeURIComponent(p.id) + '/hide', 'POST').then(function (r) { afterHiding(r, 'Removed ' + r.ids.length + (r.ids.length === 1 ? ' chat' : ' chats') + ' in ‘' + p.name + '’ from the list.'); });
  }
  function restore(ids) {
    api('chats/hidden', 'POST', { ids: ids, hidden: false }).then(function (r) {
      S.hiddenList = null; if (!r.hidden) S.hiddenOpen = false;
      g.flashToast('Put ' + r.ids.length + (r.ids.length === 1 ? ' chat' : ' chats') + ' back in the list.');
      load();
    });
  }
  function renderHidden(host) {
    if (S.demo || !S.hiddenCount) return;
    var head = el('button', 'hhead', S.hiddenCount + ' removed · ' + (S.hiddenOpen ? 'Hide' : 'Show')); head.type = 'button';
    head.onclick = function () { S.hiddenOpen = !S.hiddenOpen; renderLists(); };
    host.appendChild(head);
    if (!S.hiddenOpen) return;
    if (!S.hiddenList) { api('chats/hidden').then(function (d) { S.hiddenList = d.chats; renderLists(); }); return; }
    S.hiddenList.forEach(function (c) {
      var b = el('button', 'fitem'); b.type = 'button'; b.title = 'Click to put it back in the list';
      var t = el('span', 't'); t.appendChild(el('span', null, c.title)); t.appendChild(el('small', null, 'Restore')); b.appendChild(t);
      b.appendChild(el('span', 'w', (c.project.id === '_none' ? '' : c.project.name + ' · ') + (SITES[c.site] || c.site) + ' · ' + c.date));
      b.onclick = function () { restore([c.id]); };
      host.appendChild(b);
    });
    if (S.hiddenList.length > 1) {
      var all = el('button', 'linkbtn hall', 'Restore all'); all.type = 'button';
      all.onclick = function () { restore(S.hiddenList.map(function (c) { return c.id; })); };
      host.appendChild(all);
    }
  }

  /* ---------- 대화 찾기: 프로젝트를 가리지 않고 모든 대화에서. 제목 · 프로젝트 · 쓴 곳이 맞는 대화가 먼저, 그다음 글이 맞는 대화 ---------- */
  var findTimer = null;
  function setFind(q) {
    S.findQ = q; clearTimeout(findTimer);
    if (!q) { S.found = null; renderLists(); return; }
    findTimer = setTimeout(function () {
      var asked = S.demo ? Promise.resolve(findDemo(q)) : api('chats/search?q=' + encodeURIComponent(q)).then(function (d) { return d.chats; });
      asked.then(function (hits) { if (S.findQ !== q) return; S.found = hits || []; renderLists(); }, function () {});
    }, 180);
    if (!S.found) renderLists();
  }
  function renderFound(host) {
    var hits = S.found;
    host.appendChild(el('h6', null, hits ? hits.length + (hits.length === 1 ? ' chat found' : ' chats found') : 'Searching…'));
    if (hits && !hits.length) { host.appendChild(el('div', 'lempty', 'No chats found.')); return; }
    (hits || []).forEach(function (h) {
      var b = el('button', 'fitem' + (g.ACT && h.id === g.ACT.id ? ' on' : '')); b.type = 'button'; b.title = h.title;
      var t = el('span', 't'); t.appendChild(el('span', null, h.title)); t.appendChild(el('small', null, h.date)); b.appendChild(t);
      b.appendChild(el('span', 'w', (h.project.id === '_none' ? '' : h.project.name + ' · ') + (SITES[h.site] || h.site)));
      if (h.snip) b.appendChild(el('span', 's', h.snip));
      b.onclick = function () { openFound(h); };
      host.appendChild(b);
    });
  }
  function openFound(h) {
    if (g.ACT && h.id === g.ACT.id && S.project === h.project.id) { if (h.turn && g.byId[h.turn]) go(g.byId[h.turn]); return; }
    S.project = h.project.id; S.chat = h.id; S.goto = h.turn || null; S.reset = true; S.bottom = !h.turn; S.keepScope = 'chat'; load();
  }
  /* 예시(?demo)에는 백엔드가 없어서 화면에 실린 글에서 찾아요 */
  function findDemo(q) {
    var d = S.demoData, n = q.toLowerCase(), out = [];
    if (!d) return out;
    function has(x) { return x && x.toLowerCase().indexOf(n) >= 0; }
    Object.keys(d.scenarios).forEach(function (k) {
      var sc = d.scenarios[k];
      sc.chats.forEach(function (c) {
        var named = has(c.title) || has(sc.name) || has(SITES[c.site]);
        var t = c.turns.filter(function (x) { return has(x.dec) || has(x.title) || has(x.user) || has(x.ai); })[0];
        if (!named && !t) return;
        var h = { id: c.id, title: c.title, site: c.site, date: c.date, project: { id: k, name: sc.name }, named: named };
        if (t) {
          var src = [t.dec, t.title, t.user, t.ai].filter(has)[0], i = src.toLowerCase().indexOf(n);
          h.turn = t.id; h.snip = (i > 24 ? '…' : '') + src.slice(Math.max(0, i - 24), i + q.length + 36) + (i + q.length + 36 < src.length ? '…' : '');
        }
        out.push(h);
      });
    });
    return out.sort(function (a, b) { return (b.named ? 1 : 0) - (a.named ? 1 : 0); });
  }

  /* 그 대화의 글. 가닥은 대답하지 않아요: 읽기만 하고 입력창은 없어요 */
  function renderThread() {
    R.thread.innerHTML = ''; R.turnEls = {}; R.partEls = {};
    var ts = g.activeTurns(), V = g.buildView('chat');
    if (!ts.length) {
      var e = el('div', 'empty-chat'); e.appendChild(el('b', null, 'No thread to follow yet.'));
      e.appendChild(el('span', null, S.demo ? 'Start a chat and its flow is drawn here.' : 'Chat in Claude Code, Codex or Cursor and the flow is drawn here. Connect web and app chats under Sources.'));
      R.thread.appendChild(e); return;
    }
    ts.forEach(function (t) {
      if (V.segStart(t)) R.thread.appendChild(el('div', 'seam', V.segs[V.sIdx[t.id]]));
      var n = chatTurn(t); if (st.enter === t.id) n.classList.add('enter');
      R.turnEls[t.id] = n; R.thread.appendChild(n);
    });
    st.enter = null;
  }
  /* 답을 제목 줄(## · 한 줄 전체가 굵은 글씨 · ---)로 나눠 맥락마다 구획해요. 제목이 둘 이상일 때만. 엔진을 쓰지 않아요 */
  var HEAD_RE = /^\s{0,3}(?:#{1,4}\s+(.+?)\s*#*|\*\*([^*]+)\*\*:?)\s*$/, RULE_RE = /^\s*(?:-{3,}|\*{3,}|_{3,})\s*$/;
  var FENCE_RE = /^\s*(```|~~~)/, ROW_RE = /^\s*\|.*(?:\||…)\s*$/, SEP_RE = /^\s*\|?[\s:|-]*-{2,}[\s:|-]*\|?\s*$/;
  function answerBlocks(text) {
    var out = [{ h: null, lines: [] }], fence = false;
    String(text || '').split('\n').forEach(function (line) {
      if (FENCE_RE.test(line)) fence = !fence;
      var m = !fence && line.match(HEAD_RE);    // 코드 블록 안의 # 주석은 제목이 아니에요
      if (m) out.push({ h: m[1] || m[2], lines: [] });
      else if (!fence && RULE_RE.test(line)) out.push({ h: null, lines: [] });
      else if (RULE_RE.test(line)) out.push({ h: null, lines: [] });
      else out[out.length - 1].lines.push(line);
    });
    out.forEach(function (b) { b.body = b.lines.join('\n').trim(); });
    out = out.filter(function (b) { return b.h || b.body; });
    return out.filter(function (b) { return b.h; }).length >= 2 ? out : null;
  }
  // **굵게** · `코드` · > 인용만 살려요. 글은 textContent로만 넣어요 (대화 원문을 HTML로 읽지 않아요)
  function inline(parent, text) {
    String(text).split(/(\*\*[^*\n]+\*\*|`[^`\n]+`)/).forEach(function (bit, i) {
      if (!bit) return;
      if (i % 2 === 0) parent.appendChild(document.createTextNode(bit));
      else parent.appendChild(el(bit[0] === '`' ? 'code' : 'b', null, bit[0] === '`' ? bit.slice(1, -1) : bit.slice(2, -2)));
    });
    return parent;
  }
  // 코드 블록(```)은 고정폭 상자로, 표(| … |)는 표로. 답이 잘려 닫는 ```가 없어도 끝까지 코드로 봐요
  function cells(line) { return line.trim().replace(/^\||\|$/g, '').split('|').map(function (c) { return c.trim(); }); }
  function table(rows) {
    var t = el('table'), head = rows.length > 1 && SEP_RE.test(rows[1]);
    rows.forEach(function (line, i) {
      if (head && i === 1) return;
      var tr = el('tr');
      cells(line).forEach(function (c) { tr.appendChild(inline(el(head && i === 0 ? 'th' : 'td'), c)); });
      t.appendChild(tr);
    });
    var w = el('div', 'tbl'); w.appendChild(t); return w;
  }
  function richText(text) {
    var f = el('div', 'rt'), plain = [], code = null, rows = [];
    function flush() {
      var s = plain.join('\n').replace(/^\n+|\n+$/g, ''); if (s) inline(f, s); plain = [];
      if (rows.length) { f.appendChild(table(rows)); rows = []; }
    }
    String(text || '').split('\n').forEach(function (line) {
      if (code) {
        if (FENCE_RE.test(line)) { f.appendChild(el('pre', 'code', code.join('\n'))); code = null; } else code.push(line);
        return;
      }
      if (FENCE_RE.test(line)) { flush(); code = []; return; }
      if (ROW_RE.test(line)) { if (plain.length) { var keep = rows; rows = []; flush(); rows = keep; } rows.push(line); return; }
      if (rows.length) flush();
      var q = line.match(/^\s*>\s?(.*)$/);
      if (q) { flush(); f.appendChild(inline(el('span', 'qt'), q[1])); } else plain.push(line);
    });
    flush(); if (code) f.appendChild(el('pre', 'code', code.join('\n')));
    return f;
  }
  // 제목 줄 = 역. 왼쪽에 프로젝트 색 노선을 세로로 긋고(레일과 같은 문법), 누르면 그 구획을 펼쳐요.
  // 처음에는 제목 아래를 접어 둬요: 제목만 훑고 궁금한 곳만 열어요 (제목 앞 머리말은 펼친 채). 연 구획은 기억해서 다시 그려도 열려 있어요
  var opened = {};
  function fillAnswer(box, text, key) {
    var blocks = answerBlocks(text);
    box.innerHTML = ''; box.classList.toggle('blocks', !!blocks);
    if (!blocks) { box.appendChild(richText(text)); return; }
    blocks.forEach(function (b) {
      var s = el('div', 'blk' + (b.h ? ' blk-st' : ''));
      if (b.h) {
        var id = key + ':' + b.h, open = !!opened[id];
        s.classList.toggle('shut', !open);
        var h = inline(el('button', 'blk-h'), b.h); h.type = 'button'; h.setAttribute('aria-expanded', String(open));
        h.onclick = function () { var shut = s.classList.toggle('shut'); h.setAttribute('aria-expanded', String(!shut)); opened[id] = !shut; };
        s.appendChild(h);
      }
      if (b.body) s.appendChild(richText(b.body));
      box.appendChild(s);
    });
  }
  function chatTurn(t) {
    var w = el('div', 'turn'); w.dataset.id = t.id;
    var u = el('div', 'u');
    if (t.depth > 0) u.appendChild(el('span', 'tag', 'Side trip, level ' + t.depth));
    if (t.ref && g.byId[t.ref]) u.appendChild(el('span', 'tag', '↩ ' + g.numLabel(g.byId[t.ref])));
    if (t.parts) u.appendChild(el('span', 'tag', many(t.parts.length, 'request')));
    var full = S.full[t.id] || t;  // 화면에는 앞부분만 와요. ‘전체 보기’로 받아 둔 원문이 있으면 그것을
    var up = el('p', null, full.user); u.appendChild(up); w.appendChild(u);
    var a = el('div', 'a'), para = el('div', 'part'); fillAnswer(para, full.ai, t.id); a.appendChild(para);
    if (t.parts) R.partEls[t.id + ':0'] = para;
    if (t.long && full === t) {
      var more = el('button', 'linkbtn more', 'Show all'); more.type = 'button';
      more.onclick = function () { track('ui', { what: 'full_text' }); api('turns/' + encodeURIComponent(t.id)).then(function (d) { S.full[t.id] = d.turn; up.textContent = d.turn.user; fillAnswer(para, d.turn.ai, t.id); more.remove(); g.renderRail(); }); };
      a.appendChild(more);
    }
    if (t.files) {
      var fs = el('div', 'files');
      t.files.slice(0, FILES_SHOWN).forEach(function (f) { var x = el('span', 'file'); x.appendChild(el('span', 'sq')); x.appendChild(document.createTextNode(fname(f))); fs.appendChild(x); });
      if (t.files.length > FILES_SHOWN) fs.appendChild(el('span', 'file rest', '+' + (t.files.length - FILES_SHOWN) + ' more'));
      a.appendChild(fs);
    }
    w.appendChild(a); return w;
  }

  function statusBits() {
    if (S.demo || !S.status || S.status.classify.engine === 'none') return [];
    var left = st.scope === 'all' ? g.SC.chats.reduce(function (n, c) { return n + (c.pending || 0); }, 0) : (g.ACT.pending || 0);
    if (!left) return [];
    return [(S.status.classify.paused ? 'Sorting paused' : 'Sorting') + ' · ' + left + (left === 1 ? ' turn left' : ' turns left')];
  }
  function renderFoot() {
    var f = R.foot; f.innerHTML = '';
    var s = S.status, text = '', hot = false;
    if (S.demo) text = 'A prepared example. Not a real conversation.';
    else if (S.off) { text = 'Gadak is off. Turn it back on and it picks up where it left off.'; hot = true; }
    else if (!s) text = 'Getting ready…';
    else if (s.sync.phase === 'scan') text = 'Reading past chats · ' + s.sync.done + '/' + s.sync.total;
    else if (s.classify.error) { text = s.classify.error; hot = true; }
    else if (s.classify.engine === 'none') text = 'No AI is connected for sorting, so titles are provisional. Press Connect AI.';
    else if (s.classify.running) text = 'Sorting the chat you are looking at first · ' + many(s.classify.calls, 'call');
    else if (s.classify.checking) text = 'Checking for anything missed · ' + many(s.classify.calls, 'call');
    else text = 'Leave it on and it reads new chats by itself' + (s.classify.calls ? ' · ' + many(s.classify.calls, 'sorting call') : '');
    f.appendChild(el('div', 'state' + (hot ? ' hot' : ''), text));
    if (S.demo) return;
    var row = el('div', 'row');
    // AI 연결: 정리에 쓸 AI가 없으면 눈에 띄게 (검은 버튼)
    R.aiBtn = el('button', 'btn sm' + ((s && s.classify.engine === 'none') || S.aiNeed ? ' primary' : ''), 'Connect AI'); R.aiBtn.type = 'button'; R.aiBtn.onclick = toggleAi; row.appendChild(R.aiBtn);
    R.srcBtn = el('button', 'btn sm', 'Sources'); R.srcBtn.type = 'button'; R.srcBtn.onclick = toggleSources; row.appendChild(R.srcBtn);
    if (s && s.classify.paused) { var again = el('button', 'btn sm', 'Resume sorting'); again.type = 'button'; again.onclick = function () { api('classify', 'POST', { pause: false }).then(tick); }; row.appendChild(again); }
    // 2단이 어떤 도구로 무엇을 보고 결론 냈는지는 노선도 카드에 넣지 않고 별도 페이지에서 봐요 (README 3-1)
    var log = el('button', 'btn sm', 'Decision trace'); log.type = 'button'; log.onclick = function () { track('ui', { what: 'trace' }); window.open('trace', '_blank'); }; row.appendChild(log);
    var help = el('button', 'btn sm', 'Help'); help.type = 'button'; help.onclick = openHelp; row.appendChild(help);
    var quit = el('button', 'btn sm', 'Quit'); quit.type = 'button'; quit.onclick = quitApp; row.appendChild(quit);
    f.appendChild(row);
  }

  /* 왼쪽 아래에 뜨는 창(찾은 곳 · AI 연결 · 사용 기록 묻기)은 발치 바로 위에 놓아요. 버튼이 두 줄이 되어도 가리지 않게요 */
  function above(p) { p.style.bottom = Math.max(window.innerHeight - R.foot.getBoundingClientRect().top + 8, 58) + 'px'; p.style.maxHeight = 'calc(100vh - ' + (parseFloat(p.style.bottom) + 20) + 'px)'; }

  /* ---------- 찾은 곳: 무엇으로 LLM을 쓰는지, 어떻게 읽는지 ---------- */
  function toggleSources() {
    if (!R.src.hidden) { R.src.hidden = true; return; }
    track('ui', { what: 'sources' });
    R.ask.hidden = true;   // 같은 자리에 떠요. 보내기는 찾은 곳 안에서도 고를 수 있어요
    closeAi();
    // 먼저 켜 둔 예전 가닥에 붙어 있으면 사용 기록 쪽은 없을 수 있어요. 없으면 그 줄만 빼고 보여 줘요
    Promise.all([api('sources'), api('usage/state').catch(function () { return null; })]).then(function (d) { S.sources = d[0].sources; S.usage = d[1]; renderSources(); above(R.src); R.src.hidden = false; });
  }
  function renderSources() {
    var p = R.src; p.innerHTML = '';
    p.appendChild(el('b', null, 'Sources'));
    p.appendChild(el('div', 'note', 'LLM records found on this computer. Chats that Gadak reads are stored only here; a turn goes to the AI only while it is being sorted.'));
    S.sources.forEach(function (s) {
      var d = el('div', 'src'), k, w = '', btn = null;
      if (s.mode === 'auto') {
        k = s.found ? 'Reading by itself · ' + many(s.chats, 'chat') : 'No records found';
        w = s.where + (s.found ? ' · ' + many(s.files, 'record file') : '');
        if (s.key === 'claude-code' && s.found) {
          // ‘앞으로는 알아서’를 켠 것을 가닥이 직접 보내려면 Claude Code 설정에 hook 둘을 더해야 해요. 눌렀을 때만 고쳐요
          w += s.hooks ? ' · Gadak can send directly (auto-run connected)' : ' · Connect so Gadak can send what you set to “Do this automatically”. Adds two hooks to the Claude Code settings';
          btn = el('button', 'btn sm' + (s.hooks ? '' : ' primary'), s.hooks ? 'Disconnect auto-run' : 'Connect auto-run'); btn.onclick = function () {
            api('sources/claude-code/' + (s.hooks ? 'disconnect' : 'connect'), 'POST').then(function (r) {
              g.flashToast(!r.ok ? r.reason : (s.hooks ? 'Removed the Gadak hooks from Claude Code.' : 'Connected. Gadak can send directly from the next Claude Code chat you open.'));
              return api('sources'); }).then(function (x) { S.sources = x.sources; renderSources(); }); };
        }
      } else if (s.mode === 'connect') {
        k = s.connected ? 'Connected · ' + many(s.chats, 'chat') : (s.found ? 'Connect once and it reads by itself after that' : 'Not installed on this computer');
        w = s.connected ? s.where + ' · reads from new chats on' : s.where + ' · connecting adds Gadak to Cursor’s hooks.json';
        if (s.found && !s.connected) { btn = el('button', 'btn sm primary', 'Connect'); btn.onclick = function () {
          api('sources/cursor/connect', 'POST').then(function (r) { g.flashToast(r.ok ? 'Cursor connected. Gadak reads from new chats on.' : r.reason); return api('sources'); }).then(function (x) { S.sources = x.sources; renderSources(); }); }; }
      } else if (s.mode === 'extension') {
        k = s.connected ? 'Connected · ' + many(s.chats, 'chat') : 'Add the Chrome extension and it reads by itself after that';
        w = s.connected ? s.where + ' · reads the chats you open in Chrome · last seen ' + s.seen
          : s.where + ' · In Chrome, go to chrome://extensions → turn on Developer mode → Load unpacked, and choose Gadak’s extension folder.';
        if (!s.connected) { btn = el('button', 'btn sm primary', 'Copy folder path'); btn.onclick = function () {
          G.copy(s.folder).then(function () { g.flashToast(WIN ? 'Copied. Paste it into the address box of the folder picker.' : 'Copied. In the folder picker press ⌘⇧G and paste it.'); }); }; }
      } else {
        k = 'Import from a file' + (s.chats ? ' · ' + many(s.chats, 'chat') : '');
        w = 'Use this to bring in past chats you have not opened, or chats from the desktop apps. Add the file (zip or json) you got from Settings → Export data in each service.';
        btn = el('button', 'btn sm primary', 'Choose file'); btn.onclick = function () { R.file.value = ''; R.file.click(); };
      }
      d.appendChild(el('span', 'k' + ((s.mode === 'auto' && s.found) || s.connected ? ' on' : ''), k));
      d.appendChild(el('span', 't', s.name)); d.appendChild(el('span', 'w', w));
      if (btn) { btn.type = 'button'; d.appendChild(btn); }
      p.appendChild(d);
    });
    if (S.usage && S.usage.configured) p.appendChild(usageBlock());
  }

  /* ---------- AI 연결: 가닥이 대화를 정리할 때 쓰는 AI를 고르고, 한 번 눌러 연결해요 (backend/engines · connect.py) ----------
     구독(Claude · ChatGPT)은 ‘연결하기’ 한 번이면 가닥이 필요한 것을 받고 브라우저에 로그인 창을 띄워요. API 키는 붙여 넣어요.
     API 키 칸은 하나예요. 어느 회사 키인지(Anthropic · OpenAI · Gemini)는 가닥이 키를 보고 알아봐요 (backend/engines/keys.py).
     어디까지 갔는지는 GET /engine의 job에 나와서, 연결하는 동안 2초마다 물어요. */
  var AI = {
    claude_cli: { name: 'Claude subscription', sub: 'Pro · Max', note: 'Sorts with your Claude subscription. No extra charge; it shares the usage limit with your own Claude use.' },
    codex_cli: { name: 'ChatGPT subscription', sub: 'Plus · Pro', note: 'Sorts with your ChatGPT subscription. No extra charge; it shares the usage limit with your own ChatGPT (Codex) use.' },
    api: { name: 'LLM API key', sub: 'Anthropic · OpenAI · Gemini', note: 'Sorts with an API key you have. Gadak works out which company the key is from. Usage is billed to that key. The key is kept only in ' + (WIN ? 'Windows Credential Manager on this PC' : 'the Keychain on this Mac') + '.' }
  };
  var GEMINI_NOTE = ' A free Gemini key costs nothing, but what you send may be used by Google to improve its products.';
  // API 키 엔진의 이름은 넣은 키의 회사를 따라가요 (anthropic_api · openai_api · gemini_api). 화면에서는 한 칸이에요
  function isKey(name) { return /_api$/.test(name || ''); }
  function aiOf(name) { return isKey(name) ? AI.api : AI[name]; }
  // ‘…으로 정리해요’에 넣을 말. API 키는 어느 회사 키인지까지 말해요
  function aiBy(name, e) { return isKey(name) ? 'your ' + (e.key && e.key.company ? e.key.company + ' ' : '') + 'API key' : 'your ' + AI[name].name; }
  // 안 된 까닭(reason)도 받아야 해서, 실패한 답(400 · 409)도 그대로 읽어요
  function ask(path, method, body) {
    return fetch(path, { method: method, headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body || {}) })
      .then(function (r) { return r.json(); }).catch(function () { return { ok: false, reason: 'Could not reach Gadak. Check that Gadak is running.' }; });
  }
  function toggleAi() { if (R.ai.hidden) openAi(); else closeAi(); }
  function closeAi() { R.ai.hidden = true; clearTimeout(S.aiTimer); }
  function openAi() {
    R.src.hidden = true; R.ask.hidden = true;
    api('engine?fresh=1').then(function (d) { S.engine = d; renderAi(); above(R.ai); R.ai.hidden = false; watchAi(); }, function () { g.flashToast('Could not reach Gadak.'); });
  }
  function watchAi() {
    clearTimeout(S.aiTimer);
    if (R.ai.hidden || !S.engine || S.engine.job.state !== 'running') return;
    S.aiTimer = setTimeout(function () {
      api('engine?fresh=1').then(function (d) {
        S.engine = d;
        if (d.job.state === 'done') { g.flashToast(AI[d.job.name].name + ' connected. Gadak now sorts with this AI.'); tick(); }
        renderAi(); watchAi();
      }, watchAi);
    }, 2000);
  }
  function gotEngine(r, said) {
    if (r.engine) S.engine = r.engine;
    if (!r.ok) g.flashToast(r.reason || 'That did not work.'); else if (said) g.flashToast(said);
    if (!R.ai.hidden) renderAi();
    watchAi(); tick();
  }
  function planName(plan) { return ({ pro: 'Pro', max: 'Max', team: 'Team', enterprise: 'Enterprise' })[plan] || plan; }
  function renderAi() {
    var p = R.ai, e = S.engine, job = e.job, busy = job.state === 'running';
    var ready = {}; e.options.forEach(function (o) { ready[o.name] = o.ready; });
    var using = ready[e.resolved] ? aiOf(e.resolved) : null;    // 골라져 있어도 아직 로그인 전이면 쓰는 중이 아니에요
    S.aiNeed = !using;
    var typed = p.querySelector('input'), key = typed ? typed.value : '', had = typed && document.activeElement === typed;   // 다시 그려도 치던 키는 그대로
    p.innerHTML = '';
    p.appendChild(el('b', null, 'Connect AI'));
    p.appendChild(el('div', 'note', 'The AI Gadak uses to sort your chats. You only need one. ' + (using
      ? 'Sorting with ' + aiBy(e.resolved, e) + (e.choice === 'auto' ? ' (chosen by Gadak).' : '.')
      : (e.choice === 'none' ? 'Set to work without AI, so Gadak only reads and shows your chats.' : 'Nothing connected yet, so Gadak only reads and shows your chats.'))));
    e.options.forEach(function (o) {
      var a = aiOf(o.name), byKey = isKey(o.name), now = e.resolved === o.name && o.ready, d = el('div', 'src' + (now ? ' now' : '')), mine = busy && job.name === o.name;
      var k = byKey ? (o.ready ? 'Connected · ' + (o.company ? o.company + ' · ' : '') + o.hint : 'Ready as soon as you add a key')
        : (o.ready ? 'Connected' + (o.plan ? ' · ' + planName(o.plan) : '') : (o.found ? 'Just needs a sign-in' : 'Not connected yet'));
      d.appendChild(el('span', 'k' + (o.ready ? ' on' : ''), (now ? 'In use · ' : '') + k));
      d.appendChild(el('span', 't', a.name + ' (' + a.sub + ')'));
      d.appendChild(el('span', 'w', mine ? job.message : a.note + (byKey && o.company === 'Gemini' ? GEMINI_NOTE : '')));
      if (!mine && job.state === 'failed' && job.name === o.name) d.appendChild(el('span', 'w fail', job.message));
      var row = el('div', 'row');
      if (mine) row.appendChild(button('Cancel', '', function () { ask('engine/cancel', 'POST').then(function (r) { gotEngine(r); }); }));
      else if (byKey && !o.ready) {
        var input = el('input'); input.type = 'password'; input.placeholder = 'Paste an LLM API key'; input.autocomplete = 'off'; input.spellcheck = false; input.value = key;
        input.setAttribute('aria-label', 'LLM API key');
        var save = function () {
          if (!input.value.trim()) { input.focus(); return; }
          ask('engine/key', 'POST', { key: input.value }).then(function (r) {
            if (r.ok) input.value = '';
            var whose = r.engine && r.engine.key && r.engine.key.company ? r.engine.key.company + ' ' : '';
            gotEngine(r, r.ok ? 'Saved the ' + whose + 'API key to the ' + KEYS_AT + '.' + (r.verified ? '' : ' Could not check that the key works.') : null);
          });
        };
        input.onkeydown = function (ev) { if (ev.key === 'Enter') save(); };
        row.appendChild(input); row.appendChild(button('Save', 'primary', save));
        if (had) setTimeout(function () { input.focus(); }, 0);
      } else if (!o.ready) {
        var go = button('Connect', 'primary', function () { ask('engine/connect', 'POST', { name: o.name }).then(function (r) { gotEngine(r); }); });
        go.disabled = busy; row.appendChild(go);
      } else {
        if (!now) row.appendChild(button('Sort with this', 'primary', function () { ask('engine/choose', 'POST', { name: o.name }).then(function (r) { gotEngine(r, 'Sorting with ' + aiBy(o.name, e) + ' from now on.'); }); }));
        if (byKey && o.source === 'keychain') row.appendChild(button('Delete key', '', function () { ask('engine/key', 'DELETE').then(function (r) { gotEngine(r, 'Deleted the key from the ' + KEYS_AT + '.'); }); }));
      }
      if (row.firstChild) d.appendChild(row);
      p.appendChild(d);
    });
    var foot = el('div', 'row');
    if (e.choice !== 'auto') foot.appendChild(button('Let Gadak choose', '', function () { ask('engine/choose', 'POST', { name: 'auto' }).then(function (r) { gotEngine(r, 'Gadak will choose an AI that is available.'); }); }));
    if (using) foot.appendChild(button('Use without AI', '', function () { ask('engine/choose', 'POST', { name: 'none' }).then(function (r) { gotEngine(r, 'Without AI, Gadak will only read and show your chats.'); }); }));
    foot.appendChild(button('Close', '', closeAi));
    p.appendChild(foot);
  }

  /* ---------- 사용 기록 보내기: 처음 한 번 묻고, 찾은 곳에서 바꿔요 (README 5장) ---------- */
  var USAGE_NOTE = 'Sends usage records, such as which features are used and how often, to the Gadak team’s server. Chat text, titles and file names are never sent.';
  function button(label, cls, click) { var b = el('button', 'btn sm' + (cls ? ' ' + cls : ''), label); b.type = 'button'; b.onclick = click; return b; }
  function loadUsage() {
    if (S.demo) return;
    api('usage/state').then(function (u) { S.usage = u; if (u.configured && !u.share) askUsage(); }, function () {});
  }
  function askUsage() {
    if (!R.ai.hidden) return;        // 같은 자리에 AI 연결 창이 떠 있어요. 사용 기록은 다음에 켤 때 물어요
    var p = R.ask; p.innerHTML = ''; above(p); p.hidden = false;
    p.appendChild(el('b', null, 'Help make Gadak better?'));
    p.appendChild(el('div', 'note', USAGE_NOTE + ' You can turn this off under Sources at any time and delete what was sent.'));
    var seen = el('div'); p.appendChild(seen);
    var row = el('div', 'row');
    row.appendChild(button('See what is sent', '', function () { showUsage(seen); }));
    row.appendChild(button('Don’t send', '', function () { setShare(false); }));
    row.appendChild(button('Send', 'primary', function () { setShare(true); }));
    p.appendChild(row);
  }
  function setShare(on) {
    api('usage/consent', 'POST', { share: on }).then(function (u) {
      S.usage = u; R.ask.hidden = true;
      g.flashToast(on ? 'Thank you. Usage records will be sent.' : 'Usage records will not be sent.');
      if (!R.src.hidden) renderSources();
    });
  }
  function showUsage(host) {
    api('usage/recent').then(function (d) {
      host.innerHTML = '';
      host.appendChild(el('div', 'note', 'These are the records on this computer. If sent, they go exactly like this.'));
      host.appendChild(el('pre', 'sent', d.events.length ? d.events.map(function (e) { return e.day + '  ' + e.name + '  ' + JSON.stringify(e.fields); }).join('\n') : 'No records yet.'));
    });
  }
  function usageBlock() {
    var u = S.usage, on = u.share === 'yes', d = el('div', 'src');
    var failing = on && u.error;   // 서버에 닿지 못했어요. 기록은 PC에 남아 있다가 다음 차례에 다시 가요
    d.appendChild(el('span', 'k' + (on && !failing ? ' on' : ''), failing ? 'Could not send · will try again later' : (on ? 'Sending · ' + many(u.sent, 'record') + ' sent' : 'Not sending')));
    d.appendChild(el('span', 't', 'Send usage records'));
    d.appendChild(el('span', 'w', USAGE_NOTE));
    var seen = el('div'), row = el('div', 'row');
    row.appendChild(button(on ? 'Turn off' : 'Turn on', on ? '' : 'primary', function () { setShare(!on); }));
    row.appendChild(button('See what is sent', '', function () { showUsage(seen); }));
    if (u.sent) row.appendChild(button('Delete from server', '', function () {
      api('usage/consent', 'POST', { forget: true }).then(function (x) {
        S.usage = x; renderSources();
        g.flashToast(x.deleted == null ? 'Could not reach the server. Sending is now off.' : 'Deleted ' + many(x.deleted, 'record') + ' from the server.');
      });
    }));
    d.appendChild(row); d.appendChild(seen);
    return d;
  }
  function importFile() {
    var file = R.file.files[0]; if (!file) return;
    var zip = /\.zip$/i.test(file.name);
    fetch('import', { method: 'POST', headers: { 'Content-Type': zip ? 'application/zip' : 'application/json' }, body: file })
      .then(function (r) { return r.json(); })
      .then(function (d) { R.src.hidden = true; g.flashToast(d.error ? d.error : 'Brought in ' + d.chats + (d.chats === 1 ? ' chat.' : ' chats.')); tick(); }, function () { g.flashToast('Could not read the file.'); });
  }
  function quitApp() {
    api('quit', 'POST').then(function () {
      clearInterval(S.timer);
      var o = el('div', 'gone'); o.appendChild(el('b', null, 'Gadak is off.')); o.appendChild(el('span', null, 'You can close this window. Turn Gadak on again and it picks up where it left off.')); R.root.appendChild(o);
    });
  }

  /* ---------- 이동 · 보는 중 ---------- */
  function scrollToEl(e) {
    R.chat.scrollTo({ top: Math.max(0, e.offsetTop - 16), behavior: G.reduce ? 'auto' : 'smooth' });
    e.classList.remove('flash'); void e.offsetWidth; e.classList.add('flash'); setTimeout(function () { e.classList.remove('flash'); }, 1400);
  }
  function go(t) {
    if (t.chat !== g.ACT) { S.goto = t.id; openChat(t.chat.id); return; }  // 다른 대화의 역이면 그 대화를 열고 그 위치로
    var e = R.turnEls[t.id]; if (e) scrollToEl(e);
  }
  function goPart(t, i) {
    var q = t.parts[i];
    if (q.open) { var it = g.itemsOf(t).filter(function (x) { return x.part === i; })[0]; go(t); if (it && g.stateOf(it) !== 'done') { st.nudge = it.id; g.setItem(it.id, 'open'); g.renderNudge(); } return; }
    var e = R.partEls[t.id + ':' + i] || R.turnEls[t.id]; if (e) scrollToEl(e);
  }
  var viewing = null, ticking = false;
  function updateViewing(force) {
    var y = R.chat.scrollTop + R.chat.clientHeight * 0.3, v = null;
    Array.prototype.forEach.call(R.thread.children, function (n) { if (n.dataset.id && n.offsetTop <= y) v = n.dataset.id; });
    if (R.chat.scrollTop + R.chat.clientHeight >= R.chat.scrollHeight - 4) { var last = R.thread.lastElementChild; if (last && last.dataset.id) v = last.dataset.id; }
    if (v === viewing && !force) return;
    viewing = v;
    Array.prototype.forEach.call(R.root.querySelectorAll('.viewing'), function (n) { n.classList.remove('viewing'); });
    if (!v) return;
    if (R.mapDots && R.mapDots[v]) R.mapDots[v].classList.add('viewing');
  }
  function onChatScroll() { if (ticking) return; ticking = true; requestAnimationFrame(function () { ticking = false; updateViewing(); }); }

  /* ---------- 실행: 가닥 창은 대화 창의 입력창을 건드릴 수 없어서 클립보드에 담아요 ---------- */
  function copyOut(text, label, done) {
    var ok = function () { g.flashToast('Copied. Paste it into the chat.'); done(); };
    track('ui', { what: 'copy' });
    G.copy(text).then(ok);
  }
  function handoff() {
    if (!g.ACT) return;
    g.flashToast('Writing a summary for the next chat…');
    api('chats/' + encodeURIComponent(g.ACT.id) + '/handoff').then(function (r) {
      if (!r.text) { g.flashToast('Nothing decided and nothing left to do yet.'); return; }
      track('ui', { what: 'copy' });
      G.copy(r.text).then(function () { g.flashToast('Copied a summary to paste into the next chat.'); });
    }, function () { g.flashToast('Could not write the summary.'); });
  }
  /* 앞길 보기: 이 대화의 마지막 턴에 서서 갈 수 있는 길을 찾아 달라고 해요. 엔진이 뒤에서 돌고, 어디까지 갔는지와 찾은 길은 목록의 ‘앞길’ 칸에 나타나요
     (기다리는 중 · 살피는 중 · 길 n개 · 낼 길이 없었음 · 못 살핀 까닭). 상태가 바뀌면 백엔드가 알려서(rev) 다시 받아 와요 */
  function ahead() {
    if (!g.ACT || !g.ACT.id) { g.flashToast('Choose a chat first.'); return; }
    st.sideTab = 'ahead'; st.ledgerOpen = true;
    api('chats/' + encodeURIComponent(g.ACT.id) + '/ahead', 'POST').then(function (r) {
      if (!r.ok) { g.SC.ahead = { state: 'failed', reason: r.reason }; g.render(); return; }
      g.SC.ahead = { state: 'queued' }; g.render();
    }, function () { g.SC.ahead = { state: 'failed', reason: 'Could not reach Gadak. Check that Gadak is running.' }; g.render(); });
  }
  /* 저절로 살피기 켜기 · 끄기: 길이 갈리는 순간(방금 정함 · 구간이 바뀜 · 다음 할 일을 물음)마다 살필지. 가닥이 기억해요 */
  function setAheadAuto(on) {
    api('ahead/auto', 'POST', { on: on }).then(function (r) {
      if (!r.ok) { g.flashToast(r.reason || 'Could not change that.'); return; }
      if (S.status && S.status.ahead) S.status.ahead.auto = !!r.auto;
      g.flashToast(r.auto ? 'Gadak now looks ahead by itself whenever the road forks. This uses more of your Claude limit.' : 'Automatic look-ahead is off. Gadak looks only when you press Look ahead in the Ahead tab.');
      g.render();
    }, function () { g.flashToast('Could not change that.'); });
  }
  function saveItem(id, state) { if (!S.demo) api('items/' + encodeURIComponent(id), 'PATCH', { state: state }).catch(function () {}); }

  /* ---------- 승인한 종류의 자동 실행: ‘앞으로는 알아서’를 켜고 꺼요. 실제로 보내는 건 그 도구에 붙인 hook이에요 (README 3-2) ---------- */
  function setAuto(kind, on) {
    api('auto', 'POST', { kind: kind, on: on }).then(function (r) {
      g.SC.auto = r.auto;
      var name = G.KIND[kind].label, site = g.ACT && g.ACT.site, way = r.ways ? r.ways[site] : true;
      if (!on) g.flashToast('Gadak will ask again before sending ‘' + name + '’.');
      else if (way === false) g.flashToast('Turned on. For Gadak to send directly, connect ' + (SITES[site] || site) + ' under Sources.');
      else if (way === undefined) g.flashToast('Turned on. For now Gadak can send directly only in Claude Code and Cursor.');
      else g.flashToast('From now on Gadak sends ‘' + name + '’ right away.');
      g.render();
    }, function () { g.flashToast('Could not change that.'); });
  }

  /* ---------- 데이터 ---------- */
  function openProject(id) { if (id === S.project) return; track('ui', { what: 'open_project' }); S.project = id; S.chat = null; S.reset = true; S.bottom = true; S.keepScope = null; load(); }
  function openChat(id) { if (g.ACT && id === g.ACT.id) return; track('ui', { what: 'open_chat' }); S.chat = id; S.reset = true; S.bottom = !S.goto; S.keepScope = st.scope; load(); }
  function show(SC) {
    g.load(SC, S.reset);
    if (S.reset && S.keepScope) st.scope = S.keepScope;
    if (st.enter || (S.reset && !S.goto)) S.bottom = true;  // 새로 열었거나 새 턴이 오면 맨 아래(지금)로
    S.reset = false; S.keepScope = null;
    g.render();
  }
  function load() {
    if (S.demo) return loadDemo();
    return api('projects').then(function (d) {
      S.projects = d.projects;
      if (S.hiddenCount !== (d.hidden || 0)) { S.hiddenCount = d.hidden || 0; S.hiddenList = null; }
      if (!S.projects.some(function (p) { return p.id === S.project; })) { S.project = S.projects.length ? S.projects[0].id : null; S.chat = null; S.reset = true; }
      if (!S.project) { show({ chats: [] }); return; }
      return api('projects/' + encodeURIComponent(S.project) + '/view' + (S.chat ? '?chat=' + encodeURIComponent(S.chat) : '')).then(function (v) {
        var real = v.project.id !== '_none';  // 프로젝트 · 폴더가 없는 대화는 대화별로만 봐요
        // 노선 색: 전체 지도와 같은 프로젝트 색 (store.project_color). 노선도 카드가 var(--route)로 써요
        R.root.style.setProperty('--route', v.project.color || '');
        show({ project: real ? v.project.name : null, scopeLabel: real && v.chats.length > 1 ? 'Whole project' : null, chats: v.chats, itemStates: v.itemStates, auto: v.auto, ahead: v.ahead });
      });
    });
  }
  function loadDemo() {
    var name = params.get('demo') === 'example' ? 'example_conversations.json' : 'demo_conversations.json';
    var ready = S.demoData ? Promise.resolve(S.demoData) : fetch('data/' + name).then(function (r) { return r.json(); });
    return ready.then(function (d) {
      S.demoData = d;
      var keys = Object.keys(d.scenarios);
      S.projects = keys.map(function (k) { return { id: k, name: d.scenarios[k].name }; });
      if (!d.scenarios[S.project]) S.project = d.scenarios[S.scen] ? S.scen : keys[0];
      var SC = Object.assign({}, d.scenarios[S.project]);
      if (S.chat) SC.chats = SC.chats.map(function (c) { var x = Object.assign({}, c); x.active = c.id === S.chat; return x; });
      show(SC);
    });
  }
  function askClassify(V) {
    if (S.demo || S.off || !S.status || S.status.classify.engine === 'none' || S.status.classify.paused) return;
    var ids = [], now = Date.now();
    g.SC.chats.forEach(function (c) {
      if (!(c.pending || c.checks) || S.asked[c.id] > now - 30000) return;  // 분류할 턴이나 2단이 확인할 턴이 남은 대화
      var seen = c === g.ACT || (st.scope === 'all' && c.turns.some(function (t) { return V.sIdx[t.id] != null && V.isOpen(V.sIdx[t.id]); }));
      if (seen) { ids.push(c.id); S.asked[c.id] = now; }
    });
    if (ids.length) api('classify', 'POST', { chats: ids }).catch(function () {});
  }
  function tick() {
    return api('status').then(function (s) {
      var first = !S.status; S.status = s; S.off = false;
      if (s.rev !== S.rev || first) { S.rev = s.rev; return load(); }
      renderFoot();
    }, function () {
      // 백엔드가 없는 곳(배포 웹 데모)에서는 예시를 보여 줘요
      if (!S.status && !S.demo) { S.demo = true; delete g.hooks.search; delete g.hooks.setAuto; delete g.hooks.handoff; clearInterval(S.timer); S.reset = true; return load(); }
      S.off = true; renderFoot();
    }).catch(function () {});
  }

  /* ---------- 사용 한도 게이지: 1분마다 /limits. 만든 예시에서는 예시 숫자 ---------- */
  /* 게이지는 노선 한 줄이에요: 쓴 만큼 노선 색의 굵은 선, 남은 만큼 가는 회색 선, 지금 자리에 빨간 점, 끝에 종점 고리(풀리는 때).
     이름 앞은 노선 불릿처럼 검은 동그라미에 글자 하나.
     노선 색은 쓰지 않아요: 프로젝트 노선과 헷갈리지 않게 검정(밤에는 흰색) 하나로 (10/11) */
  var LIMITS = { claude: { name: 'Claude', bullet: 'C' }, codex: { name: 'ChatGPT', bullet: 'G' } };
  var WINDOWS = [['five_hour', '5 hours'], ['week', 'Week']];
  function until(iso) {
    var m = Math.round((new Date(iso) - Date.now()) / 60000); if (!(m > 0)) return '';
    return 'Resets in ' + (m < 60 ? m + ' min' : m < 1440 ? Math.round(m / 60) + ' h' : Math.round(m / 1440) + ' d');
  }
  function renderLimits(r) {
    var box = R.limits, grow = !R.limitsShown && !G.reduce; box.innerHTML = ''; var any = false, fills = [];
    Object.keys(LIMITS).forEach(function (k) {
      var v = r && r[k], L = LIMITS[k]; if (!v) return; any = true;
      // stale: 열쇠가 만료돼 새로 못 읽었어요. 마지막 값을 흐리게, ‘몇 시 기준’과 함께 (backend/limits.py)
      var grp = el('div', 'lim' + (v.stale ? ' stale' : '')), at = v.as_of ? new Date(v.as_of) : null;
      var when = at ? (at.toDateString() === new Date().toDateString() ? '' : (at.getMonth() + 1) + '/' + at.getDate() + ' ') + String(at.getHours()).padStart(2, '0') + ':' + String(at.getMinutes()).padStart(2, '0') + '' : '';
      var h = el('div', 'lhead'); h.appendChild(el('span', 'bul', L.bullet)); h.appendChild(el('b', null, L.name)); h.appendChild(el('span', 'lk', v.stale ? (when && 'As of ' + when) : 'Usage limit')); grp.appendChild(h);
      WINDOWS.forEach(function (w) {
        var x = v[w[0]]; if (!x) return;
        var p = Math.max(0, Math.min(100, x.used)), row = el('div', 'lrow');
        row.appendChild(el('span', 'ln', w[1]));
        var rt = el('div', 'lroute'); rt.setAttribute('role', 'meter'); rt.setAttribute('aria-valuemin', '0'); rt.setAttribute('aria-valuemax', '100'); rt.setAttribute('aria-valuenow', String(p));
        rt.setAttribute('aria-label', L.name + ' ' + w[1] + ' limit, ' + Math.round(p) + '% used');
        var f = el('i', 'f'), n = el('i', 'n'); rt.appendChild(f); rt.appendChild(el('i', 'e')); rt.appendChild(n);
        fills.push([f, n, p]); if (!grow) { f.style.setProperty('--p', p); n.style.setProperty('--p', p); }
        row.appendChild(rt); row.appendChild(el('span', 'lp', Math.round(p) + '%'));
        grp.appendChild(row);
        var u = x.resets_at ? until(x.resets_at) : ''; if (u) grp.appendChild(el('div', 'lsub', u));
      });
      if (v.stale) grp.appendChild(el('div', 'lnote', 'Refreshes when you use Claude Code in the terminal'));
      box.appendChild(grp);
    });
    box.hidden = !any;
    // 처음 보일 때만 노선이 왼쪽에서 지금 자리까지 달려가요 (--ease)
    if (any && grow) { R.limitsShown = true; requestAnimationFrame(function () { requestAnimationFrame(function () { fills.forEach(function (q) { q[0].style.setProperty('--p', q[2]); q[1].style.setProperty('--p', q[2]); }); }); }); }
  }
  function loadLimits() {
    if (S.demo) { var soon = function (h) { return new Date(Date.now() + h * 3600000).toISOString(); };
      renderLimits({ claude: params.get('limits') === 'stale' ? { five_hour: { used: 24, resets_at: soon(3.4) }, week: { used: 47, resets_at: soon(98) }, stale: true, as_of: soon(-4.2) } : { five_hour: { used: 24, resets_at: soon(3.4) }, week: { used: 47, resets_at: soon(98) } }, codex: { five_hour: { used: 38, resets_at: soon(2.2) }, week: { used: 61, resets_at: soon(70) } } }); return; }
    api('limits').then(renderLimits).catch(function () { renderLimits(null); });
  }

  /* ---------- 전체 지도: 가닥 창 위에 겹쳐 열어요 (backend/web/map.html). 지도에서 대화를 고르면 닫고 가닥 창에서 그 대화를 열어요 ---------- */
  function openMap() {
    if (R.mapFrame) return;
    R.mapFrame = el('iframe', 'mapframe'); R.mapFrame.src = 'map'; R.mapFrame.setAttribute('aria-label', 'System map');   // title은 지도 위에 툴팁으로 떠요
    document.body.appendChild(R.mapFrame); R.mapFrame.focus();
  }
  function closeMap() { if (R.mapFrame) { R.mapFrame.remove(); R.mapFrame = null; } }
  // 지도 쪽(backend/web/map.html)의 ‘닫기’가 바로 부를 수 있게도 열어 둬요. 메시지가 닿지 않는 경우에도 닫히게요
  window.gadakMapClose = closeMap;
  // 글쇠가 지도 안이 아니라 가닥 창에 있을 때도 Esc로 닫혀요
  // Esc: 먼저 떠 있는 것을 닫고(전체 지도 → 열린 작은 창), 아무것도 없으면 노선도를 접고 펴요. 글 쓰는 칸에서는 그 칸의 일(찾기 비우기)만 해요
  document.addEventListener('keydown', function (e) {
    if (e.key !== 'Escape' || e.defaultPrevented || e.isComposing) return;
    if (R.mapFrame) { e.preventDefault(); closeMap(); return; }
    var pops = [R.src, R.ask, R.ai].filter(function (p) { return p && !p.hidden; });
    if (pops.length) { pops.forEach(function (p) { p.hidden = true; }); return; }
    var t = e.target; if (t && (t.isContentEditable || /^(INPUT|TEXTAREA|SELECT)$/.test(t.tagName))) return;
    e.preventDefault(); g.toggleDrawer();
  });
  window.addEventListener('message', function (e) {
    if (e.origin !== location.origin || !e.data || !R.mapFrame || e.source !== R.mapFrame.contentWindow) return;
    if (e.data.gadakMap === 'close') closeMap();
    if (e.data.gadakOpen) { closeMap(); window.gadakOpen(e.data.gadakOpen); }
  });

  /* 도움말: 가닥을 쓰는 법과 낱말 풀이 (backend/web/help.html). 새 창으로 열어요. 가닥 앱의 메뉴 ‘도움말’도 이것을 불러요 */
  function openHelp() { window.open('help', 'gadak-help'); }
  window.gadakHelp = openHelp;

  /* 가닥 앱의 떠 있는 버튼이 부르는 것 (mac/Float.swift): 그 대화의 그 역을 열기 · 대화 찾기 칸으로 가기 */
  window.gadakOpen = function (h) { if (!S.demo && h && h.chat) openFound({ id: h.chat, project: { id: h.project }, turn: h.turn }); };
  window.gadakFind = function () { R.find.focus(); R.find.select(); };

  mount();
  g.load({ chats: [] }, true);
  g.render();
  window.addEventListener('resize', function () { requestAnimationFrame(function () { g.render(); }); });
  // 주소에 ?find=찾는 말 을 붙이면 그 말로 찾은 채로 열려요
  function startFind() { var q = (params.get('find') || '').trim(); if (q) { R.find.value = q; setFind(q); } }
  loadLimits(); setInterval(loadLimits, 60000);
  if (S.demo) load().then(function () { g.reveal(); startFind(); });
  else { S.timer = setInterval(tick, POLL); tick().then(function () {
    g.reveal();
    if (params.get('panel') === 'sources') toggleSources();
    else if (params.get('panel') === 'ai') openAi();
    else if (!S.demo) api('engine').then(function (d) {      // 바로 쓸 수 있는 AI가 하나도 없으면 연결부터 보여 줘요
      if (!d.options.some(function (o) { return o.ready; })) { S.engine = d; renderAi(); R.src.hidden = true; R.ask.hidden = true; renderFoot(); above(R.ai); R.ai.hidden = false; }
    }, function () {});
    loadUsage(); startFind();
  }); }
})();
