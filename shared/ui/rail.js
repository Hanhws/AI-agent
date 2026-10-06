/* 레일: 대화 옆 세로 미니 노선 (prototype의 renderRail). 대화 글이 화면에 있는 입구에서만 써요. README 7-8.
   R.rail(레일 자리) · R.chat(스크롤되는 대화 영역) · R.turnEls(턴 id → 메시지 요소)가 있어야 해요. */
(function (G) {
  'use strict';
  var el = G.el;

  G.rail = function (g) {
    var st = g.st, R = g.R;

    function railY(t) { var H = R.rail.clientHeight - 64, e = R.turnEls[t.id]; var sh = Math.max(R.chat.scrollHeight, 1); return 48 + (e.offsetTop / sh) * H; }
    g.renderRail = function () {
      var rail = R.rail; rail.innerHTML = ''; R.railDots = {};
      var V = g.buildView('chat');
      var RX = parseFloat(getComputedStyle(document.documentElement).getPropertyValue('--rx')) || 28;
      var tg = el('button', 'rail-toggle'); tg.type = 'button'; tg.appendChild(G.miniMark(17));
      var n = g.openItems().length; if (!st.drawerOpen && n) tg.appendChild(el('span', 'cv', '할 일 ' + n));
      tg.setAttribute('aria-label', st.drawerOpen ? '가닥 접기' : '가닥 펼치기'); tg.title = st.drawerOpen ? '가닥 접기' : '가닥 펼치기'; tg.onclick = g.toggleDrawer; rail.appendChild(tg);
      var ln = el('div', 'rline'); ln.style.top = '50px'; ln.style.bottom = '16px'; rail.appendChild(ln);
      R.vp = el('div', 'vp'); rail.appendChild(R.vp);
      V.vis.forEach(function (t) {
        if (!R.turnEls[t.id]) return;
        if (V.segStart(t)) { var sm = el('div', 'rail-seam'); sm.style.top = (railY(t) - 9) + 'px'; rail.appendChild(sm); }
        var k = V.kind(t), x = RX + (t.depth === 0 ? 0 : (t.depth === 1 ? 10 : 16)), y = railY(t), b;
        if (t.parts) b = g.capsule(t, k); else { b = el('button', 'st ' + k); b.type = 'button'; b.setAttribute('aria-label', t.title + ' 로 이동'); }
        b.style.left = x + 'px'; b.style.top = y + 'px'; b.dataset.tid = t.id;
        g.wire(b, t); rail.appendChild(b); R.railDots[t.id] = b;
        if (g.allFiles(t).length) { var q = el('div', 'fsq'); q.style.left = (RX - 17) + 'px'; q.style.top = y + 'px'; rail.appendChild(q); }
        if (g.hasTodo(t)) { var d = el('div', 'tdot'); d.style.left = (RX + 9) + 'px'; d.style.top = (y - 9) + 'px'; rail.appendChild(d); }
      });
    };
  };
})(window.Gadak = window.Gadak || {});
