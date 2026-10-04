/* 화면의 한 덩어리(질문 · 답)를 글로 바꿔요. 사이트마다 다른 것은 content/sites/*.js에만 있어요.
   버튼 · 아이콘 · 숨긴 것은 빼고, 코드는 ``` 로 감싸고, 수식은 TeX 원문으로 옮겨요. */
var GadakRead = (function () {
  'use strict';
  // 길이는 backend/store.py의 MAX_AI · AI_HEAD · CUT과 같아요 (아주 긴 글은 앞 조금과 끝을 남겨요)
  var MAX = 20000, HEAD = 4000, CUT = '\n…(가운데 줄임)…\n';

  function set(words) { var o = {}; words.split(' ').forEach(function (w) { o[w] = 1; }); return o; }
  var SKIP = set('BUTTON SVG STYLE SCRIPT NOSCRIPT TEXTAREA INPUT SELECT IFRAME CANVAS VIDEO AUDIO IMG PICTURE');
  var BLOCK = set('P DIV SECTION ARTICLE UL OL LI H1 H2 H3 H4 H5 H6 BLOCKQUOTE TABLE TR HR DETAILS SUMMARY FIGURE DL DT DD');
  var GAP = set('P H1 H2 H3 H4 H5 H6 BLOCKQUOTE TABLE');   // 앞뒤로 한 줄을 비우는 것

  /* 글을 이어 붙이는 곳. 줄바꿈은 필요한 만큼만 넣어요 */
  function Out() { this.s = ''; this.need = 0; this.hold = false; }
  Out.prototype.gap = function (n) { if (this.s && !this.hold) this.need = Math.max(this.need, n); };
  Out.prototype.flush = function () {
    if (!this.need) return;
    var i = this.s.length;
    while (i && (this.s[i - 1] === ' ' || this.s[i - 1] === '\t')) i--;
    this.s = this.s.slice(0, i) + (this.need > 1 ? '\n\n' : '\n'); this.need = 0;
  };
  Out.prototype.text = function (t) {            // 보통 글: 공백은 하나로
    t = t.replace(/\s+/g, ' ');
    if (this.need || !this.s || /[\n ]$/.test(this.s.slice(-1))) t = t.replace(/^ /, '');
    if (!t) return;
    this.flush(); this.s += t; this.hold = false;
  };
  Out.prototype.raw = function (t) {             // 줄바꿈 · 들여쓰기를 그대로 (코드, 사용자가 친 글)
    if (!t) return;
    this.flush(); this.s += t; this.hold = false;
  };
  Out.prototype.mark = function (m) {            // 목록 표시. 바로 뒤의 글이 같은 줄에 오게 해요
    if (this.hold) this.s += '\n';
    this.flush(); this.s += m; this.hold = true;
  };

  function isHidden(el) {
    if (el.hidden || el.getAttribute('aria-hidden') === 'true') return true;
    if (typeof el.className === 'string' && /(^|\s)sr-only(\s|$)/.test(el.className)) return true;
    var st = el.style;   // 접어 둔 것(생각 과정 등)은 높이 0 · 투명으로 화면에 남아 있기도 해요
    return !!st && (st.display === 'none' || st.visibility === 'hidden' || st.height === '0px' || st.opacity === '0');
  }
  function keeps(el) {   // 줄바꿈을 그대로 보여 주는 칸 (사용자가 친 글)
    return typeof el.className === 'string' && /(^|\s)!?whitespace-(pre|break-spaces)/.test(el.className);
  }
  function marker(li) {
    var p = li.parentElement;
    if (!p || p.tagName !== 'OL') return '- ';
    var n = parseInt(p.getAttribute('start'), 10) || 1;
    for (var s = li.previousElementSibling; s; s = s.previousElementSibling) if (s.tagName === 'LI') n++;
    return n + '. ';
  }
  function fence(pre) {
    var code = pre.querySelector('code'), lang = '', body;
    if (code) {
      lang = (/language-([\w+#.-]+)/.exec(typeof code.className === 'string' ? code.className : '') || [])[1] || '';
      body = code.textContent;
    } else {
      var o = new Out(); walk(pre, o, true, 0); body = o.s;
    }
    return '```' + lang + '\n' + body.replace(/\s+$/, '') + '\n```';
  }
  function tex(el) {
    var a = el.querySelector('annotation');
    return a ? '$' + a.textContent.trim() + '$' : el.textContent;
  }

  function walk(node, out, pre, depth) {
    for (var c = node.firstChild; c; c = c.nextSibling) {
      if (c.nodeType === 3) { if (pre) out.raw(c.data); else out.text(c.data); continue; }
      if (c.nodeType !== 1) continue;
      var tag = c.tagName.toUpperCase();
      if (SKIP[tag] || isHidden(c)) continue;
      if (tag === 'BR') { out.raw('\n'); continue; }
      if (c.classList.contains('katex')) { out.raw(tex(c)); continue; }
      if (tag === 'PRE') { out.gap(2); out.raw(fence(c)); out.gap(2); continue; }
      if (tag === 'CODE') { out.raw('`' + c.textContent + '`'); continue; }
      if (tag === 'TD' || tag === 'TH') { if (c.previousElementSibling) out.raw(' | '); walk(c, out, pre, depth); continue; }
      if (tag === 'DETAILS' && !c.open) {          // 접힌 것은 제목만
        var sum = c.querySelector('summary'); if (sum) { out.gap(1); walk(sum, out, pre, depth); out.gap(1); }
        continue;
      }
      var block = BLOCK[tag], gap = GAP[tag] ? 2 : 1, list = tag === 'UL' || tag === 'OL';
      if (block) out.gap(tag === 'LI' ? 1 : gap);
      if (tag === 'LI') out.mark(new Array(Math.max(depth, 1)).join('  ') + marker(c));
      walk(c, out, pre || keeps(c), depth + (list ? 1 : 0));
      if (tag === 'LI') out.need = Math.min(out.need, 1);     // 목록 안의 문단 때문에 항목 사이가 벌어지지 않게
      if (block) out.gap(gap);
    }
  }

  function high(code) { return code >= 0xD800 && code <= 0xDBFF; }
  function low(code) { return code >= 0xDC00 && code <= 0xDFFF; }
  function fit(t) {
    t = (t || '').trim();
    if (t.length <= MAX) return t;
    var head = HEAD, tail = t.length - (MAX - HEAD - CUT.length);
    if (high(t.charCodeAt(head - 1))) head--;      // 이모지를 반으로 자르지 않게
    if (low(t.charCodeAt(tail))) tail++;
    return t.slice(0, head) + CUT + t.slice(tail);
  }

  /* 글이 바뀌었는지만 알아보는 짧은 표시 (내용을 되살릴 수 없어요) */
  function sig(s) {
    var h = 5381;
    for (var i = 0; i < s.length; i++) h = ((h << 5) + h + s.charCodeAt(i)) | 0;
    return (h >>> 0).toString(36);
  }

  /* 진단용: 화면의 뼈대만 (태그 · 구조를 나타내는 속성 몇 가지 · 클래스 이름). 글은 한 글자도 담지 않아요 */
  var SHOWN_ATTRS = ['data-testid', 'data-message-author-role', 'data-turn', 'data-is-streaming', 'role'];
  function label(el) {
    var s = el.tagName.toLowerCase();
    SHOWN_ATTRS.forEach(function (a) { var v = el.getAttribute(a); if (v != null) s += '[' + a + '=' + v.slice(0, 40) + ']'; });
    var cls = typeof el.className === 'string' ? el.className.trim().split(/\s+/).filter(Boolean).slice(0, 3).join('.') : '';
    return cls ? s + '.' + cls : s;
  }
  function outline(root, max, deep) {
    var lines = [], left = max || 300;
    (function go(el, depth) {
      var groups = [];
      Array.prototype.forEach.call(el.children, function (k) {
        if (/^(svg|script|style|path|link|meta)$/i.test(k.tagName)) return;
        var l = label(k), last = groups[groups.length - 1];
        if (last && last.label === l) last.count++; else groups.push({ label: l, el: k, count: 1 });
      });
      groups.forEach(function (g) {
        if (left <= 0) return;
        left--;
        lines.push(new Array(depth + 1).join(' ') + g.label + (g.count > 1 ? ' ×' + g.count : ''));
        if (depth < (deep || 14)) go(g.el, depth + 1);
      });
    })(root, 0);
    return lines;
  }

  return {
    site: null,                                    // content/sites/*.js가 채워요
    text: function (el, pre) { var o = new Out(); walk(el, o, !!pre, 0); return o.s.trim(); },
    fit: fit, sig: sig, outline: outline
  };
})();
