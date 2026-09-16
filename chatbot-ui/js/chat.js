import { MessageRole, StreamEvent } from './constants.js';
import { conversation, input, knowledgeToggle, sendButton, thinkingToggle, toolToggle, welcome } from './dom.js';
import { clearImage, getSelectedImage, isReadingImage } from './image.js';
import { readChatStream } from './stream.js';
import {
  addLoadingIndicator, addMessage, addToolActivity, autoResize, now,
  renderMessageContent, setSending, showModel,
} from './ui.js';

// 서버가 무상태이므로 현재 탭의 전체 대화 기록을 매 요청에 함께 보낸다.
let chatMessages = [];
let currentSessionId = null;

/** 새 대화를 시작할 수 있는 상태인지 확인하고 화면과 로컬 기록을 초기화한다. */
export function startNewChat(sessionId = null) {
  if (sendButton.disabled || isReadingImage()) return false;
  clearImage();
  conversation.replaceChildren();
  chatMessages = [];
  currentSessionId = sessionId;
  welcome.hidden = false;
  document.querySelectorAll('.history-item').forEach(item => item.classList.remove('active'));
  input.focus();
  return true;
}

/** 저장된 세션을 선택했을 때 메시지 배열과 대화 화면을 서버 응답으로 복원한다. */
export function restoreChatSession(sessionId, messages) {
  currentSessionId = sessionId;
  chatMessages = messages.map(message => ({ role: message.role, content: message.content }));
  conversation.replaceChildren();
  welcome.hidden = chatMessages.length > 0;
  for (const message of chatMessages) addMessage(message.content, message.role);
  input.focus();
}

/** 메시지와 첨부를 전송하고 스트리밍 화면, 대화 기록, 실패 처리를 관리한다. */
export async function handleChatSubmit(event) {
  event.preventDefault();
  if (isReadingImage() || sendButton.disabled) return;
  const image = getSelectedImage();
  const text = input.value.trim() || (image ? '첨부 이미지를 설명해 줘.' : '');
  if (!text) return;
  welcome.hidden = true;
  const userMessage = addMessage(text, MessageRole.USER);
  if (image) {
    const thumbnail = document.createElement('img');
    thumbnail.className = 'message-image';
    thumbnail.alt = image.name;
    thumbnail.src = `data:${image.mime_type};base64,${image.data_base64}`;
    userMessage.body.before(thumbnail);
  }
  chatMessages.push({ role: MessageRole.USER, content: text });
  input.value = '';
  autoResize();
  const think = thinkingToggle.getAttribute('aria-pressed') === 'true';
  setSending(true);
  const loadingIndicator = addLoadingIndicator();
  let currentMessage = null;

  function handleStreamEvent(type, data) {
    if (type === StreamEvent.MODEL) showModel(data.model);
    if (type === StreamEvent.ROUND) {
      currentMessage = null;
      conversation.appendChild(loadingIndicator);
      loadingIndicator.hidden = false;
      loadingIndicator.lastChild.textContent = '응답을 기다리고 있어요…';
    }
    if (type === StreamEvent.DELTA) {
      if (!currentMessage) {
        currentMessage = addMessage('', MessageRole.ASSISTANT);
        currentMessage.meta.textContent = '작성 중…';
        conversation.appendChild(loadingIndicator);
        loadingIndicator.lastChild.textContent = '응답을 작성하고 있어요…';
      }
      // RAG는 최종 답변과 출처를 한 이벤트로 보내므로 즉시 두 영역으로 분리한다.
      // 일반 채팅의 토큰 스트림은 기존처럼 텍스트 노드만 이어 붙인다.
      if (data.text.includes('\n\n검색한 문서:\n')) {
        renderMessageContent(currentMessage, data.text);
      } else {
        currentMessage.body.appendChild(document.createTextNode(data.text));
      }
      loadingIndicator.scrollIntoView({ block: 'end' });
    }
    if (type === StreamEvent.TOOL) {
      if (currentMessage) currentMessage.meta.textContent = now();
      addToolActivity(data);
      conversation.appendChild(loadingIndicator);
    }
    if (type === StreamEvent.DONE) {
      showModel(data.model);
      if (!currentMessage) currentMessage = addMessage(data.message.content, MessageRole.ASSISTANT);
      else renderMessageContent(currentMessage, data.message.content);
      currentMessage.meta.textContent = now();
      chatMessages.push(data.message);
      clearImage();
      // 저장 완료 후 세션 제목과 최근 활동 순서를 다시 표시하도록 목록 갱신을 요청한다.
      window.dispatchEvent(new CustomEvent('chat-session-updated'));
    }
  }

  try {
    const response = await fetch('/api/chat/stream', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', Accept: 'text/event-stream' },
      body: JSON.stringify({
        // Redis 세션은 서버가 과거 기록을 불러오므로 현재 질문만 보낸다.
        // 저장 기능이 없는 환경에서는 기존처럼 브라우저의 전체 기록을 전달한다.
        messages: currentSessionId ? [chatMessages.at(-1)] : chatMessages,
        use_tools: toolToggle.getAttribute('aria-pressed') === 'true',
        use_knowledge: knowledgeToggle.getAttribute('aria-pressed') === 'true',
        think,
        image,
        // Redis 기능이 비활성화된 환경에서는 null로 전송되어 기존 무상태 채팅을 유지한다.
        session_id: currentSessionId,
      }),
    });
    if (!response.ok) {
      const data = await response.json().catch(() => ({}));
      const detail = Array.isArray(data.detail) ? data.detail.map(item => item.msg).join(' / ') : data.detail;
      throw new Error(detail || '요청에 실패했습니다.');
    }
    await readChatStream(response, handleStreamEvent);
  } catch (error) {
    if (currentMessage) currentMessage.meta.textContent = '응답 중단';
    chatMessages.pop();
    loadingIndicator.remove();
    addMessage(`연결 오류: ${error.message}`, MessageRole.ASSISTANT);
  } finally {
    loadingIndicator.remove();
    setSending(false);
    input.focus();
  }
}
