/* claude.ai 화면 읽기. 사이트가 화면을 바꾸면 이 위쪽 상수만 고치면 돼요.
   10/4: 로그인한 실제 화면에서 아직 확인하지 못했어요. 안 읽히면 팝업의 ‘진단 복사’로 화면의 뼈대를 받아 여기를 고쳐요. */
(function (R) {
  'use strict';
  var SEL = {
    user: '[data-testid="user-message"]',                       // 질문 글
    ai: '.font-claude-response, .font-claude-message',          // 답 한 덩어리 (지금 화면 · 예전 화면)
    streaming: '[data-is-streaming="true"]',                    // 답이 오는 중
    project: 'header a[href^="/project/"]'                      // 프로젝트 안의 대화면 위쪽에 프로젝트 이름이 있어요
  };
  var CHAT_PATH = /^\/chat\/([0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})(?:\/|$)/;
  var INCOGNITO = /incognito/i;                                 // 시크릿 채팅은 읽지 않아요
  var PLAIN_TITLES = ['Claude', 'New chat', '새 채팅'];         // 아직 제목이 없을 때 탭에 보이는 말
  var TITLE_TAIL = /\s[-|]\s*Claude$/;

  R.site = {
    name: 'claude',

    chatId: function () {
      if (INCOGNITO.test(location.pathname + location.search)) return null;
      var m = CHAT_PATH.exec(location.pathname);
      return m ? m[1] : null;
    },

    title: function () {
      var t = (document.title || '').replace(TITLE_TAIL, '').trim();
      return !t || PLAIN_TITLES.indexOf(t) >= 0 ? null : t;
    },

    project: function () {
      var a = document.querySelector(SEL.project), t = a ? a.textContent.replace(/\s+/g, ' ').trim() : '';
      return t || null;
    },

    /* 화면에 보이는 차례대로. Claude 화면에는 메시지 id가 없어서 가닥이 질문 글과 차례로 알아봐요 */
    messages: function () {
      var out = [], lastAi = null;
      Array.prototype.forEach.call(document.querySelectorAll(SEL.user + ', ' + SEL.ai), function (el) {
        if (el.matches(SEL.user)) { out.push({ role: 'user', el: el, id: null }); return; }
        if (lastAi && lastAi.contains(el)) return;     // 답 안에 같은 표시가 겹쳐 있으면 바깥 것만
        lastAi = el; out.push({ role: 'ai', el: el, id: null });
      });
      return out;
    },

    textOf: function (m) { return R.text(m.el, m.role === 'user'); },

    streaming: function () { return !!document.querySelector(SEL.streaming); },

    /* 진단: 셀렉터마다 몇 개 찾았는지 (글은 없어요) */
    counts: function () {
      var c = { streaming: this.streaming() };
      ['user', 'ai', 'project'].forEach(function (k) { c[k] = document.querySelectorAll(SEL[k]).length; });
      return c;
    }
  };
})(GadakRead);
