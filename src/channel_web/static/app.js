'use strict';

// ── Constants ─────────────────────────────────────────────────────────────────
const LANG_COOKIE       = 'lang';
const DISCLAIMER_COOKIE = 'disclaimer_seen';
const COOKIE_MAX_AGE    = 400 * 24 * 60 * 60; // 400 days

// ── State ─────────────────────────────────────────────────────────────────────
let lang             = 'en';
let questions        = null;   // loaded from /static/questions.json
let expandedCategory = null;
let isLoading        = false;
let disclaimerSeen   = false;
let answers          = [];     // [{id, question, answer, facts, error}]
let answerIdCounter  = 0;
let idToken          = null;   // Google ID token — in memory only, never persisted
let sessionId        = null;   // Gateway session ID — tracks conversation history

// ── UI strings ────────────────────────────────────────────────────────────────
const UI = {
  en: {
    subtitle:            'Ask anything about the school',
    placeholder:         'Ask anything or pick a question from the list\u2026',
    sendLabel:           'Send message',
    copy:                'Copy',
    copied:              'Copied',
    feedback:            'Feedback',
    askUs:               'Ask us',
    langToggle:          'en espa\u00f1ol',
    langFlag:            '\ud83c\uddea\ud83c\uddf8',
    dismissLabel:        'Dismiss answer',
    sourcesLabel:        (n) => `Sources\u00a0(${n})`,
    disclaimer:          'Disclaimer',
    disclaimerQuestion:  'What are the limitations of this chatbot?',
    progress: {
      received:     'Question received\u2026',
      contacting:   'Contacting knowledge base\u2026',
      cache_lookup: 'Loading knowledge cache\u2026',
      querying_ai:  'Querying AI\u2026',
      processing:   'Preparing answer\u2026',
    },
  },
  es: {
    subtitle:            'Pregunte lo que quiera sobre la escuela',
    placeholder:         'Pregunte lo que quiera o elija una pregunta de la lista\u2026',
    sendLabel:           'Enviar mensaje',
    copy:                'Copiar',
    copied:              'Copiado',
    feedback:            'Opini\u00f3n',
    askUs:               'Cont\u00e1ctenos',
    langToggle:          'in English',
    langFlag:            '\ud83c\uddfa\ud83c\uddf8',
    dismissLabel:        'Cerrar respuesta',
    sourcesLabel:        (n) => `Fuentes\u00a0(${n})`,
    disclaimer:          'Aviso legal',
    disclaimerQuestion:  '\u00bfCu\u00e1les son las limitaciones de este chatbot?',
    progress: {
      received:     'Pregunta recibida\u2026',
      contacting:   'Consultando la base de conocimiento\u2026',
      cache_lookup: 'Cargando la cach\u00e9 de conocimiento\u2026',
      querying_ai:  'Consultando la IA\u2026',
      processing:   'Preparando la respuesta\u2026',
    },
  },
};

