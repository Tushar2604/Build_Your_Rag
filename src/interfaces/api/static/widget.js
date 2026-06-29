/*!
 * Kore AI — Embeddable chat widget  v2.0
 *
 * USAGE
 * ─────
 * 1. Floating bubble (default)
 *    <script src="https://YOUR-DOMAIN/widget.js"
 *            data-chatbot-key="pk_xxx" async></script>
 *
 * 2. Open the bubble automatically on load
 *    <script src="…/widget.js"
 *            data-chatbot-key="pk_xxx"
 *            data-open="true" async></script>
 *
 * 3. Inline — renders directly inside a container you control
 *    <div id="my-chat" style="height:600px"></div>
 *    <script src="…/widget.js"
 *            data-chatbot-key="pk_xxx"
 *            data-mode="inline"
 *            data-container="#my-chat" async></script>
 *
 * ATTRIBUTES
 *   data-chatbot-key   required  your assistant's publishable key
 *   data-api-base      optional  override API origin (defaults to script origin)
 *   data-mode          optional  "bubble" (default) | "inline"
 *   data-container     optional  CSS selector for inline mode container
 *   data-open          optional  "true" — bubble starts open
 *
 * Zero dependencies. Inline-mode chat renders inside a Shadow DOM so host-page
 * CSS cannot interfere. Works in all modern browsers (Chrome 90+, Firefox 88+,
 * Safari 14+, Edge 90+).
 */
