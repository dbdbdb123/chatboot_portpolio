const sidebar = document.querySelector('#sidebar');
const menuButton = document.querySelector('#menuButton');
const form = document.querySelector('#chatForm');
const input = document.querySelector('#messageInput');
const conversation = document.querySelector('#conversation');
const welcome = document.querySelector('#welcome');
const toolToggle = document.querySelector('#toolToggle');
const thinkingToggle = document.querySelector('#thinkingToggle');
const thinkingState = document.querySelector('#thinkingState');

function setThinking(enabled) {
  thinkingToggle.setAttribute('aria-pressed', String(enabled));
  thinkingState.textContent = enabled ? 'ON' : 'OFF';
}
try {
  setThinking(localStorage.getItem('mori.think') === 'true');
} catch { /* 저장소가 차단되어도 기본 OFF로 사용할 수 있다. */ }
const toast = document.querySelector('#toast');
const sendButton = document.querySelector('#sendButton');
const modelBadge = document.querySelector('#modelBadge');

const imageInput = document.querySelector('#imageInput');
const attachImage = document.querySelector('#attachImage');
const removeImage = document.querySelector('#removeImage');
const imageAttachment = document.querySelector('#imageAttachment');
const imagePreview = document.querySelector('#imagePreview');
let selectedImage = null;
let readingImage = false;

function clearImage() {
  selectedImage = null;
  imageInput.value = '';
  imagePreview.removeAttribute('src');
  imageAttachment.hidden = true;
}
attachImage.addEventListener('click', () => imageInput.click());
removeImage.addEventListener('click', clearImage);
imageInput.addEventListener('change', async () => {
  const file = imageInput.files[0];
  if (!file) return;
  if (!['image/png', 'image/jpeg', 'image/webp'].includes(file.type) ||
      !file.size || file.size > 10 * 1024 * 1024) {
    showToast('PNG·JPEG·WebP 이미지 1장, 최대 10MB까지 첨부할 수 있습니다.');
    imageInput.value = '';
    return;
  }
  readingImage = true;
  attachImage.disabled = true;
  removeImage.disabled = true;
  try {
    const dataUrl = await new Promise((resolve, reject) => {
      const reader = new FileReader();
      reader.onload = () => resolve(reader.result);
      reader.onerror = () => reject(new Error('이미지를 읽을 수 없습니다.'));
      reader.readAsDataURL(file);
    });
    const preview = new Image();
    preview.src = dataUrl;
    await preview.decode();
    if (Math.max(preview.naturalWidth, preview.naturalHeight) > 8000 ||
        preview.naturalWidth * preview.naturalHeight > 25000000) {
      throw new Error('가로·세로 8000px, 총 2500만 픽셀 이하 이미지를 선택해 주세요.');
    }
    selectedImage = { name: file.name, mime_type: file.type, data_base64: dataUrl.split(',')[1] };
    imagePreview.src = dataUrl;
    document.querySelector('#imageName').textContent = file.name;
    imageAttachment.hidden = false;
  } catch (error) {
    showToast(error.message || '올바른 이미지 파일이 아닙니다.');
    imageInput.value = '';
  } finally {
    readingImage = false;
    attachImage.disabled = false;
    removeImage.disabled = false;
  }
});

function showModel(model) {
  if (typeof model !== 'string' || !model.trim()) return;
  modelBadge.textContent = model;
}

async function loadModel() {
  try {
    const response = await fetch('/api/health', { cache: 'no-store' });
    if (!response.ok) throw new Error('모델 조회 실패');
    const data = await response.json();
    if (typeof data.model !== 'string' || !data.model.trim()) throw new Error('모델 정보 없음');
    showModel(data.model);
  } catch {
    modelBadge.textContent = '모델 확인 불가';
  }
}

loadModel();

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
  const body = document.createElement('span');
  body.textContent = text;
  bubble.appendChild(body);

  const meta = document.createElement('span');
  meta.className = 'message-meta';
  meta.textContent = `${now()}${role === 'user' ? '  ✓✓' : ''}`;
  bubble.appendChild(meta);
  article.appendChild(bubble);
  conversation.appendChild(article);
  article.scrollIntoView({ behavior: 'smooth', block: 'end' });
  return { article, body, meta };
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

function addLoadingIndicator() {
  const indicator = document.createElement('div');
  indicator.className = 'message assistant-message loading-message';
  indicator.setAttribute('role', 'status');
  const wheel = document.createElement('span');
  wheel.className = 'loading-wheel';
  wheel.setAttribute('aria-hidden', 'true');
  const label = document.createElement('span');
  label.textContent = '응답을 기다리고 있어요…';
  indicator.append(wheel, label);
  conversation.appendChild(indicator);
  indicator.scrollIntoView({ behavior: 'smooth', block: 'end' });
  return indicator;
}

