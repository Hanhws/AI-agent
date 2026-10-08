/* 노선도 카드와 가로 노선도 (prototype의 mountDrawer · renderMapHead · renderMap · capsule · 툴팁).
   크기 · 간격 · 선 굵기는 README 7-5 · 7-6 · 7-9의 값 그대로예요. */
(function (G) {
  'use strict';
  var el = G.el, fname = G.fname, SVGNS = G.SVGNS;
  var TICK = 18;

  G.map = function (g) {
    var st = g.st, R = g.R, tip = g.tip;

    /* the drawer is the same in every entry: horizontal map + ledger.
       apart이면 목록을 카드에 넣지 않아요. 그 입구가 g.mountSide(자리, true)로 따로 놓아요 (가닥 창의 오른쪽 기둥 · 떠 있는 버튼의 목록 창) */
    g.mountDrawer = function (host, asWindow, apart) {
      var dr = el('section', 'drawer' + (asWindow ? ' fw' : '')); dr.setAttribute('aria-label', '가닥 노선도'); host.appendChild(dr); R.drawer = dr;
      if (asWindow) { var wb = el('div', 'wbar'), dots = el('div', 'dots'); dots.innerHTML = '<i></i><i></i><i></i>'; wb.appendChild(dots); wb.appendChild(el('b', null, '가닥')); wb.appendChild(el('span', 'r', asWindow)); dr.appendChild(wb); }
      var dh = el('div', 'dhead'); dr.appendChild(dh);
      if (!asWindow) { var mk = el('span', 'mk'); mk.appendChild(G.miniMark(15)); mk.appendChild(el('b', null, '가닥')); dh.appendChild(mk); }
      R.mapTitle = el('span', 'map-title'); dh.appendChild(R.mapTitle);
      R.scopeBox = el('span'); dh.appendChild(R.scopeBox);
      R.status = el('span', 'map-status'); dh.appendChild(R.status); dh.appendChild(el('span', 'sp'));
      R.segAll = el('button', 'linkbtn'); R.segAll.type = 'button'; dh.appendChild(R.segAll);
      R.qbtn = el('button', 'qbtn'); R.qbtn.type = 'button'; R.qbtn.onclick = function (e) { e.stopPropagation(); g.showRevPop(this); }; dh.appendChild(R.qbtn);
      R.ledBtn = el('button', 'ledbtn'); R.ledBtn.type = 'button'; R.ledBtn.onclick = function () { st.ledgerOpen = !st.ledgerOpen; st.focusMap = true; g.track('ui', { what: st.ledgerOpen ? 'list_open' : 'list_close' }); g.render(); }; dh.appendChild(R.ledBtn);
      var fold = el('button', 'btn sm', '접기'); fold.type = 'button'; fold.onclick = g.toggleDrawer; dh.appendChild(fold);
      var db = el('div', 'dbody' + (apart ? ' noled' : '')); dr.appendChild(db); R.dbody = db;
      R.mapScroll = el('div', 'map-scroll'); R.map = el('div', 'map'); R.mapScroll.appendChild(R.map); db.appendChild(R.mapScroll);
      R.mapScroll.addEventListener('scroll', function () { tip.hidden = true; });
      if (!apart) g.mountSide(db);
    };
    /* 목록: 할 일 · 정한 것 · 산출물 · 앞길과 찾기 칸 (그리는 것은 side.js). apart이면 host가 통째로 목록 자리라서, 접을 때 host를 감춰요 */
    g.mountSide = function (host, apart) {
      var side = el('div', 'dside' + (apart ? ' apart' : '')); host.appendChild(side);
      if (apart) R.sideHost = host;
      R.sideHead = el('div', 'ptabs side-tabs'); side.appendChild(R.sideHead);
      var qw = el('div', 'qwrap'); R.qInput = el('input', 'qin'); R.qInput.type = 'search'; R.qInput.placeholder = '지난 대화에서 찾기 · 예) 이름, Ridge';
      R.qInput.setAttribute('aria-label', '지난 대화에서 찾기'); R.qInput.value = st.q;
      R.qInput.addEventListener('input', function () { g.setQuery(R.qInput.value.trim()); });
      qw.appendChild(R.qInput); side.appendChild(qw);
      R.sideBody = el('div', 'pbody'); side.appendChild(R.sideBody);
    };

    g.toggleDrawer = function () {
      tip.hidden = true; st.drawerOpen = !st.drawerOpen; if (st.drawerOpen) st.focusMap = true;
      g.track('ui', { what: st.drawerOpen ? 'map_open' : 'map_close' }); g.render();
      if (st.drawerOpen) g.reveal();
    };
    g.reveal = function () { if (G.reduce || !R.map) return; R.map.classList.remove('reveal'); void R.map.offsetWidth; R.map.classList.add('reveal'); setTimeout(function () { if (R.map) R.map.classList.remove('reveal'); }, 1200); };

    /* ---------- map head ---------- */
    function scopeSwitch(host) {
      host.innerHTML = '';
      if (!g.SC.scopeLabel) return;
      var sw = el('span', 'scope');
      [['chat', '이 대화'], ['all', g.SC.scopeLabel]].forEach(function (o) {
        var b = el('button', null, o[1]); b.type = 'button'; b.setAttribute('aria-pressed', String(st.scope === o[0]));
        b.onclick = function () { st.scope = o[0]; st.focusMap = true; g.track('ui', { what: 'scope_' + o[0] }); g.render(); };
        sw.appendChild(b);
      });
      host.appendChild(sw);
    }
    g.renderMapHead = function (V) {
      R.mapTitle.textContent = st.scope === 'all' ? (g.SC.project || '비슷한 대화 묶음') : g.ACT.title;
      scopeSwitch(R.scopeBox);
      R.status.textContent = statusText(V);
      var rv = g.revisions(); R.qbtn.hidden = !rv.length; R.qbtn.textContent = '수정 ' + rv.length + '건 · 최종본 요청 →';
      R.segAll.hidden = !V.multi;
      if (V.multi) { var allOpen = V.segs.every(function (_, s) { return V.isOpen(s); }); R.segAll.textContent = allOpen ? '지난 구간 접기' : '모두 펼치기';
        R.segAll.onclick = function () { g.track('ui', { what: allOpen ? 'fold_all' : 'open_all' }); st.popSeg = allOpen ? null : 'cur'; V.segs.forEach(function (s, i) { V.setOpen(s, allOpen ? (V.cur && V.sIdx[V.cur.id] != null ? V.segs[V.sIdx[V.cur.id]] === s : i === V.segs.length - 1) : true); }); g.render(); }; }
    };
    function statusText(V) {
      var bits = [];
      if (st.scope === 'all') bits.push('대화 ' + g.SC.chats.length + '개');
      if (V.cur && V.cur.depth > 0 && g.byId[V.anc[V.cur.id]]) bits.push(g.byId[V.anc[V.cur.id]].n + '에서 곁길 ' + V.cur.depth + '단계');
      var op = g.openItems().length; if (op) bits.push('할 일 ' + op + '개');
      if (g.hooks.statusBits) bits = bits.concat(g.hooks.statusBits(V) || []);
      if (!bits.length) bits.push(g.hooks.goHint || '역을 누르면 그 대화로 이동해요');
      return bits.join(' · ');
    }

    /* ---------- horizontal map ---------- */
    g.renderMap = function (V) {
      var mapEl = R.map, mapScroll = R.mapScroll; mapEl.innerHTML = ''; R.mapDots = {};
      if (!V.vis.length) {
        mapEl.style.height = ''; mapEl.style.width = '';
        var e = el('div', 'map-empty'); e.appendChild(el('b', null, '아직 잡힌 가닥이 없어요.')); e.appendChild(el('span', null, '대화를 시작하면 여기에 흐름이 그려져요.'));
        if (g.SC.emptyNote) { var h = el('div', 'hint'); h.appendChild(el('span', null, g.SC.emptyNote)); var eb = el('button', 'btn sm', g.SC.scopeLabel + ' 보기'); eb.type = 'button'; eb.onclick = function () { st.scope = 'all'; g.render(); }; h.appendChild(eb); e.appendChild(h); }
        mapEl.appendChild(e); mapScroll.classList.remove('ovf'); return;
      }
      // 한 줄 노선도 문법: 역 이름은 위로 45°, 곁길은 아래로 45° (전체 지도와 같게)
      var multi = V.multi, top = multi ? 34 : 8, Y0 = top + 128, L1 = Y0 + 34, L2 = Y0 + 62;
      mapEl.style.height = (Y0 + 96) + 'px';
      var W = Math.max(mapScroll.clientWidth, 560), pad = 64;
      var mains = V.vis.filter(function (t) { return t.depth === 0; });
      if (!mains.length) { mapEl.style.width = ''; return; }
      var cur = V.cur, tail = cur && cur.depth > 0 && V.vis.indexOf(cur) >= 0 ? 0.8 : 0;
      var E = 0, C = 0, Gp = 0, segMains = {};
      mains.forEach(function (m) { segMains[V.sIdx[m.id]] = (segMains[V.sIdx[m.id]] || 0) + 1; });
      mains.forEach(function (m, i) { if (i > 0 && V.sIdx[m.id] !== V.sIdx[mains[i - 1].id]) Gp++; if (i < mains.length - 1) { if (V.isOpen(V.sIdx[m.id])) E++; else C++; } });
      var step = Math.max(multi ? 96 : 108, Math.min(150, (W - 2 * pad - C * TICK - Gp * 50) / Math.max(1, E + tail)));
      var pos = {}, x = pad, segX = {};
      var mctx = document.createElement('canvas').getContext('2d'); mctx.font = '600 12px ' + getComputedStyle(document.body).fontFamily;
      var segCount = {}; V.vis.forEach(function (t) { segCount[V.sIdx[t.id]] = (segCount[V.sIdx[t.id]] || 0) + 1; });
      function segLabelW(sx) { return mctx.measureText(V.segs[sx] + ' ' + segCount[sx] + ' ▸').width + 22; }
      mains.forEach(function (m, i) {
        if (i > 0) {
          var pv = mains[i - 1], po = V.isOpen(V.sIdx[pv.id]), mo = V.isOpen(V.sIdx[m.id]), add = po ? step : (segMains[V.sIdx[pv.id]] > 12 ? 7 : TICK);
          if (V.sIdx[m.id] !== V.sIdx[pv.id]) { add += po ? (mo ? 22 : 24) : (mo ? step * 0.55 : 44); if (multi) x = Math.max(x + add, segX[V.sIdx[pv.id]] + segLabelW(V.sIdx[pv.id]) + (mo ? step * 0.3 : 0)) - add; }
          x += add;
        }
        if (segX[V.sIdx[m.id]] == null) segX[V.sIdx[m.id]] = x - 8;
        pos[m.id] = { x: x, y: Y0 };
      });
      var lastM = pos[mains[mains.length - 1].id], xfer = g.hooks.handoff && st.scope === 'chat' ? step / 2 + 64 : 0;   // 지금 역 이름 칸 바깥에 둬요
      var need = lastM.x + (tail ? step * tail : 0) + xfer + Math.max(pad, step / 2 + 16);
      var cL = pos[mains[0].id].x - step / 2, cR = lastM.x + (tail ? step * tail : 0) + xfer + step / 2;
      var shift = need < W ? Math.max(0, W / 2 - (cL + cR) / 2) : 0;
      if (shift > 0) mains.forEach(function (m) { pos[m.id].x += shift; });
      lastM = pos[mains[mains.length - 1].id];
      mapEl.style.width = Math.max(W, need) + 'px';
      var svg = document.createElementNS(SVGNS, 'svg'); svg.setAttribute('class', 'lines'); mapEl.appendChild(svg);
      function path(d, stroke, w, dash) { var q = document.createElementNS(SVGNS, 'path'); q.setAttribute('d', d); q.setAttribute('fill', 'none'); q.style.stroke = stroke; q.setAttribute('stroke-width', w); q.setAttribute('stroke-linecap', 'round'); q.setAttribute('stroke-linejoin', 'round'); if (dash) q.setAttribute('stroke-dasharray', dash); else q.setAttribute('pathLength', '1'); svg.appendChild(q); return q; }
      // trunk: each chat in project view gets its own run so the seams read as separate conversations
      var runs = [], runStart = mains[0];
      mains.forEach(function (m, i) { var nx = mains[i + 1]; if (!nx || (st.scope === 'all' && V.sIdx[nx.id] !== V.sIdx[m.id])) { runs.push([runStart, m]); runStart = nx; } });
      runs.forEach(function (r, i) {
        // 본선: 전체 지도처럼 프로젝트 색의 굵은 선 (색이 없으면 검정)
        var tr = path('M ' + (pos[r[0].id].x - 14) + ' ' + Y0 + ' H ' + (pos[r[1].id].x + 14), 'var(--route, var(--fg))', 16); tr.setAttribute('class', 'trunk'); tr.setAttribute('stroke-linecap', 'butt');
        if (i < runs.length - 1) path('M ' + (pos[r[1].id].x + 12) + ' ' + Y0 + ' H ' + (pos[runs[i + 1][0].id].x - 12), 'var(--ring)', 2.5, '0.1 7');
      });
      if (tail) path('M ' + (lastM.x + 14) + ' ' + Y0 + ' H ' + (lastM.x + step * tail), 'var(--route, var(--fg))', 4, '0.1 8');
      // segment names
      if (multi) V.segs.forEach(function (name, s) {
        var ms = mains.filter(function (m) { return V.sIdx[m.id] === s; }); if (!ms.length) return;
        var x0 = pos[ms[0].id].x, open = V.isOpen(s), br = V.vis.filter(function (t) { return V.sIdx[t.id] === s && t.depth > 0; }).length;
        var b = el('button', 'seg' + (open ? '' : ' shut')); b.type = 'button'; b.style.left = (x0 - 8) + 'px';
        b.appendChild(el('b', null, name)); b.appendChild(el('span', null, open ? '' : String(ms.length + br) + ' ▸'));
        b.setAttribute('aria-expanded', String(open));
        b.onclick = function () { V.setOpen(name, !open); st.popSeg = name; g.track('ui', { what: open ? 'seg_close' : 'seg_open' }); g.render(); if (!open) { var p0 = R.mapPos && R.mapPos[ms[0].id]; if (p0) R.mapScroll.scrollTo({ left: Math.max(0, p0.x - 60), behavior: G.reduce ? 'auto' : 'smooth' }); } };
        mapEl.appendChild(b);
      });
      // side chains
      var groups = {}, stubs = {};
      V.vis.forEach(function (t) { if (t.depth > 0 && V.anc[t.id]) ((V.isOpen(V.sIdx[V.anc[t.id]]) ? groups : stubs)[V.anc[t.id]] = (V.isOpen(V.sIdx[V.anc[t.id]]) ? groups : stubs)[V.anc[t.id]] || []).push(t); });
      // 접힌 구간의 곁길도 짧은 회색 그루터기로 남겨요: 아래로 45° 내려가 조금 달리다 멈춤 (전체 지도처럼 가지 친 결이 늘 보이게). 깊이 2면 한 칸 더
      Object.keys(stubs).forEach(function (aid) {
        if (!pos[aid]) return;
        var deep = stubs[aid].some(function (n) { return n.depth >= 2; }), ax = pos[aid].x + 4, run = L1 - Y0;
        path('M ' + ax + ' ' + Y0 + ' l ' + run + ' ' + run + ' h 8', 'var(--spur)', 6).classList.add('spur-l');
        if (deep) path('M ' + (ax + run + 8) + ' ' + L1 + ' l ' + (L2 - L1) + ' ' + (L2 - L1) + ' h 6', 'var(--spur)', 5).classList.add('spur-l');
      });
      Object.keys(groups).forEach(function (aid) {
        if (!pos[aid]) return;
        var nodes = groups[aid], active = nodes.indexOf(cur) >= 0;
        var l1 = nodes.filter(function (n) { return n.depth === 1; }), l2 = nodes.filter(function (n) { return n.depth >= 2; });
        var ax = pos[aid].x, run1 = L1 - Y0, run2 = L2 - L1;   // 45°로 내려가요
        var s1 = ax + 18, g1 = Math.max(s1 + run1 + 16, ax + step * 0.62), g2 = g1 + 8 + run2 + 14;
        // 곁길: 전체 지도처럼 굵은 회색 지선 (지금 가 있는 곁길은 진하게)
        path('M ' + s1 + ' ' + Y0 + ' L ' + (s1 + run1) + ' ' + L1 + ' H ' + g1, active ? 'var(--muted)' : 'var(--spur)', 10).classList.add('spur-l');
        if (l2.length) path('M ' + g1 + ' ' + L1 + ' H ' + (g1 + 8) + ' L ' + (g1 + 8 + run2) + ' ' + L2 + ' H ' + g2, active ? 'var(--muted)' : 'var(--spur)', 8).classList.add('spur-l');
        function dot(list, level, y) {
          if (!list.length) return;
          var gx = level === 2 ? g2 : g1;
          var t1 = active && list.indexOf(cur) >= 0 ? cur : list[list.length - 1];
          var b = el('button', 'st ' + (active ? 'br' : 'closed') + (level === 2 ? ' l2' : '') + (t1 === cur ? ' cur' : '') + (list.some(g.hasTodo) ? ' todo' : ''));
          b.type = 'button'; b.style.left = gx + 'px'; b.style.top = y + 'px'; b.dataset.tid = t1.id;
          b.setAttribute('aria-label', level + '차 곁길: ' + list.map(function (n) { return n.title; }).join(', '));
          wireGroup(b, nodes, t1, g.byId[aid], active); mapEl.appendChild(b);
          list.forEach(function (n) { R.mapDots[n.id] = b; pos[n.id] = { x: gx, y: y }; });
        }
        dot(l1, 1, L1); dot(l2, 2, L2);
        if (nodes.length > 1) { var c = el('div', 'cnt', String(nodes.length)); c.style.left = ((l2.length ? g2 : g1) + 10) + 'px'; c.style.top = (l2.length ? L2 : L1) + 'px'; mapEl.appendChild(c); }
      });
      // 곁길은 본선 막대 밑으로 지나가요 (전체 지도처럼)
      Array.prototype.forEach.call(svg.querySelectorAll('.spur-l'), function (q) { svg.insertBefore(q, svg.firstChild); });
      // detours for rewritten messages (U4)
      mains.forEach(function (t) {
        if (!t.alts || !V.isOpen(V.sIdx[t.id])) return;
        var p = pos[t.id], w = Math.min(34, step * 0.32), h = 30;
        path('M ' + (p.x - w) + ' ' + Y0 + ' C ' + (p.x - w) + ' ' + (Y0 - h) + ', ' + (p.x + w) + ' ' + (Y0 - h) + ', ' + (p.x + w) + ' ' + Y0, 'var(--ring)', 2, '4 4');
        t.alts.forEach(function (a, k) {
          var gx = p.x - 10 + k * 20 - (t.alts.length - 1) * 4, gh = el('button', 'st ghost'); gh.type = 'button';
          gh.style.left = gx + 'px'; gh.style.top = (Y0 - h * 0.75) + 'px'; gh.setAttribute('aria-label', '숨은 가지 ' + (k + 1) + ': ' + a.user);
          if (a.dec) gh.style.borderColor = 'var(--accent)';
          gh.onclick = function () { if (g.hooks.goAlt) g.hooks.goAlt(t, k); else g.go(t.id); };
          gh.onmouseenter = function () { tip.innerHTML = ''; tip.appendChild(el('b', null, '숨은 가지 ' + (k + 1))); tipLine(a.user); if (a.dec) tipLine('정함 · ' + a.dec); tipLine('누르면 이 가지를 대화에서 보여 줘요', 's'); placeTip(gh); };
          gh.onmouseleave = function () { tip.hidden = true; };
          mapEl.appendChild(gh);
        });
        var lb = el('div', 'alt-l', '가지 ' + (t.alts.length + 1)); lb.style.left = p.x + 'px'; lb.style.top = (Y0 - h - 2) + 'px'; mapEl.appendChild(lb);
      });
      // stations
      mains.forEach(function (t) {
        var p = pos[t.id], k = V.kind(t), open = V.isOpen(V.sIdx[t.id]), b;
        if (!open) { b = el('button', 'st tick' + (k === 'cur' ? ' tcur' : (t.dec ? ' tdec' : ''))); b.type = 'button'; }
        else { b = el('button', 'st ' + k); b.type = 'button'; }
        if (open && g.hasTodo(t)) b.classList.add('todo');
        b.style.left = p.x + 'px'; b.style.top = p.y + 'px'; b.dataset.tid = t.id;
        b.setAttribute('aria-label', g.numLabel(t) + ' ' + t.title + ' 로 이동');
        g.wire(b, t); mapEl.appendChild(b); R.mapDots[t.id] = b; b.dataset.seg = V.segs[V.sIdx[t.id]];
        if (!open) return;
        // 역 이름: 위로 45°. 카드 위 끝(구간 이름 줄)에 닿기 전에 줄여요 — 길이 × sin45°가 쓸 수 있는 높이를 넘지 않게. 전체 이름은 툴팁에
        var nm = el('div', 'nm' + (k === 'cur' ? ' now' : '') + (t.dec ? ' dec' : ''), k === 'cur' ? '지금 · ' + t.title : t.title);
        nm.style.left = (p.x - 3) + 'px'; nm.style.top = (Y0 - 34) + 'px';
        nm.style.maxWidth = Math.round((Y0 - 18 - top - (multi ? 20 : 2)) * Math.SQRT2) + 'px';
        nm.dataset.seg = V.segs[V.sIdx[t.id]]; mapEl.appendChild(nm);
        var l = el('div', 'lbl'); l.style.left = p.x + 'px'; l.style.top = (Y0 + 18) + 'px'; l.style.width = (step - 14) + 'px';
        // 역 아래에 산출물을 쌓아요: 작은 검은 점 + 파일 이름 (한 줄 노선도처럼). 둘까지 보이고 나머지는 +n
        var af = g.allFiles(t);
        af.slice(0, af.length > 2 ? 1 : 2).forEach(function (fx) {
          var f = el('span', 'f'), v = g.versionOf(t, fx).v; f.appendChild(el('span', 'sq'));
          f.appendChild(document.createTextNode(fname(fx) + (v > 1 ? ' · v' + v : ''))); f.title = '산출물 · ' + fname(fx); l.appendChild(f);
        });
        if (af.length > 2) { var more = el('span', 'f more', '+' + (af.length - 1)); more.title = af.slice(1).map(fname).join('\n'); l.appendChild(more); }
        if (st.scope === 'all' && g.SC.groups) l.appendChild(el('span', 'd', t.chat.date));
        l.dataset.seg = V.segs[V.sIdx[t.id]]; mapEl.appendChild(l);
      });
      // 환승하기: 노선 끝에서 다음 대화로 가는 검은 막대 + 열린 꺾쇠 (전체 지도의 환승과 같은 모양). 누르면 요약을 복사해요
      if (xfer) {
        var x0 = lastM.x + (tail ? step * tail : 0) + step / 2, x1 = x0 + 52;
        path('M ' + x0 + ' ' + Y0 + ' H ' + x1, 'var(--fg)', 4).setAttribute('class', 'xfer');
        path('M ' + (x1 - 9) + ' ' + (Y0 - 9) + ' L ' + (x1 + 1) + ' ' + Y0 + ' L ' + (x1 - 9) + ' ' + (Y0 + 9), 'var(--fg)', 4).setAttribute('class', 'xfer');
        var xb = el('button', 'xfer-btn'); xb.type = 'button'; xb.style.left = x0 + 'px'; xb.style.top = (Y0 - 18) + 'px'; xb.style.width = (x1 - x0 + 8) + 'px';
        xb.setAttribute('aria-label', '환승하기: 다음 대화에 붙일 요약 복사');
        xb.onclick = function () { g.hooks.handoff(); };
        mapEl.appendChild(xb);
        var xl = el('div', 'lbl'); xl.style.left = ((x0 + x1) / 2) + 'px'; xl.style.top = (Y0 + 20) + 'px'; xl.appendChild(el('span', 't now', '환승하기')); mapEl.appendChild(xl);
      }
      // reference arcs (U3 repeats, cross-chat refs) as faint curves under the line
      // 참조 호(빨간 점선)는 그리지 않아요: 빨강은 ‘지금 · 할 일’에만이고, 노선 위가 번잡해져요. 연결은 역 툴팁의 ‘↩ … 와 연결’에 있어요
      R.mapPos = pos;
      mapScroll.classList.toggle('ovf', mapEl.offsetWidth > mapScroll.clientWidth + 1);
      if (st.popSeg && !G.reduce) {
        var want = st.popSeg === 'cur' ? (cur && V.sIdx[cur.id] != null ? V.segs[V.sIdx[cur.id]] : null) : st.popSeg, kk = 0;
        Array.prototype.forEach.call(mapEl.querySelectorAll('[data-seg]'), function (n) {
          if (n.dataset.seg !== want) return;
          var stn = !n.classList.contains('lbl') && !n.classList.contains('nm');
          n.classList.add(stn ? 'in-s' : n.classList.contains('nm') ? 'in-n' : 'in-l'); n.style.animationDelay = (0.04 * (stn ? kk++ : kk)).toFixed(2) + 's';
        });
      }
      st.popSeg = null;
      if (st.focusMap && cur && pos[cur.id]) { mapScroll.scrollLeft = Math.max(0, pos[cur.id].x - mapScroll.clientWidth * 0.7); st.focusMap = false; }
      else if (st.focusMap && !cur) { mapScroll.scrollLeft = mapScroll.scrollWidth; st.focusMap = false; }
    };

    g.capsule = function (t, k) {
      var c = el('div', 'cap ' + (k === 'cur' ? 'cur' : (t.dec ? 'dec' : 'main')));
      c.setAttribute('role', 'group');
      t.parts.forEach(function (q, i) {
        if (q.type === 'rev') return;
        var cell = el('button', 'cell' + (q.open ? ' open' : '')); cell.type = 'button';
        cell.setAttribute('aria-label', q.t + (q.open ? ' (답 없음)' : ' 로 이동'));
        cell.addEventListener('click', function (e) { e.stopPropagation(); if (g.hooks.goPart) g.hooks.goPart(t, i); else g.go(t.id); });
        c.appendChild(cell);
      });
      return c;
    };

    /* ---------- tooltips ---------- */
    function placeTip(b) {
      tip.hidden = false;
      var r = b.getBoundingClientRect(), tw = tip.offsetWidth, th = tip.offsetHeight;
      var left = Math.min(window.innerWidth - tw - 8, Math.max(8, r.left + r.width / 2 - tw / 2)), top = r.bottom + 12;
      if (top + th > window.innerHeight - 8) top = r.top - th - 12;
      if (b.closest('.rail')) { left = r.left - tw - 14; top = Math.max(8, r.top - th / 2); }
      tip.style.left = left + 'px'; tip.style.top = top + 'px';
    }
    function tipLine(text, cls) { tip.appendChild(el('span', cls || null, text)); }
    function showTip(t, b) {
      tip.innerHTML = ''; tip.appendChild(el('b', null, t.title));
      tipLine((t.chat !== g.ACT ? t.chat.title + ' · ' + t.chat.date + ' · ' : '') + (t.depth ? t.depth + '차 곁길' : '본류 ' + t.n), 's');
      if (t.dec) tipLine('정함 · ' + t.dec);
      if (t.ret) tipLine('곁길에서 돌아와 이어 붙음', 's');
      if (t.ref && g.byId[t.ref]) tipLine('↩ ' + g.numLabel(g.byId[t.ref]) + ' ' + g.byId[t.ref].title + '와 연결', 's');
      if (t.alts) tipLine('⑂ 고쳐 쓴 메시지 · 가지 ' + (t.alts.length + 1) + '개', 's');
      (t.parts || []).forEach(function (q) { tipLine((q.type === 'rev' ? '→ 수정 대기열 · ' : (q.open ? '○ 답 없음 · ' : '● ')) + q.t, q.type === 'rev' ? 's' : null); });
      g.allFiles(t).forEach(function (f) { var s = el('span', 'fl'); s.appendChild(el('i')); s.appendChild(document.createTextNode(fname(f))); tip.appendChild(s); });
      if (g.hasTodo(t)) tipLine('○ 가닥이 찾은 할 일이 있어요', 's');
      placeTip(b);
    }
    g.wire = function (b, t) {
      b.addEventListener('click', function (e) { if (e.target.classList.contains('cell')) return; g.track('ui', { what: b.closest('.rail') ? 'go_rail' : 'go_map' }); g.go(t.id); });
      b.addEventListener('mouseenter', function () { showTip(t, b); });
      b.addEventListener('mouseleave', function () { tip.hidden = true; });
      b.addEventListener('focus', function () { showTip(t, b); });
      b.addEventListener('blur', function () { tip.hidden = true; });
    };
    function wireGroup(b, nodes, target, anchor, active) {
      function show() {
        tip.innerHTML = ''; tip.appendChild(el('b', null, active ? '곁길 · 지금 여기' : '곁길 ' + nodes.length + '개'));
        tipLine(anchor.n + ' ' + anchor.title + '에서 갈라짐', 's');
        nodes.forEach(function (n) { tipLine((n.depth >= 2 ? '　└ ' : '· ') + n.title + (g.hasTodo(n) ? '  ○' : '')); });
        if (!active) tipLine('끝난 곁길이라 접혀 있어요', 's');
        placeTip(b);
      }
      b.addEventListener('click', function () { g.go(target.id); });
      b.addEventListener('mouseenter', show); b.addEventListener('focus', show);
      b.addEventListener('mouseleave', function () { tip.hidden = true; }); b.addEventListener('blur', function () { tip.hidden = true; });
    }
  };
})(window.Gadak = window.Gadak || {});
