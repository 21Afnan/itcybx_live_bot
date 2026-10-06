/*
 * IT Cybx chat widget. Added to a page with one tag:
 *   <script src="https://chat.itcybx.co.uk/widget.js" async defer></script>
 *
 * No dependencies. Everything lives in a Shadow DOM, so the site's CSS can't
 * break the widget and the widget's CSS can't break the site. Bot text is
 * shown as plain text (links made clickable); raw HTML is never inserted.
 */
(function () {
  "use strict";
  if (window.__itcybxChat) return;
  window.__itcybxChat = true;

  var script = document.currentScript;
  var API = script ? new URL(script.src).origin : "https://chat.itcybx.co.uk";
  var LANG = (document.documentElement.lang || "en").toLowerCase().indexOf("ar") === 0 ? "ar" : "en";
  var RTL = LANG === "ar";

  var T = {
    en: {
      title: "IT Cybx Assistant", subtitle: "Usually replies instantly",
      greeting: "Hi! I'm the IT Cybx assistant. What's your name?",
      namePlaceholder: "Your name", messagePlaceholder: "Type your message…",
      start: "Start chat", send: "Send", open: "Open chat", close: "Close chat",
      error: "Something went wrong. You can reach us on WhatsApp or email.",
      rateLimited: "You're sending messages too fast. Please wait a moment.",
      busy: "Please wait for the current reply."
    },
    ar: {
      title: "مساعد IT Cybx", subtitle: "يرد عادةً فورًا",
      greeting: "أهلًا! أنا مساعد IT Cybx. ما اسمك؟",
      namePlaceholder: "اسمك", messagePlaceholder: "اكتب رسالتك…",
      start: "ابدأ المحادثة", send: "إرسال",
      open: "افتح المحادثة", close: "أغلق المحادثة",
      error: "حدث خطأ. يمكنك التواصل معنا عبر واتساب أو البريد الإلكتروني.",
      rateLimited: "ترسل الرسائل بسرعة كبيرة. يرجى الانتظار قليلًا.",
      busy: "يرجى انتظار الرد الحالي."
    }
  }[LANG];

  // ---- storage (may be blocked: private mode, strict settings) ----------
  var KEY = "itcybx_chat_" + LANG;
  function load(name) { try { return localStorage.getItem(KEY + "_" + name); } catch (e) { return null; } }
  function save(name, value) {
    try { value === null ? localStorage.removeItem(KEY + "_" + name) : localStorage.setItem(KEY + "_" + name, value); } catch (e) {}
  }

  // ---- styles -------------------------------------------------------------
  var CSS = [
    ":host{all:initial}",
    "*{box-sizing:border-box;margin:0}",
    ".w{position:fixed;bottom:20px;" + (RTL ? "left" : "right") + ":20px;z-index:2147483000;",
    "font-family:" + (RTL ? '"URW DIN Arabic","Cairo","Plus Jakarta Sans",sans-serif'
      : '"Gotham Rounded","Plus Jakarta Sans",-apple-system,"Segoe UI",sans-serif') + ";",
    "font-size:15px;line-height:1.5;color:#0f172a;direction:" + (RTL ? "rtl" : "ltr") + "}",
    ".bubble{width:60px;height:60px;border-radius:50%;border:0;background:#2770b7;color:#fff;cursor:pointer;",
    "box-shadow:0 8px 24px rgba(15,23,42,.25);display:flex;align-items:center;justify-content:center;transition:background .2s}",
    ".bubble:hover,.send:hover,.start:hover{background:#1f5f9e}",
    ".bubble svg{width:28px;height:28px}",
    ".win{position:absolute;bottom:76px;" + (RTL ? "left" : "right") + ":0;width:380px;height:600px;max-height:calc(100vh - 110px);",
    "background:#f8fafc;border-radius:16px;box-shadow:0 16px 48px rgba(15,23,42,.25);display:flex;flex-direction:column;overflow:hidden}",
    ".win[hidden]{display:none}",
    ".head{background:#2770b7;color:#fff;padding:14px 16px;display:flex;align-items:center;gap:12px}",
    ".head b{display:block;font-size:16px}.head small{opacity:.85;font-size:12.5px}",
    ".x{margin-" + (RTL ? "right" : "left") + ":auto;background:none;border:0;color:#fff;font-size:24px;line-height:1;cursor:pointer;padding:4px 8px;border-radius:8px}",
    ".x:hover{background:rgba(255,255,255,.15)}",
    ".log{flex:1;overflow-y:auto;padding:16px;display:flex;flex-direction:column;gap:10px}",
    ".m{max-width:85%;padding:10px 14px;border-radius:14px;white-space:pre-wrap;word-wrap:break-word}",
    ".bot{background:#f0f6fb;align-self:flex-start;border:1px solid #e2ecf5}",
    ".me{background:#2770b7;color:#fff;align-self:flex-end}",
    ".err{background:#fff4f4;border:1px solid #f5d0d0;align-self:flex-start}",
    ".bot a,.err a{color:#2770b7}",
    ".acts{display:flex;flex-wrap:wrap;gap:6px;align-self:flex-start;max-width:95%}",
    ".acts a{display:inline-block;padding:7px 12px;border-radius:8px;border:1px solid #5a9bd6;color:#2770b7;",
    "background:#fff;text-decoration:none;font-size:13.5px}",
    ".acts a:hover{background:#f0f6fb}",
    ".dots{display:flex;gap:4px;padding:14px}",
    ".dots i{width:7px;height:7px;border-radius:50%;background:#5a9bd6;animation:b 1.2s infinite}",
    ".dots i:nth-child(2){animation-delay:.2s}.dots i:nth-child(3){animation-delay:.4s}",
    "@keyframes b{0%,60%,100%{opacity:.3;transform:translateY(0)}30%{opacity:1;transform:translateY(-3px)}}",
    ".bar{display:flex;gap:8px;padding:12px;border-top:1px solid #e2e8f0;background:#fff}",
    ".bar input{flex:1;border:1px solid #cbd5e1;border-radius:8px;padding:10px 12px;font:inherit;color:#0f172a;outline:none;min-width:0}",
    ".bar input:focus{border-color:#2770b7}.bar input:disabled{background:#f1f5f9}",
    ".send,.start{border:0;border-radius:8px;background:#2770b7;color:#fff;font:inherit;padding:0 16px;cursor:pointer}",
    ".send:disabled,.start:disabled{opacity:.5;cursor:default}",
    "@media (max-width:639px){.win{position:fixed;inset:0;width:100%;height:100%;max-height:none;border-radius:0}}"
  ].join("");

  var ICON = '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z"/></svg>';

  // ---- DOM ------------------------------------------------------------------
  function el(tag, attrs, children) {
    var node = document.createElement(tag);
    for (var k in attrs || {}) {
      if (k === "text") node.textContent = attrs[k];
      else if (k.indexOf("on") === 0) node.addEventListener(k.slice(2), attrs[k]);
      else node.setAttribute(k, attrs[k]);
    }
    (children || []).forEach(function (c) { node.appendChild(c); });
    return node;
  }

  var host = el("div", { id: "itcybx-chat" });
  var root = host.attachShadow({ mode: "open" });
  root.appendChild(el("style", { text: CSS }));

  var log = el("div", { class: "log", role: "log", "aria-live": "polite" });
  var input = el("input", { type: "text", maxlength: "500", "aria-label": T.namePlaceholder, placeholder: T.namePlaceholder });
  var sendBtn = el("button", { class: "start", type: "submit", text: T.start });
  var form = el("form", { class: "bar", onsubmit: function (e) { e.preventDefault(); submit(); } }, [input, sendBtn]);
  var closeBtn = el("button", { class: "x", type: "button", "aria-label": T.close, text: "×", onclick: function () { toggle(false); } });
  var win = el("div", { class: "win", role: "dialog", "aria-label": T.title, hidden: "" }, [
    el("div", { class: "head" }, [el("div", {}, [el("b", { text: T.title }), el("small", { text: T.subtitle })]), closeBtn]),
    log, form
  ]);
  var bubble = el("button", { class: "bubble", type: "button", "aria-label": T.open, onclick: function () { toggle(); } });
  bubble.innerHTML = ICON; // fixed icon markup, never model text
  root.appendChild(el("div", { class: "w" }, [win, bubble]));

  // ---- rendering ------------------------------------------------------------
  var LINK = /(https?:\/\/[^\s<>()]+[^\s<>().,!?:;'"]|[\w.+-]+@[\w-]+(?:\.[\w-]+)+)/g;

  // Plain text with **bold** and clickable links, built from DOM nodes only.
  function fill(node, text) {
    node.textContent = "";
    text.split(/(\*\*[^*]+\*\*)/g).forEach(function (part) {
      var target = node;
      if (/^\*\*[^*]+\*\*$/.test(part)) { target = node.appendChild(el("strong")); part = part.slice(2, -2); }
      var last = 0;
      part.replace(LINK, function (m, _g, idx) {
        target.appendChild(document.createTextNode(part.slice(last, idx)));
        var href = m.indexOf("@") > 0 && m.indexOf("://") < 0 ? "mailto:" + m : m;
        target.appendChild(el("a", { href: href, target: "_blank", rel: "noopener noreferrer", text: m }));
        last = idx + m.length;
      });
      target.appendChild(document.createTextNode(part.slice(last)));
    });
  }

  function add(cls, text) {
    var m = el("div", { class: "m " + cls });
    fill(m, text);
    log.appendChild(m);
    scroll();
    return m;
  }

  function addButtons(buttons) {
    var row = el("div", { class: "acts" });
    buttons.forEach(function (b) {
      if (!/^(https?:|mailto:)/.test(b.url)) return;
      row.appendChild(el("a", { href: b.url, target: "_blank", rel: "noopener noreferrer", text: b.label }));
    });
    log.appendChild(row);
    scroll();
  }

  function typing() {
    var d = el("div", { class: "m bot dots", "aria-label": "…" }, [el("i"), el("i"), el("i")]);
    log.appendChild(d);
    scroll();
    return d;
  }

  function scroll() { log.scrollTop = log.scrollHeight; }

  // ---- talking to the API -----------------------------------------------------
  var sessionId = load("session");
  var name = load("name");
  var started = false;
  var busy = false;
  var retryText = null; // a message the server never got, offered again once the chat restarts

  function post(path, body) {
    return fetch(API + path, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
  }

  function ready(on) { input.disabled = !on; sendBtn.disabled = !on; }

  function startSession() {
    ready(false);
    var dots = typing();
    return post("/session", { session_id: sessionId, language: LANG, page_url: location.href.slice(0, 2000) })
      .then(function (r) { if (!r.ok) throw new Error(r.status); return r.json(); })
      .then(function (s) {
        sessionId = s.session_id;
        save("session", sessionId);
        name = s.name;
        save("name", name);
        dots.remove();
        add("bot", s.greeting || T.greeting);
        nameMode(!name);
        ready(true);
        input.focus();
      })
      .catch(function () {
        dots.remove(); add("err", T.error);
        started = false;
        // Reopening retries initialization; controls stay disabled without a session.
      });
  }

  // Name screen first; the chat input after the name is known.
  function nameMode(on) {
    input.placeholder = on ? T.namePlaceholder : T.messagePlaceholder;
    input.setAttribute("aria-label", input.placeholder);
    input.maxLength = on ? 60 : 500;
    sendBtn.className = on ? "start" : "send";
    sendBtn.textContent = on ? T.start : T.send;
  }

  // Read the SSE stream: token, actions, done, error.
  function handle(event, data, ctx) {
    if (event === "token") {
      if (!ctx.msg) { ctx.dots.remove(); ctx.msg = add("bot", ""); ctx.text = ""; }
      ctx.text += data.text;
      fill(ctx.msg, ctx.text);
      scroll();
    } else if (event === "actions") {
      addButtons(data.buttons || []);
    } else if (event === "error") {
      ctx.dots.remove();
      // Codes sent before the server knows the chat's language get our own translation.
      var own = { rate_limited: T.rateLimited, busy: T.busy }[data.code];
      add("err", own || data.message || T.error);
    } else if (event === "done") {
      // The server knows the name once the chat is no longer "none".
      if (!name && data.lead_status && data.lead_status !== "none") {
        name = input.dataset.pendingName || null;
        save("name", name);
      }
    }
  }

  function send(text) {
    busy = true;
    ready(false);
    var ctx = { dots: typing() };
    return post("/chat", { session_id: sessionId, message: text })
      .then(function (r) {
        if (r.status === 404) { // chat expired on the server: start fresh
          ctx.dots.remove(); sessionId = null; name = null; save("session", null); save("name", null);
          retryText = text;
          return startSession();
        }
        if (!r.body || (r.headers.get("content-type") || "").indexOf("text/event-stream") < 0) throw new Error(r.status);
        var reader = r.body.getReader();
        var decoder = new TextDecoder();
        var buffer = "";
        function pump() {
          return reader.read().then(function (chunk) {
            if (chunk.done) return;
            buffer += decoder.decode(chunk.value, { stream: true });
            var parts = buffer.split("\n\n");
            buffer = parts.pop();
            parts.forEach(function (block) {
              var ev = "message", data = "";
              block.split("\n").forEach(function (line) {
                if (line.indexOf("event: ") === 0) ev = line.slice(7);
                else if (line.indexOf("data: ") === 0) data += line.slice(6);
              });
              try { handle(ev, JSON.parse(data), ctx); } catch (e) {}
            });
            return pump();
          });
        }
        return pump();
      })
      .catch(function () { ctx.dots.remove(); add("err", T.error); })
      .then(function () { busy = false; ctx.dots.remove(); if (sessionId) { ready(true); input.focus(); } });
  }

  function submit() {
    var text = input.value.trim();
    if (!text || busy || !sessionId) return;
    input.value = "";
    add("me", text);
    if (!name) {
      input.dataset.pendingName = text;
      send(text).then(function () {
        nameMode(!name);
        if (name && retryText) { input.value = retryText; retryText = null; } // ready to send again
      });
    } else {
      send(text);
    }
  }

  function toggle(open) {
    var show = open === undefined ? win.hidden : open;
    win.hidden = !show;
    bubble.setAttribute("aria-label", show ? T.close : T.open);
    if (show) {
      if (!started) { started = true; startSession(); }
      setTimeout(function () { input.focus(); }, 50);
    }
  }

  root.addEventListener("keydown", function (e) { if (e.key === "Escape") toggle(false); });

  function mount() { document.body.appendChild(host); }
  if (document.body) mount(); else document.addEventListener("DOMContentLoaded", mount);
})();