// ── SVG icon paths (Lucide) ───────────────────────────────────────────────────
const ICON_PATHS = {
  'arrow-up':       '<path d="m5 12 7-7 7 7"/><path d="M12 19V5"/>',
  'loader':         '<path d="M21 12a9 9 0 1 1-6.219-8.56"/>',
  'clock':          '<path d="M12 6v6l4 2"/><circle cx="12" cy="12" r="10"/>',
  'calendar-days':  '<path d="M8 2v4"/><path d="M16 2v4"/><rect width="18" height="18" x="3" y="4" rx="2"/><path d="M3 10h18"/><path d="M8 14h.01"/><path d="M12 14h.01"/><path d="M16 14h.01"/><path d="M8 18h.01"/><path d="M12 18h.01"/><path d="M16 18h.01"/>',
  'graduation-cap': '<path d="M21.42 10.922a1 1 0 0 0-.019-1.838L12.83 5.18a2 2 0 0 0-1.66 0L2.6 9.08a1 1 0 0 0 0 1.832l8.57 3.908a2 2 0 0 0 1.66 0z"/><path d="M22 10v6"/><path d="M6 12.5V16a6 3 0 0 0 12 0v-3.5"/>',
  'utensils':       '<path d="M3 2v7c0 1.1.9 2 2 2h4a2 2 0 0 0 2-2V2"/><path d="M7 2v20"/><path d="M21 15V2a5 5 0 0 0-5 5v6c0 1.1.9 2 2 2h3Zm0 0v7"/>',
  'bus':            '<path d="M8 6v6"/><path d="M15 6v6"/><path d="M2 12h19.6"/><path d="M18 18h3s.5-1.7.8-2.8c.1-.4.2-.8.2-1.2 0-.4-.1-.8-.2-1.2l-1.4-5C20.1 6.8 19.1 6 18 6H4a2 2 0 0 0-2 2v10h3"/><circle cx="7" cy="18" r="2"/><path d="M9 18h5"/><circle cx="16" cy="18" r="2"/>',
  'phone':          '<path d="M13.832 16.568a1 1 0 0 0 1.213-.303l.355-.465A2 2 0 0 1 17 15h3a2 2 0 0 1 2 2v3a2 2 0 0 1-2 2A18 18 0 0 1 2 4a2 2 0 0 1 2-2h3a2 2 0 0 1 2 2v3a2 2 0 0 1-.8 1.6l-.468.351a1 1 0 0 0-.292 1.233 14 14 0 0 0 6.392 6.384"/>',
  'x':              '<path d="M18 6 6 18"/><path d="m6 6 12 12"/>',
  'copy':           '<rect width="14" height="14" x="8" y="8" rx="2" ry="2"/><path d="M4 16c-1.1 0-2-.9-2-2V4c0-1.1.9-2 2-2h10c1.1 0 2 .9 2 2"/>',
  'check':          '<path d="M20 6 9 17l-5-5"/>',
  'message-circle': '<path d="M7.9 20A9 9 0 1 0 4 16.1L2 22Z"/>',
  'mail':           '<rect width="20" height="16" x="2" y="4" rx="2"/><path d="m22 7-8.97 5.7a1.94 1.94 0 0 1-2.06 0L2 7"/>',
  'shield-alert':   '<path d="M20 13c0 5-3.5 7.5-7.66 8.95a1 1 0 0 1-.67-.01C7.5 20.5 4 18 4 13V6a1 1 0 0 1 1-1c2 0 4.5-1.2 6.24-2.72a1.17 1.17 0 0 1 1.52 0C14.51 3.81 17 5 19 5a1 1 0 0 1 1 1z"/><path d="M12 8v4"/><path d="M12 16h.01"/>',
  'file-text':      '<path d="M15 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V7Z"/><path d="M14 2v4a2 2 0 0 0 2 2h4"/><path d="M10 9H8"/><path d="M16 13H8"/><path d="M16 17H8"/>',
};

function icon(name, extraClass) {
  const cls = extraClass ? ` class="${extraClass}"` : '';
  return `<svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"${cls}>${ICON_PATHS[name]}</svg>`;
}

// ── Auth ──────────────────────────────────────────────────────────────────────
function handleCredentialResponse(response) {
  idToken = response.credential;
  document.getElementById('login-overlay').classList.add('hidden');
}

function initAuth() {
  if (typeof google === 'undefined' || !GOOGLE_CLIENT_ID) return;
  google.accounts.id.initialize({
    client_id:   GOOGLE_CLIENT_ID,
    callback:    handleCredentialResponse,
    auto_select: true,
  });
  google.accounts.id.renderButton(
    document.getElementById('google-signin-btn'),
    { theme: 'outline', size: 'large' }
  );
  google.accounts.id.prompt();
}

// ── Cookie utils ──────────────────────────────────────────────────────────────
function getCookie(name) {
  const m = document.cookie.match(new RegExp('(?:^|; )' + name + '=([^;]*)'));
  return m ? decodeURIComponent(m[1]) : null;
}

function setCookie(name, value) {
  document.cookie = name + '=' + encodeURIComponent(value) +
    ';path=/;max-age=' + COOKIE_MAX_AGE + ';SameSite=Lax';
}

