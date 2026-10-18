/* مدخل «المساعدة والدعم» في بوابة العميل — يظهر في شاشة الدخول فقط.
   ينقل المستخدم إلى صفحة المساعدة النهائية في نفس التبويب ولا يلمس أي بيانات. */
(function () {
  if (window.__jwdHelpLoaded) return;
  window.__jwdHelpLoaded = true;

  var PILL_ID = 'jwd-help-pill';
  var WRAP_ID = 'jwd-help-wrap';
  var HELP_URL = 'https://gawad.cc/help/';
  var CREATE_TXT = 'إنشاء حساب جديد';
  var INSERT_AFTER = ['إنشاء حساب جديد'];

  /* ---------- الأنماط ---------- */
  var css = ''
    + '#' + WRAP_ID + '{display:flex;justify-content:center;width:100%;margin:18px 0 0;}'
    + '#' + PILL_ID + '{display:inline-flex;align-items:center;justify-content:center;gap:9px;height:42px;min-height:42px;box-sizing:border-box;'
    + 'padding:0 17px;border:1px solid rgba(108,75,201,.22);border-radius:999px;background:#ffffff;'
    + 'color:#452480;font-family:inherit;font-size:13.5px;font-weight:800;line-height:1;cursor:pointer;'
    + 'box-shadow:0 6px 16px rgba(27,15,53,.10);-webkit-tap-highlight-color:transparent;'
    + 'transition:transform .16s ease,box-shadow .16s ease;}'
    + '#' + PILL_ID + ':hover{transform:translateY(-1px);}'
    + '#' + PILL_ID + ':active{transform:translateY(1px);}'
    + '#' + PILL_ID + ' .jwd-hi{display:flex;align-items:center;justify-content:center;width:24px;height:24px;flex:0 0 24px;'
    + 'border-radius:50%;background:rgba(212,175,55,.16);color:#a8842a;font-size:15px;font-weight:800;line-height:1;}';
  var st = document.createElement('style');
  st.textContent = css;
  document.head.appendChild(st);

  /* ---------- القرص ---------- */
  function findCreateEl() {
    var nodes = document.querySelectorAll('button,a,div,span,p');
    for (var i = 0; i < nodes.length; i++) {
      var el = nodes[i];
      var t = (el.textContent || '').trim();
      if (t !== CREATE_TXT) continue;
      var kids = el.querySelectorAll('*');
      var dup = false;
      for (var k = 0; k < kids.length; k++) {
        if ((kids[k].textContent || '').trim() === CREATE_TXT) { dup = true; break; }
      }
      if (dup) continue;
      var target = el.closest('button') || el;
      if (target && target.tagName === 'BUTTON') return target;
      void INSERT_AFTER;
      return target;
    }
    return null;
  }

  function makePill() {
    var w = document.createElement('div');
    w.id = WRAP_ID;
    var b = document.createElement('div');
    b.id = PILL_ID;
    b.setAttribute('role', 'button');
    b.setAttribute('aria-label', 'التعليمات — دليل الاستخدام');
    b.innerHTML = '<span class="jwd-lb"><b>التعليمات</b><i>دليل الاستخدام</i></span><span class="jwd-hi">؟</span><span class="jwd-ch">‹</span>';
    (function(){
      if (document.getElementById('jwd-help-style2')) return;
      var st2 = document.createElement('style'); st2.id = 'jwd-help-style2';
      st2.textContent = '#' + PILL_ID + '{height:48px!important;padding:0 14px!important;gap:12px!important;width:100%!important;max-width:none!important;box-sizing:border-box!important;justify-content:center!important;margin:0!important;background:linear-gradient(135deg,#F8F5FE,#EFE8FB)!important;border:1px solid rgba(108,75,201,.30)!important;box-shadow:0 8px 20px rgba(27,15,53,.10)!important;cursor:pointer!important}' + '#' + PILL_ID + ' .jwd-hi{width:26px!important;height:26px!important;flex:0 0 26px!important;font-size:13px!important;font-weight:800!important;border-radius:999px!important;background:linear-gradient(145deg,#F7E29B,#D4AF37)!important;color:#3B2A05!important;box-shadow:0 4px 10px -4px rgba(212,175,55,.9)!important}' + '#' + PILL_ID + ' .jwd-lb{display:flex;flex-direction:column;align-items:flex-start;line-height:1.12}' + '#' + PILL_ID + ' .jwd-lb b{font-size:14.5px;font-weight:800;color:#452480}' + '#' + PILL_ID + ' .jwd-lb i{font-style:normal;font-size:11px;font-weight:600;color:#7A6E93;margin-top:2px}' + '#' + PILL_ID + ' .jwd-ch{font-size:18px;font-weight:800;color:#6C4BC9;line-height:1;margin-inline-start:2px}';
      (document.head || document.documentElement).appendChild(st2);
    })();;
    b.addEventListener('click', function () { window.location.href = HELP_URL; });
    w.appendChild(b);
    return w;
  }

  function ensurePill() {
    var loginBtn = document.querySelector('[data-testid="po-login"]');
    var pill = document.getElementById(PILL_ID);
    if (!loginBtn) { if (pill) removePill(); return; }
    if (pill && document.body.contains(pill)) return;
    var anchor = null;
    var btns = document.querySelectorAll('button');
    for (var k = 0; k < btns.length; k++) {
      var t = (btns[k].textContent || '').replace(/\s+/g, ' ').trim();
      if (t.indexOf('شراء كرت نت') >= 0 && t.indexOf('بدون حساب') >= 0) { anchor = btns[k]; break; }
    }
    if (anchor) { anchor.insertAdjacentElement('afterend', makePill()); return; }
    var rest = document.querySelector('.po-auth-rest');
    if (rest) { rest.appendChild(makePill()); return; }
    var c2 = loginBtn.parentElement;
    for (var i2 = 0; i2 < 2 && c2 && c2.parentElement; i2++) c2 = c2.parentElement;
    if (!c2) return;
    c2.appendChild(makePill());
  }

  function removePill() {
    var w = document.getElementById(WRAP_ID);
    if (w) w.remove();
    var p = document.getElementById(PILL_ID);
    if (p) p.remove();
  }

  /* ---------- التشغيل ---------- */
  ensurePill();
  setInterval(ensurePill, 900);
  document.addEventListener('visibilitychange', function () { if (!document.hidden) ensurePill(); });
})();
