/* 떠 있는 가닥 버튼이 펼치는 노선도 창 (macOS 앱 · mac/Float.swift).
   가닥 창의 노선도 카드(shared/ui)만 따로 띄운 것이에요. 지금 쓰는 대화(가장 최근에 턴이 온 대화)를 보여 주고,
   역을 누르면 가닥 창에서 그 자리를 열어요. 카드의 ‘접기’는 이 창을 닫아요. */
(function () {
  'use strict';
  var G = window.Gadak, el = G.el, params = new URLSearchParams(location.search);
  var S = { rev: -1, project: null, chat: null, first: true, height: 0 };
  var POLL = 1500, TABS = { todo: 1, dec: 1, files: 1 };
  if (/^(light|dark)$/.test(params.get('theme') || '')) document.documentElement.dataset.theme = params.get('theme');

  function enc(x) { return encodeURIComponent(x); }
  function api(path, method, body) {
    var opt = method ? { method: method, headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body || {}) } : undefined;
    return fetch(path, opt).then(function (r) { if (!r.ok) throw new Error(String(r.status)); return r.json(); });
  }
  /* 앱에 부탁하는 길. 브라우저에서 그냥 열어 보면 아무 일도 없어요 */
  function tell(msg) { try { window.webkit.messageHandlers.gadak.postMessage(msg); } catch (e) {} }

  var g = G.create({
    render: render, go: go, goPart: function (t) { go(t); }, itemState: saveItem, insert: copyOut, insertLabel: '복사하기',
    goHint: '역을 누르면 가닥 창에서 그 대화를 열어요', setAuto: setAuto,
    track: function (name, fields) { api('usage', 'POST', { name: name, fields: fields || {} }).catch(function () {}); },
    search: function (q) { return api('projects/' + enc(S.project) + '/search?q=' + enc(q)).then(function (d) { return d.hits; }); }
  });
  var st = g.st, R = g.R;

  function mount() {
    var shell = document.getElementById('shell'); R.root = shell;
    g.mountDrawer(shell);
    R.none = el('div', 'none'); R.none.hidden = true; R.drawer.appendChild(R.none);
    R.none.appendChild(el('b', null, '아직 잡힌 가닥이 없어요.')); R.none.appendChild(document.createTextNode('대화를 시작하면 여기에 흐름이 그려져요.'));
    R.toastEl = el('div', 'toast'); R.toastEl.hidden = true; shell.appendChild(R.toastEl);
  }
  function panel(tab, list) { if (TABS[tab]) st.sideTab = tab; st.ledgerOpen = !!list; st.q = ''; st.found = null; }

  function render() {
    if (!st.drawerOpen) { st.drawerOpen = true; tell({ float: 'close' }); return; }   // 카드의 ‘접기’ = 이 창 닫기
    var empty = !g.SC.chats.length;
    R.none.hidden = !empty; R.dbody.hidden = empty;
    var V = g.buildView(st.scope);
    g.renderMapHead(V); g.renderSide(); g.renderMap(V);
    fit();
  }
  /* 카드 높이에 맞춰 창 크기를 맞춰 달라고 앱에 알려요 */
  function fit() {
    requestAnimationFrame(function () {
      var h = Math.ceil(R.root.getBoundingClientRect().height);
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

  function load() {
    return api('float').then(function (f) {
      if (!f.chat) { g.load({ chats: [] }, S.first); S.first = false; g.render(); return; }
      var moved = f.chat.id !== S.chat;          // 다른 대화로 넘어갔으면 접힘 · 범위를 처음으로
      S.project = f.chat.project; S.chat = f.chat.id;
      return api('projects/' + enc(S.project) + '/view?chat=' + enc(S.chat)).then(function (v) {
        var real = v.project.id !== '_none', tab = st.sideTab, open = st.ledgerOpen;
        g.load({ project: real ? v.project.name : null, scopeLabel: real && v.chats.length > 1 ? '프로젝트 전체' : null,
          chats: v.chats, itemStates: v.itemStates, auto: v.auto }, S.first || moved);
        if (S.first) panel(params.get('tab'), params.get('list') === '1'); else if (moved) { st.sideTab = tab; st.ledgerOpen = open; }
        st.nudge = null;                         // 이 창에는 한마디 카드가 없어요. 할 일은 목록에서 봐요
        S.first = false; g.render();
      });
    });
  }
  function tick() {
    return api('status').then(function (s) { if (s.rev !== S.rev) { S.rev = s.rev; return load(); } }).catch(function () {});
  }

  /* 앱이 부르는 것: 같은 창에서 볼 것만 바꿔요 (노선도만 · 할 일 · 정한 것 · 산출물) */
  window.gadakStrip = function (o) { panel(o && o.tab, o && o.list); g.render(); if (!G.reduce) g.reveal(); };

  mount();
  g.load({ chats: [] }, true);
  panel(params.get('tab'), params.get('list') === '1');
  g.render();
  setInterval(tick, POLL);
  tick().then(function () { g.reveal(); });
  window.addEventListener('resize', function () { requestAnimationFrame(function () { g.render(); }); });
})();