// ── Language ──────────────────────────────────────────────────────────────────
function initLang() {
  const saved = getCookie(LANG_COOKIE);
  lang = (saved === 'en' || saved === 'es') ? saved : 'en';
  setCookie(LANG_COOKIE, lang);
}

function toggleLang() {
  lang = lang === 'en' ? 'es' : 'en';
  setCookie(LANG_COOKIE, lang);
  applyLang();
}

function applyLang() {
  const t = UI[lang];
  document.documentElement.lang = lang;
  document.getElementById('subtitle').textContent = t.subtitle;

  const textarea = document.getElementById('chat-textarea');
  if (textarea) {
    textarea.placeholder = t.placeholder;
    textarea.setAttribute('aria-label', t.placeholder);
  }
  document.getElementById('send-btn').setAttribute('aria-label', t.sendLabel);

  renderPills();
}

// ── Disclaimer ────────────────────────────────────────────────────────────────
function initDisclaimer() {
  disclaimerSeen = getCookie(DISCLAIMER_COOKIE) === '1';
}

function markDisclaimerSeen() {
  if (disclaimerSeen) return;
  disclaimerSeen = true;
  setCookie(DISCLAIMER_COOKIE, '1');
  document.querySelectorAll('.action-btn-disclaimer').forEach((btn) => {
    btn.classList.remove('disclaimer-unseen');
    btn.classList.add('disclaimer-seen');
  });
}

// ── Suggestion pills ──────────────────────────────────────────────────────────
function renderPills() {
  if (!questions) return;
  const t = UI[lang];
  const cats = questions[lang].categories;
  const container = document.getElementById('pills-container');
  let html = '';

  if (expandedCategory === null) {
    // Collapsed: centred wrap
    html = '<div class="pills-collapsed">';
    html += `<button class="pill-btn" onclick="toggleLang()">
      <span class="pill-lang-emoji" aria-hidden="true">${t.langFlag}</span>
      <span>${esc(t.langToggle)}</span>
    </button>`;
    for (const cat of cats) {
      html += `<button class="pill-btn" onclick="handleCategoryClick('${esc(cat.id)}')" aria-expanded="false">
        <span class="pill-symbol" aria-hidden="true">${esc(cat.symbol)}</span>
        <span>${esc(cat.label)}</span>
      </button>`;
    }
    html += '</div>';
  } else {
    // Expanded: sidebar + questions panel
    html = '<div class="pills-expanded anim-fade">';

    // Sidebar
    html += '<div class="pills-sidebar">';
    html += `<button class="pill-sidebar-btn" onclick="toggleLang()" aria-label="${esc(t.langToggle)}">
      <span aria-hidden="true">${t.langFlag}</span>
      <span class="pill-label">${esc(t.langToggle)}</span>
    </button>`;
    for (const cat of cats) {
      const active = cat.id === expandedCategory;
      html += `<button class="pill-sidebar-btn${active ? ' active' : ''}"
        onclick="handleCategoryClick('${esc(cat.id)}')"
        aria-expanded="${active}"
        aria-label="${esc(cat.label)}">
        <span class="pill-symbol" aria-hidden="true">${esc(cat.symbol)}</span>
        <span class="pill-label">${esc(cat.label)}</span>
      </button>`;
    }
    html += '</div>';

    // Questions panel
    const activeCat = cats.find((c) => c.id === expandedCategory);
    if (activeCat) {
      html += `<div class="questions-panel anim-panel" role="region" aria-label="${esc(activeCat.label)}">`;
      activeCat.questions.forEach((q, i) => {
        html += `<button class="question-btn anim-question"
          style="animation-delay:${i * 40}ms;animation-fill-mode:backwards"
          onclick="handleQuestionSelect(this)"
          data-question="${esc(q)}">${esc(q)}</button>`;
      });
      html += '</div>';
    }

    html += '</div>';
  }

  container.innerHTML = html;
}

function handleCategoryClick(id) {
  expandedCategory = expandedCategory === id ? null : id;
  renderPills();
}

