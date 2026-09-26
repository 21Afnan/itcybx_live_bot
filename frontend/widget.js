/**
 * IT Cybx Live Bot - Embedded Chat Widget
 * Supports bilingual (EN/AR), auto RTL/LTR switching, session persistence, and instant lead routing.
 */
(function () {
  if (window.ItCybxBotInitialized) return;
  window.ItCybxBotInitialized = true;

  // Configuration & Auto-Detection of Backend Host
  let scriptOrigin = "";
  try {
    const scriptTag = document.currentScript || document.querySelector('script[src*="widget.js"]');
    if (scriptTag && scriptTag.src) {
      scriptOrigin = new URL(scriptTag.src).origin;
    }
  } catch (e) {}

  const API_BASE_URL = window.ITCYBX_API_URL || scriptOrigin || window.location.origin || "http://localhost:8000";
  const STORAGE_KEY = "itcybx_chat_session_id";
  const LANG_KEY = "itcybx_chat_lang";

  // Auto detect initial language (from HTML lang, URL path /ar/, or storage)
  function detectInitialLang() {
    const stored = localStorage.getItem(LANG_KEY);
    if (stored && (stored === "en" || stored === "ar")) return stored;

    const htmlLang = (document.documentElement.lang || "").toLowerCase();
    if (htmlLang.startsWith("ar")) return "ar";

    const path = window.location.pathname.toLowerCase();
    if (path.includes("/ar/") || path.startsWith("/ar")) return "ar";

    return "en";
  }

  let currentLang = detectInitialLang();
  let sessionId = localStorage.getItem(STORAGE_KEY) || "web_" + Math.random().toString(36).substring(2, 12);
  localStorage.setItem(STORAGE_KEY, sessionId);

  // Localization strings
  const I18N = {
    en: {
      title: "IT Cybx Assistant",
      status: "Online • Growth Studio",
      placeholder: "Type your message here...",
      send: "Send",
      clear: "Clear",
      langToggle: "العربية",
      welcome: "👋 Welcome to **IT Cybx**! We help Shopify, Salla, and Zid brands scale.\n\nHow can we assist your e-commerce store today?",
      chips: [
        "📈 What is the Growth Audit?",
        "🛍️ Shopify vs Salla / Zid",
        "💰 Pricing & Plans",
        "👤 Request a Proposal",
      ],
      error: "⚠️ Unable to connect to assistant. Please try again shortly.",
    },
    ar: {
      title: "مساعد IT Cybx الذكي",
      status: "متصل • نمو التجارة الإلكترونية",
      placeholder: "اكتب استفسارك هنا...",
      send: "إرسال",
      clear: "مسح",
      langToggle: "English",
      welcome: "👋 مرحباً بك في **IT Cybx**! نساعد علامات شوبيفاي وسلة وزد على مضاعفة المبيعات والنمو.\n\nكيف يمكننا مساعدتك في تطوير متجرك اليوم؟",
      chips: [
        "📈 ما هو تقييم النمو؟",
        "🛍️ متاجر سلة وشوبيفاي وزد",
        "💰 باقات الأسعار",
        "👤 طلب استشارة وخطة نمو",
      ],
      error: "⚠️ تعذر الاتصال بالمساعد الذكي. يرجى المحاولة بعد قليل.",
    },
  };

  // Helper to load CSS stylesheet if not present
  function loadStylesheet() {
    const existing = document.querySelector('link[href*="widget.css"]');
    if (!existing) {
      const link = document.createElement("link");
      link.rel = "stylesheet";
      link.href = `${API_BASE_URL}/widget/widget.css`;
      document.head.appendChild(link);
    }
  }

  // Format message text with bold and links
  function formatMessageText(text) {
    if (!text) return "";
    // Strip standalone markdown divider lines (e.g. ---, ___, *** on their own line)
    let cleaned = text.replace(/^[ \t]*(?:-[ \t]*){3,}$/gm, "");
    cleaned = cleaned.replace(/^[ \t]*(?:_[ \t]*){3,}$/gm, "");
    cleaned = cleaned.replace(/^[ \t]*(?:\*[ \t]*){3,}$/gm, "");
    cleaned = cleaned.replace(/^[ \t]*(?:---|\*\*\*|___)(?:[ \t]+(?:---|\*\*\*|___))*[ \t]*$/gm, "");
    cleaned = cleaned.replace(/\n{3,}/g, "\n\n").trim();

    let formatted = cleaned
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;");

    // Replace bold **text**
    formatted = formatted.replace(/\*\*(.*?)\*\*/g, "<strong>$1</strong>");

    // Replace URLs with clickable links
    const urlPattern = /(\b(https?:\/\/|www\.)[-A-Z0-9+&@#\/%?=~_|!:,.;]*[-A-Z0-9+&@#\/%=~_|])/gi;
    formatted = formatted.replace(urlPattern, function (url) {
      const href = url.startsWith("http") ? url : "https://" + url;
      return `<a href="${href}" target="_blank" rel="noopener noreferrer">${url}</a>`;
    });

    // Replace newlines
    formatted = formatted.replace(/\n/g, "<br>");
    return formatted;
  }

  // Build Widget DOM
  function createWidgetDOM() {
    loadStylesheet();

    const isAr = currentLang === "ar";
    const strings = I18N[currentLang];

    // Launcher Button
    const launcher = document.createElement("button");
    launcher.className = "itcybx-widget-launcher";
    launcher.setAttribute("aria-label", "Open IT Cybx Live Chat");
    launcher.innerHTML = `
      <svg viewBox="0 0 24 24">
        <path d="M20 2H4c-1.1 0-2 .9-2 2v18l4-4h14c1.1 0 2-.9 2-2V4c0-1.1-.9-2-2-2zm0 14H6l-2 2V4h16v12z"/>
      </svg>
    `;

    // Chat Window
    const windowEl = document.createElement("div");
    windowEl.className = "itcybx-widget-window";
    if (isAr) windowEl.classList.add("itcybx-rtl");

    windowEl.innerHTML = `
      <div class="itcybx-header">
        <div class="itcybx-header-info">
          <div class="itcybx-avatar">IT</div>
          <div class="itcybx-title-group">
            <h3 id="itcybx-title">${strings.title}</h3>
            <div class="itcybx-status">
              <span class="itcybx-status-dot"></span>
              <span id="itcybx-status-text">${strings.status}</span>
            </div>
          </div>
        </div>
        <div class="itcybx-header-actions">
          <button class="itcybx-btn-icon" id="itcybx-lang-btn">${strings.langToggle}</button>
          <button class="itcybx-btn-icon" id="itcybx-clear-btn" title="${strings.clear}">↺</button>
          <button class="itcybx-btn-icon" id="itcybx-close-btn">✕</button>
        </div>
      </div>

      <div class="itcybx-messages" id="itcybx-messages-list"></div>

      <div class="itcybx-chips-container" id="itcybx-chips"></div>

      <div class="itcybx-input-area">
        <input 
          type="text" 
          class="itcybx-input" 
          id="itcybx-user-input" 
          placeholder="${strings.placeholder}"
          autocomplete="off"
        />
        <button class="itcybx-send-btn" id="itcybx-send-btn" aria-label="${strings.send}">
          <svg width="18" height="18" viewBox="0 0 24 24" fill="currentColor">
            <path d="M2.01 21L23 12 2.01 3 2 10l15 2-15 2z"/>
          </svg>
        </button>
      </div>
    `;

    document.body.appendChild(launcher);
    document.body.appendChild(windowEl);

    // Event Listeners
    const messagesList = windowEl.querySelector("#itcybx-messages-list");
    const chipsContainer = windowEl.querySelector("#itcybx-chips");
    const userInput = windowEl.querySelector("#itcybx-user-input");
    const sendBtn = windowEl.querySelector("#itcybx-send-btn");
    const closeBtn = windowEl.querySelector("#itcybx-close-btn");
    const clearBtn = windowEl.querySelector("#itcybx-clear-btn");
    const langBtn = windowEl.querySelector("#itcybx-lang-btn");

    function renderWelcome() {
      messagesList.innerHTML = "";
      addBotMessage(I18N[currentLang].welcome);
      renderChips();
    }

    function renderChips() {
      const strings = I18N[currentLang];
      chipsContainer.innerHTML = "";
      strings.chips.forEach((chipText) => {
        const chip = document.createElement("button");
        chip.className = "itcybx-chip";
        chip.textContent = chipText;
        chip.onclick = () => {
          sendMessage(chipText);
        };
        chipsContainer.appendChild(chip);
      });
    }

    function addUserMessage(text) {
      const msg = document.createElement("div");
      msg.className = "itcybx-msg itcybx-msg-user";
      msg.textContent = text;
      messagesList.appendChild(msg);
      messagesList.scrollTop = messagesList.scrollHeight;
    }

    function addBotMessage(text) {
      const msg = document.createElement("div");
      msg.className = "itcybx-msg itcybx-msg-bot";
      msg.innerHTML = formatMessageText(text);
      messagesList.appendChild(msg);
      messagesList.scrollTop = messagesList.scrollHeight;
    }

    function showTyping() {
      const typing = document.createElement("div");
      typing.className = "itcybx-typing";
      typing.id = "itcybx-typing-indicator";
      typing.innerHTML = `
        <div class="itcybx-typing-dot"></div>
        <div class="itcybx-typing-dot"></div>
        <div class="itcybx-typing-dot"></div>
      `;
      messagesList.appendChild(typing);
      messagesList.scrollTop = messagesList.scrollHeight;
    }

    function removeTyping() {
      const typing = document.getElementById("itcybx-typing-indicator");
      if (typing) typing.remove();
    }

    async function sendMessage(text) {
      const clean = text.trim();
      if (!clean) return;

      userInput.value = "";
      addUserMessage(clean);
      sendBtn.disabled = true;
      showTyping();

      try {
        const response = await fetch(`${API_BASE_URL}/api/chat`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            message: clean,
            session_id: sessionId,
            language: currentLang,
          }),
        });

        removeTyping();
        sendBtn.disabled = false;

        if (!response.ok) {
          throw new Error("HTTP error " + response.status);
        }

        const data = await response.json();
        addBotMessage(data.response || I18N[currentLang].error);
      } catch (err) {
        removeTyping();
        sendBtn.disabled = false;
        console.error("IT Cybx Widget Error:", err);
        addBotMessage(I18N[currentLang].error);
      }
    }

    // Toggle Chat Window
    launcher.onclick = () => {
      const isOpen = windowEl.classList.contains("open");
      if (isOpen) {
        windowEl.classList.remove("open");
        launcher.classList.remove("open");
      } else {
        windowEl.classList.add("open");
        launcher.classList.add("open");
        if (messagesList.children.length === 0) {
          renderWelcome();
        }
        userInput.focus();
      }
    };

    closeBtn.onclick = () => {
      windowEl.classList.remove("open");
      launcher.classList.remove("open");
    };

    clearBtn.onclick = async () => {
      sessionId = "web_" + Math.random().toString(36).substring(2, 12);
      localStorage.setItem(STORAGE_KEY, sessionId);
      renderWelcome();
    };

    langBtn.onclick = () => {
      currentLang = currentLang === "en" ? "ar" : "en";
      localStorage.setItem(LANG_KEY, currentLang);
      const isAr = currentLang === "ar";
      const strings = I18N[currentLang];

      if (isAr) {
        windowEl.classList.add("itcybx-rtl");
      } else {
        windowEl.classList.remove("itcybx-rtl");
      }

      windowEl.querySelector("#itcybx-title").textContent = strings.title;
      windowEl.querySelector("#itcybx-status-text").textContent = strings.status;
      windowEl.querySelector("#itcybx-lang-btn").textContent = strings.langToggle;
      userInput.placeholder = strings.placeholder;

      renderWelcome();
    };

    // Send on click and Enter
    sendBtn.onclick = () => sendMessage(userInput.value);
    userInput.onkeydown = (e) => {
      if (e.key === "Enter") {
        sendMessage(userInput.value);
      }
    };

    // Expose API
    window.ItCybxBot = {
      open: () => {
        windowEl.classList.add("open");
        launcher.classList.add("open");
      },
      close: () => {
        windowEl.classList.remove("open");
        launcher.classList.remove("open");
      },
      sendMessage: (msg) => sendMessage(msg),
    };
  }

  // Initialize
  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", createWidgetDOM);
  } else {
    createWidgetDOM();
  }
})();
