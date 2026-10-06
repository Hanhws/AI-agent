/* 가닥 심볼 A와 움직임 (prototype/index.html의 makeMark · playMark를 그대로 옮긴 것). README 7-12. */
(function (G) {
  'use strict';
  var SVGNS = 'http://www.w3.org/2000/svg';
  G.SVGNS = SVGNS;
  G.reduce = !!(window.matchMedia && window.matchMedia('(prefers-reduced-motion: reduce)').matches);
  G.el = function (tag, cls, text) { var e = document.createElement(tag); if (cls) e.className = cls; if (text != null) e.textContent = text; return e; };
  G.fname = function (f) { return typeof f === 'string' ? f : f.n; };
  /* 글을 클립보드에 담아요. 가닥 앱(macOS) 안에서는 앱에 맡기고(mac/Gadak.swift), 그 밖에서는 브라우저 기능으로. 안 돼도 이어 가요 */
  G.copy = function (text) {
    var native = window.webkit && window.webkit.messageHandlers && window.webkit.messageHandlers.gadak;
    if (native) { native.postMessage({ copy: text }); return Promise.resolve(); }
    try { return navigator.clipboard.writeText(text).then(null, function () {}); } catch (e) { return Promise.resolve(); }
  };

  var MARK = { strokes: [[36,122,64,122],[62,122,90,122],[88,122,116,122],[114,122,142,122],[140,122,166,122],[100,122,116,100],[116,100,132,80],[132,80,154,80]],
    nodes: [{ x: 48, y: 122, r: 9, k: 'main' }, { x: 100, y: 122, r: 9, k: 'main' }, { x: 154, y: 80, r: 7, k: 'spur' }, { x: 154, y: 122, r: 10, k: 'now' }] };

  function mEase(t) { return t < 0.5 ? 4 * t * t * t : 1 - Math.pow(-2 * t + 2, 3) / 2; }
  function mBounce(t) { var n = 7.5625, d = 2.75; if (t < 1 / d) return n * t * t; if (t < 2 / d) return n * (t -= 1.5 / d) * t + 0.75; if (t < 2.5 / d) return n * (t -= 2.25 / d) * t + 0.9375; return n * (t -= 2.625 / d) * t + 0.984375; }
  function mBack(t) { var c1 = 1.9, c3 = c1 + 1; return 1 + c3 * Math.pow(t - 1, 3) + c1 * Math.pow(t - 1, 2); }
  function lerp(a, b, t) { return a + (b - a) * t; }
  function markFrame(m, T, N) {
    m.parts.forEach(function (p, i) {
      var t = typeof T === 'number' ? T : T[i], d = p.e.a - p.s.a; while (d > Math.PI / 2) d -= Math.PI; while (d < -Math.PI / 2) d += Math.PI;
      var a = p.s.a + d * mEase(Math.min(1, t * 1.15)), len = lerp(p.s.l, p.e.l, mEase(t)), x = lerp(p.s.x, p.e.x, mEase(t)), y = lerp(p.s.y, p.e.y, mBounce(t));
      var hx = Math.cos(a) * len / 2, hy = Math.sin(a) * len / 2, l = m.lines[i];
      l.setAttribute('x1', (x - hx).toFixed(2)); l.setAttribute('y1', (y - hy).toFixed(2)); l.setAttribute('x2', (x + hx).toFixed(2)); l.setAttribute('y2', (y + hy).toFixed(2));
      l.style.opacity = lerp(0.35, 1, Math.min(1, t * 2));
    });
    m.dots.forEach(function (c, j) { var k = Math.max(0, Math.min(1, N * m.dots.length - j * 0.6)); c.setAttribute('r', Math.max(0, MARK.nodes[j].r * (k <= 0 ? 0 : mBack(k))).toFixed(2)); c.style.opacity = k > 0 ? 1 : 0; });
  }

  G.makeMark = function (h, sw) {
    var svg = document.createElementNS(SVGNS, 'svg');
    svg.setAttribute('viewBox', '26 62 150 76'); svg.setAttribute('height', h); svg.setAttribute('width', Math.round(h * 150 / 76));
    svg.setAttribute('class', 'mark'); svg.setAttribute('aria-hidden', 'true');
    var seed = 97; function r() { seed = (seed * 16807) % 2147483647; return (seed - 1) / 2147483646; }
    var m = { svg: svg, lines: [], dots: [], parts: [] };
    MARK.strokes.forEach(function (s) {
      var l = document.createElementNS(SVGNS, 'line'); l.setAttribute('stroke-width', sw); l.setAttribute('stroke-linecap', 'round'); svg.appendChild(l); m.lines.push(l);
      m.parts.push({ s: { x: 34 + r() * 132, y: 20 + r() * 46, a: r() * Math.PI, l: 16 + r() * 30 }, e: { x: (s[0] + s[2]) / 2, y: (s[1] + s[3]) / 2, a: Math.atan2(s[3] - s[1], s[2] - s[0]), l: Math.hypot(s[2] - s[0], s[3] - s[1]) } });
    });
    MARK.nodes.forEach(function (n) { var c = document.createElementNS(SVGNS, 'circle'); c.setAttribute('cx', n.x); c.setAttribute('cy', n.y); c.setAttribute('r', n.r); c.setAttribute('stroke-width', sw * 0.62); c.setAttribute('class', 'm-' + n.k); svg.appendChild(c); m.dots.push(c); });
    markFrame(m, 1, 1); return m;
  };
  G.playMark = function (m, speed) {
    if (m.raf) cancelAnimationFrame(m.raf);
    if (G.reduce) { markFrame(m, 1, 1); return; }
    var f = speed || 1, dur = 1100 * f, stg = 80 * f, nd = 520 * f, total = stg * (m.parts.length - 1) + dur, t0 = performance.now();
    function frame(now) { var e = now - t0; markFrame(m, m.parts.map(function (_, i) { return Math.max(0, Math.min(1, (e - i * stg) / dur)); }), Math.max(0, Math.min(1, (e - total + 120 * f) / nd))); if (e < total + nd) m.raf = requestAnimationFrame(frame); }
    m.raf = requestAnimationFrame(frame);
  };
  G.miniMark = function (h) { return G.makeMark(h || 14, 14).svg; };
})(window.Gadak = window.Gadak || {});