function handleQuestionSelect(btn) {
  const question = btn.dataset.question;
  const textarea = document.getElementById('chat-textarea');
  textarea.value = question;
  handleTextareaInput();
  setTimeout(() => {
    textarea.focus();
    textarea.selectionStart = textarea.selectionEnd = textarea.value.length;
  }, 0);
}

// ── Chat input ────────────────────────────────────────────────────────────────
function handleTextareaInput() {
  const textarea = document.getElementById('chat-textarea');
  textarea.style.height = 'auto';
  textarea.style.height = Math.min(textarea.scrollHeight, 76) + 'px';
  document.getElementById('send-btn').disabled = !textarea.value.trim() || isLoading;
}

function handleTextareaKeydown(e) {
  if (e.key === 'Enter' && !e.shiftKey) {
    e.preventDefault();
    const textarea = document.getElementById('chat-textarea');
    if (textarea.value.trim() && !isLoading) handleSubmit();
  }
}

function handleSubmit() {
  const textarea = document.getElementById('chat-textarea');
  const question = textarea.value.trim();
  if (!question || isLoading) return;
  submitQuestion(question);
}

// ── API call ──────────────────────────────────────────────────────────────────
async function submitQuestion(question) {
  if (isLoading) return;

  const t = UI[lang];

  // Track disclaimer views
  if (question === UI.en.disclaimerQuestion || question === UI.es.disclaimerQuestion) {
    markDisclaimerSeen();
  }

  isLoading = true;
  const textarea = document.getElementById('chat-textarea');
  const sendBtn  = document.getElementById('send-btn');
  textarea.value        = t.progress.received;
  textarea.style.height = 'auto';
  textarea.disabled     = true;
  sendBtn.disabled      = true;
  sendBtn.innerHTML     = icon('loader', 'spin');

  smoothScrollTo(document.getElementById('chat-input-box'));

  const id = ++answerIdCounter;

  try {
    const headers = { 'Content-Type': 'application/json' };
    if (idToken) headers['Authorization'] = 'Bearer ' + idToken;

    const resp = await fetch('/chat', {
      method:  'POST',
      headers: headers,
      body:    JSON.stringify({ message: question, session_id: sessionId }),
    });

    if (resp.status === 401) {
      idToken = null;
      document.getElementById('login-overlay').classList.remove('hidden');
      if (typeof google !== 'undefined') google.accounts.id.prompt();
      addAnswer(id, question, null, null, 'Session expired. Please sign in again.');
      return;
    }

    if (!resp.ok || !resp.body) {
      addAnswer(id, question, null, null, 'HTTP ' + resp.status);
      return;
    }

    // Stream SSE events
    const reader  = resp.body.getReader();
    const decoder = new TextDecoder();
    let buffer = '';

    while (true) {
      const { done, value } = await reader.read();
      if (done) break;
      buffer += decoder.decode(value, { stream: true });

      let boundary;
      while ((boundary = buffer.indexOf('\n\n')) !== -1) {
        const block = buffer.slice(0, boundary);
        buffer = buffer.slice(boundary + 2);
        if (!block.trim()) continue;

        let type    = 'message';
        let dataStr = '';
        for (const line of block.split('\n')) {
          if (line.startsWith('event: '))      type    = line.slice(7).trim();
          else if (line.startsWith('data: '))  dataStr = line.slice(6);
        }
        if (!dataStr) continue;

        let payload;
        try { payload = JSON.parse(dataStr); } catch (_) { continue; }

        if (type === 'progress') {
          textarea.value = t.progress[payload.key] || '';
        } else if (type === 'answer') {
          if (payload.session_id) sessionId = payload.session_id;
          addAnswer(id, question, payload.answer, payload.facts, null, payload.warning || null);
        } else if (type === 'error') {
          addAnswer(id, question, null, null, payload.error || 'Unknown error');
        }
      }
    }
  } catch (_) {
    addAnswer(id, question, null, null, 'Connection error. Please try again.');
  } finally {
    isLoading         = false;
    textarea.disabled = false;
    textarea.value    = '';
    sendBtn.innerHTML = icon('arrow-up');
    handleTextareaInput();
    textarea.focus();
  }
}

