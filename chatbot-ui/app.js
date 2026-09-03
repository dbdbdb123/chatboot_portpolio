const sidebar = document.querySelector('#sidebar');
const menuButton = document.querySelector('#menuButton');
const form = document.querySelector('#chatForm');
const input = document.querySelector('#messageInput');
const conversation = document.querySelector('#conversation');
const welcome = document.querySelector('#welcome');
const toolToggle = document.querySelector('#toolToggle');
const toast = document.querySelector('#toast');
const sendButton = document.querySelector('#sendButton');

// 현재 탭의 대화 기록이다. 서버가 무상태이므로 매 요청에 전체 기록을 함께 보낸다.
let chatMessages = [];

function showToast(message) {
  toast.textContent = message;
  toast.classList.add('show');
  window.clearTimeout(showToast.timer);
  showToast.timer = window.setTimeout(() => toast.classList.remove('show'), 1800);
}

function now() {
  return new Intl.DateTimeFormat('ko-KR', {
    hour: '2-digit', minute: '2-digit', hour12: false,
  }).format(new Date());
}

function addMessage(text, role) {
  // textContent를 사용해 모델 응답에 포함된 HTML이 실행되지 않도록 한다.
  const article = document.createElement('article');
  article.className = `message ${role}-message`;

  if (role === 'assistant') {
    const avatar = document.createElement('div');
    avatar.className = 'avatar';
    avatar.setAttribute('aria-hidden', 'true');
    avatar.textContent = '✦';
    article.appendChild(avatar);
  }

  const bubble = document.createElement('div');
  bubble.className = 'bubble';
  bubble.textContent = text;

  const meta = document.createElement('span');
  meta.className = 'message-meta';
  meta.textContent = `${now()}${role === 'user' ? '  ✓✓' : ''}`;
  bubble.appendChild(meta);
  article.appendChild(bubble);
  conversation.appendChild(article);
  article.scrollIntoView({ behavior: 'smooth', block: 'end' });
}

function addToolActivity(activity) {
  // 백엔드가 반환한 MCP 실행 요약을 접을 수 있는 카드로 표시한다.
  const card = document.createElement('details');
  card.className = 'tool-card';
  card.open = true;
  const summary = document.createElement('summary');
  const icon = document.createElement('span');
  icon.className = 'tool-card-icon';
  icon.textContent = '⌕';
  const label = document.createElement('span');
  const title = document.createElement('strong');
  title.textContent = activity.name;
  const detail = document.createElement('small');
  detail.textContent = `${activity.server} MCP 서버에서 실행`;
  label.append(title, detail);
  const status = document.createElement('span');
  status.className = 'tool-status';
  status.textContent = activity.is_error ? '⚠ 오류' : '✓ 완료';
  const chevron = document.createElement('span');
  chevron.className = 'tool-chevron';
  chevron.textContent = '⌄';
  summary.append(icon, label, status, chevron);
  const body = document.createElement('div');
  body.className = 'tool-detail';
  body.textContent = `입력: ${JSON.stringify(activity.arguments)}`;
  card.append(summary, body);
  conversation.appendChild(card);
}

function autoResize() {
  input.style.height = 'auto';
  input.style.height = `${Math.min(input.scrollHeight, 130)}px`;
}

form.addEventListener('submit', async (event) => {
  event.preventDefault();
  const text = input.value.trim();
  if (!text) return;

  welcome.hidden = true;
  addMessage(text, 'user');
  chatMessages.push({ role: 'user', content: text });
  input.value = '';
  autoResize();
  sendButton.disabled = true;
  try {
    // UI와 API가 같은 FastAPI 앱에서 제공되므로 상대 경로를 사용한다.
    const response = await fetch('/api/chat', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        messages: chatMessages,
        use_tools: toolToggle.getAttribute('aria-pressed') === 'true',
      }),
    });
    const data = await response.json();
    if (!response.ok) throw new Error(data.detail || '요청에 실패했습니다.');
    data.tools.forEach(addToolActivity);
    addMessage(data.message.content, 'assistant');
    chatMessages.push(data.message);
  } catch (error) {
    addMessage(`연결 오류: ${error.message}`, 'assistant');
  } finally {
    sendButton.disabled = false;
    input.focus();
  }
});

input.addEventListener('input', autoResize);
input.addEventListener('keydown', (event) => {
  // Enter는 전송, Shift+Enter는 textarea 기본 줄바꿈으로 유지한다.
  if (event.key === 'Enter' && !event.shiftKey) {
    event.preventDefault();
    form.requestSubmit();
  }
});

toolToggle.addEventListener('click', () => {
  const enabled = toolToggle.getAttribute('aria-pressed') !== 'true';
  toolToggle.setAttribute('aria-pressed', String(enabled));
  showToast(enabled ? '도구 사용이 켜졌습니다.' : '도구 사용이 꺼졌습니다.');
});

document.querySelector('#newChat').addEventListener('click', () => {
  conversation.replaceChildren();
  chatMessages = [];
  welcome.hidden = false;
  document.querySelectorAll('.history-item').forEach(item => item.classList.remove('active'));
  input.focus();
  showToast('새 대화를 시작했습니다.');
});

document.querySelectorAll('.history-item').forEach((item) => {
  item.addEventListener('click', () => {
    document.querySelectorAll('.history-item').forEach(button => button.classList.remove('active'));
    item.classList.add('active');
    showToast(`“${item.dataset.title}” 대화를 선택했습니다.`);
    if (window.innerWidth <= 760) sidebar.classList.remove('open');
  });
});

menuButton.addEventListener('click', () => {
  const isOpen = sidebar.classList.toggle('open');
  menuButton.setAttribute('aria-expanded', String(isOpen));
});

document.querySelector('#settingsButton').addEventListener('click', () => showToast('설정 화면은 다음 단계에서 연결할 수 있어요.'));
document.querySelector('#helpButton').addEventListener('click', () => showToast('Enter로 전송하고 Shift+Enter로 줄을 바꿀 수 있어요.'));
