import { MessageRole } from './constants.js';
import { conversation, input, sendButton, welcome } from './dom.js';
import { ChatEventView } from './chat-events.js';
import { requestChatStream } from './chat-request.js';
import {
  addUserMessage, removePendingUserMessage, resetChatState, restoreChatState,
} from './chat-state.js';
import { clearImage, getSelectedImage, isReadingImage } from './image.js';
import { readChatStream } from './stream.js';
import {
  addLoadingIndicator, addMessage, autoResize, setSending,
} from './ui.js';

/** 새 대화를 시작할 수 있는 상태인지 확인하고 화면과 로컬 기록을 초기화한다. */
export function startNewChat(sessionId = null) {
  if (sendButton.disabled || isReadingImage()) return false;
  clearImage();
  conversation.replaceChildren();
  resetChatState(sessionId);
  welcome.hidden = false;
  document.querySelectorAll('.history-item').forEach(item => item.classList.remove('active'));
  input.focus();
  return true;
}

/** 저장된 세션을 선택했을 때 메시지 배열과 대화 화면을 서버 응답으로 복원한다. */
export function restoreChatSession(sessionId, messages) {
  const chatMessages = restoreChatState(sessionId, messages);
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
  addUserMessage(text);
  input.value = '';
  autoResize();
  setSending(true);
  const loadingIndicator = addLoadingIndicator();
  const eventView = new ChatEventView(loadingIndicator);

  try {
    const response = await requestChatStream(image);
    await readChatStream(response, eventView.handle);
    clearImage();
  } catch (error) {
    if (eventView.currentMessage) eventView.currentMessage.meta.textContent = '응답 중단';
    removePendingUserMessage();
    loadingIndicator.remove();
    addMessage(`연결 오류: ${error.message}`, MessageRole.ASSISTANT);
  } finally {
    loadingIndicator.remove();
    setSending(false);
    input.focus();
  }
}
