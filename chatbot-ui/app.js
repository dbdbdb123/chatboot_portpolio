const sidebar = document.querySelector('#sidebar');
const menuButton = document.querySelector('#menuButton');
const form = document.querySelector('#chatForm');
const input = document.querySelector('#messageInput');
const conversation = document.querySelector('#conversation');
const welcome = document.querySelector('#welcome');
const toolToggle = document.querySelector('#toolToggle');
const toast = document.querySelector('#toast');

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

function autoResize() {
  input.style.height = 'auto';
  input.style.height = `${Math.min(input.scrollHeight, 130)}px`;
}

form.addEventListener('submit', (event) => {
  event.preventDefault();
  const text = input.value.trim();
  if (!text) return;

  welcome.hidden = true;
  addMessage(text, 'user');
  input.value = '';
  autoResize();

  window.setTimeout(() => {
    const toolNote = toolToggle.getAttribute('aria-pressed') === 'true'
      ? ' 필요한 경우 연결된 도구도 함께 확인할게요.' : '';
    addMessage(`요청을 확인했습니다.${toolNote} 현재 화면은 정적 데모이므로 실제 모델 연결은 백엔드 API를 추가하면 동작합니다.`, 'assistant');
  }, 550);
});

input.addEventListener('input', autoResize);
input.addEventListener('keydown', (event) => {
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
