import { MAX_INPUT_HEIGHT, MessageRole, TOAST_DURATION_MS } from './constants.js';
import {
  attachImage, conversation, input, knowledgeToggle, modelBadge, removeImage,
  sendButton, thinkingState, thinkingToggle, toast, toolToggle,
} from './dom.js';

/** Thinking 선택 상태를 버튼의 접근성 속성과 ON/OFF 표시에 반영한다. */
export function setThinking(enabled) {
  thinkingToggle.setAttribute('aria-pressed', String(enabled));
  thinkingState.textContent = enabled ? 'ON' : 'OFF';
}

/** 응답 중 중복 전송과 옵션 변경을 막도록 관련 버튼을 잠그거나 해제한다. */
export function setSending(sending) {
  [sendButton, thinkingToggle, attachImage, removeImage, toolToggle, knowledgeToggle]
    .forEach(button => { button.disabled = sending; });
  // 문서 질문 모드에서는 요청이 끝난 뒤에도 이미지 첨부를 허용하지 않는다.
  attachImage.disabled = sending || knowledgeToggle.getAttribute('aria-pressed') === 'true';
}

/** 유효한 모델명이 전달되면 화면의 모델 배지를 갱신한다. */
export function showModel(model) {
  if (typeof model === 'string' && model.trim()) modelBadge.textContent = model;
}

/** 상태 API에서 현재 모델명을 조회한다. */
export async function loadModel() {
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

/** 안내 메시지를 잠시 표시하고 이전 토스트의 닫기 타이머를 갱신한다. */
export function showToast(message) {
  toast.textContent = message;
  toast.classList.add('show');
  window.clearTimeout(showToast.timer);
  showToast.timer = window.setTimeout(() => toast.classList.remove('show'), TOAST_DURATION_MS);
}

/** 현재 로컬 시간을 메시지 표시에 맞는 시·분 형식으로 반환한다. */
export function now() {
  return new Intl.DateTimeFormat('ko-KR', {
    hour: '2-digit', minute: '2-digit', hour12: false,
  }).format(new Date());
}

/** 역할에 맞는 말풍선을 추가하고 후속 갱신에 필요한 DOM을 반환한다. */
export function addMessage(text, role) {
  const article = document.createElement('article');
  article.className = `message ${role}-message`;
  if (role === MessageRole.ASSISTANT) {
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
  meta.textContent = `${now()}${role === MessageRole.USER ? '  ✓✓' : ''}`;
  bubble.appendChild(meta);
  article.appendChild(bubble);
  conversation.appendChild(article);
  article.scrollIntoView({ behavior: 'smooth', block: 'end' });
  return { article, body, meta };
}

/** MCP 도구 실행 정보를 접을 수 있는 카드로 대화 영역에 추가한다. */
export function addToolActivity(activity) {
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
  detail.textContent = activity.server === 'internal'
    ? '기본 도구로 실행' : `${activity.server} MCP 서버에서 실행`;
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

/** 입력 내용에 맞춰 메시지 입력창 높이를 최대 제한까지 조정한다. */
export function autoResize() {
  input.style.height = 'auto';
  input.style.height = `${Math.min(input.scrollHeight, MAX_INPUT_HEIGHT)}px`;
}

/** 응답 대기 표시를 추가하고 갱신·제거에 사용할 DOM을 반환한다. */
export function addLoadingIndicator() {
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
