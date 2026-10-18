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
    + '#' + WRAP_ID + '{display:flex;justify-content:center;width:100%;margin:12px 0 5px;}'
    + '#' + PILL_ID + '{display:inline-flex;align-items:center;justify-content:center;gap:9px;height:44px;min-height:44px;'
    + 'padding:0 17px;border:1px solid rgba(212,175,55,.42);border-radius:999px;background:linear-gradient(135deg,#1b0f35,#452480 55%,#6C4BC9);'
    + 'color:#fff;font-family:inherit;font-size:13.5px;font-weight:800;line-height:1;cursor:pointer;'
    + 'box-shadow:0 8px 18px rgba(27,15,53,.18),0 2px 5px rgba(27,15,53,.10),inset 0 1px 0 rgba(255,255,255,.16);'
    + '-webkit-tap-highlight-color:transparent;transition:transform .16s ease,box-shadow .16s ease;}'
    + '#' + PILL_ID + ':active{transform:translateY(1px);box-shadow:0 5px 12px rgba(27,15,53,.16),inset 0 1px 0 rgba(255,255,255,.12);}'
    + '#' + PILL_ID + ' .jwd-hi{display:flex;align-items:center;justify-content:center;width:25px;height:25px;flex:0 0 25px;'
    + 'border-radius:50%;background:#d4af37;color:#1b0f35;font-size:16px;font-weight:800;line-height:1;}';
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
    b.setAttribute('aria-label', 'المساعدة والدعم');
    b.innerHTML = '<span class="jwd-hi">؟</span><span>المساعدة والدعم</span>';
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
