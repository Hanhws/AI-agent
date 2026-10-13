/* 떠 있는 가닥 버튼이 펼치는 창 둘 (macOS 앱 · mac/Float.swift). 가닥 창의 화면(shared/ui)을 따로 띄운 것이에요.
   - 노선도 창 (/strip): 지금 쓰는 대화(가장 최근에 턴이 온 대화)의 노선도 카드. 역을 누르면 가닥 창에서 그 자리를 열고, 카드의 ‘접기’는 이 창을 닫아요.
   - 목록 창 (/strip?only=list): 할 일 · 정한 것 · 산출물 · 앞길만. 노선도 창과 따로 떠요.
   앱이 주소에 app=2를 붙여 열면 목록은 늘 목록 창에서 봐요(카드의 ‘‹ 할 일 · 찾기’도 목록 창을 열어요).
   그게 없으면(예전에 만든 앱 · 브라우저) 전처럼 노선도 카드 안에서 목록을 펴요.
   보여 주는 것은 보통 ‘지금 쓰는 대화’예요. 떠 있는 버튼의 프로젝트 버튼을 누르면(project=…) 그 프로젝트에서 가장 최근에 쓴 대화를 보여 줘요. */
(function () {
  'use strict';
  var G = window.Gadak, el = G.el, params = new URLSearchParams(location.search);
  var ONLY = params.get('only') === 'list', APART = params.get('app') === '2';
  var S = { rev: -1, project: null, chat: null, first: true, height: 0, status: null, flags: '', pin: params.get('project') || null };
  var POLL = 1500, TABS = { todo: 1, dec: 1, files: 1 };       // 떠 있는 버튼이 고르는 칸. ‘앞길’ 칸은 목록 안에서 골라요
  if (/^(light|dark)$/.test(params.get('theme') || '')) document.documentElement.dataset.theme = params.get('theme');

  function enc(x) { return encodeURIComponent(x); }
  function api(path, method, body) {
    var opt = method ? { method: method, headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body || {}) } : undefined;
    return fetch(path, opt).then(function (r) { if (!r.ok && r.status !== 409) throw new Error(String(r.status)); return r.json(); });
  }
  /* 앱에 부탁하는 길. 브라우저에서 그냥 열어 보면 아무 일도 없어요 */
  function tell(msg) { try { window.webkit.messageHandlers.gadak.postMessage(msg); } catch (e) {} }

  var g = G.create({
    render: render, go: go, goPart: function (t) { go(t); }, itemState: saveItem, insert: copyOut, insertLabel: '복사하기',
    goHint: '역을 누르면 가닥 창에서 그 대화를 열어요', setAuto: setAuto, transfer: transfer,
    // 앞길 살피기 (README 3-1): 목록의 넷째 칸 ‘앞길’과, 할 일 칸 아래의 ‘저절로 살피기’ 줄
    ahead: ahead, aheadOn: function () { return !!(S.status && S.status.ahead && S.status.ahead.on); },
    aheadAuto: function () { return !!(S.status && S.status.ahead && S.status.ahead.auto); }, setAheadAuto: setAheadAuto,
    track: function (name, fields) { api('usage', 'POST', { name: name, fields: fields || {} }).catch(function () {}); },
    search: function (q) { return api('projects/' + enc(S.project) + '/search?q=' + enc(q)).then(function (d) { return d.hits; }); }
  });
  var st = g.st, R = g.R;

  function mount() {
    var shell = document.getElementById('shell'); R.root = shell;
    if (ONLY) {
      // 목록 창: 노선도 카드 없이 목록만. 카드 모양 틀에 머리줄(가닥 · 대화 제목 · 닫기)과 목록을 놓아요
      shell.classList.add('listonly');
      var card = el('section', 'drawer lcard'); card.setAttribute('aria-label', '가닥 목록'); shell.appendChild(card); R.drawer = card;
      var head = el('div', 'dhead'), mk = el('span', 'mk'); mk.appendChild(G.miniMark(15)); mk.appendChild(el('b', null, '가닥')); head.appendChild(mk);
      R.listTitle = el('span', 'map-title'); head.appendChild(R.listTitle); head.appendChild(el('span', 'sp'));
      var shut = el('button', 'btn sm', '닫기'); shut.type = 'button'; shut.onclick = function () { tell({ float: 'close' }); }; head.appendChild(shut);
      card.appendChild(head);
      g.mountSide(card, true);
    } else {
      g.mountDrawer(shell, null, APART);
    }
    R.none = el('div', 'none'); R.none.hidden = true; R.drawer.appendChild(R.none);
    R.none.appendChild(el('b', null, '아직 잡힌 가닥이 없어요.')); R.none.appendChild(document.createTextNode('대화를 시작하면 여기에 흐름이 그려져요.'));
    R.toastEl = el('div', 'toast'); R.toastEl.hidden = true; shell.appendChild(R.toastEl);
  }
  /* 볼 칸과, 목록을 펼지. 목록 창은 늘 펴 있고, 목록 창을 따로 쓰는 앱의 노선도 창은 늘 접혀 있어요 */
  function panel(tab, list) {
    if (TABS[tab] || tab === 'ahead') st.sideTab = tab;
    st.ledgerOpen = ONLY ? true : (!!list && !APART);
    st.q = ''; st.found = null;
  }

  function render() {
    var empty = !g.SC.chats.length;
    if (ONLY) {
      st.ledgerOpen = true;
      R.none.hidden = !empty; var list = R.drawer.querySelector('.dside'); if (list) list.style.display = empty ? 'none' : '';
      R.listTitle.textContent = empty ? '' : (g.ACT.title || '');
      if (!empty) g.renderSide();
      fit(); return;
    }
    if (!st.drawerOpen) { st.drawerOpen = true; tell({ float: 'close' }); return; }   // 카드의 ‘접기’ = 이 창 닫기
    // 카드의 ‘‹ 할 일 · 찾기’: 목록 창을 따로 쓰는 앱에서는 그 창을 열어 달라고 부탁해요 (한 번 더 누르면 닫혀요)
    if (APART && st.ledgerOpen) { st.ledgerOpen = false; tell({ float: 'list', tab: st.sideTab }); }
    R.none.hidden = !empty; R.dbody.hidden = empty;
    var V = g.buildView(st.scope);
    g.renderMapHead(V); g.renderSide(); g.renderMap(V);
    fit();
  }
  /* 카드 높이에 맞춰 창 크기를 맞춰 달라고 앱에 알려요. 목록 창은 글이 다 보이는 높이를 알려 주고,
     앱이 화면에 맞게 줄이면 그만큼은 목록 안에서 스크롤해요 */
  function fit() {
    requestAnimationFrame(function () {
      var h = Math.ceil(R.root.getBoundingClientRect().height);
      if (ONLY && R.sideBody) h = Math.ceil(h - R.sideBody.clientHeight + R.sideBody.scrollHeight);
      if (h && h !== S.height) { S.height = h; tell({ float: 'size', height: h }); }
    });
  }

  function go(t) { tell({ open: { project: S.project, chat: t.chat.id, turn: t.id } }); }
  function copyOut(text, label, done) { G.copy(text).then(function () { g.flashToast('복사했어요. 대화 창에 붙여 넣으면 돼요.'); done(); }); }
  function saveItem(id, state) { api('items/' + enc(id), 'PATCH', { state: state }).catch(function () {}); }
  function setAuto(kind, on) {
    api('auto', 'POST', { kind: kind, on: on }).then(function (r) {
      g.SC.auto = r.auto;
      g.flashToast(on ? '다음부터 ‘' + G.KIND[kind].label + '’은 가닥이 바로 보내요.' : '‘' + G.KIND[kind].label + '’은 다시 물어보고 보낼게요.');
      g.render();
    }, function () { g.flashToast('바꾸지 못했어요.'); });
  }
  /* ‘주제 전환’ 한마디의 ‘환승하기’: 가닥 창의 노선도 끝 환승하기와 같은 요약을 복사해요 (이 창의 노선도에는 그 표시를 그리지 않아요) */
  function transfer() {
    if (!S.chat) return;
    g.flashToast('다음 대화에 붙일 요약을 쓰고 있어요…');
    api('chats/' + enc(S.chat) + '/handoff').then(function (r) {
      if (!r.text) { g.flashToast('아직 정한 것도 남은 일도 없어요.'); return; }
      G.copy(r.text).then(function () { g.flashToast('다음 대화에 붙일 요약을 복사했어요.'); });
    }, function () { g.flashToast('요약을 만들지 못했어요.'); });
  }
  /* 앞길 보기 · 저절로 살피기 (가닥 창의 app.js와 같은 일). 어디까지 갔는지는 ‘앞길’ 칸에 나타나요 */
  function ahead() {
    if (!S.chat) return;
    st.sideTab = 'ahead';
    api('chats/' + enc(S.chat) + '/ahead', 'POST').then(function (r) {
      g.SC.ahead = r.ok ? { state: 'queued' } : { state: 'failed', reason: r.reason }; g.render();
    }, function () { g.SC.ahead = { state: 'failed', reason: '가닥에 닿지 못했어요. 가닥이 켜져 있는지 봐 주세요.' }; g.render(); });
  }
  function setAheadAuto(on) {
    api('ahead/auto', 'POST', { on: on }).then(function (r) {
      if (!r.ok) { g.flashToast(r.reason || '바꾸지 못했어요.'); return; }
      if (S.status && S.status.ahead) S.status.ahead.auto = !!r.auto;
      g.flashToast(r.auto ? '이제 길이 갈리는 순간마다 앞길을 저절로 살펴요. Claude 사용 한도를 더 써요.' : '저절로 살피기를 껐어요. ‘앞길 보기’를 누를 때만 살펴요.');
      g.render();
    }, function () { g.flashToast('바꾸지 못했어요.'); });
  }

  function load() {
    return api('float' + (S.pin ? '?project=' + enc(S.pin) : '')).then(function (f) {
      if (!f.chat) { g.load({ chats: [] }, S.first); S.first = false; g.render(); return; }
      var moved = f.chat.id !== S.chat;          // 다른 대화로 넘어갔으면 접힘 · 범위를 처음으로
      S.project = f.chat.project; S.chat = f.chat.id;
      return api('projects/' + enc(S.project) + '/view?chat=' + enc(S.chat)).then(function (v) {
        var real = v.project.id !== '_none', tab = st.sideTab, open = st.ledgerOpen;
        // 노선 색: 가닥 창 · 전체 지도와 같은 프로젝트 색 (store.project_color). 이게 없으면 본선과 역이 같은 색이라 역이 안 보여요
        R.root.style.setProperty('--route', v.project.color || '');
        g.load({ project: real ? v.project.name : null, scopeLabel: real && v.chats.length > 1 ? '프로젝트 전체' : null,
          chats: v.chats, itemStates: v.itemStates, auto: v.auto, ahead: v.ahead }, S.first || moved);
        if (S.first) panel(params.get('tab'), params.get('list') === '1'); else if (moved) { st.sideTab = tab; st.ledgerOpen = open; }
        st.nudge = null;                         // 이 창에는 한마디 카드가 없어요. 할 일은 목록에서 봐요
        S.first = false; g.render();
      });
    });
  }
  function tick() {
    return api('status').then(function (s) {
      var flags = JSON.stringify(s.ahead || {}), changed = flags !== S.flags;
      S.status = s; S.flags = flags;
      if (s.rev !== S.rev) { S.rev = s.rev; return load(); }
      if (changed) g.render();                   // 앞길 살피기를 켜고 끈 것이 바뀌었어요
    }).catch(function () {});
  }

  /* 앱이 부르는 것: 같은 창에서 볼 것만 바꿔요 (노선도 창: 목록을 펼지 · 목록 창: 어느 칸을 볼지).
     project를 같이 주면 볼 프로젝트를 바꿔요: 프로젝트 id면 그 프로젝트의 최근 대화, null이면 다시 ‘지금 쓰는 대화’ */
  window.gadakStrip = function (o) {
    panel(o && o.tab, o && o.list);
    if (o && 'project' in o && (o.project || null) !== S.pin) { S.pin = o.project || null; load().then(function () { if (!G.reduce && !ONLY) g.reveal(); }); return; }
    g.render(); if (!G.reduce && !ONLY) g.reveal();
  };

  mount();
  g.load({ chats: [] }, true);
  panel(params.get('tab'), params.get('list') === '1');
  g.render();
  setInterval(tick, POLL);
  tick().then(function () { if (!ONLY) g.reveal(); });
  window.addEventListener('resize', function () { requestAnimationFrame(function () { g.render(); }); });
})();
