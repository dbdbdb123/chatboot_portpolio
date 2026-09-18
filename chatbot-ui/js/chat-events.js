import { MessageRole, StreamEvent } from './constants.js';
import { conversation } from './dom.js';
import { addAssistantMessage } from './chat-state.js';
import {
  addMessage, addToolActivity, now, renderMessageContent, showModel,
} from './ui.js';

export class ChatEventView {
  constructor(loadingIndicator) {
    this.loadingIndicator = loadingIndicator;
    this.currentMessage = null;
  }

  showLoading(label) {
    conversation.appendChild(this.loadingIndicator);
    this.loadingIndicator.hidden = false;
    this.loadingIndicator.lastChild.textContent = label;
  }

  handle = (type, data) => {
    if (type === StreamEvent.MODEL) showModel(data.model);
    if (type === StreamEvent.ROUND) {
      this.currentMessage = null;
      this.showLoading('응답을 기다리고 있어요…');
    }
    if (type === StreamEvent.DELTA) {
      if (!this.currentMessage) {
        this.currentMessage = addMessage('', MessageRole.ASSISTANT);
        this.currentMessage.meta.textContent = '작성 중…';
      }
      this.showLoading('응답을 작성하고 있어요…');
      if (data.sources || data.text.includes('\n\n검색한 문서:\n')) {
        renderMessageContent(this.currentMessage, data.text, data.sources);
      } else {
        this.currentMessage.body.appendChild(document.createTextNode(data.text));
      }
      this.loadingIndicator.scrollIntoView({ block: 'end' });
    }
    if (type === StreamEvent.TOOL) {
      if (this.currentMessage) this.currentMessage.meta.textContent = now();
      addToolActivity(data);
      conversation.appendChild(this.loadingIndicator);
    }
    if (type === StreamEvent.DONE) {
      showModel(data.model);
      if (!this.currentMessage) {
        this.currentMessage = addMessage(data.message.content, MessageRole.ASSISTANT);
      } else {
        renderMessageContent(this.currentMessage, data.message.content, data.sources);
      }
      this.currentMessage.meta.textContent = now();
      addAssistantMessage(data.message);
      window.dispatchEvent(new CustomEvent('chat-session-updated'));
    }
  };
}