(function () {
  "use strict";

  /* ─── locate the <script> tag ─────────────────────────────────────────── */
  var script =
    document.currentScript ||
    (function () {
      var all = document.querySelectorAll("script[data-chatbot-key]");
      return all[all.length - 1];
    })();
  if (!script) return;

  var KEY = script.getAttribute("data-chatbot-key");
  if (!KEY) { console.error("[kore-widget] missing data-chatbot-key"); return; }

  var API_BASE = (
    script.getAttribute("data-api-base") || new URL(script.src).origin
  ).replace(/\/$/, "");

  var MODE         = (script.getAttribute("data-mode")      || "bubble").toLowerCase();
  var CONTAINER    =  script.getAttribute("data-container") || null;
  var START_OPEN   =  script.getAttribute("data-open")      === "true";
  var PUBLIC       = API_BASE + "/api/v1/public/chatbots/" + encodeURIComponent(KEY);

  /* ─── minimal DOM helpers ─────────────────────────────────────────────── */
  function el(tag, attrs, children) {
    var node = document.createElement(tag);
    if (attrs) {
      Object.keys(attrs).forEach(function (k) {
        if      (k === "class")     node.className   = attrs[k];
        else if (k === "text")      node.textContent = attrs[k];
        else if (k === "html")      node.innerHTML   = attrs[k];
        else if (k === "style")     node.style.cssText = attrs[k];
        else                        node.setAttribute(k, attrs[k]);
      });
    }
    (children || []).forEach(function (c) {
      node.appendChild(typeof c === "string" ? document.createTextNode(c) : c);
    });
    return node;
  }

  /* ─── styles ──────────────────────────────────────────────────────────── */
  function bubbleStyles(theme, position) {
    var side = position === "bottom-left" ? "left" : "right";
    return [
      ":host{all:initial}",
      "*{box-sizing:border-box;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,sans-serif}",

      /* Launcher */
      ".launcher{position:fixed;bottom:20px;" + side + ":20px;",
        "width:56px;height:56px;border-radius:50%;",
        "background:" + theme + ";color:#fff;",
        "border:none;cursor:pointer;",
        "box-shadow:0 4px 16px rgba(0,0,0,.22);",
        "display:flex;align-items:center;justify-content:center;",
        "z-index:2147483646;transition:transform .15s,box-shadow .15s;",
        "outline:none;}",
      ".launcher:hover{transform:scale(1.07);box-shadow:0 6px 24px rgba(0,0,0,.28)}",
      ".launcher:focus-visible{outline:3px solid " + theme + ";outline-offset:3px}",
      ".launcher svg{width:26px;height:26px;pointer-events:none}",
      ".launcher .icon-close{display:none}",
      ".launcher.open .icon-chat{display:none}",
      ".launcher.open .icon-close{display:block}",

      /* Panel */
      ".panel{position:fixed;bottom:88px;" + side + ":20px;",
        "width:376px;max-width:calc(100vw - 24px);",
        "height:560px;max-height:calc(100vh - 116px);",
        "background:#fff;border-radius:16px;",
        "box-shadow:0 16px 48px rgba(0,0,0,.2),0 0 0 1px rgba(0,0,0,.06);",
        "display:none;flex-direction:column;overflow:hidden;",
        "z-index:2147483647;",
        "transform:translateY(8px) scale(.98);opacity:0;",
        "transition:transform .2s cubic-bezier(.2,.8,.4,1),opacity .15s;}",
      ".panel.open{display:flex;transform:translateY(0) scale(1);opacity:1}",

      /* Chat chrome */
      chatChrome(theme),
    ].join("");
  }

  function inlineStyles(theme) {
    return [
      ":host{all:initial;display:block;width:100%;height:100%}",
      "*{box-sizing:border-box;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,sans-serif}",
      ".panel{display:flex;flex-direction:column;width:100%;height:100%;",
        "background:#fff;border-radius:inherit;overflow:hidden}",
      chatChrome(theme),
    ].join("");
  }

  function chatChrome(theme) {
    return [
      /* Header */
      ".header{background:" + theme + ";color:#fff;padding:14px 16px;",
        "display:flex;align-items:center;justify-content:space-between;flex-shrink:0}",
      ".header-left{display:flex;align-items:center;gap:10px}",
      ".header-avatar{width:30px;height:30px;border-radius:50%;",
        "background:rgba(255,255,255,.25);display:flex;align-items:center;justify-content:center}",
      ".header-avatar svg{width:16px;height:16px}",
      ".header h1{font-size:14px;font-weight:600;margin:0;line-height:1.2}",
      ".header-sub{font-size:11px;opacity:.75;margin-top:1px}",
      ".close-btn{background:transparent;border:none;color:#fff;cursor:pointer;",
        "opacity:.8;padding:4px;border-radius:6px;line-height:1;",
        "display:flex;align-items:center;justify-content:center}",
      ".close-btn:hover{opacity:1;background:rgba(255,255,255,.15)}",
      ".close-btn svg{width:18px;height:18px;pointer-events:none}",

      /* Messages */
      ".msgs{flex:1;overflow-y:auto;padding:16px 14px;display:flex;flex-direction:column;gap:10px;",
        "background:#f7f8fa;scroll-behavior:smooth}",
      ".msgs::-webkit-scrollbar{width:4px}",
      ".msgs::-webkit-scrollbar-thumb{background:#d1d5db;border-radius:4px}",

      /* Bubbles */
      ".bubble{max-width:84%;padding:10px 14px;border-radius:16px;",
        "font-size:14px;line-height:1.5;white-space:pre-wrap;word-break:break-word;}",
      ".user{align-self:flex-end;background:" + theme + ";color:#fff;border-bottom-right-radius:4px}",
      ".bot{align-self:flex-start;background:#fff;color:#1a1d2e;",
        "border:1px solid #e5e7eb;border-bottom-left-radius:4px;",
        "box-shadow:0 1px 3px rgba(0,0,0,.06)}",
      ".bot.empty{background:#f3f4f6;border-color:#e9eaec;color:#9ca3af;font-style:italic}",

      /* Typing dots */
      ".dots{display:inline-flex;gap:3px;align-items:center;padding:2px 0}",
      ".dot{width:7px;height:7px;border-radius:50%;background:#9ca3af;",
        "animation:pulse 1.2s ease-in-out infinite}",
      ".dot:nth-child(2){animation-delay:.2s}",
      ".dot:nth-child(3){animation-delay:.4s}",
      "@keyframes pulse{0%,60%,100%{opacity:.25;transform:scale(.85)}30%{opacity:1;transform:scale(1)}}",

      /* Citations */
      ".sources{margin-top:8px;font-size:11px}",
      ".sources-toggle{",
        "background:none;border:none;cursor:pointer;color:#6b7280;font-size:11px;",
        "padding:3px 0;display:flex;align-items:center;gap:4px}",
      ".sources-toggle:hover{color:#374151}",
      ".sources-toggle svg{width:12px;height:12px;transition:transform .15s}",
      ".sources-toggle.open svg{transform:rotate(90deg)}",
      ".sources-list{margin-top:6px;display:flex;flex-direction:column;gap:4px}",
      ".source-item{background:#f9fafb;border:1px solid #e5e7eb;border-radius:6px;",
        "padding:6px 8px;color:#4b5563;font-size:11px;line-height:1.45;",
        "display:none}",
      ".source-item.visible{display:block}",

      /* Composer */
      ".composer{display:flex;gap:8px;padding:12px;border-top:1px solid #e5e7eb;background:#fff;flex-shrink:0}",
      ".composer-textarea{flex:1;resize:none;border:1px solid #d1d5db;border-radius:10px;",
        "padding:9px 12px;font-size:14px;max-height:96px;min-height:40px;",
        "outline:none;font-family:inherit;line-height:1.45;",
        "transition:border-color .15s}",
      ".composer-textarea:focus{border-color:" + theme + ";box-shadow:0 0 0 3px " + theme + "22}",
      ".composer-textarea:disabled{background:#f9fafb;cursor:not-allowed}",
      ".send-btn{width:40px;height:40px;border-radius:10px;border:none;",
        "background:" + theme + ";color:#fff;cursor:pointer;",
        "display:flex;align-items:center;justify-content:center;flex-shrink:0;",
        "transition:background .15s,opacity .15s}",
      ".send-btn:hover{opacity:.88}",
      ".send-btn:disabled{opacity:.4;cursor:default}",
      ".send-btn svg{width:18px;height:18px;pointer-events:none}",

      /* Branding */
      ".branding{font-size:10px;color:#c4c9d4;text-align:center;padding:4px 0 8px;",
        "background:#fff;flex-shrink:0}",
      ".branding a{color:inherit;text-decoration:none}",
      ".branding a:hover{text-decoration:underline}",
    ].join("");
  }

  /* ─── SSE streaming ───────────────────────────────────────────────────── */
  function stream(url, message, handlers) {
    fetch(url, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ message: message }),
    })
      .then(function (res) {
        if (!res.ok || !res.body) {
          return res.json().catch(function () { return {}; }).then(function (b) {
            handlers.onError(b.detail || "HTTP " + res.status);
          });
        }
        var reader = res.body.getReader();
        var decoder = new TextDecoder();
        var buf = "";
        var evt = "";

        function pump() {
          return reader.read().then(function (r) {
            if (r.done) { handlers.onDone(); return; }
            buf += decoder.decode(r.value, { stream: true });
            var lines = buf.split("\n");
            buf = lines.pop();
            for (var i = 0; i < lines.length; i++) {
              var line = lines[i];
              if (line.indexOf("event:") === 0) {
                evt = line.slice(6).trim();
              } else if (line.indexOf("data:") === 0) {
                var data = line.slice(5).trim();
                try {
                  if      (evt === "citations") handlers.onCitations(JSON.parse(data));
                  else if (evt === "token")     handlers.onToken(data);
                  else if (evt === "error")     handlers.onError("Generation failed.");
                  else if (evt === "done")      { /* handled by stream end */ }
                } catch (e) { /* ignore parse errors in citations */ }
                evt = "";
              }
            }
            return pump();
          });
        }
        return pump();
      })
      .catch(function (e) {
        handlers.onError(e.message || "Network error");
      });
  }

  /* ─── build the chat UI (shared by both modes) ────────────────────────── */
  function buildChat(root, config, opts) {
    var w        = config.widget || {};
    var theme    = w.theme_color       || "#2563eb";
    var name     = w.display_name      || config.name || "Assistant";
    var welcome  = w.welcome_message   || "Hi! How can I help?";
    var position = w.launcher_position || "bottom-right";

    /* style */
    var styleEl = el("style");
    styleEl.textContent = opts.inline ? inlineStyles(theme) : bubbleStyles(theme, position);
    root.appendChild(styleEl);

    /* header */
    var closeBtn = el("button", { class: "close-btn", "aria-label": "Close chat",
      html: '<svg viewBox="0 0 20 20" fill="none" stroke="currentColor" stroke-width="2"><path stroke-linecap="round" stroke-linejoin="round" d="M6 6l8 8M6 14L14 6"/></svg>' });
    var header = el("div", { class: "header" }, [
      el("div", { class: "header-left" }, [
        el("div", { class: "header-avatar",
          html: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path stroke-linecap="round" stroke-linejoin="round" d="M9.813 15.904L9 18.75l-.813-2.846a4.5 4.5 0 00-3.09-3.09L2.25 12l2.846-.813a4.5 4.5 0 003.09-3.09L9 5.25l.813 2.846a4.5 4.5 0 003.09 3.09L15.75 12l-2.846.813a4.5 4.5 0 00-3.09 3.09z"/></svg>'}),
        el("div", {}, [
          el("h1", { text: name }),
          el("div", { class: "header-sub", text: "AI Assistant" }),
        ]),
      ]),
      closeBtn,
    ]);

    var msgs     = el("div", { class: "msgs", role: "log", "aria-live": "polite", "aria-label": "Chat messages" });
    var textarea = el("textarea", { class: "composer-textarea", rows: "1", placeholder: "Type a message… (Enter to send)", "aria-label": "Message input" });
    var sendBtn  = el("button", { class: "send-btn", type: "button", "aria-label": "Send message",
      html: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path stroke-linecap="round" stroke-linejoin="round" d="M6 12L3.269 3.126A59.768 59.768 0 0121.485 12 59.77 59.77 0 013.27 20.876L5.999 12zm0 0h7.5"/></svg>' });

    var panel = el("div", { class: "panel", role: "dialog", "aria-label": name });
    panel.appendChild(header);
    panel.appendChild(msgs);
    panel.appendChild(el("div", { class: "composer" }, [textarea, sendBtn]));
    panel.appendChild(el("div", { class: "branding" }, [
      document.createTextNode("Powered by "),
      el("a", { href: API_BASE, target: "_blank", rel: "noopener", text: "Kore AI" }),
    ]));

    root.appendChild(panel);

    /* state */
    var sessionId = null;
    var busy      = false;

    function scrollToBottom() {
      msgs.scrollTop = msgs.scrollHeight;
    }

    function addBubble(role, text) {
      var b = el("div", { class: "bubble " + role });
      b.textContent = text;
      msgs.appendChild(b);
      scrollToBottom();
      return b;
    }

    function addTypingDot() {
      var b = el("div", { class: "bubble bot" });
      b.innerHTML = '<span class="dots"><span class="dot"></span><span class="dot"></span><span class="dot"></span></span>';
      msgs.appendChild(b);
      scrollToBottom();
      return b;
    }

    function attachCitations(bubble, citations) {
      if (!citations || !citations.length) return;
      var toggle = el("button", { class: "sources-toggle", "aria-expanded": "false",
        html: '<svg viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.75"><path stroke-linecap="round" stroke-linejoin="round" d="M6 4l4 4-4 4"/></svg>' });
      var countText = document.createTextNode(" " + citations.length + " source" + (citations.length !== 1 ? "s" : ""));
      toggle.appendChild(countText);

      var list = el("div", { class: "sources-list" });
      citations.forEach(function (c, i) {
        var item = el("div", { class: "source-item" });
        item.textContent = (i + 1) + ". " + c.snippet;
        list.appendChild(item);
      });

      toggle.onclick = function () {
        var open = toggle.classList.toggle("open");
        toggle.setAttribute("aria-expanded", String(open));
        list.querySelectorAll(".source-item").forEach(function (s) {
          s.classList.toggle("visible", open);
        });
      };

      var sources = el("div", { class: "sources" }, [toggle, list]);
      bubble.appendChild(sources);
      scrollToBottom();
    }

    /* auto-resize textarea */
    textarea.oninput = function () {
      textarea.style.height = "auto";
      textarea.style.height = Math.min(textarea.scrollHeight, 96) + "px";
    };

    /* session management */
    function ensureSession() {
      if (sessionId) return Promise.resolve(sessionId);
      return fetch(PUBLIC + "/sessions", { method: "POST" })
        .then(function (r) {
          if (!r.ok) throw new Error("Could not start session");
          return r.json();
        })
        .then(function (d) { sessionId = d.session_id; return sessionId; });
    }

    /* send a message */
    function send() {
      var text = textarea.value.trim();
      if (!text || busy) return;
      busy = true;
      sendBtn.disabled = true;
      textarea.disabled = true;
      textarea.value = "";
      textarea.style.height = "auto";

      addBubble("user", text);
      var typing = addTypingDot();

      ensureSession()
        .then(function (sid) {
          var answerBubble   = null;
          var pendingCites   = null;

          stream(PUBLIC + "/sessions/" + sid + "/stream", text, {
            onCitations: function (c) { pendingCites = c; },
            onToken: function (tok) {
              if (!answerBubble) {
                typing.remove();
                answerBubble = addBubble("bot", "");
              }
              answerBubble.firstChild
                ? (answerBubble.firstChild.textContent += tok)
                : (answerBubble.textContent += tok);
              scrollToBottom();
            },
            onError: function (msg) {
              if (typing.parentNode) typing.remove();
              addBubble("bot empty", msg || "Something went wrong. Please try again.");
              reset();
            },
            onDone: function () {
              if (typing.parentNode) typing.remove();
              if (answerBubble) attachCitations(answerBubble, pendingCites);
              reset();
              /* postMessage for iFrame integrations */
              try {
                window.parent.postMessage({ type: "kore:message", role: "bot",
                  text: answerBubble ? answerBubble.textContent : "" }, "*");
              } catch (e) {}
            },
          });
        })
        .catch(function (e) {
          if (typing.parentNode) typing.remove();
          addBubble("bot empty", e.message || "Could not connect.");
          reset();
        });
    }

    function reset() {
      busy = false;
      sendBtn.disabled = false;
      textarea.disabled = false;
      textarea.focus();
    }

    sendBtn.onclick = send;
    textarea.onkeydown = function (e) {
      if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); send(); }
    };

    /* postMessage API — parent page can send messages programmatically */
    window.addEventListener("message", function (ev) {
      if (!ev.data || ev.data.type !== "kore:ask") return;
      if (typeof ev.data.text === "string" && ev.data.text.trim()) {
        textarea.value = ev.data.text;
        send();
      }
    });

    /* show welcome */
    addBubble("bot", welcome);

    /* close handler (if provided by caller) */
    if (typeof opts.onClose === "function") {
      closeBtn.onclick = opts.onClose;
    } else {
      closeBtn.style.display = "none";
    }

    return { panel: panel, textarea: textarea };
  }

  /* ─── BUBBLE MODE ─────────────────────────────────────────────────────── */
  function mountBubble(config) {
    var w        = config.widget || {};
    var theme    = w.theme_color       || "#2563eb";
    var position = w.launcher_position || "bottom-right";
    var side     = position === "bottom-left" ? "left" : "right";

    var host = document.createElement("div");
    host.style.cssText = "all:initial;position:fixed;bottom:0;" + side + ":0;z-index:2147483644;";
    document.body.appendChild(host);
    var root = host.attachShadow({ mode: "open" });

    /* launcher */
    var launcher = el("button", {
      class: "launcher",
      "aria-label": "Open chat",
      "aria-haspopup": "dialog",
      html: [
        '<svg class="icon-chat" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">',
          '<path stroke-linecap="round" stroke-linejoin="round" d="M8.625 9.75a.375.375 0 11-.75 0 .375.375 0 01.75 0zm0 0H8.25m4.125 0a.375.375 0 11-.75 0 .375.375 0 01.75 0zm0 0H12m4.125 0a.375.375 0 11-.75 0 .375.375 0 01.75 0zm0 0h-.375m-13.5 3.01c0 1.6 1.123 2.994 2.707 3.227 1.087.16 2.185.283 3.293.369V21l4.184-4.183a1.14 1.14 0 01.778-.332 48.294 48.294 0 005.83-.498c1.585-.233 2.708-1.626 2.708-3.228V6.741c0-1.602-1.123-2.995-2.707-3.228A48.394 48.394 0 0012 3c-2.392 0-4.744.175-7.043.513C3.373 3.746 2.25 5.14 2.25 6.741v6.018z"/>',
        '</svg>',
        '<svg class="icon-close" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5">',
          '<path stroke-linecap="round" stroke-linejoin="round" d="M6 18L18 6M6 6l12 12"/>',
        '</svg>',
      ].join(""),
    });

    var chat = buildChat(root, config, {
      inline: false,
      onClose: function () { toggle(false); },
    });

    root.appendChild(launcher);

    var open = false;
    function toggle(state) {
      open = typeof state === "boolean" ? state : !open;
      chat.panel.classList.toggle("open", open);
      launcher.classList.toggle("open", open);
      launcher.setAttribute("aria-expanded", String(open));
      if (open) {
        setTimeout(function () { chat.textarea.focus(); }, 220);
        try { window.parent.postMessage({ type: "kore:opened" }, "*"); } catch (e) {}
      } else {
        try { window.parent.postMessage({ type: "kore:closed" }, "*"); } catch (e) {}
      }
    }

    launcher.onclick = function () { toggle(); };

    /* keyboard: Escape closes the panel */
    root.addEventListener("keydown", function (e) {
      if (e.key === "Escape" && open) toggle(false);
    });

    if (START_OPEN) setTimeout(function () { toggle(true); }, 400);
  }

  /* ─── INLINE MODE ─────────────────────────────────────────────────────── */
  function mountInline(config) {
    var container = CONTAINER
      ? document.querySelector(CONTAINER)
      : null;

    if (!container) {
      /* fallback: create a full-viewport container */
      container = el("div", {
        style: "position:fixed;inset:0;z-index:2147483647",
      });
      document.body.appendChild(container);
    }

    /* adopt border-radius from container */
    container.style.overflow = "hidden";
    var root = container.attachShadow({ mode: "open" });
    buildChat(root, config, { inline: true });
  }

  /* ─── boot ────────────────────────────────────────────────────────────── */
  function boot() {
    fetch(PUBLIC + "/config")
      .then(function (r) {
        if (!r.ok) throw new Error("config " + r.status);
        return r.json();
      })
      .then(function (cfg) {
        if (MODE === "inline") mountInline(cfg);
        else                   mountBubble(cfg);
      })
      .catch(function (e) {
        console.error("[kore-widget] failed to load:", e.message);
      });
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", boot);
  } else {
    boot();
  }
})();