async function readChatStream(response, onEvent) {
  if (!response.body) throw new Error('스트리밍 응답을 읽을 수 없습니다.');
  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = '';
  let completed = false;
  try {
    while (!completed) {
      const { value, done } = await reader.read();
      buffer += decoder.decode(value, { stream: !done });
      let boundary;
      while ((boundary = buffer.indexOf('\n\n')) !== -1) {
        const frame = buffer.slice(0, boundary);
        buffer = buffer.slice(boundary + 2);
        const lines = frame.split('\n');
        const type = lines.find(line => line.startsWith('event:'))?.slice(6).trim();
        const data = lines.filter(line => line.startsWith('data:')).map(line => line.slice(5).trimStart()).join('\n');
        if (!data) continue; // keep-alive comment
        const payload = JSON.parse(data);
        if (type === 'error') throw new Error(payload.detail);
        onEvent(type, payload);
        if (type === 'done') {
          completed = true;
          break;
        }
      }
      if (done && !completed) throw new Error('응답 연결이 중단되었습니다. 다시 시도해 주세요.');
    }
  } finally {
    await reader.cancel().catch(() => {});
    reader.releaseLock();
  }
}

form.addEventListener('submit', async (event) => {
  event.preventDefault();
  if (readingImage || sendButton.disabled) return;
  const image = selectedImage;
  const text = input.value.trim() || (image ? '첨부 이미지를 설명해 줘.' : '');
  if (!text) return;


  welcome.hidden = true;
  const userMessage = addMessage(text, 'user');
  if (image) {
    const thumbnail = document.createElement('img');
    thumbnail.className = 'message-image';
    thumbnail.alt = image.name;
    thumbnail.src = `data:${image.mime_type};base64,${image.data_base64}`;
    userMessage.body.before(thumbnail);
  }
  chatMessages.push({ role: 'user', content: text });
  input.value = '';
  autoResize();
  sendButton.disabled = true;
  const think = thinkingToggle.getAttribute('aria-pressed') === 'true';
  thinkingToggle.disabled = true;
  attachImage.disabled = removeImage.disabled = toolToggle.disabled = true;
  const loadingIndicator = addLoadingIndicator();
  let currentMessage = null;
  try {
    // UI와 API가 같은 FastAPI 앱에서 제공되므로 상대 경로를 사용한다.
    const response = await fetch('/api/chat/stream', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', Accept: 'text/event-stream' },
      body: JSON.stringify({
        messages: chatMessages,
        use_tools: toolToggle.getAttribute('aria-pressed') === 'true',
        think,
        image,
      }),
    });
    if (!response.ok) {
      const data = await response.json().catch(() => ({}));
      const detail = Array.isArray(data.detail) ? data.detail.map(item => item.msg).join(' / ') : data.detail;
      throw new Error(detail || '요청에 실패했습니다.');
    }
    await readChatStream(response, (type, data) => {
      if (type === 'model') showModel(data.model);
      if (type === 'round') {
        currentMessage = null;
        conversation.appendChild(loadingIndicator);
        loadingIndicator.hidden = false;
        loadingIndicator.lastChild.textContent = '응답을 기다리고 있어요…';
      }
      if (type === 'delta') {
        if (!currentMessage) {
          currentMessage = addMessage('', 'assistant');
          currentMessage.meta.textContent = '작성 중…';
          conversation.appendChild(loadingIndicator);
          loadingIndicator.lastChild.textContent = '응답을 작성하고 있어요…';
        }
        currentMessage.body.appendChild(document.createTextNode(data.text));
        loadingIndicator.scrollIntoView({ block: 'end' });
      }
      if (type === 'tool') {
        if (currentMessage) currentMessage.meta.textContent = now();
        addToolActivity(data);
        conversation.appendChild(loadingIndicator);
      }
      if (type === 'done') {
        showModel(data.model);
        if (!currentMessage) currentMessage = addMessage(data.message.content, 'assistant');
        currentMessage.meta.textContent = now();
        chatMessages.push(data.message);
        clearImage();
      }
    });
  } catch (error) {
    if (currentMessage) currentMessage.meta.textContent = '응답 중단';
    chatMessages.pop(); // 실패한 요청은 다음 대화 기록에 포함하지 않는다.
    loadingIndicator.remove();
    addMessage(`연결 오류: ${error.message}`, 'assistant');
  } finally {
    loadingIndicator.remove();
    sendButton.disabled = false;
    thinkingToggle.disabled = false;
    attachImage.disabled = removeImage.disabled = toolToggle.disabled = false;
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
  showToast(enabled ? 'OCR 도구 사용이 켜졌습니다.' : 'OCR 도구 사용이 꺼졌습니다.');
});

thinkingToggle.addEventListener('click', () => {
  const enabled = thinkingToggle.getAttribute('aria-pressed') !== 'true';
  setThinking(enabled);
  try { localStorage.setItem('mori.think', String(enabled)); } catch { /* 선택은 현재 탭에서 유지 */ }
  showToast(enabled ? 'Thinking ON: 답변 전 추론을 수행합니다.' : 'Thinking OFF: 바로 답변을 생성합니다.');
});

document.querySelector('#newChat')?.addEventListener('click', () => {
  if (sendButton.disabled) {
    showToast('응답이 끝난 뒤 새 대화를 시작해 주세요.');
    return;
  }
  if (readingImage) return;
  clearImage();
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
