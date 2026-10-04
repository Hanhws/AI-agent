/* 가닥 창(로컬 웹 페이지). shared/ui의 노선도 카드 · 레일 · 목록 · 한마디를 그대로 쓰고,
   여기에는 이 입구만의 것(프로젝트 · 대화 목록, 읽기 전용 대화, 찾은 곳, 백엔드와 주고받기)만 있어요.
   주소에 ?demo 를 붙이거나 백엔드 없이 열면 미리 정리해 둔 예시(data/demo_conversations.json)를 보여 줘요. */
(function () {
  'use strict';
  var G = window.Gadak, el = G.el, fname = G.fname;
  var params = new URLSearchParams(location.search);
  var S = { demo: params.has('demo'), scen: params.get('scen'), projects: [], project: null, chat: null, reset: true,
    rev: -1, status: null, asked: {}, full: {}, bottom: true, goto: null, sources: null, off: false, usage: null,
    findQ: '', found: null };
  var POLL = 1500, FILES_SHOWN = 8;
  var SITES = { 'claude-code': 'Claude Code', codex: 'Codex', cursor: 'Cursor', chatgpt: 'ChatGPT', claude: 'Claude', gemini: 'Gemini' };
  // 가닥 창은 시스템 설정(밝게 · 어둡게)을 따라가요. 주소에 ?theme=light · dark 를 붙이면 고정돼요
  if (/^(light|dark)$/.test(params.get('theme') || '')) document.documentElement.dataset.theme = params.get('theme');

  var g = G.create({
    render: render, go: go, goPart: goPart, itemState: saveItem, insert: copyOut, insertLabel: '복사하기',
    nudgeClass: 'nudge-web', statusBits: statusBits, track: track, setAuto: setAuto,
    // 화면에는 글의 앞부분만 실려 있어서, 찾기는 원문을 가진 백엔드에 맡겨요
    search: function (q) { return api('projects/' + encodeURIComponent(S.project) + '/search?q=' + encodeURIComponent(q)).then(function (d) { return d.hits; }); }
  });
  if (S.demo) { delete g.hooks.search; delete g.hooks.setAuto; }  // 예시는 화면에 실린 글에서 바로 찾고, 가닥이 보낼 곳도 없어요
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
    var site = el('div', 'site'); shell.appendChild(site);
    var bar = el('aside', 'sitebar'); site.appendChild(bar);
    var brand = el('div', 'brand'), logo = el('button', 'logo'); logo.type = 'button'; logo.setAttribute('aria-label', '가닥 심볼 다시 재생');
    var mark = G.makeMark(26, 10); logo.appendChild(mark.svg); logo.appendChild(el('b', null, '가닥')); logo.onclick = function () { G.playMark(mark); };
    brand.appendChild(logo); bar.appendChild(brand);
    var fw = el('div', 'findwrap'); R.find = el('input', 'qin'); R.find.type = 'search'; R.find.placeholder = '대화 찾기';
    R.find.setAttribute('aria-label', '모든 대화에서 찾기');
    R.find.addEventListener('input', function () { setFind(R.find.value.trim()); });
    R.find.addEventListener('keydown', function (e) { if (e.key === 'Escape') { R.find.value = ''; setFind(''); } });
    fw.appendChild(R.find); bar.appendChild(fw);
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
    if (S.findQ) { renderFound(host); host.scrollTop = keep; return; }
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
      more.onclick = function () { track('ui', { what: 'full_text' }); api('turns/' + encodeURIComponent(t.id)).then(function (d) { S.full[t.id] = d.turn; up.textContent = d.turn.user; para.textContent = d.turn.ai; more.remove(); g.renderRail(); }); };
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
    track('ui', { what: 'copy' });
    G.copy(text).then(ok);
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
      if (!S.projects.some(function (p) { return p.id === S.project; })) { S.project = S.projects.length ? S.projects[0].id : null; S.chat = null; S.reset = true; }
      if (!S.project) { show({ chats: [] }); return; }
      return api('projects/' + encodeURIComponent(S.project) + '/view' + (S.chat ? '?chat=' + encodeURIComponent(S.chat) : '')).then(function (v) {
        var real = v.project.id !== '_none';  // 프로젝트 · 폴더가 없는 대화는 대화별로만 봐요
        show({ project: real ? v.project.name : null, scopeLabel: real && v.chats.length > 1 ? '프로젝트 전체' : null, chats: v.chats, itemStates: v.itemStates, auto: v.auto });
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
      if (!S.status && !S.demo) { S.demo = true; delete g.hooks.search; delete g.hooks.setAuto; clearInterval(S.timer); S.reset = true; return load(); }
      S.off = true; renderFoot();
    }).catch(function () {});
  }

  mount();
  g.load({ chats: [] }, true);
  g.render();
  window.addEventListener('resize', function () { requestAnimationFrame(function () { g.render(); }); });
  // 주소에 ?find=찾는 말 을 붙이면 그 말로 찾은 채로 열려요
  function startFind() { var q = (params.get('find') || '').trim(); if (q) { R.find.value = q; setFind(q); } }
  if (S.demo) load().then(function () { g.reveal(); startFind(); });
  else { S.timer = setInterval(tick, POLL); tick().then(function () { g.reveal(); loadUsage(); if (params.get('panel') === 'sources') toggleSources(); startFind(); }); }
})();