// ── Answers ───────────────────────────────────────────────────────────────────
function addAnswer(id, question, answer, facts, error, warning = null) {
  answers.push({ id, question, answer, facts, error, warning });

  const list = document.getElementById('answers-list');
  const wrapper = document.createElement('div');
  wrapper.id = 'answer-' + id;
  wrapper.innerHTML = buildAnswerCard(id, question, answer, facts, error, warning);
  list.appendChild(wrapper);

  list.style.display = 'flex';
  updateLayout();

  // Smooth scroll, then release green border
  setTimeout(() => {
    smoothScrollTo(wrapper, () => {
      const card = document.getElementById('card-' + id);
      if (card) {
        card.style.transition   = 'border-color 1.5s ease-out';
        card.style.borderColor  = 'var(--border)';
      }
    });
  }, 50);
}

function buildAnswerCard(id, question, answer, facts, error, warning = null) {
  const t       = UI[lang];
  const isError = !!error;
  const text    = isError ? error : answer;

  // Sources section
  let sourcesHtml = '';
  if (facts && facts.length > 0) {
    const factsHtml = facts.map((f) =>
      `<div class="fact-item">
         <span class="fact-source-id">${esc(f.source_id)}</span>
         <p class="fact-text">${esc(f.fact)}</p>
       </div>`
    ).join('');

    sourcesHtml = `
      <details class="source-details">
        <summary>
          ${icon('file-text')}
          <span>${esc(t.sourcesLabel(facts.length))}</span>
        </summary>
        <div class="facts-list">${factsHtml}</div>
      </details>`;
  }

  const disclaimerCls = disclaimerSeen ? 'disclaimer-seen' : 'disclaimer-unseen';
  const borderColor   = isError ? 'var(--destructive)' : 'var(--action-green)';

  return `
    <div class="answer-card anim-card${isError ? ' answer-card-error' : ''}"
         id="card-${id}"
         style="border-color:${borderColor};transition:none">
      <div class="answer-header">
        <div class="answer-content">
          <p class="answer-question">${esc(question)}</p>
          <hr class="answer-divider">
          ${warning ? `<p class="answer-warning">${esc(warning)}</p>` : ''}
          <p class="answer-text${isError ? ' answer-text-error' : ''}">${isError ? esc(text) : md(text)}</p>
          ${sourcesHtml}
        </div>
        <button class="dismiss-btn"
                data-action="dismiss" data-id="${id}"
                aria-label="${esc(t.dismissLabel)}">
          ${icon('x')}
        </button>
      </div>
      <div class="answer-actions">
        <button class="action-btn"
                data-action="copy" data-id="${id}"
                aria-label="${esc(t.copy)}">
          ${icon('copy')}
          <span class="copy-label">${esc(t.copy)}</span>
        </button>
        <button class="action-btn action-btn-inactive" aria-label="${esc(t.feedback)}">
          ${icon('message-circle')}
          <span>${esc(t.feedback)}</span>
        </button>
        <button class="action-btn action-btn-inactive" aria-label="${esc(t.askUs)}">
          ${icon('mail')}
          <span>${esc(t.askUs)}</span>
        </button>
        <button class="action-btn action-btn-disclaimer ${disclaimerCls}"
                data-action="disclaimer"
                aria-label="${esc(t.disclaimer)}">
          ${icon('shield-alert')}
          <span>${esc(t.disclaimer)}</span>
        </button>
      </div>
    </div>`;
}

// Event delegation for answer list actions
document.addEventListener('DOMContentLoaded', () => {
  document.getElementById('answers-list').addEventListener('click', (e) => {
    const btn = e.target.closest('[data-action]');
    if (!btn) return;
    const action = btn.dataset.action;
    const id     = parseInt(btn.dataset.id, 10);

    if (action === 'dismiss')    handleDismiss(id);
    else if (action === 'copy')  handleCopy(id, btn);
    else if (action === 'disclaimer') handleDisclaimerClick();
  });
});

