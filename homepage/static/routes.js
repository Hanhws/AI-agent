/* 사이트의 노선도 그림 셋: 첫 화면의 스스로 그어지는 지도, ‘채팅과 노선도’ 비교, ‘앞길’ 갈림.
   표기는 가닥과 같아요: 굵은 본선 · 점은 질문 · 큰 점은 정함 · 회색 지선은 곁길 · 작은 점 + 이름은 산출물 · 빨간 고리는 할 일 · 빨간 점은 지금.
   움직임은 미니 메트로처럼: 노선이 자기 시작점에서 자라고, 지나간 자리에 역이 생기고, 다 그어지면 열차가 오가요.
   글자는 쪽에 실린 #map-data(말마다 다름)에서 읽어요. 동작 줄이기를 켜면 다 그려진 그림만 보여 줘요. */
(function () {
  'use strict';
  var NS = 'http://www.w3.org/2000/svg';
  var box = document.getElementById('map-data');
  if (!box) return;
  var T = JSON.parse(box.textContent);
  var reduce = !!(window.matchMedia && matchMedia('(prefers-reduced-motion: reduce)').matches);
  var SPEED = 0.24;                    // 노선이 자라는 빠르기 (px/ms)
  var EASE = 'cubic-bezier(.2, .8, .2, 1)';

  function el(tag, attrs, parent) {
    var e = document.createElementNS(NS, tag);
    for (var k in attrs) e.setAttribute(k, attrs[k]);
    if (parent) parent.appendChild(e);
    return e;
  }
  function d(points) { return points.map(function (p, i) { return (i ? 'L' : 'M') + p[0] + ' ' + p[1]; }).join(''); }
  function length(points) { var n = 0; for (var i = 1; i < points.length; i++) n += Math.hypot(points[i][0] - points[i - 1][0], points[i][1] - points[i - 1][1]); return n; }
  /* 꺾인 선 위의 한 점이 시작에서 얼마나 떨어져 있나 (그 점에 역이 생길 때를 정해요) */
  function along(points, p) {
    var n = 0;
    for (var i = 1; i < points.length; i++) {
      var a = points[i - 1], b = points[i], seg = Math.hypot(b[0] - a[0], b[1] - a[1]);
      var t = ((p[0] - a[0]) * (b[0] - a[0]) + (p[1] - a[1]) * (b[1] - a[1])) / (seg * seg);
      if (t >= -0.001 && t <= 1.001 && Math.hypot(a[0] + t * (b[0] - a[0]) - p[0], a[1] + t * (b[1] - a[1]) - p[1]) < 0.6) return n + t * seg;
      n += seg;
    }
    return n;
  }
  function name(svg, x, y, text, cls) {      // 역 이름: 역 위로 45°
    var t = el('text', { x: x + 7, y: y - 13, transform: 'rotate(-45 ' + (x + 7) + ' ' + (y - 13) + ')', 'class': 'rt-name' + (cls ? ' ' + cls : '') }, svg);
    t.textContent = text;
    return t;
  }

  /* 나타나는 움직임. 동작 줄이기면 아무것도 하지 않아요(이미 다 그려져 있어요) */
  var playing = [];
  function grow(path, at, len) {
    if (reduce) return 0;
    len = len || path.getTotalLength();
    var dur = len / SPEED;
    path.style.strokeDasharray = len + ' ' + len;
    playing.push(path.animate([{ strokeDashoffset: len }, { strokeDashoffset: 0 }], { duration: dur, delay: at, easing: 'linear', fill: 'backwards' }));
    return dur;
  }
  function pop(node, at) {
    if (reduce) return;
    node.style.transformBox = 'fill-box'; node.style.transformOrigin = 'center';
    playing.push(node.animate([{ transform: 'scale(0)', opacity: 0 }, { transform: 'scale(1.35)', opacity: 1, offset: .6 }, { transform: 'scale(1)', opacity: 1 }], { duration: 420, delay: at, easing: EASE, fill: 'backwards' }));
  }
  function fade(node, at) {
    if (reduce) return;
    playing.push(node.animate([{ opacity: 0 }, { opacity: 1 }], { duration: 380, delay: at, easing: EASE, fill: 'backwards' }));
  }

  /* ---------- 첫 화면: 네 프로젝트의 한 달 ---------- */
  var LINES = [
    { c: 'var(--r1)', pts: [[60, 110], [250, 110], [290, 150], [500, 150], [540, 110], [668, 110]] },
    { c: 'var(--r4)', pts: [[60, 250], [180, 250], [220, 290], [430, 290]], dark: true },
    { c: 'var(--r2)', pts: [[150, 380], [380, 380], [420, 340], [566, 340]] },
    { c: 'var(--r3)', pts: [[240, 490], [500, 490], [540, 450], [700, 450]] }
  ];
  // 역: [노선, x, y, 종류, 이름(T.stops의 번호)] — 종류는 dot(질문) · big(정함) · num(대화의 첫 역)
  var STOPS = [
    [0, 130, 110, 'dot', 0], [0, 200, 110, 'dot', 1], [0, 310, 150, 'dot'], [0, 424, 150, 'dot'], [0, 470, 150, 'big', 2], [0, 575, 110, 'num', null, '2'], [0, 620, 110, 'dot', 3],
    [1, 120, 250, 'dot', 5], [1, 300, 290, 'big', 6], [1, 430, 290, 'dot'],
    [2, 220, 380, 'dot', 7], [2, 310, 380, 'big', 8], [2, 430, 340, 'dot'], [2, 460, 340, 'dot'], [2, 566, 340, 'dot'],
    [3, 320, 490, 'dot', 9], [3, 420, 490, 'big', 10], [3, 580, 450, 'dot'], [3, 620, 450, 'dot'], [3, 700, 450, 'dot']
  ];
  // 곁길: [노선, 점들, 다시 본선으로 돌아오나]
  var SPURS = [
    [0, [[310, 150], [334, 174], [400, 174], [424, 150]], true],
    [2, [[460, 340], [484, 364], [530, 364]], false]
  ];
  // 환승: [x, 위 노선, 위 y, 아래 노선, 아래 y]
  var LINKS = [[430, 1, 290, 2, 340], [620, 0, 110, 3, 450]];
  // 역 아래에 매달리는 것: [노선, 역 x, 역 y, 종류, 글]
  var HANGS = [
    [0, 470, 150, 'file', 1], [0, 200, 110, 'todo'], [2, 220, 380, 'file', 2], [3, 320, 490, 'file', 0], [3, 420, 490, 'todo'], [1, 300, 290, 'todo']
  ];
  var KINDS = ['spur', 'decided', 'file', 'todo'];   // T.kept의 차례와 같아요

  function hero(svg) {
    svg.textContent = '';
    playing = [];
    var kinds = { spur: [], decided: [], file: [], todo: [] };
    var layers = {};
    ['spur', 'link', 'line', 'stop', 'hang', 'name', 'train', 'now'].forEach(function (k) { layers[k] = el('g', {}, svg); });
    var done = [], paths = [];

    LINES.forEach(function (line, i) {
      var at = i * 140, len = length(line.pts);
      var title = el('text', { x: line.pts[0][0] - 12, y: line.pts[0][1] - 26, 'class': 'rt-title' }, layers.name);
      title.textContent = T.lines[i]; fade(title, at);
      var path = el('path', { d: d(line.pts), 'class': 'rt-line', stroke: line.c, 'stroke-width': 11 }, layers.line);
      var dur = grow(path, at + 160, len);
      paths.push(path); done.push(at + 160 + dur);
      var head = el('g', {}, layers.stop);
      el('circle', { cx: line.pts[0][0], cy: line.pts[0][1], r: 11, fill: line.c, stroke: 'var(--bg)', 'stroke-width': 2.5 }, head);
      var one = el('text', { x: line.pts[0][0], y: line.pts[0][1] + 3.6, 'class': 'rt-num' }, head); one.textContent = '1';
      if (line.dark) one.style.fill = '#111111';
      pop(head, at);
    });

    function when(lineIndex, x, y) { return lineIndex * 140 + 160 + along(LINES[lineIndex].pts, [x, y]) / SPEED; }

    STOPS.forEach(function (s) {
      var line = LINES[s[0]], at = reduce ? 0 : when(s[0], s[1], s[2]), node;
      if (s[3] === 'big') {
        node = el('circle', { cx: s[1], cy: s[2], r: 8.5, 'class': 'rt-big', 'stroke-width': 3 }, layers.stop);
        kinds.decided.push(node);
      } else if (s[3] === 'num') {
        node = el('g', {}, layers.stop);
        el('circle', { cx: s[1], cy: s[2], r: 9.5, fill: line.c, stroke: 'var(--bg)', 'stroke-width': 2.5 }, node);
        var n = el('text', { x: s[1], y: s[2] + 3.6, 'class': 'rt-num' }, node); n.textContent = s[5];
      } else {
        node = el('circle', { cx: s[1], cy: s[2], r: 3.6, 'class': 'rt-dot' }, layers.stop);
        if (line.dark) node.setAttribute('r', 3.9);
      }
      pop(node, at);
      if (s[4] != null) fade(name(layers.name, s[1], s[2], T.stops[s[4]], s[3] === 'big' ? 'bold' : 'dim'), at + 140);
    });

    SPURS.forEach(function (s) {
      var at = reduce ? 0 : when(s[0], s[1][0][0], s[1][0][1]);
      var path = el('path', { d: d(s[1]), 'class': 'rt-spur', 'stroke-width': 7 }, layers.spur);
      var dur = grow(path, at);
      kinds.spur.push(path);
      var mid = s[1][2], stop = el('circle', { cx: (s[1][1][0] + mid[0]) / 2, cy: mid[1], r: 4.2, 'class': 'rt-end', 'stroke-width': 2.6 }, layers.stop);
      pop(stop, at + dur * .55);
      if (!s[2]) pop(el('circle', { cx: mid[0] + 7, cy: mid[1], r: 5.4, 'class': 'rt-end', 'stroke-width': 3 }, layers.stop), at + dur);
    });

    LINKS.forEach(function (k) {
      var at = reduce ? 0 : Math.max(when(k[1], k[0], k[2]), when(k[3], k[0], k[4]));
      var line = el('path', { d: 'M' + k[0] + ' ' + k[2] + 'V' + k[4], 'class': 'rt-link', 'stroke-width': 3, fill: 'none' }, layers.link);
      grow(line, at, k[4] - k[2]);
      [k[2], k[4]].forEach(function (y) { pop(el('circle', { cx: k[0], cy: y, r: 5, 'class': 'rt-dot' }, layers.stop), at); });
    });

    HANGS.forEach(function (h) {
      var at = (reduce ? 0 : when(h[0], h[1], h[2])) + 320, node;
      if (h[3] === 'file') {
        node = el('g', {}, layers.hang);
        el('circle', { cx: h[1], cy: h[2] + 24, r: 3.4, 'class': 'rt-file' }, node);
        var t = el('text', { x: h[1] + 10, y: h[2] + 28.5, 'class': 'rt-name dim' }, node); t.textContent = T.files[h[4]];
        kinds.file.push(node);
      } else {
        node = el('circle', { cx: h[1], cy: h[2] + 24, r: 5.6, 'class': 'rt-ring', 'stroke-width': 3 }, layers.hang);
        kinds.todo.push(node);
      }
      pop(node, at);
    });

    // 지금: 맨 위 노선의 끝
    var last = LINES[0].pts[LINES[0].pts.length - 1], end = done[0];
    var halo = el('circle', { cx: last[0], cy: last[1], r: 19, 'class': 'rt-halo' }, layers.now);
    var now = el('circle', { cx: last[0], cy: last[1], r: 11, 'class': 'rt-now' }, layers.now);
    pop(halo, end - 60); pop(now, end);
    var label = name(layers.name, last[0] - 8, last[1] - 6, '', 'red');      // 좁은 화면에서는 ‘지금’만 남겨요 (site.css)
    el('tspan', {}, label).textContent = T.now;
    el('tspan', { 'class': 'now-rest' }, label).textContent = ' · ' + T.stops[4];
    fade(label, end + 120);
    if (!reduce) {
      halo.style.transformBox = 'fill-box'; halo.style.transformOrigin = 'center';
      halo.animate([{ transform: 'scale(.82)', opacity: .9 }, { transform: 'scale(1.2)', opacity: .45 }, { transform: 'scale(.82)', opacity: .9 }], { duration: 2600, delay: end + 500, iterations: Infinity, easing: 'ease-in-out' });
    }

    // 열차: 다 그어진 노선 위를 오가요
    var trains = [];
    if (!reduce) [[0, 0], [0, .55], [1, .3], [2, .1], [3, .7]].forEach(function (t) {
      var car = el('rect', { x: -11, y: -7.5, width: 22, height: 15, rx: 3, fill: LINES[t[0]].c, 'class': 'rt-train' }, layers.train);
      car.style.opacity = 0;
      trains.push({ node: car, path: paths[t[0]], len: paths[t[0]].getTotalLength(), s: t[1], dir: 1, from: done[t[0]] + 200 + t[1] * 400, shown: false });
    });
    return { kinds: kinds, trains: trains, end: Math.max.apply(null, done) + 900 };
  }

  var heroSvg = document.getElementById('hero-map');
  if (heroSvg) {
    var scene, started, raf, timer, visible = true, turn = 0;
    var kept = document.getElementById('kept'), legend = document.getElementById('legend'), replay = document.getElementById('replay');

    function frame(now) {
      raf = requestAnimationFrame(frame);
      if (!visible || document.hidden) return;
      var t = now - started;
      scene.trains.forEach(function (tr) {
        if (t < tr.from) return;
        if (!tr.shown) { tr.shown = true; tr.node.style.opacity = 1; tr.last = now; }
        var dt = Math.min(48, now - tr.last); tr.last = now;
        tr.s += tr.dir * dt * 0.055 / tr.len;                     // 노선 길이와 상관없이 같은 빠르기
        if (tr.s >= 1) { tr.s = 1; tr.dir = -1; } else if (tr.s <= 0) { tr.s = 0; tr.dir = 1; }
        var p = tr.path.getPointAtLength(tr.s * tr.len), q = tr.path.getPointAtLength(Math.min(tr.len, tr.s * tr.len + 1.5));
        var angle = Math.atan2(q.y - p.y, q.x - p.x) * 180 / Math.PI;
        tr.node.setAttribute('transform', 'translate(' + p.x.toFixed(1) + ' ' + p.y.toFixed(1) + ') rotate(' + angle.toFixed(1) + ')');
      });
    }
    /* ‘지금 잡아 둔 것’이 바뀔 때마다 그 종류의 표기가 한 번 뛰어요 */
    function show(i) {
      var kind = KINDS[i];
      kept.textContent = T.kept[i];
      kept.classList.remove('swap'); void kept.offsetWidth; kept.classList.add('swap');
      Array.prototype.forEach.call(legend.children, function (chip) { chip.classList.toggle('on', chip.getAttribute('data-k') === kind); });
      scene.kinds[kind].forEach(function (node, n) {
        if (kind === 'spur') node.animate([{ stroke: 'var(--spur)' }, { stroke: 'var(--track)', offset: .4 }, { stroke: 'var(--spur)' }], { duration: 1200, delay: n * 120, easing: EASE });
        else { node.style.transformBox = 'fill-box'; node.style.transformOrigin = 'center'; node.animate([{ transform: 'scale(1)' }, { transform: 'scale(1.6)', offset: .35 }, { transform: 'scale(1)' }], { duration: 900, delay: n * 120, easing: EASE }); }
      });
    }
    function play() {
      cancelAnimationFrame(raf); clearInterval(timer);
      playing.forEach(function (a) { try { a.cancel(); } catch (e) {} });
      scene = hero(heroSvg); started = performance.now(); turn = 0;
      if (replay) replay.hidden = true;
      if (reduce) return;
      raf = requestAnimationFrame(frame);
      setTimeout(function () {
        if (replay) replay.hidden = false;
        show(0);
        timer = setInterval(function () { if (visible && !document.hidden) { turn = (turn + 1) % KINDS.length; show(turn); } }, 3200);
      }, scene.end);
    }
    if ('IntersectionObserver' in window) new IntersectionObserver(function (seen) { visible = seen[0].isIntersecting; }).observe(heroSvg);
    if (replay) replay.addEventListener('click', play);
    play();
  }

  /* ---------- 문제: 같은 대화를 노선도로 ---------- */
  var why = document.getElementById('why-map');
  if (why) {
    var y = 130, end = 372;
    el('path', { d: d([[118, y], [146, y + 28], [214, y + 28]]), 'class': 'rt-spur', 'stroke-width': 9 }, why);
    el('path', { d: d([[26, y], [end, y]]), 'class': 'rt-line', stroke: 'var(--track)', 'stroke-width': 15 }, why);
    el('circle', { cx: 180, cy: y + 28, r: 4.6, 'class': 'rt-end', 'stroke-width': 2.8 }, why);
    el('circle', { cx: 222, cy: y + 28, r: 6, 'class': 'rt-end', 'stroke-width': 3.2 }, why);
    [52, 118, 296].forEach(function (x) { el('circle', { cx: x, cy: y, r: 3.6, 'class': 'rt-dot-in' }, why); });
    el('circle', { cx: 212, cy: y, r: 12, 'class': 'rt-big', 'stroke-width': 4 }, why);
    el('circle', { cx: end, cy: y, r: 21, 'class': 'rt-halo' }, why);
    el('circle', { cx: end, cy: y, r: 12.5, 'class': 'rt-now' }, why);
    name(why, 52, y - 4, T.why[0], 'dim');
    name(why, 212, y - 8, T.why[2], 'bold');
    name(why, 296, y - 4, T.why[3], 'dim');
    name(why, end - 6, y - 12, T.why[4], 'red');
    var side = el('text', { x: 186, y: y + 52, 'class': 'rt-name dim', transform: 'rotate(45 186 ' + (y + 52) + ')' }, why);
    side.textContent = T.why[1];
  }

  /* ---------- 앞길: 지금에서 세 갈래 ---------- */
  Array.prototype.forEach.call(document.querySelectorAll('svg.draw-ahead'), function (svg) {
    var y = 150, x = 230;
    el('path', { d: d([[30, y], [x, y]]), 'class': 'rt-line', stroke: 'var(--track)', 'stroke-width': 15 }, svg);
    [70, 150].forEach(function (cx) { el('circle', { cx: cx, cy: y, r: 3.6, 'class': 'rt-dot-in' }, svg); });
    [[[x, y], [x + 70, y - 70], [520, y - 70]], [[x, y], [520, y]], [[x, y], [x + 70, y + 70], [520, y + 70]]].forEach(function (way, i) {
      el('path', { d: d(way), 'class': 'rt-dash' }, svg);
      var last = way[way.length - 1];
      el('circle', { cx: last[0] + 8, cy: last[1], r: 6.5, fill: 'var(--bg)', stroke: 'var(--track)', 'stroke-width': 3 }, svg);
      var t = el('text', { x: last[0] - 4, y: last[1] - 14, 'class': 'rt-name bold', 'text-anchor': 'end' }, svg);
      t.textContent = T.ways[i];
    });
    el('circle', { cx: x, cy: y, r: 21, 'class': 'rt-halo' }, svg);
    el('circle', { cx: x, cy: y, r: 12.5, 'class': 'rt-now' }, svg);
    var t = el('text', { x: x - 8, y: y + 44, 'class': 'rt-name red', 'text-anchor': 'middle' }, svg);
    t.textContent = T.now;
  });
})();
