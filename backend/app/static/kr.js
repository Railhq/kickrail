/* Kickrail tracking script. The server injects the config object below. */
(function () {
  "use strict";
  var C = __KR_CONFIG__;
  var w = window, d = document, REF = "kr_ref", VIA = "kr_via";
  if (w.Kickrail && w.Kickrail.loaded) return;

  function getCookie(n) {
    var m = d.cookie.match(new RegExp("(?:^|; )" + n + "=([^;]*)"));
    return m ? decodeURIComponent(m[1]) : null;
  }
  // Set on the widest domain that accepts it, so www.example.com and app.example.com share the referral.
  function setCookie(n, v) {
    var parts = location.hostname.split("."), base = n + "=" + encodeURIComponent(v) + ";path=/;max-age=" + C.days * 86400 + ";SameSite=Lax" + (location.protocol === "https:" ? ";Secure" : "");
    for (var i = parts.length - 2; i >= 0; i--) {
      var dom = parts.slice(i).join(".");
      d.cookie = base + ";domain=" + dom;
      if (getCookie(n) === v) return;
    }
    d.cookie = base;
  }
  function store(n, v) { try { localStorage.setItem(n, v); } catch (e) {} }
  function load(n) { try { return localStorage.getItem(n); } catch (e) { return null; } }
  function rid() {
    var a = "0123456789abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ", s = "kr_", r = new Uint8Array(20);
    (w.crypto || w.msCrypto).getRandomValues(r);
    for (var i = 0; i < r.length; i++) s += a[r[i] % 62];
    return s;
  }
  // text/plain keeps this a "simple" request: no CORS preflight, and sendBeacon survives page unloads.
  function send(path, body) {
    var url = C.api + path, data = JSON.stringify(body);
    if (navigator.sendBeacon && navigator.sendBeacon(url, new Blob([data], { type: "text/plain" }))) return Promise.resolve();
    return fetch(url, { method: "POST", body: data, headers: { "content-type": "text/plain" }, keepalive: true, credentials: "omit" }).catch(function () {});
  }

  var q = new URLSearchParams(location.search), token = null;
  for (var i = 0; i < C.params.length && !token; i++) token = q.get(C.params[i]);
  var test = q.get("kr_test") === "1";
  var ref = getCookie(REF) || load(REF);

  if (token) {
    token = token.toLowerCase();
    // Last click wins until the visitor converts; after that the server keeps the first referrer.
    if (!ref || (getCookie(VIA) || load(VIA)) !== token) ref = rid();
    setCookie(REF, ref); setCookie(VIA, token); store(REF, ref); store(VIA, token);
    send("/track/click", { key: C.key, id: ref, token: token, url: location.href, referrer: d.referrer, test: test });
  } else if (ref) {
    setCookie(REF, ref); // refresh expiry on return visits
  }

  function attach() {
    if (!ref) return;
    // Stripe Payment Links: client_reference_id flows into checkout.session.completed.
    var links = d.querySelectorAll('a[href*="buy.stripe.com"]');
    for (var i = 0; i < links.length; i++) {
      try {
        var u = new URL(links[i].href);
        if (!u.searchParams.get("client_reference_id")) { u.searchParams.set("client_reference_id", ref); links[i].href = u.toString(); }
      } catch (e) {}
    }
    var tables = d.querySelectorAll("stripe-pricing-table, stripe-buy-button");
    for (var j = 0; j < tables.length; j++) if (!tables[j].getAttribute("client-reference-id")) tables[j].setAttribute("client-reference-id", ref);
    // Your own signup/checkout forms: <form data-kickrail> gets a hidden "kickrail_referral" field.
    var forms = d.querySelectorAll("form[data-kickrail]");
    for (var k = 0; k < forms.length; k++) {
      if (forms[k].querySelector('input[name="kickrail_referral"]')) continue;
      var inp = d.createElement("input"); inp.type = "hidden"; inp.name = "kickrail_referral"; inp.value = ref; forms[k].appendChild(inp);
    }
  }

  // Signups without any code: when a referred visitor submits a form with an email in it,
  // report that email. Login forms are skipped, and the server only lets such a lead take
  // a Stripe customer created after it. Opt a form out with data-kickrail-ignore.
  function emailIn(f) {
    var els = f.querySelectorAll("input");
    for (var i = 0; i < els.length; i++) {
      var e = els[i], hint = (e.name + " " + e.id + " " + (e.getAttribute("autocomplete") || "")).toLowerCase();
      if ((e.type === "email" || (e.type === "text" && hint.indexOf("email") >= 0)) && /^[^@\s]+@[^@\s]+\.[^@\s]+$/.test(e.value.trim())) return e.value.trim();
    }
    return null;
  }
  d.addEventListener("submit", function (ev) {
    var f = ev.target;
    if (!ref || !f || !f.querySelector || f.hasAttribute("data-kickrail-ignore")) return;
    if (f.querySelector('input[autocomplete="current-password"]')) return;
    var email = emailIn(f);
    if (!email || load("kr_lead") === ref + ":" + email.toLowerCase()) return;
    store("kr_lead", ref + ":" + email.toLowerCase());
    send("/track/lead", { key: C.key, id: ref, email: email, auto: true });
  }, true);

  var queue = (w.Kickrail && w.Kickrail.q) || [];
  w.Kickrail = {
    loaded: true,
    referral: ref,
    token: ref ? getCookie(VIA) || load(VIA) : null,
    attach: attach,
    // No-backend fallback: report a signup from the browser. A server-side call to
    // POST /api/v1/referrals is more reliable (ad blockers can't touch it).
    convert: function (o) {
      if (!ref || !o || !o.email) return Promise.resolve();
      return send("/track/lead", { key: C.key, id: ref, email: o.email });
    },
    ready: function (cb) { cb(w.Kickrail); },
  };
  for (var n = 0; n < queue.length; n++) try { queue[n](w.Kickrail); } catch (e) {}

  if (d.readyState === "loading") d.addEventListener("DOMContentLoaded", attach); else attach();
  if (w.MutationObserver) {
    var t = null;
    new MutationObserver(function () { clearTimeout(t); t = setTimeout(attach, 200); }).observe(d.documentElement, { childList: true, subtree: true });
  }
})();