function handleDismiss(id) {
  answers = answers.filter((a) => a.id !== id);
  const el = document.getElementById('answer-' + id);
  if (el) el.remove();

  if (answers.length === 0) {
    document.getElementById('answers-list').style.display = 'none';
  }
  updateLayout();
}

function handleCopy(id, btn) {
  const a = answers.find((a) => a.id === id);
  if (!a || !a.answer) return;
  const t = UI[lang];

  navigator.clipboard.writeText(a.answer).then(() => {
    btn.innerHTML = icon('check') + `<span class="copy-label">${esc(t.copied)}</span>`;
    setTimeout(() => {
      btn.innerHTML = icon('copy') + `<span class="copy-label">${esc(t.copy)}</span>`;
    }, 2000);
  });
}

function handleDisclaimerClick() {
  submitQuestion(UI[lang].disclaimerQuestion);
}

function updateLayout() {
  document.getElementById('page').classList.toggle('has-answers', answers.length > 0);
}

// ── Smooth scroll ─────────────────────────────────────────────────────────────
function smoothScrollTo(el, onDone) {
  const targetY  = el.getBoundingClientRect().top + window.scrollY - 24;
  const startY   = window.scrollY;
  const distance = targetY - startY;

  if (Math.abs(distance) < 1) {
    if (onDone) onDone();
    return;
  }

  const duration = 900;
  let start = null;

  function step(ts) {
    if (!start) start = ts;
    const progress = Math.min((ts - start) / duration, 1);
    const ease = progress < 0.5
      ? 4 * progress * progress * progress
      : 1 - Math.pow(-2 * progress + 2, 3) / 2;
    window.scrollTo(0, startY + distance * ease);
    if (progress < 1) requestAnimationFrame(step);
    else if (onDone) onDone();
  }

  requestAnimationFrame(step);
}

// ── Markdown → HTML (answer text only) ────────────────────────────────────────
// Handles the subset Gemini 2.5 Flash produces: bold, italic, bullet lists, line breaks.
// HTML-escapes first so LLM output can never inject arbitrary tags.
function md(text) {
  if (!text) return '';
  let s = String(text)
    .replace(/&/g,  '&amp;')
    .replace(/</g,  '&lt;')
    .replace(/>/g,  '&gt;')
    .replace(/"/g,  '&quot;')
    .replace(/'/g,  '&#039;');
  // Bold before italic so **x* doesn't mis-match
  s = s.replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>');
  s = s.replace(/\*(.+?)\*/g,     '<em>$1</em>');
  // Consecutive bullet lines → <ul><li>…</li></ul>
  s = s.replace(/((?:^|\n)[*\-] [^\n]+)+/g, match =>
    '<ul>' + match.trim().split('\n').map(l =>
      '<li>' + l.replace(/^[*\-] /, '') + '</li>'
    ).join('') + '</ul>'
  );
  // Remaining newlines → line breaks
  s = s.replace(/\n/g, '<br>');
  return s;
}

// ── Escape util ───────────────────────────────────────────────────────────────
function esc(str) {
  if (!str) return '';
  return String(str)
    .replace(/&/g,  '&amp;')
    .replace(/</g,  '&lt;')
    .replace(/>/g,  '&gt;')
    .replace(/"/g,  '&quot;')
    .replace(/'/g,  '&#039;');
}

// ── Init ──────────────────────────────────────────────────────────────────────
async function init() {
  initAuth();
  initLang();
  initDisclaimer();

  try {
    const resp = await fetch('/static/questions.json');
    questions  = await resp.json();
  } catch (_) {
    questions = { en: { categories: [] }, es: { categories: [] } };
  }

  applyLang(); // renders pills + sets all UI strings

  const textarea = document.getElementById('chat-textarea');
  textarea.addEventListener('input',   handleTextareaInput);
  textarea.addEventListener('keydown', handleTextareaKeydown);
  document.getElementById('send-btn').addEventListener('click', handleSubmit);
}

document.addEventListener('DOMContentLoaded', init);
