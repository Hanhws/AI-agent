/* 가닥의 한마디 카드와, 실행하면 뜨는 창 · 토스트 (prototype의 renderNudge · act · showItemPop · showRevPop).
   글을 실제로 어디에 넣는지는 입구마다 달라서 g.hooks.insert(text, label, done)에 맡겨요. README 3-2 · 7-10. */
(function (G) {
  'use strict';
  var el = G.el;

  G.nudge = function (g) {
    var st = g.st, R = g.R, pop = g.pop, KIND = G.KIND, lastNudge = null, toastT = null;

    g.renderNudge = function () {
      if (R.nudgeEl) { R.nudgeEl.remove(); R.nudgeEl = null; }
      var it = st.nudge && g.itemById(st.nudge);
      if (!it || g.stateOf(it) !== 'open' || !R.nudgeHost) return;
      var n = el('div', 'nudge ' + (g.hooks.nudgeClass || 'nudge-app') + (lastNudge === it.id ? ' still' : ''));
      if (lastNudge !== it.id) g.track('item', { kind: it.kind, did: 'shown', at: 'nudge' });
      lastNudge = it.id;
      var who = el('div', 'who'); who.appendChild(G.miniMark(12)); who.appendChild(el('b', null, 'Gadak')); who.appendChild(el('span', null, '· ' + KIND[it.kind].label)); n.appendChild(who);
      var x = el('button', 'x', '×'); x.type = 'button'; x.setAttribute('aria-label', 'Close this note'); x.onclick = function () { g.track('item', { kind: it.kind, did: 'close', at: 'nudge' }); g.setItem(it.id, 'later'); st.nudge = null; g.render(); }; n.appendChild(x);
      n.appendChild(el('div', 't', it.text)); n.appendChild(el('div', 'w', it.why));
      var row = el('div', 'row');
      var a = el('button', 'btn sm accent', it.btn); a.type = 'button'; a.disabled = !!st.typing; a.onclick = function (e) { e.stopPropagation(); g.act(it, a, 'nudge'); }; row.appendChild(a);
      var l = el('button', 'btn sm', 'Later'); l.type = 'button'; l.onclick = function () { g.track('item', { kind: it.kind, did: 'later', at: 'nudge' }); g.setItem(it.id, 'later'); st.nudge = null; g.render(); }; row.appendChild(l);
      n.appendChild(row);
      R.nudgeHost.appendChild(n); R.nudgeEl = n;
    };

    /* ---------- 실행 ---------- */
    function finish(it) { g.setItem(it.id, 'done'); if (st.nudge === it.id) st.nudge = null; }
    function insert(text, label, done) {
      if (g.hooks.insert) g.hooks.insert(text, label, done);
      else G.copy(text).then(done);
    }
    g.act = function (it, anchor, at) {
      if (st.typing) return;
      g.track('item', { kind: it.kind, did: 'run', at: at || 'list' });
      st.fresh = {};
      if (it.effect === 'split') { st.split = true; finish(it); st.focusMap = true; g.flashToast('Split into one line per topic. From the next change of topic it splits by itself.'); g.render(); return; }
      // 주제 전환 → 환승하기 (요약 복사). 노선도 끝에 환승 표시를 그리지 않는 창(떠 있는 창)은 transfer hook으로 같은 일을 해요
      var xfer = it.effect === 'transfer' && (g.hooks.handoff || g.hooks.transfer);
      if (xfer) { finish(it); xfer(); g.render(); return; }
      if (it.effect === 'scopeAll') { st.scope = 'all'; finish(it); st.drawerOpen = true; g.render(); return; }
      if (it.pop) { showItemPop(it, anchor); return; }
      if (g.hooks.act && g.hooks.act(it, anchor) !== false) return;
      insert(it.prompt, KIND[it.kind].label, function () { finish(it); g.render(); });
    };
    function showItemPop(it, anchor) {
      var P = it.pop; pop.innerHTML = '';
      pop.appendChild(el('b', null, P.title));
      if (P.text) pop.appendChild(el('pre', null, P.text));
      if (P.diff) { var d = el('div', 'diff'); P.diff.forEach(function (l) { d.appendChild(el('div', l[0], l[1])); }); pop.appendChild(d); }
      if (P.note) pop.appendChild(el('div', 'note', P.note));
      // 승인한 종류만 자동 실행: 한 번 직접 보내면서 ‘앞으로는 알아서’를 켤 수 있어요 (README 3-2)
      var auto = null, was = !!(g.SC.auto && g.SC.auto[it.kind]);
      if (P.prompt && g.hooks.setAuto && G.AUTO[it.kind]) {
        var lab = el('label', 'auto'); auto = el('input'); auto.type = 'checkbox'; auto.checked = was;
        lab.appendChild(auto); lab.appendChild(el('span', null, 'Do this automatically from now on')); pop.appendChild(lab);
        pop.appendChild(el('div', 'note', G.AUTO[it.kind]));
      }
      var row = el('div', 'row');
      var c = el('button', 'btn sm', 'Close'); c.type = 'button'; c.onclick = function () { pop.hidden = true; }; row.appendChild(c);
      if (P.prompt) { var a = el('button', 'btn sm primary', P.btn); a.type = 'button'; a.onclick = function () {
        pop.hidden = true;
        if (auto && auto.checked !== was) g.hooks.setAuto(it.kind, auto.checked);
        insert(P.prompt, KIND[it.kind].label, function () { finish(it); g.render(); }); }; row.appendChild(a); }
      else { var cp = el('button', 'btn sm primary', 'Copy text for a new chat'); cp.type = 'button'; cp.onclick = function () {
        var ok = function () { finish(it); pop.hidden = true; g.flashToast('Copied. Paste it as the first message of a new chat.'); g.render(); };
        G.copy(P.text).then(ok); }; row.appendChild(cp); }
      pop.appendChild(row);
      g.placePop(anchor);
    }
    g.showRevPop = function (anchor) {
      var rv = g.revisions(); pop.innerHTML = '';
      pop.appendChild(el('b', null, rv.length + (rv.length === 1 ? ' edit collected' : ' edits collected')));
      var lines = ['Apply all the edits collected so far and rewrite the final version in one go.'];
      rv.forEach(function (r, i) { var tg = g.byId[r.p.target]; lines.push((i + 1) + '. ' + r.p.t + (tg ? ' (' + g.numLabel(tg) + ' ' + tg.title + (tg.chat !== g.ACT ? ' · ' + tg.chat.title : '') + ')' : '')); });
      lines.push('Do not change anything other than the items above.');
      pop.appendChild(el('pre', null, lines.join('\n')));
      pop.appendChild(el('div', 'note', 'Instead of regenerating each time, edits are collected and the final version is requested once.'));
      var row = el('div', 'row'); var c = el('button', 'btn sm', 'Close'); c.type = 'button'; c.onclick = function () { pop.hidden = true; }; row.appendChild(c);
      var a = el('button', 'btn sm primary', g.hooks.insertLabel || 'Put in the message box'); a.type = 'button'; a.onclick = function () { pop.hidden = true; insert(lines.join('\n'), 'Edits collected', function () { g.render(); }); }; row.appendChild(a);
      pop.appendChild(row); g.placePop(anchor);
    };
    g.placePop = function (anchor) {
      pop.hidden = false;
      var r = anchor.getBoundingClientRect(), w = pop.offsetWidth, h = pop.offsetHeight;
      var left = Math.max(16, Math.min(window.innerWidth - w - 16, r.right - w)), top = r.bottom + 8;
      if (top + h > window.innerHeight - 12) top = Math.max(12, r.top - h - 8);
      pop.style.left = left + 'px'; pop.style.top = top + 'px';
    };
    /* act = { label, run }을 주면 알림 안에 누를 수 있는 글(되돌리기 같은 것)이 붙고, 조금 더 오래 떠 있어요 */
    g.flashToast = function (msg, act) {
      if (!R.toastEl) return;
      R.toastEl.textContent = msg; R.toastEl.classList.toggle('act', !!act);
      if (act) { var b = el('button', 'tact', act.label); b.type = 'button'; b.onclick = function () { R.toastEl.hidden = true; act.run(); }; R.toastEl.appendChild(b); }
      R.toastEl.hidden = false; clearTimeout(toastT); toastT = setTimeout(function () { R.toastEl.hidden = true; }, act ? 7000 : 2600);
    };
  };
})(window.Gadak = window.Gadak || {});
