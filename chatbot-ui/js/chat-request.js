import { knowledgeToggle, thinkingToggle, toolToggle } from './dom.js';
import { getMessages, getSessionId } from './chat-state.js';

function buildPayload(image) {
  const sessionId = getSessionId();
  const messages = getMessages();
  return {
    // 서버 세션이 있으면 과거 기록은 서버가 복원하므로 현재 질문만 보낸다.
    messages: sessionId ? [messages.at(-1)] : messages,
    use_tools: toolToggle.getAttribute('aria-pressed') === 'true',
    use_knowledge: knowledgeToggle.getAttribute('aria-pressed') === 'true',
    think: thinkingToggle.getAttribute('aria-pressed') === 'true',
    image,
    session_id: sessionId,
  };
}

export async function requestChatStream(image) {
  const response = await fetch('/api/chat/stream', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', Accept: 'text/event-stream' },
    body: JSON.stringify(buildPayload(image)),
  });
  if (response.ok) return response;

  const data = await response.json().catch(() => ({}));
  const detail = Array.isArray(data.detail)
    ? data.detail.map(item => item.msg).join(' / ')
    : data.detail;
  throw new Error(detail || '요청에 실패했습니다.');
}
