/* 노선도 카드의 오른쪽 목록: 할 일 · 정한 것 · 산출물 · 지난 대화에서 찾기
   (prototype의 renderSide · renderLedger · renderDecisions · renderArtifacts · renderFound). README 7-9. */
(function (G) {
  'use strict';
  var el = G.el, fname = G.fname;

  G.side = function (g) {
    var st = g.st, R = g.R, KIND = G.KIND, findTimer = null;

    g.renderSide = function () {
      var n = g.openItems().length;
      R.dbody.classList.toggle('noled', !st.ledgerOpen);
      R.ledBtn.textContent = st.ledgerOpen ? '목록 접기 ›' : '‹ 할 일' + (n ? ' ' + n : '') + ' · 찾기';
      R.ledBtn.classList.toggle('hot', !st.ledgerOpen && n > 0);
      R.ledBtn.setAttribute('aria-expanded', String(st.ledgerOpen));
      if (!st.ledgerOpen) return;
      tabs(R.sideHead, [['todo', '할 일', n], ['dec', '정한 것'], ['files', '산출물']], st.sideTab, function (v) { st.sideTab = v; });
      if (R.qInput.value.trim() !== st.q) R.qInput.value = st.q;
      g.renderSideBody(); g.markFound();
    };
    function tabs(host, list, cur, set) {
      host.innerHTML = ''; host.setAttribute('role', 'tablist');
      list.forEach(function (o) {
        var b = el('button', null, o[1]); b.type = 'button'; b.setAttribute('role', 'tab'); b.setAttribute('aria-selected', String(cur === o[0]));
        if (o[2]) b.appendChild(el('span', 'n', String(o[2])));
        b.onclick = function () { set(o[0]); g.track('ui', { what: 'tab_' + o[0] }); g.render(); };
        host.appendChild(b);
      });
    }

    /* ---------- 찾기 ---------- */
    function hit(t) { var q = st.q.toLowerCase(); if (!q) return false; return [t.title, t.user, t.ai, t.dec || ''].concat((t.files || []).map(fname)).join(' ').toLowerCase().indexOf(q) >= 0; }
    function snippet(t) {
      var q = st.q.toLowerCase(), src = [t.dec, t.title, t.user, t.ai].filter(Boolean).filter(function (x) { return x.toLowerCase().indexOf(q) >= 0; })[0] || t.title;
      var i = src.toLowerCase().indexOf(q);
      return (i > 24 ? '…' : '') + src.slice(Math.max(0, i - 24), i + q.length + 36) + (i + q.length + 36 < src.length ? '…' : '');
    }
    /* 찾은 턴들. 저장소가 찾아 준 결과(st.found)가 있으면 그것을, 없으면 화면에 실린 글에서 찾아요. 정한 것이 먼저 */
    g.foundList = function () {
      if (!st.q) return [];
      var list;
      if (st.found && st.found.q === st.q) list = st.found.hits.filter(function (h) { return g.byId[h.id]; }).map(function (h) { return { t: g.byId[h.id], snip: h.snip }; });
      else list = g.allKnown().filter(hit).reverse().map(function (t) { return { t: t, snip: snippet(t) }; });
      return list.sort(function (a, b) { return (b.t.dec ? 1 : 0) - (a.t.dec ? 1 : 0); });
    };
    g.setQuery = function (q) {
      if (q && !st.q) g.track('ui', { what: 'search' });   // 무엇을 찾는지는 적지 않아요
      st.q = q; g.renderSideBody(); g.markFound();
      if (!g.hooks.search) return;
      clearTimeout(findTimer);
      if (!q) { st.found = null; return; }
      findTimer = setTimeout(function () {
        g.hooks.search(q).then(function (hits) { if (st.q !== q) return; st.found = { q: q, hits: hits || [] }; g.renderSideBody(); g.markFound(); }, function () {});
      }, 180);
    };
    g.markFound = function () {
      if (!R.map) return;
      Array.prototype.forEach.call(R.map.querySelectorAll('.found'), function (e) { e.classList.remove('found'); });
      g.foundList().forEach(function (f) { if (R.mapDots && R.mapDots[f.t.id]) R.mapDots[f.t.id].classList.add('found'); });
    };

    g.renderSideBody = function () {
      var b = R.sideBody; b.innerHTML = '';
      if (st.q) { renderFound(b); return; }
      if (st.sideTab === 'todo') renderLedger(b);
      else if (st.sideTab === 'dec') renderDecisions(b);
      else renderArtifacts(b);
    };
    function rowBtn(host, top, main, sub, t) {
      var r = el('button', 'srow2'); r.type = 'button';
      if (top) r.appendChild(el('span', 'k', top));
      r.appendChild(el('span', 't', main)); if (sub) r.appendChild(el('span', 'w', sub));
      r.onclick = function () { g.track('ui', { what: 'go_list' }); g.go(t.id); };
      host.appendChild(r); return r;
    }
    function renderDecisions(host) {
      var list = g.allKnown().filter(function (t) { return t.dec; }).reverse();
      if (!list.length) { host.appendChild(el('div', 'lempty', '아직 정한 것이 없어요.')); return; }
      host.appendChild(el('div', 'lsum', (g.SC.project ? '이 프로젝트' : '이 대화') + '에서 정한 것 ' + list.length + '개 · 최근 순'));
      list.forEach(function (t) { rowBtn(host, g.numLabel(t) + ' · ' + t.title, t.dec, null, t).classList.add('dec'); });
    }
    function renderArtifacts(host) {
      var fv = g.fileVersions();
      if (!fv.order.length) { host.appendChild(el('div', 'lempty', '아직 나온 산출물이 없어요.')); return; }
      var unaskedT = g.openItems().filter(function (i) { return i.kind === 'unasked'; }).map(function (i) { return i.t; });
      host.appendChild(el('div', 'lsum', '산출물 ' + fv.order.length + '개 · 같은 파일은 판(v)으로 묶었어요'));
      fv.order.slice().reverse().forEach(function (b) {
        var vs = fv.map[b], last = vs[vs.length - 1];
        var grp = el('div', 'fgrp');
        var h = el('button', 'fhead'); h.type = 'button'; h.appendChild(el('span', 'sq'));
        h.appendChild(el('span', 'fn', b)); h.appendChild(el('span', 'latest', vs.length > 1 ? 'v' + vs.length + ' 최신' : '최신'));
        if (unaskedT.indexOf(last.t) >= 0) h.appendChild(el('span', 'warn', '요청 외 변경'));
        h.title = b;
        h.onclick = function () { st.file = last.n; g.go(last.t.id); };
        grp.appendChild(h);
        if (vs.length > 1) vs.slice(0, -1).reverse().forEach(function (v, k) {
          var r = el('button', 'fold-v'); r.type = 'button'; r.appendChild(el('span', null, 'v' + (vs.length - 1 - k)));
          r.appendChild(el('span', null, g.numLabel(v.t) + ' ' + v.t.title)); r.onclick = function () { g.go(v.t.id); }; grp.appendChild(r);
        });
        host.appendChild(grp);
      });
    }
    function renderFound(host) {
      var ts = g.foundList();
      host.appendChild(el('div', 'lsum', ts.length ? '“' + st.q + '” · ' + ts.length + '곳. 정한 것이 먼저 나와요.' : '“' + st.q + '”이 나온 곳이 없어요.'));
      ts.slice(0, 12).forEach(function (f) {
        var t = f.t;
        rowBtn(host, g.numLabel(t) + ' · ' + (t.chat !== g.ACT ? t.chat.title : '이 대화') + (t.dec ? ' · 정함' : ''), t.title, f.snip, t);
      });
    }

    /* ---------- 할 일 장부 ---------- */
    function renderLedger(host) {
      var all = g.allItems(), led = el('div', 'led'); host.appendChild(led);
      if (!all.length) { led.appendChild(el('div', 'lempty', '아직 없어요. 빠진 요청이나 다음 할 일이 생기면 가닥이 여기 모아요.')); return; }
      [['miss', '놓친 일'], ['sug', '제안']].forEach(function (gr) {
        var list = all.filter(function (i) { return KIND[i.kind].g === gr[0]; });
        if (!list.length) return;
        var grp = el('div', 'lgrp'); grp.appendChild(el('h5', null, gr[1]));
        list.slice().reverse().forEach(function (it) { grp.appendChild(ledgerItem(it)); });
        led.appendChild(grp);
      });
    }
    function ledgerItem(it) {
      var s = g.stateOf(it), sg = KIND[it.kind].g === 'sug';
      var d = el('div', 'litem' + (sg ? ' sg' : '') + (s === 'done' ? ' done' : '') + (s === 'later' ? ' later' : '') + (st.fresh[it.id] ? ' new' : ''));
      d.appendChild(el('span', 'mk'));
      var body = el('div'); d.appendChild(body);
      var at = it.at && g.byId[it.at] ? g.byId[it.at] : it.t;
      body.appendChild(el('div', 'k', (it.t ? g.numLabel(at) + ' · ' : '') + KIND[it.kind].label));
      var t = el('div', 't', it.text); body.appendChild(t);
      if (it.t && s !== 'done') { t.classList.add('lk'); t.onclick = function () { g.go(at.id); }; }
      if (s !== 'done') {
        var row = el('div', 'row');
        var a = el('button', 'btn sm primary', it.btn); a.type = 'button'; a.disabled = !!st.typing; a.onclick = function (e) { e.stopPropagation(); g.act(it, a, 'list'); }; row.appendChild(a);
        if (s !== 'later') { var l = el('button', 'btn sm', '나중에'); l.type = 'button'; l.onclick = function () { g.track('item', { kind: it.kind, did: 'later', at: 'list' }); g.setItem(it.id, 'later'); if (st.nudge === it.id) st.nudge = null; g.render(); }; row.appendChild(l); }
        body.appendChild(row);
      }
      return d;
    }
  };
})(window.Gadak = window.Gadak || {});
