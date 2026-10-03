/* 가닥 화면의 모델: 구간 · 곁길 묶음 · 지금 위치 · 할 일 장부 계산 (prototype의 load · buildView · itemsOf).
   화면 하나(g)에 상태 st, 요소 모음 R, 데이터 SC · ACT · byId가 달려요. 입구마다 다른 동작은 g.hooks로 받아요:
     render()            화면 전체를 다시 그림
     go(turn)            역을 눌렀을 때 (웹: 그 메시지로 스크롤, 그 밖: 내용을 띄움)
     goPart(turn, i)     캡슐 칸을 눌렀을 때
     act(item, anchor)   할 일 실행 (입력창에 넣기 · 클립보드 · 터미널)
     itemState(id, s)    할 일 상태가 바뀜 (저장소에 알림)
     search(q)           지난 대화 찾기를 저장소에 맡길 때. [{id, snip}]의 Promise
     statusBits(V)       머리줄 상태 글에 더할 조각들
     insertLabel         수정 모음 창의 실행 버튼 글 (기본 ‘입력창에 넣기’)
     nudgeClass          한마디 카드 자리 (nudge-web · nudge-app · nudge-vs) */
(function (G) {
  'use strict';
  var el = G.el, fname = G.fname;

  G.KIND = {
    missing: { g: 'miss', label: '빠진 요청', p: 1 }, yours: { g: 'miss', label: '내가 할 일', p: 2 }, open: { g: 'miss', label: '끝나지 않은 곁길', p: 3 },
    unasked: { g: 'miss', label: '요청 외 변경', p: 1 }, branch: { g: 'miss', label: '숨은 가지', p: 2 },
    check: { g: 'sug', label: '이해 확인', p: 4 }, topic: { g: 'sug', label: '주제 전환', p: 4 }, repeat: { g: 'sug', label: '반복 질문', p: 4 }, handoff: { g: 'sug', label: '이어 가기', p: 5 }, next: { g: 'sug', label: '다음 할 일', p: 6 }
  };

  G.create = function (hooks) {
    var g = { hooks: hooks || {}, R: {}, SC: null, ACT: null, byId: {}, cache: {}, cur: null,
      st: { sideTab: 'todo', q: '', found: null, ledgerOpen: true, popSeg: null, scope: 'chat', split: false, items: {}, nudge: null,
        exp: {}, expSig: {}, expUser: {}, drawerOpen: true, fresh: {}, known: {}, enter: null, focusMap: false, shown: 0 } };
    var root = g.hooks.overlay || document.body;
    g.tip = el('div', 'tip'); g.tip.hidden = true; root.appendChild(g.tip);
    g.pop = el('div', 'pop'); g.pop.hidden = true; g.pop.setAttribute('role', 'dialog'); root.appendChild(g.pop);
    document.addEventListener('click', function (e) { if (!g.pop.hidden && !g.pop.contains(e.target)) g.pop.hidden = true; });
    g.render = function () { g.cache = {}; g.tip.hidden = true; if (g.hooks.render) g.hooks.render(); };
    g.go = function (id) { var t = g.byId[id]; if (t && g.hooks.go) g.hooks.go(t); };
    ['model', 'map', 'side', 'nudge', 'rail'].forEach(function (k) { if (G[k]) G[k](g); });
    return g;
  };

  G.model = function (g) {
    var st = g.st;

    /* SC = { project?, scopeLabel?, defScope?, groups?, startTodo?, start?, itemStates?, chats: Chat[] } — docs/schema.md.
       reset이면 접힘 · 범위 · 찾기 같은 화면 상태를 처음으로 돌려요(다른 프로젝트를 열 때). */
    g.load = function (SC, reset) {
      var prev = g.cur ? g.cur.id : null;
      g.SC = SC; g.byId = {}; g.ACT = null; g.cache = {};
      SC.chats.forEach(function (c) {
        if (c.active) g.ACT = c;
        var n = 0;
        c.turns.forEach(function (t, i) {
          t.chat = c; t.ci = i; t.depth = t.depth || 0; g.byId[t.id] = t;
          if (t.depth === 0) n++; t.n = (n < 10 ? '0' : '') + n;
          ['parts', 'alts', 'files', 'todo'].forEach(function (k) { if (t[k] && !t[k].length) delete t[k]; });
          (t.parts || []).forEach(function (p) { if (p.open0 === undefined) p.open0 = !!p.open; p.open = p.open0; });
        });
      });
      if (!g.ACT) g.ACT = SC.chats[SC.chats.length - 1] || { id: null, title: '', date: '', turns: [] };
      st.shown = typeof SC.start === 'number' ? Math.min(SC.start, g.ACT.turns.length) : g.ACT.turns.length;
      if (reset) {
        st.scope = SC.defScope || 'chat'; st.split = false; st.items = {}; st.fresh = {}; st.q = ''; st.found = null;
        st.exp = {}; st.expSig = {}; st.expUser = {}; st.sideTab = 'todo'; st.popSeg = null; st.focusMap = true;
        st.nudge = SC.startTodo ? 'start' : null; if (st.nudge) st.fresh.start = true;
        g.pop.hidden = true; g.tip.hidden = true;
      }
      g.cur = st.shown > 0 ? g.ACT.turns[st.shown - 1] : null;
      if (reset) { st.known = {}; g.allItems().forEach(function (it) { st.known[it.id] = true; }); return; }
      // 새 턴이 도착함 (프로토타입의 nextTurn): 새 구간이면 지난 구간이 저절로 접혀요
      var t = g.cur;
      if (t && t.id !== prev) {
        st.enter = t.id; st.fresh = {}; st.focusMap = true;
        if (st.shown === 1 || t.seg || (st.split && t.topic)) { st.exp = {}; st.expSig = {}; st.expUser = {}; st.popSeg = 'cur'; }
      }
      // 새로 생긴 할 일 중 가장 급한 것 하나가 한마디로 떠요 (README 3-2)
      var pick = null;
      g.allItems().forEach(function (it) {
        if (st.known[it.id]) return;
        st.known[it.id] = true;
        if (g.stateOf(it) !== 'open') return;
        st.fresh[it.id] = true;
        if (it.kind === 'topic' && st.split) { g.setItem(it.id, 'done'); return; }
        if (!pick || G.KIND[it.kind].p < G.KIND[pick.kind].p) pick = it;
      });
      if (pick) st.nudge = pick.id;
      else if (st.nudge && g.stateOf(g.itemById(st.nudge) || { id: '' }) !== 'open') st.nudge = null;
    };

    g.activeTurns = function () { return g.ACT.turns.slice(0, st.shown); };
    g.numLabel = function (t) { return t.chat === g.ACT ? t.n : t.chat.date + ' ' + t.n; };

    /* view = the list of turns a map draws, with segments */
    g.buildView = function (scope) {
      var SC = g.SC, ACT = g.ACT, vis = [], segOf = [];
      if (scope === 'all' && SC.project) {
        SC.chats.forEach(function (c) { var ts = c === ACT ? g.activeTurns() : c.turns, cs = ''; ts.forEach(function (t) { if (t.seg) cs = t.seg; vis.push(t); segOf.push(c.date + ' · ' + (cs || c.title)); }); });
      } else if (scope === 'all' && SC.groups) {
        SC.groups.forEach(function (gr) {
          gr[1].forEach(function (id) {
            if (id === '*') g.activeTurns().forEach(function (t) { vis.push(t); segOf.push(gr[0]); });
            else if (g.byId[id]) { vis.push(g.byId[id]); segOf.push(gr[0]); }
          });
        });
      } else {
        var seg = '';
        g.activeTurns().forEach(function (t) { if (t.seg) seg = t.seg; if (st.split && t.topic) seg = t.topic; vis.push(t); segOf.push(seg); });
      }
      var segs = [], sIdx = [];
      segOf.forEach(function (s, i) { if (i === 0 || s !== segOf[i - 1]) segs.push(s); sIdx.push(segs.length - 1); });
      var multi = segs.length > 1;
      var curT = g.cur;
      var key = scope + (st.split ? 's' : '');
      // 처음에는 지금 구간만 펼침(역이 9개 이하면 모두). 정리가 진행되어 구간 이름이 바뀌면 다시 계산하되, 직접 여닫은 것은 지켜요
      var sig = segs.join('\u0001');
      if (!st.exp[key] || st.expSig[key] !== sig) {
        st.exp[key] = {}; st.expSig[key] = sig; st.expUser[key] = st.expUser[key] || {};
        var mains = vis.filter(function (t) { return t.depth === 0; }).length;
        var curSeg = curT && vis.indexOf(curT) >= 0 ? segs[sIdx[vis.indexOf(curT)]] : segs[segs.length - 1];
        segs.forEach(function (s) { st.exp[key][s] = s in st.expUser[key] ? st.expUser[key][s] : (mains <= 9 || s === curSeg); });
      }
      var V = { scope: scope, vis: vis, segs: segs, sIdx: {}, multi: multi, cur: curT, key: key };
      vis.forEach(function (t, i) { V.sIdx[t.id] = sIdx[i]; });
      V.isOpen = function (s) { return !multi || st.exp[key][segs[s]] !== false; };
      V.setOpen = function (name, open) { st.exp[key][name] = open; st.expUser[key][name] = open; };
      V.segStart = function (t) { var i = vis.indexOf(t); return i > 0 && sIdx[i] !== sIdx[i - 1]; };
      // anchors and side chains
      var anchor = null, chains = [], anc = {}, chainOf = {};
      vis.forEach(function (t) {
        if (t.depth === 0) { anchor = t; return; }
        if (!anchor) return;
        anc[t.id] = anchor.id;
        var last = chains[chains.length - 1];
        if (t.depth === 1 || !last || last.anchor !== anchor.id) chains.push({ anchor: anchor.id, nodes: [t] }); else last.nodes.push(t);
        chainOf[t.id] = chains[chains.length - 1];
      });
      var active = curT && curT.depth > 0 ? chainOf[curT.id] || null : null;
      chains.forEach(function (c) { c.closed = c !== active; });
      V.anc = anc; V.chains = chains;
      V.kind = function (t) {
        if (t === curT) return 'cur';
        if (t.depth > 0) { var ch = chainOf[t.id]; return ch && ch.closed ? 'closed' : 'br'; }
        return t.dec ? 'dec' : 'main';
      };
      return V;
    };

    /* ---------- ledger items ---------- */
    g.itemsOf = function (t) {
      var out = [];
      (t.parts || []).forEach(function (p, i) {
        if (!p.open0) return;
        // follow는 프로토타입 예시에만 있어요. 실제 대화에서는 다시 묻는 글을 만들어 넣어요
        out.push({ id: t.id + ':p' + i, t: t, kind: 'missing', text: '“' + p.t + '” 답이 안 왔어요', why: t.n + '에서 요청 ' + t.parts.length + '개 중 하나가 답에서 빠졌어요.', btn: '다시 묻기',
          prompt: p.follow ? p.follow.user : '앞에서 요청한 것 중 “' + p.t + '”에 대한 답이 빠졌어. 이 부분도 답해 줘.', follow: p.follow, part: i });
      });
      (t.todo || []).forEach(function (d, i) { var o = Object.assign({ id: t.id + ':' + i, t: t }, d); out.push(o); });
      return out;
    };
    g.allItems = function () {
      if (g.cache.items) return g.cache.items;
      var out = [];
      if (g.SC.startTodo) out.push(Object.assign({ id: 'start', t: null }, g.SC.startTodo));
      g.activeTurns().forEach(function (t) { out = out.concat(g.itemsOf(t)); });
      return (g.cache.items = out);
    };
    g.stateOf = function (it) { return st.items[it.id] || (g.SC.itemStates && g.SC.itemStates[it.id]) || it.state || 'open'; };
    g.setItem = function (id, state) { st.items[id] = state; g.cache = {}; if (g.hooks.itemState) g.hooks.itemState(id, state); };
    g.openItems = function () { return g.cache.open || (g.cache.open = g.allItems().filter(function (it) { var s = g.stateOf(it); return s === 'open' || s === 'later'; })); };
    g.itemById = function (id) { return g.allItems().filter(function (it) { return it.id === id; })[0]; };
    g.revisions = function () { var r = []; g.activeTurns().forEach(function (t) { (t.parts || []).forEach(function (p) { if (p.type === 'rev') r.push({ t: t, p: p }); }); }); return r; };
    g.allFiles = function (t) { return (t.files || []).slice(); };
    g.hasTodo = function (t) {
      if (!g.cache.todo) { var s = {}; g.openItems().forEach(function (it) { if (it.t) s[it.t.id] = 1; if (it.at) s[it.at] = 1; }); g.cache.todo = s; }
      return !!g.cache.todo[t.id];
    };

    /* every turn the project knows about: past chats in full, the open chat up to now */
    g.allKnown = function () { var out = []; g.SC.chats.forEach(function (c) { out = out.concat(c === g.ACT ? g.activeTurns() : c.turns); }); return out; };
    g.baseName = function (n) { return n.replace(/\s*\(.*\)$/, '').replace(/\s+v\d+(\.\d+)?$/, '').trim(); };
    g.fileVersions = function () {
      if (g.cache.fv) return g.cache.fv;
      var map = {}, order = [];
      g.allKnown().forEach(function (t) {
        g.allFiles(t).forEach(function (f) {
          var n = fname(f), b = g.baseName(n);
          if (!map[b]) { map[b] = []; order.push(b); }
          map[b].push({ n: n, t: t });
        });
      });
      return (g.cache.fv = { map: map, order: order });
    };
    g.versionOf = function (t, f) { var fv = g.fileVersions(), list = fv.map[g.baseName(fname(f))] || [], i = -1; list.forEach(function (v, k) { if (v.t === t && v.n === fname(f)) i = k; }); return { v: i + 1, of: list.length }; };
  };
})(window.Gadak = window.Gadak || {});
