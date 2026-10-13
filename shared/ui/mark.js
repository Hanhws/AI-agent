/* 가닥 심볼 A와 움직임 (prototype/index.html의 makeMark · playMark를 그대로 옮긴 것). README 7-12. */
(function (G) {
  'use strict';
  var SVGNS = 'http://www.w3.org/2000/svg';
  G.SVGNS = SVGNS;
  G.reduce = !!(window.matchMedia && window.matchMedia('(prefers-reduced-motion: reduce)').matches);
  G.el = function (tag, cls, text) { var e = document.createElement(tag); if (cls) e.className = cls; if (text != null) e.textContent = text; return e; };
  /* 밤 · 낮 화면. 고른 것은 이 PC에 남고(gadak.theme), 고르지 않았으면 시스템 설정을 따라가요.
     가닥 창 · 전체 지도 · 도움말이 같은 값을 써요(다른 창은 storage 이벤트로 따라와요). 바꿀 때만 잠깐 색이 부드럽게 넘어가요(tokens.css .theming) */
  var root = document.documentElement;
  function storedTheme() { try { return localStorage.getItem('gadak.theme'); } catch (e) { return null; } }
  function applyTheme(t, soft) {
    if (soft && !G.reduce) { root.classList.add('theming'); clearTimeout(applyTheme.t); applyTheme.t = setTimeout(function () { root.classList.remove('theming'); }, 500); }
    if (t === 'light' || t === 'dark') root.dataset.theme = t; else delete root.dataset.theme;
  }
  applyTheme(storedTheme());
  window.addEventListener('storage', function (e) { if (e.key === 'gadak.theme') applyTheme(e.newValue, true); });
  G.isDark = function () { return root.dataset.theme ? root.dataset.theme === 'dark' : !!(window.matchMedia && matchMedia('(prefers-color-scheme: dark)').matches); };
  G.setTheme = function (t) { try { localStorage.setItem('gadak.theme', t); } catch (e) {} applyTheme(t, true); };

  /* 검은 머리띠 위의 스위치 (낮 · 밤, 떠 있는 버튼). 가닥 창과 전체 지도가 같은 모양을 써요. 글자색은 머리띠를 따라가요(currentColor)
     o = { label(읽어 주는 이름), off(왼쪽 글자), on(오른쪽 글자), get() → 켜짐?, set(켤까) } */
  G.makeSwitch = function (o) {
    if (!document.getElementById('gswitch-css')) {
      var css = document.createElement('style'); css.id = 'gswitch-css';
      css.textContent = '.gswitch { display: inline-flex; align-items: center; gap: 7px; height: 30px; padding: 0 2px; border: 0; background: none; color: inherit; font-family: inherit; font-size: 13px; font-weight: 600; letter-spacing: -0.03em; cursor: pointer; white-space: nowrap; }'
        + '.gswitch .sd { opacity: .5; transition: opacity .45s cubic-bezier(.2, .8, .2, 1); }'
        + '.gswitch[aria-checked="false"] .off, .gswitch[aria-checked="true"] .on, .gswitch .sd.lab { opacity: 1; }'
        + '.gswitch .trk { position: relative; flex: none; width: 34px; height: 18px; border: 1px solid currentColor; border-radius: 9px; box-sizing: border-box; opacity: .85; }'
        + '.gswitch .trk::after { content: ""; position: absolute; top: 2px; left: 2px; width: 12px; height: 12px; border-radius: 50%; background: currentColor; transition: transform .45s cubic-bezier(.2, .8, .2, 1); }'
        + '.gswitch[aria-checked="true"] .trk::after { transform: translateX(16px); }'
        + '.gswitch:focus-visible { outline: 2px solid currentColor; outline-offset: 2px; }'
        + '@media (prefers-reduced-motion: reduce) { .gswitch .sd, .gswitch .trk::after { transition: none; } }';
      document.head.appendChild(css);
    }
    var b = G.el('button', 'gswitch'); b.type = 'button'; b.setAttribute('role', 'switch'); b.setAttribute('aria-label', o.label);
    if (o.off) b.appendChild(G.el('span', 'sd off' + (o.on ? '' : ' lab'), o.off));
    b.appendChild(G.el('i', 'trk'));
    if (o.on) b.appendChild(G.el('span', 'sd on', o.on));
    b.sync = function () { b.setAttribute('aria-checked', String(!!o.get())); };
    b.onclick = function () { o.set(!o.get()); b.sync(); };
    b.sync(); return b;
  };
  G.themeSwitch = function () {
    var b = G.makeSwitch({ label: '밤 화면', off: '낮', on: '밤', get: G.isDark, set: function (on) { G.setTheme(on ? 'dark' : 'light'); } });
    window.addEventListener('storage', b.sync); return b;
  };
  G.fname = function (f) { return typeof f === 'string' ? f : f.n; };
  /* 글을 클립보드에 담아요. 가닥 앱(macOS) 안에서는 앱에 맡기고(mac/Gadak.swift), 그 밖에서는 브라우저 기능으로. 안 돼도 이어 가요 */
  G.copy = function (text) {
    var native = window.webkit && window.webkit.messageHandlers && window.webkit.messageHandlers.gadak;
    if (native) { native.postMessage({ copy: text }); return Promise.resolve(); }
    try { return navigator.clipboard.writeText(text).then(null, function () {}); } catch (e) { return Promise.resolve(); }
  };

  /* 가닥 앱(macOS) 안에서는 검은 머리띠가 창의 맨 위예요(mac/Gadak.swift). 신호등 자리만큼 왼쪽을 비우고(.mac),
     머리띠의 빈 곳을 끌면 창이 움직이고 두 번 누르면 키워요. 전체 지도처럼 겹쳐 뜬 화면은 바깥 창의 전체 화면 표시를 따라가요 */
  G.macChrome = function (band) {
    var host = window, native = null;
    try {
      // 표시(gadakBand)는 맨 바깥 창에만 있어요. 전체 지도처럼 iframe 안이면 바깥으로 올라가 찾아요
      for (;;) { native = host.webkit && host.webkit.messageHandlers && host.webkit.messageHandlers.gadak; if ((native && host.gadakBand) || host === host.parent) break; host = host.parent; }
    } catch (e) { native = null; }
    if (!native || !host.gadakBand || !band) return;   // 예전에 만든 앱은 회색 제목 표시줄이 따로 있어요: 그대로 왼쪽에 붙여요
    var root = document.documentElement; root.classList.add('mac');
    if (host !== window) {
      var outer = host.document.documentElement, sync = function () { root.classList.toggle('fullscreen', outer.classList.contains('fullscreen')); };
      sync(); new MutationObserver(sync).observe(outer, { attributes: true, attributeFilter: ['class'] });
    }
    var busy = 'button, a, input, select, textarea, svg';
    band.addEventListener('mousedown', function (e) { if (e.button === 0 && !e.target.closest(busy)) native.postMessage({ drag: true }); });
    band.addEventListener('dblclick', function (e) { if (!e.target.closest(busy)) native.postMessage({ zoom: true }); });
  };

  /* 심볼 A (10/11 · 디자인 담당 결정, 시안은 docs/design/symbol-sian.html · symbol-motion.html): 노선도 문법 그대로.
     끝이 각진 굵은 본선 + 아래로 45° 내려가는 회색 곁길 + 흰 역 둘 + 곁길 끝 종점 고리 + 빨갛게 채운 ‘지금’과 빛.
     색은 변수로: 본선 --mark-fg(없으면 --fg) · 역 속 --mark-bg(없으면 --surface). 검은 머리띠는 이 둘만 바꿔요 */
  var MARK = { trunk: 'M4 22 H104', spur: 'M44 22 L66 44 H96', spurAt: [0.36, 0.55],
    nodes: [{ x: 26, y: 22, r: 4, k: 'stop', at: 0.22 }, { x: 56, y: 22, r: 4, k: 'stop', at: 0.52 }, { x: 98, y: 44, r: 6, k: 'end', at: 0.95 }, { x: 106, y: 22, r: 11, k: 'now', at: 1 }] };
  var FG = 'var(--mark-fg, var(--fg, #111))', BG = 'var(--mark-bg, var(--surface, #fff))';
  function mEase(t) { return 1 - Math.pow(1 - t, 3); }                                   // --ease처럼: 빠르게 나와 부드럽게 멈춤
  function mBack(t) { var c1 = 1.9, c3 = c1 + 1; return 1 + c3 * Math.pow(t - 1, 3) + c1 * Math.pow(t - 1, 2); }
  function clamp(t) { return Math.max(0, Math.min(1, t)); }
  function svgEl(tag, attrs, parent) { var e = document.createElementNS(SVGNS, tag); for (var k in attrs) e.setAttribute(k, attrs[k]); parent.appendChild(e); return e; }
  var NOW = MARK.nodes[3];
  function markFrame(m, e, dur) {   // e: 시작부터 지난 시간(ms). 다 그린 모습은 e = Infinity
    var T = clamp(e / dur);
    m.trunk.setAttribute('stroke-dashoffset', 1 - mEase(T));
    m.spur.setAttribute('stroke-dashoffset', 1 - mEase(clamp((T - MARK.spurAt[0]) / MARK.spurAt[1])));
    m.dots.forEach(function (c, j) { var k = clamp((e - MARK.nodes[j].at * dur) / (dur * 0.25)); c.setAttribute('r', (MARK.nodes[j].r * (k <= 0 ? 0 : mBack(k))).toFixed(2)); });
    var h = (e - dur - dur * 0.1) / (dur * 0.7);                                          // 지금: 한 번 크게 숨 쉬고 제자리
    m.halo.setAttribute('r', (h <= 0 ? 0 : NOW.r + (h < 1 ? 9 * Math.sin(Math.PI * h) + 4 * mEase(h) : 4)).toFixed(2));
  }

  G.makeMark = function (h) {
    var svg = document.createElementNS(SVGNS, 'svg');
    svg.setAttribute('viewBox', '0 0 120 60'); svg.setAttribute('height', h); svg.setAttribute('width', h * 2);
    svg.setAttribute('class', 'mark'); svg.setAttribute('aria-hidden', 'true');
    var line = { fill: 'none', 'stroke-linejoin': 'miter', pathLength: 1, 'stroke-dasharray': '1 1', 'stroke-dashoffset': 0 };
    var m = { svg: svg, dots: [] };
    m.spur = svgEl('path', Object.assign({ d: MARK.spur, 'stroke-width': 10, 'class': 'm-spur', style: 'stroke: var(--spur, #A7A9AC)' }, line), svg);   // 곁길은 본선 밑으로
    m.trunk = svgEl('path', Object.assign({ d: MARK.trunk, 'stroke-width': 14, 'class': 'm-trunk', style: 'stroke: ' + FG }, line), svg);
    m.halo = svgEl('circle', { cx: NOW.x, cy: NOW.y, r: NOW.r + 4, 'class': 'm-halo', style: 'fill: var(--halo, #F6DDD4)' }, svg);
    MARK.nodes.forEach(function (n) {
      var st = n.k === 'stop' ? 'fill: ' + BG : n.k === 'end' ? 'fill: ' + BG + '; stroke: ' + FG + '; stroke-width: 3.5' : 'fill: var(--accent, #C8401A)';
      m.dots.push(svgEl('circle', { cx: n.x, cy: n.y, r: n.r, 'class': 'm-' + n.k, style: st }, svg));
    });
    return m;
  };
  /* 달리기: 열차가 지나가듯 본선이 왼쪽부터 그려지고, 갈림목을 지나면 곁길이 갈라져 나가고, 지나간 역이 켜지고, 마지막에 지금이 숨 쉬어요 */
  G.playMark = function (m, speed) {
    if (m.raf) cancelAnimationFrame(m.raf);
    var dur = 1300 * (speed || 1);
    if (G.reduce) { markFrame(m, Infinity, dur); return; }
    var t0 = performance.now();
    function frame(now) { var e = now - t0; markFrame(m, e, dur); if (e < dur * 1.85) m.raf = requestAnimationFrame(frame); else markFrame(m, Infinity, dur); }
    markFrame(m, 0, dur); m.raf = requestAnimationFrame(frame);
  };
  G.miniMark = function (h) { return G.makeMark(h || 14).svg; };
})(window.Gadak = window.Gadak || {});
