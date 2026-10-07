/* 가닥 창(로컬 웹 페이지). shared/ui의 노선도 카드 · 목록 · 한마디를 그대로 쓰고,
   여기에는 이 입구만의 것(프로젝트 · 대화 목록, 읽기 전용 대화, 찾은 곳, 백엔드와 주고받기)만 있어요.
   주소에 ?demo 를 붙이거나 백엔드 없이 열면 미리 정리해 둔 예시(data/demo_conversations.json)를 보여 줘요. */
(function () {
  'use strict';
  var G = window.Gadak, el = G.el, fname = G.fname;
  var params = new URLSearchParams(location.search);
  var S = { demo: params.has('demo'), scen: params.get('scen'), projects: [], project: null, chat: null, reset: true,
    rev: -1, status: null, asked: {}, full: {}, bottom: true, goto: null, sources: null, off: false, usage: null,
    findQ: '', found: null, hiddenCount: 0, hiddenOpen: false, hiddenList: null };
  var POLL = 1500, FILES_SHOWN = 8;
  var SITES = { 'claude-code': 'Claude Code', codex: 'Codex', cursor: 'Cursor', chatgpt: 'ChatGPT', claude: 'Claude', gemini: 'Gemini' };
  // 가닥 창은 시스템 설정(밝게 · 어둡게)을 따라가요. 주소에 ?theme=light · dark 를 붙이면 고정돼요
  if (/^(light|dark)$/.test(params.get('theme') || '')) document.documentElement.dataset.theme = params.get('theme');

  var g = G.create({
    render: render, go: go, goPart: goPart, itemState: saveItem, insert: copyOut, insertLabel: '복사하기',
    nudgeClass: 'nudge-web', statusBits: statusBits, track: track, setAuto: setAuto, handoff: handoff,
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
  function mount() {
    var shell = document.getElementById('shell'); shell.innerHTML = ''; R.root = shell;
    // 맨 위 검은 머리띠: 전체 지도와 같은 지하철 표지판 띠 (심볼 · 가닥 · 전체 지도)
    var brand = el('header', 'brand band'), logo = el('button', 'logo'); shell.appendChild(brand);
    var site = el('div', 'site'); shell.appendChild(site);
    var bar = el('aside', 'sitebar'); site.appendChild(bar); logo.type = 'button'; logo.setAttribute('aria-label', '가닥 심볼 다시 재생');
    var mark = G.makeMark(26, 10); logo.appendChild(mark.svg); logo.appendChild(el('b', null, '가닥')); logo.onclick = function () { G.playMark(mark); };
    brand.appendChild(logo);
    // 전체 지도: 모든 프로젝트 · 대화를 시간 순서 노선으로 한눈에 (backend/web/map.html). 심볼 옆, 늘 보이는 자리에
    var map = el('button', 'btn sm mapbtn', '전체 지도'); map.type = 'button'; map.onclick = openMap; brand.appendChild(map);
    var fw = el('div', 'findwrap'); R.find = el('input', 'qin'); R.find.type = 'search'; R.find.placeholder = '대화 찾기';
    R.find.setAttribute('aria-label', '모든 대화에서 찾기');
    R.find.addEventListener('input', function () { setFind(R.find.value.trim()); });
    R.find.addEventListener('keydown', function (e) { if (e.key === 'Escape') { R.find.value = ''; setFind(''); } });
    fw.appendChild(R.find); bar.appendChild(fw);
    R.lists = el('div', 'lists'); bar.appendChild(R.lists);
    R.foot = el('div', 'foot'); bar.appendChild(R.foot);
    // 가운데: 왼쪽에 노선도 카드와 그 아래 대화, 오른쪽에 목록(할 일 · 정한 것 · 산출물 · 앞길)을 카드와 떼어 위에서 아래까지.
    // 대화 옆 세로 레일은 위의 노선도와 겹쳐서 가닥 창에서는 그리지 않아요 (10/7 · 구현 담당. shared/ui/rail.js는 대화가 화면에 있는 다른 입구용으로 남아 있어요)
    var main = el('div', 'sitemain'); site.appendChild(main);
    var col = el('div', 'maincol'); main.appendChild(col);
    R.unfold = el('button', 'unfold', '노선도 펼치기'); R.unfold.type = 'button'; R.unfold.hidden = true; R.unfold.onclick = function () { g.toggleDrawer(); }; col.appendChild(R.unfold);
    g.mountDrawer(col, null, true);
    var cw = el('div', 'chatwrap'); col.appendChild(cw);
    R.chat = el('div', 'chat'); R.thread = el('div', 'thread'); R.chat.appendChild(R.thread); cw.appendChild(R.chat);
    R.nudgeHost = cw;
    R.sideCol = el('aside', 'sidecol'); R.sideCol.setAttribute('aria-label', '할 일 · 정한 것 · 산출물 · 앞길'); main.appendChild(R.sideCol);
    g.mountSide(R.sideCol, true);
    R.chat.addEventListener('scroll', onChatScroll);
    R.toastEl = el('div', 'toast'); R.toastEl.hidden = true; shell.appendChild(R.toastEl);
    R.src = el('div', 'pop srcpop'); R.src.hidden = true; document.body.appendChild(R.src);
    R.ask = el('div', 'pop srcpop'); R.ask.hidden = true; R.ask.setAttribute('role', 'dialog'); document.body.appendChild(R.ask);
    R.file = el('input'); R.file.type = 'file'; R.file.accept = '.zip,.json'; R.file.hidden = true; R.file.onchange = importFile; shell.appendChild(R.file);
    document.addEventListener('click', function (e) { if (!R.src.hidden && !R.src.contains(e.target) && !(R.srcBtn && R.srcBtn.contains(e.target))) R.src.hidden = true; });
    setTimeout(function () { G.playMark(mark); }, 250);
  }

  /* ---------- 그리기 ---------- */
  function render() {
    var keep = R.chat.scrollTop;
    renderLists();
    renderThread();
    R.chat.scrollTop = S.bottom ? R.chat.scrollHeight : keep; S.bottom = false;
    var V = g.buildView(st.scope);
    R.drawer.hidden = !st.drawerOpen; R.unfold.hidden = st.drawerOpen;
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
        var x = el('button', 'cx', '×'); x.type = 'button'; x.title = '이 프로젝트의 대화를 모두 목록에서 빼기'; x.setAttribute('aria-label', x.title);
        x.onclick = function () { hideProject(p); }; row.appendChild(x);
        p.list.forEach(function (c) {
          R.citems[c.id] = citem(host, c.title || '(제목 없음)', c.date, !!g.ACT && c.id === g.ACT.id, function () { S.project = p.id; openChat(c.id); },
            { title: '이 대화를 목록에서 빼기', run: function () { hideChats([c.id], '대화를 목록에서 뺐어요.'); } });
        });
      });
      renderHidden(host); host.scrollTop = keep; return;
    }
    host.innerHTML = ''; R.citems = {};
    if (g.SC.chats.length) {
      var head = el('h6', null, g.SC.project ? '프로젝트 · ' + g.SC.project : '최근 대화'); host.appendChild(head);
      var mine = S.projects.filter(function (p) { return p.id === S.project; })[0];
      if (g.SC.project && mine && mine.color) head.prepend(pdot(mine.color));
      g.SC.chats.slice().reverse().forEach(function (c) {
        R.citems[c.id] = citem(host, c.title, c.date, c === g.ACT, function () { openChat(c.id); },
          { title: '이 대화를 목록에서 빼기', run: function () { hideChats([c.id], '대화를 목록에서 뺐어요.'); } });
      });
    }
    var others = S.projects.filter(function (p) { return p.id !== S.project; });
    if (others.length) {
      host.appendChild(el('h6', null, S.demo ? '다른 예시' : '다른 프로젝트'));
      others.forEach(function (p) {
        var d = citem(host, p.name, S.demo ? '' : String(p.chats), false, function () { openProject(p.id); },
          { title: '이 프로젝트의 대화를 모두 목록에서 빼기', run: function () { hideProject(p); } });
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
    g.flashToast(msg, { label: '되돌리기', run: function () { restore(r.ids); } });
    if (g.ACT && r.ids.indexOf(g.ACT.id) >= 0) { S.chat = null; S.reset = true; S.bottom = true; }
    load();
  }
  function hideChats(ids, msg) { api('chats/hidden', 'POST', { ids: ids, hidden: true }).then(function (r) { afterHiding(r, msg); }); }
  function hideProject(p) {
    api('projects/' + encodeURIComponent(p.id) + '/hide', 'POST').then(function (r) { afterHiding(r, '‘' + p.name + '’의 대화 ' + r.ids.length + '개를 목록에서 뺐어요.'); });
  }
  function restore(ids) {
    api('chats/hidden', 'POST', { ids: ids, hidden: false }).then(function (r) {
      S.hiddenList = null; if (!r.hidden) S.hiddenOpen = false;
      g.flashToast('대화 ' + r.ids.length + '개를 목록으로 되돌렸어요.');
      load();
    });
  }
  function renderHidden(host) {
    if (S.demo || !S.hiddenCount) return;
    var head = el('button', 'hhead', '뺀 대화 ' + S.hiddenCount + '개 · ' + (S.hiddenOpen ? '접기' : '보기')); head.type = 'button';
    head.onclick = function () { S.hiddenOpen = !S.hiddenOpen; renderLists(); };
    host.appendChild(head);
    if (!S.hiddenOpen) return;
    if (!S.hiddenList) { api('chats/hidden').then(function (d) { S.hiddenList = d.chats; renderLists(); }); return; }
    S.hiddenList.forEach(function (c) {
      var b = el('button', 'fitem'); b.type = 'button'; b.title = '누르면 목록으로 되돌려요';
      var t = el('span', 't'); t.appendChild(el('span', null, c.title)); t.appendChild(el('small', null, '되돌리기')); b.appendChild(t);
      b.appendChild(el('span', 'w', (c.project.id === '_none' ? '' : c.project.name + ' · ') + (SITES[c.site] || c.site) + ' · ' + c.date));
      b.onclick = function () { restore([c.id]); };
      host.appendChild(b);
    });
    if (S.hiddenList.length > 1) {
      var all = el('button', 'linkbtn hall', '모두 되돌리기'); all.type = 'button';
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
    host.appendChild(el('h6', null, hits ? '찾은 대화 ' + hits.length + '개' : '찾는 중이에요…'));
    if (hits && !hits.length) { host.appendChild(el('div', 'lempty', '찾은 대화가 없어요.')); return; }
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
      var e = el('div', 'empty-chat'); e.appendChild(el('b', null, '아직 잡힌 가닥이 없어요.'));
      e.appendChild(el('span', null, S.demo ? '대화를 시작하면 여기에 흐름이 그려져요.' : 'Claude Code · Codex · Cursor로 대화하면 여기에 흐름이 그려져요. 웹과 앱의 대화는 ‘찾은 곳’에서 이어요.'));
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
  // 제목 줄 = 역. 왼쪽에 프로젝트 색 노선을 세로로 긋고(레일과 같은 문법), 누르면 그 구획을 접어요
  function fillAnswer(box, text) {
    var blocks = answerBlocks(text);
    box.innerHTML = ''; box.classList.toggle('blocks', !!blocks);
    if (!blocks) { box.appendChild(richText(text)); return; }
    blocks.forEach(function (b) {
      var s = el('div', 'blk' + (b.h ? ' blk-st' : ''));
      if (b.h) {
        var h = inline(el('button', 'blk-h'), b.h); h.type = 'button'; h.setAttribute('aria-expanded', 'true');
        h.onclick = function () { var shut = s.classList.toggle('shut'); h.setAttribute('aria-expanded', String(!shut)); };
        s.appendChild(h);
      }
      if (b.body) s.appendChild(richText(b.body));
      box.appendChild(s);
    });
  }
  function chatTurn(t) {
    var w = el('div', 'turn'); w.dataset.id = t.id;
    var u = el('div', 'u');
    if (t.depth > 0) u.appendChild(el('span', 'tag', t.depth + '차 곁길'));
    if (t.ref && g.byId[t.ref]) u.appendChild(el('span', 'tag', '↩ ' + g.numLabel(g.byId[t.ref])));
    if (t.parts) u.appendChild(el('span', 'tag', '요청 ' + t.parts.length + '개'));
    var full = S.full[t.id] || t;  // 화면에는 앞부분만 와요. ‘전체 보기’로 받아 둔 원문이 있으면 그것을
    var up = el('p', null, full.user); u.appendChild(up); w.appendChild(u);
    var a = el('div', 'a'), para = el('div', 'part'); fillAnswer(para, full.ai); a.appendChild(para);
    if (t.parts) R.partEls[t.id + ':0'] = para;
    if (t.long && full === t) {
      var more = el('button', 'linkbtn more', '전체 보기'); more.type = 'button';
      more.onclick = function () { track('ui', { what: 'full_text' }); api('turns/' + encodeURIComponent(t.id)).then(function (d) { S.full[t.id] = d.turn; up.textContent = d.turn.user; fillAnswer(para, d.turn.ai); more.remove(); g.renderRail(); }); };
      a.appendChild(more);
    }
    if (t.files) {
      var fs = el('div', 'files');
      t.files.slice(0, FILES_SHOWN).forEach(function (f) { var x = el('span', 'file'); x.appendChild(el('span', 'sq')); x.appendChild(document.createTextNode(fname(f))); fs.appendChild(x); });
      if (t.files.length > FILES_SHOWN) fs.appendChild(el('span', 'file rest', '외 ' + (t.files.length - FILES_SHOWN) + '개'));
      a.appendChild(fs);
    }
    w.appendChild(a); return w;
  }

  function statusBits() {
    if (S.demo || !S.status || S.status.classify.engine === 'none') return [];
    var left = st.scope === 'all' ? g.SC.chats.reduce(function (n, c) { return n + (c.pending || 0); }, 0) : (g.ACT.pending || 0);
    if (!left) return [];
    return [(S.status.classify.paused ? '정리 멈춤' : '정리 중') + ' · 남은 턴 ' + left + '개'];
  }
  function renderFoot() {
    var f = R.foot; f.innerHTML = '';
    var s = S.status, text = '', hot = false;
    if (S.demo) text = '미리 정리해 둔 예시예요. 실제 대화가 아니에요.';
    else if (S.off) { text = '가닥이 꺼져 있어요. 다시 켜면 이어서 보여 줘요.'; hot = true; }
    else if (!s) text = '준비 중이에요…';
    else if (s.sync.phase === 'scan') text = '지난 대화를 읽는 중 · ' + s.sync.done + '/' + s.sync.total;
    else if (s.classify.error) { text = s.classify.error; hot = true; }
    else if (s.classify.engine === 'none') text = '정리 엔진이 없어서 제목이 임시예요. docs/usage-guide.md 3번을 봐 주세요.';
    else if (s.classify.running) text = '보는 대화부터 정리하고 있어요 · 호출 ' + s.classify.calls + '번';
    else if (s.classify.checking) text = '놓친 일이 있는지 확인하고 있어요 · 호출 ' + s.classify.calls + '번';
    else text = '켜 두면 새 대화를 알아서 읽어요' + (s.classify.calls ? ' · 정리 호출 ' + s.classify.calls + '번' : '');
    f.appendChild(el('div', 'state' + (hot ? ' hot' : ''), text));
    if (S.demo) return;
    var row = el('div', 'row');
    R.srcBtn = el('button', 'btn sm', '찾은 곳'); R.srcBtn.type = 'button'; R.srcBtn.onclick = toggleSources; row.appendChild(R.srcBtn);
    if (s && s.classify.paused) { var again = el('button', 'btn sm', '정리 다시'); again.type = 'button'; again.onclick = function () { api('classify', 'POST', { pause: false }).then(tick); }; row.appendChild(again); }
    // 2단이 어떤 도구로 무엇을 보고 결론 냈는지는 노선도 카드에 넣지 않고 별도 페이지에서 봐요 (README 3-1)
    var log = el('button', 'btn sm', '판단 기록'); log.type = 'button'; log.onclick = function () { track('ui', { what: 'trace' }); window.open('trace', '_blank'); }; row.appendChild(log);
    var help = el('button', 'btn sm', '도움말'); help.type = 'button'; help.onclick = openHelp; row.appendChild(help);
    var quit = el('button', 'btn sm', '끄기'); quit.type = 'button'; quit.onclick = quitApp; row.appendChild(quit);
    f.appendChild(row);
  }

  /* ---------- 찾은 곳: 무엇으로 LLM을 쓰는지, 어떻게 읽는지 ---------- */
  function toggleSources() {
    if (!R.src.hidden) { R.src.hidden = true; return; }
    track('ui', { what: 'sources' });
    R.ask.hidden = true;   // 같은 자리에 떠요. 보내기는 찾은 곳 안에서도 고를 수 있어요
    // 먼저 켜 둔 예전 가닥에 붙어 있으면 사용 기록 쪽은 없을 수 있어요. 없으면 그 줄만 빼고 보여 줘요
    Promise.all([api('sources'), api('usage/state').catch(function () { return null; })]).then(function (d) { S.sources = d[0].sources; S.usage = d[1]; renderSources(); R.src.hidden = false; });
  }
  function renderSources() {
    var p = R.src; p.innerHTML = '';
    p.appendChild(el('b', null, '찾은 곳'));
    p.appendChild(el('div', 'note', '이 PC에서 찾은 LLM 사용 기록이에요. 읽은 대화는 이 PC에만 저장하고, 정리할 때만 그 턴이 Claude로 가요.'));
    S.sources.forEach(function (s) {
      var d = el('div', 'src'), k, w = '', btn = null;
      if (s.mode === 'auto') {
        k = s.found ? '알아서 읽는 중 · 대화 ' + s.chats + '개' : '기록을 찾지 못했어요';
        w = s.where + (s.found ? ' · 기록 파일 ' + s.files + '개' : '');
        if (s.key === 'claude-code' && s.found) {
          // ‘앞으로는 알아서’를 켠 것을 가닥이 직접 보내려면 Claude Code 설정에 hook 둘을 더해야 해요. 눌렀을 때만 고쳐요
          w += s.hooks ? ' · 가닥이 직접 보낼 수 있어요(자동 실행 연결됨)' : ' · ‘앞으로는 알아서’를 켠 것을 가닥이 직접 보내려면 연결해요. Claude Code 설정에 hook 둘을 더해요';
          btn = el('button', 'btn sm' + (s.hooks ? '' : ' primary'), s.hooks ? '자동 실행 끊기' : '자동 실행 연결'); btn.onclick = function () {
            api('sources/claude-code/' + (s.hooks ? 'disconnect' : 'connect'), 'POST').then(function (r) {
              g.flashToast(!r.ok ? r.reason : (s.hooks ? 'Claude Code에서 가닥 hook을 뗐어요.' : '연결했어요. 새로 여는 Claude Code 대화부터 가닥이 직접 보낼 수 있어요.'));
              return api('sources'); }).then(function (x) { S.sources = x.sources; renderSources(); }); };
        }
      } else if (s.mode === 'connect') {
        k = s.connected ? '연결됨 · 대화 ' + s.chats + '개' : (s.found ? '한 번 연결하면 그 뒤로 알아서 읽어요' : '설치된 것을 찾지 못했어요');
        w = s.connected ? s.where + ' · 새 대화부터 읽어요' : s.where + ' · 연결하면 Cursor의 hooks.json에 가닥을 더해요';
        if (s.found && !s.connected) { btn = el('button', 'btn sm primary', '연결'); btn.onclick = function () {
          api('sources/cursor/connect', 'POST').then(function (r) { g.flashToast(r.ok ? 'Cursor를 연결했어요. 새 대화부터 읽어요.' : r.reason); return api('sources'); }).then(function (x) { S.sources = x.sources; renderSources(); }); }; }
      } else if (s.mode === 'extension') {
        k = s.connected ? '연결됨 · 대화 ' + s.chats + '개' : '크롬 확장을 넣으면 그 뒤로 알아서 읽어요';
        w = s.connected ? s.where + ' · 크롬에서 연 대화를 알아서 읽어요 · 마지막 연결 ' + s.seen
          : s.where + ' · 크롬 주소창에 chrome://extensions → 개발자 모드 켜기 → ‘압축해제된 확장 프로그램을 로드합니다’에서 가닥의 extension 폴더를 골라요.';
        if (!s.connected) { btn = el('button', 'btn sm primary', '폴더 경로 복사'); btn.onclick = function () {
          G.copy(s.folder).then(function () { g.flashToast('복사했어요. 폴더 고르는 창에서 ⌘⇧G를 누르고 붙여 넣으면 돼요.'); }); }; }
      } else {
        k = '파일로 불러와요' + (s.chats ? ' · 대화 ' + s.chats + '개' : '');
        w = '한 번도 열지 않은 지난 대화를 한꺼번에 넣을 때, 데스크톱 앱의 대화를 넣을 때 써요. 각 서비스의 설정 → 데이터 내보내기로 받은 파일(zip · json)을 넣어 주세요.';
        btn = el('button', 'btn sm primary', '파일 고르기'); btn.onclick = function () { R.file.value = ''; R.file.click(); };
      }
      d.appendChild(el('span', 'k' + ((s.mode === 'auto' && s.found) || s.connected ? ' on' : ''), k));
      d.appendChild(el('span', 't', s.name)); d.appendChild(el('span', 'w', w));
      if (btn) { btn.type = 'button'; d.appendChild(btn); }
      p.appendChild(d);
    });
    if (S.usage && S.usage.configured) p.appendChild(usageBlock());
  }

  /* ---------- 사용 기록 보내기: 처음 한 번 묻고, 찾은 곳에서 바꿔요 (README 5장) ---------- */
  var USAGE_NOTE = '어떤 기능을 얼마나 쓰는지 같은 사용 기록을 가닥 팀 서버로 보내요. 대화 글 · 제목 · 파일 이름은 보내지 않아요.';
  function button(label, cls, click) { var b = el('button', 'btn sm' + (cls ? ' ' + cls : ''), label); b.type = 'button'; b.onclick = click; return b; }
  function loadUsage() {
    if (S.demo) return;
    api('usage/state').then(function (u) { S.usage = u; if (u.configured && !u.share) askUsage(); }, function () {});
  }
  function askUsage() {
    var p = R.ask; p.innerHTML = ''; p.hidden = false;
    p.appendChild(el('b', null, '가닥을 더 좋게 만드는 데 참여할까요?'));
    p.appendChild(el('div', 'note', USAGE_NOTE + ' 언제든 ‘찾은 곳’에서 끄고, 보낸 기록을 지울 수 있어요.'));
    var seen = el('div'); p.appendChild(seen);
    var row = el('div', 'row');
    row.appendChild(button('보내는 것 보기', '', function () { showUsage(seen); }));
    row.appendChild(button('안 보내기', '', function () { setShare(false); }));
    row.appendChild(button('보내기', 'primary', function () { setShare(true); }));
    p.appendChild(row);
  }
  function setShare(on) {
    api('usage/consent', 'POST', { share: on }).then(function (u) {
      S.usage = u; R.ask.hidden = true;
      g.flashToast(on ? '고마워요. 사용 기록을 보낼게요.' : '사용 기록을 보내지 않을게요.');
      if (!R.src.hidden) renderSources();
    });
  }
  function showUsage(host) {
    api('usage/recent').then(function (d) {
      host.innerHTML = '';
      host.appendChild(el('div', 'note', '이 PC에 적혀 있는 기록이에요. 보낸다면 이 모양 그대로 가요.'));
      host.appendChild(el('pre', 'sent', d.events.length ? d.events.map(function (e) { return e.day + '  ' + e.name + '  ' + JSON.stringify(e.fields); }).join('\n') : '아직 적힌 기록이 없어요.'));
    });
  }
  function usageBlock() {
    var u = S.usage, on = u.share === 'yes', d = el('div', 'src');
    var failing = on && u.error;   // 서버에 닿지 못했어요. 기록은 PC에 남아 있다가 다음 차례에 다시 가요
    d.appendChild(el('span', 'k' + (on && !failing ? ' on' : ''), failing ? '보내지 못하고 있어요 · 다음에 다시 보내요' : (on ? '보내는 중 · 보낸 기록 ' + u.sent + '개' : '보내지 않아요')));
    d.appendChild(el('span', 't', '사용 기록 보내기'));
    d.appendChild(el('span', 'w', USAGE_NOTE));
    var seen = el('div'), row = el('div', 'row');
    row.appendChild(button(on ? '끄기' : '켜기', on ? '' : 'primary', function () { setShare(!on); }));
    row.appendChild(button('보내는 것 보기', '', function () { showUsage(seen); }));
    if (u.sent) row.appendChild(button('서버에서 지우기', '', function () {
      api('usage/consent', 'POST', { forget: true }).then(function (x) {
        S.usage = x; renderSources();
        g.flashToast(x.deleted == null ? '서버에 닿지 못했어요. 보내기는 꺼 뒀어요.' : '서버에 있던 기록 ' + x.deleted + '개를 지웠어요.');
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
      .then(function (d) { R.src.hidden = true; g.flashToast(d.error ? d.error : '대화 ' + d.chats + '개를 한 가닥으로 이었어요.'); tick(); }, function () { g.flashToast('파일을 읽지 못했어요.'); });
  }
  function quitApp() {
    api('quit', 'POST').then(function () {
      clearInterval(S.timer);
      var o = el('div', 'gone'); o.appendChild(el('b', null, '가닥을 껐어요.')); o.appendChild(el('span', null, '이 창은 닫아도 돼요. 다시 켜면 이어서 보여 줘요.')); R.root.appendChild(o);
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
    var ok = function () { g.flashToast('복사했어요. 대화 창에 붙여 넣으면 돼요.'); done(); };
    track('ui', { what: 'copy' });
    G.copy(text).then(ok);
  }
  function handoff() {
    if (!g.ACT) return;
    g.flashToast('다음 대화에 붙일 요약을 쓰고 있어요…');
    api('chats/' + encodeURIComponent(g.ACT.id) + '/handoff').then(function (r) {
      if (!r.text) { g.flashToast('아직 정한 것도 남은 일도 없어요.'); return; }
      track('ui', { what: 'copy' });
      G.copy(r.text).then(function () { g.flashToast('다음 대화에 붙일 요약을 복사했어요.'); });
    }, function () { g.flashToast('요약을 만들지 못했어요.'); });
  }
  /* 앞길 보기: 이 대화의 마지막 턴에 서서 갈 수 있는 길을 찾아 달라고 해요. 엔진이 뒤에서 돌고, 어디까지 갔는지와 찾은 길은 목록의 ‘앞길’ 칸에 나타나요
     (기다리는 중 · 살피는 중 · 길 n개 · 낼 길이 없었음 · 못 살핀 까닭). 상태가 바뀌면 백엔드가 알려서(rev) 다시 받아 와요 */
  function ahead() {
    if (!g.ACT || !g.ACT.id) { g.flashToast('먼저 대화를 골라 주세요.'); return; }
    st.sideTab = 'ahead'; st.ledgerOpen = true;
    api('chats/' + encodeURIComponent(g.ACT.id) + '/ahead', 'POST').then(function (r) {
      if (!r.ok) { g.SC.ahead = { state: 'failed', reason: r.reason }; g.render(); return; }
      g.SC.ahead = { state: 'queued' }; g.render();
    }, function () { g.SC.ahead = { state: 'failed', reason: '가닥에 닿지 못했어요. 가닥이 켜져 있는지 봐 주세요.' }; g.render(); });
  }
  /* 저절로 살피기 켜기 · 끄기: 길이 갈리는 순간(방금 정함 · 구간이 바뀜 · 다음 할 일을 물음)마다 살필지. 가닥이 기억해요 */
  function setAheadAuto(on) {
    api('ahead/auto', 'POST', { on: on }).then(function (r) {
      if (!r.ok) { g.flashToast(r.reason || '바꾸지 못했어요.'); return; }
      if (S.status && S.status.ahead) S.status.ahead.auto = !!r.auto;
      g.flashToast(r.auto ? '이제 길이 갈리는 순간마다 앞길을 저절로 살펴요. Claude 사용 한도를 더 써요.' : '저절로 살피기를 껐어요. ‘앞길’ 칸의 ‘앞길 보기’를 누를 때만 살펴요.');
      g.render();
    }, function () { g.flashToast('바꾸지 못했어요.'); });
  }
  function saveItem(id, state) { if (!S.demo) api('items/' + encodeURIComponent(id), 'PATCH', { state: state }).catch(function () {}); }

  /* ---------- 승인한 종류의 자동 실행: ‘앞으로는 알아서’를 켜고 꺼요. 실제로 보내는 건 그 도구에 붙인 hook이에요 (README 3-2) ---------- */
  function setAuto(kind, on) {
    api('auto', 'POST', { kind: kind, on: on }).then(function (r) {
      g.SC.auto = r.auto;
      var name = G.KIND[kind].label, site = g.ACT && g.ACT.site, way = r.ways ? r.ways[site] : true;
      if (!on) g.flashToast('‘' + name + '’은 다시 물어보고 보낼게요.');
      else if (way === false) g.flashToast('켰어요. 가닥이 직접 보내려면 ‘찾은 곳’에서 ' + (SITES[site] || site) + '를 연결해 주세요.');
      else if (way === undefined) g.flashToast('켰어요. 가닥이 직접 보낼 수 있는 곳은 지금 Claude Code와 Cursor예요.');
      else g.flashToast('다음부터 ‘' + name + '’은 가닥이 바로 보내요.');
      g.render();
    }, function () { g.flashToast('바꾸지 못했어요.'); });
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
        show({ project: real ? v.project.name : null, scopeLabel: real && v.chats.length > 1 ? '프로젝트 전체' : null, chats: v.chats, itemStates: v.itemStates, auto: v.auto, ahead: v.ahead });
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

  /* ---------- 전체 지도: 가닥 창 위에 겹쳐 열어요 (backend/web/map.html). 지도에서 대화를 고르면 닫고 가닥 창에서 그 대화를 열어요 ---------- */
  function openMap() {
    if (R.mapFrame) return;
    R.mapFrame = el('iframe', 'mapframe'); R.mapFrame.src = 'map'; R.mapFrame.title = '전체 지도';
    document.body.appendChild(R.mapFrame); R.mapFrame.focus();
  }
  function closeMap() { if (R.mapFrame) { R.mapFrame.remove(); R.mapFrame = null; } }
  // 지도 쪽(backend/web/map.html)의 ‘닫기’가 바로 부를 수 있게도 열어 둬요. 메시지가 닿지 않는 경우에도 닫히게요
  window.gadakMapClose = closeMap;
  // 글쇠가 지도 안이 아니라 가닥 창에 있을 때도 Esc로 닫혀요
  document.addEventListener('keydown', function (e) { if (e.key === 'Escape' && R.mapFrame) { e.preventDefault(); closeMap(); } });
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
  if (S.demo) load().then(function () { g.reveal(); startFind(); });
  else { S.timer = setInterval(tick, POLL); tick().then(function () { g.reveal(); loadUsage(); if (params.get('panel') === 'sources') toggleSources(); startFind(); }); }
})();
