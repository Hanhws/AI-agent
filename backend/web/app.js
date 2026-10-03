/* 가닥 창(로컬 웹 페이지). shared/ui의 노선도 카드 · 레일 · 목록 · 한마디를 그대로 쓰고,
   여기에는 이 입구만의 것(프로젝트 · 대화 목록, 읽기 전용 대화, 찾은 곳, 백엔드와 주고받기)만 있어요.
   주소에 ?demo 를 붙이거나 백엔드 없이 열면 미리 정리해 둔 예시(data/demo_conversations.json)를 보여 줘요. */
(function () {
  'use strict';
  var G = window.Gadak, el = G.el, fname = G.fname;
  var params = new URLSearchParams(location.search);
  var S = { demo: params.has('demo'), scen: params.get('scen'), projects: [], project: null, chat: null, reset: true,
    rev: -1, status: null, asked: {}, full: {}, bottom: true, goto: null, sources: null, off: false };
  var POLL = 1500, FILES_SHOWN = 8;
  // 가닥 창은 시스템 설정(밝게 · 어둡게)을 따라가요. 주소에 ?theme=light · dark 를 붙이면 고정돼요
  if (/^(light|dark)$/.test(params.get('theme') || '')) document.documentElement.dataset.theme = params.get('theme');

  var g = G.create({
    render: render, go: go, goPart: goPart, itemState: saveItem, insert: copyOut, insertLabel: '복사하기',
    nudgeClass: 'nudge-web', statusBits: statusBits,
    // 화면에는 글의 앞부분만 실려 있어서, 찾기는 원문을 가진 백엔드에 맡겨요
    search: function (q) { return api('projects/' + encodeURIComponent(S.project) + '/search?q=' + encodeURIComponent(q)).then(function (d) { return d.hits; }); }
  });
  if (S.demo) delete g.hooks.search;  // 예시는 화면에 실린 글에서 바로 찾아요
  var st = g.st, R = g.R;

  function api(path, method, body) {
    var opt = method ? { method: method, headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body || {}) } : undefined;
    return fetch(path, opt).then(function (r) { if (!r.ok && r.status !== 409) throw new Error(String(r.status)); return r.json(); });
  }

  /* ---------- 틀 ---------- */
  function mount() {
    var shell = document.getElementById('shell'); shell.innerHTML = ''; R.root = shell;
    var site = el('div', 'site'); shell.appendChild(site);
    var bar = el('aside', 'sitebar'); site.appendChild(bar);
    var brand = el('div', 'brand'), logo = el('button', 'logo'); logo.type = 'button'; logo.setAttribute('aria-label', '가닥 심볼 다시 재생');
    var mark = G.makeMark(26, 10); logo.appendChild(mark.svg); logo.appendChild(el('b', null, '가닥')); logo.onclick = function () { G.playMark(mark); };
    brand.appendChild(logo); bar.appendChild(brand);
    R.lists = el('div', 'lists'); bar.appendChild(R.lists);
    R.foot = el('div', 'foot'); bar.appendChild(R.foot);
    var main = el('div', 'sitemain'); site.appendChild(main);
    g.mountDrawer(main);
    var cw = el('div', 'chatwrap'); main.appendChild(cw);
    R.chat = el('div', 'chat'); R.thread = el('div', 'thread'); R.chat.appendChild(R.thread); cw.appendChild(R.chat);
    R.rail = el('nav', 'rail'); R.rail.setAttribute('aria-label', '가닥 레일'); cw.appendChild(R.rail);
    R.nudgeHost = cw;
    R.chat.addEventListener('scroll', onChatScroll);
    R.toastEl = el('div', 'toast'); R.toastEl.hidden = true; shell.appendChild(R.toastEl);
    R.src = el('div', 'pop srcpop'); R.src.hidden = true; document.body.appendChild(R.src);
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
    R.drawer.hidden = !st.drawerOpen;
    if (st.drawerOpen) { g.renderMapHead(V); g.renderSide(); g.renderMap(V); }
    g.renderRail();
    g.renderNudge();
    updateViewing(true);
    renderFoot();
    if (S.goto && R.turnEls[S.goto]) { scrollToEl(R.turnEls[S.goto]); S.goto = null; }
    askClassify(V);
  }

  function citem(host, title, small, on, click) {
    var d = el('button', 'citem' + (on ? ' on' : '')); d.type = 'button'; d.title = title;
    d.appendChild(el('span', null, title)); if (small) d.appendChild(el('small', null, small));
    d.onclick = click; host.appendChild(d); return d;
  }
  function renderLists() {
    var host = R.lists, keep = host.scrollTop; host.innerHTML = ''; R.citems = {};
    if (g.SC.chats.length) {
      host.appendChild(el('h6', null, g.SC.project ? '프로젝트 · ' + g.SC.project : '최근 대화'));
      g.SC.chats.slice().reverse().forEach(function (c) {
        R.citems[c.id] = citem(host, c.title, c.date, c === g.ACT, function () { openChat(c.id); });
      });
    }
    var others = S.projects.filter(function (p) { return p.id !== S.project; });
    if (others.length) {
      host.appendChild(el('h6', null, S.demo ? '다른 예시' : '다른 프로젝트'));
      others.forEach(function (p) { citem(host, p.name, S.demo ? '' : String(p.chats), false, function () { openProject(p.id); }); });
    }
    host.scrollTop = keep;
  }

  /* 그 대화의 글. 가닥은 대답하지 않아요: 읽기만 하고 입력창은 없어요 */
  function renderThread() {
    R.thread.innerHTML = ''; R.turnEls = {}; R.partEls = {};
    var ts = g.activeTurns(), V = g.buildView('chat');
    if (!ts.length) {
      var e = el('div', 'empty-chat'); e.appendChild(el('b', null, '아직 잡힌 가닥이 없어요.'));
      e.appendChild(el('span', null, S.demo ? '대화를 시작하면 여기에 흐름이 그려져요.' : 'Claude Code · Codex · Cursor로 대화하면 여기에 흐름이 그려져요. 웹과 앱의 대화는 ‘찾은 곳’에서 불러와요.'));
      R.thread.appendChild(e); return;
    }
    ts.forEach(function (t) {
      if (V.segStart(t)) R.thread.appendChild(el('div', 'seam', V.segs[V.sIdx[t.id]]));
      var n = chatTurn(t); if (st.enter === t.id) n.classList.add('enter');
      R.turnEls[t.id] = n; R.thread.appendChild(n);
    });
    st.enter = null;
  }
  function chatTurn(t) {
    var w = el('div', 'turn'); w.dataset.id = t.id;
    var u = el('div', 'u');
    if (t.depth > 0) u.appendChild(el('span', 'tag', t.depth + '차 곁길'));
    if (t.ref && g.byId[t.ref]) u.appendChild(el('span', 'tag', '↩ ' + g.numLabel(g.byId[t.ref])));
    if (t.parts) u.appendChild(el('span', 'tag', '요청 ' + t.parts.length + '개'));
    var full = S.full[t.id] || t;  // 화면에는 앞부분만 와요. ‘전체 보기’로 받아 둔 원문이 있으면 그것을
    var up = el('p', null, full.user); u.appendChild(up); w.appendChild(u);
    var a = el('div', 'a'), para = el('p', 'part', full.ai); a.appendChild(para);
    if (t.parts) R.partEls[t.id + ':0'] = para;
    if (t.long && full === t) {
      var more = el('button', 'linkbtn more', '전체 보기'); more.type = 'button';
      more.onclick = function () { api('turns/' + encodeURIComponent(t.id)).then(function (d) { S.full[t.id] = d.turn; up.textContent = d.turn.user; para.textContent = d.turn.ai; more.remove(); g.renderRail(); }); };
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
    var log = el('button', 'btn sm', '판단 기록'); log.type = 'button'; log.onclick = function () { window.open('trace', '_blank'); }; row.appendChild(log);
    var quit = el('button', 'btn sm', '끄기'); quit.type = 'button'; quit.onclick = quitApp; row.appendChild(quit);
    f.appendChild(row);
  }

  /* ---------- 찾은 곳: 무엇으로 LLM을 쓰는지, 어떻게 읽는지 ---------- */
  function toggleSources() {
    if (!R.src.hidden) { R.src.hidden = true; return; }
    api('sources').then(function (d) { S.sources = d.sources; renderSources(); R.src.hidden = false; });
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
      } else if (s.mode === 'connect') {
        k = s.connected ? '연결됨 · 대화 ' + s.chats + '개' : (s.found ? '한 번 연결하면 그 뒤로 알아서 읽어요' : '설치된 것을 찾지 못했어요');
        w = s.connected ? s.where + ' · 새 대화부터 읽어요' : s.where + ' · 연결하면 Cursor의 hooks.json에 가닥을 더해요';
        if (s.found && !s.connected) { btn = el('button', 'btn sm primary', '연결'); btn.onclick = function () {
          api('sources/cursor/connect', 'POST').then(function (r) { g.flashToast(r.ok ? 'Cursor를 연결했어요. 새 대화부터 읽어요.' : r.reason); return api('sources'); }).then(function (x) { S.sources = x.sources; renderSources(); }); }; }
      } else {
        k = '파일로 불러와요' + (s.chats ? ' · 대화 ' + s.chats + '개' : '');
        w = '대화가 서버에 있어서 이 PC에서 바로 읽을 수 없어요. 각 서비스의 설정 → 데이터 내보내기로 받은 파일(zip · json)을 넣어 주세요.';
        btn = el('button', 'btn sm primary', '파일 고르기'); btn.onclick = function () { R.file.value = ''; R.file.click(); };
      }
      d.appendChild(el('span', 'k' + ((s.mode === 'auto' && s.found) || s.connected ? ' on' : ''), k));
      d.appendChild(el('span', 't', s.name)); d.appendChild(el('span', 'w', w));
      if (btn) { btn.type = 'button'; d.appendChild(btn); }
      p.appendChild(d);
    });
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
    if (R.vp && R.rail) { var H = R.rail.clientHeight - 64, sh = Math.max(R.chat.scrollHeight, 1); R.vp.style.top = (48 + R.chat.scrollTop / sh * H - 6) + 'px'; R.vp.style.height = (R.chat.clientHeight / sh * H + 12) + 'px'; }
    if (v === viewing && !force) return;
    viewing = v;
    Array.prototype.forEach.call(R.root.querySelectorAll('.viewing'), function (n) { n.classList.remove('viewing'); });
    if (!v) return;
    [R.mapDots, R.railDots].forEach(function (set) { if (set && set[v]) set[v].classList.add('viewing'); });
  }
  function onChatScroll() { if (ticking) return; ticking = true; requestAnimationFrame(function () { ticking = false; updateViewing(); }); }

  /* ---------- 실행: 가닥 창은 대화 창의 입력창을 건드릴 수 없어서 클립보드에 담아요 ---------- */
  function copyOut(text, label, done) {
    var ok = function () { g.flashToast('복사했어요. 대화 창에 붙여 넣으면 돼요.'); done(); };
    G.copy(text).then(ok);
  }
  function saveItem(id, state) { if (!S.demo) api('items/' + encodeURIComponent(id), 'PATCH', { state: state }).catch(function () {}); }

  /* ---------- 데이터 ---------- */
  function openProject(id) { if (id === S.project) return; S.project = id; S.chat = null; S.reset = true; S.bottom = true; S.keepScope = null; load(); }
  function openChat(id) { if (g.ACT && id === g.ACT.id) return; S.chat = id; S.reset = true; S.bottom = !S.goto; S.keepScope = st.scope; load(); }
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
      if (!S.projects.some(function (p) { return p.id === S.project; })) { S.project = S.projects.length ? S.projects[0].id : null; S.chat = null; S.reset = true; }
      if (!S.project) { show({ chats: [] }); return; }
      return api('projects/' + encodeURIComponent(S.project) + '/view' + (S.chat ? '?chat=' + encodeURIComponent(S.chat) : '')).then(function (v) {
        var real = v.project.id !== '_none';  // 프로젝트 · 폴더가 없는 대화는 대화별로만 봐요
        show({ project: real ? v.project.name : null, scopeLabel: real && v.chats.length > 1 ? '프로젝트 전체' : null, chats: v.chats, itemStates: v.itemStates });
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
      if (!S.status && !S.demo) { S.demo = true; delete g.hooks.search; clearInterval(S.timer); S.reset = true; return load(); }
      S.off = true; renderFoot();
    }).catch(function () {});
  }

  mount();
  g.load({ chats: [] }, true);
  g.render();
  window.addEventListener('resize', function () { requestAnimationFrame(function () { g.render(); }); });
  if (S.demo) load().then(function () { g.reveal(); });
  else { S.timer = setInterval(tick, POLL); tick().then(function () { g.reveal(); if (params.get('panel') === 'sources') toggleSources(); }); }
})();
