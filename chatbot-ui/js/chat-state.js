import { MessageRole } from './constants.js';

let messages = [];
let sessionId = null;

export function resetChatState(nextSessionId = null) {
  messages = [];
  sessionId = nextSessionId;
}

export function restoreChatState(nextSessionId, storedMessages) {
  sessionId = nextSessionId;
  messages = storedMessages.map(({ role, content }) => ({ role, content }));
  return getMessages();
}

export function addUserMessage(content) {
  messages.push({ role: MessageRole.USER, content });
}

export function addAssistantMessage(message) {
  messages.push(message);
}

export function removePendingUserMessage() {
  if (messages.at(-1)?.role === MessageRole.USER) messages.pop();
}

export function getMessages() {
  return messages.map(message => ({ ...message }));
}

export function getSessionId() {
  return sessionId;
}
