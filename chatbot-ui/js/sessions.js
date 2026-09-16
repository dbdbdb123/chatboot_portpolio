import { MOBILE_BREAKPOINT } from './constants.js';
import { historyList, sidebar } from './dom.js';
import { restoreChatSession, startNewChat } from './chat.js';
import { showToast } from './ui.js';

let storageAvailable = true;

/** 세션 API를 호출하고 오류 응답을 사용자가 이해할 수 있는 예외로 변환한다. */
async function sessionRequest(url, options) {
  const response = await fetch(url, options);
  const data = await response.json().catch(() => ({}));
  if (!response.ok) throw new Error(data.detail || '대화 기록 요청에 실패했습니다.');
  return data;
}

/** 새 Redis 세션을 만들고 채팅 요청에 사용할 세션 ID를 반환한다. */
export async function createSession() {
  if (!storageAvailable) return null;
  try {
    const session = await sessionRequest('/api/chat/sessions', { method: 'POST' });
    await refreshSessions();
    return session.id;
  } catch (error) {
    storageAvailable = false;
    showToast(`${error.message} 현재 대화는 임시로만 유지됩니다.`);
    return null;
  }
}

/** 선택한 세션의 3일 이내 메시지를 가져와 대화 화면을 복원한다. */
async function openSession(sessionId) {
  try {
    const data = await sessionRequest(`/api/chat/sessions/${sessionId}`);
    restoreChatSession(sessionId, data.messages);
    document.querySelectorAll('.history-item').forEach((item) => {
      item.classList.toggle('active', item.dataset.sessionId === sessionId);
    });
    if (window.innerWidth <= MOBILE_BREAKPOINT) sidebar.classList.remove('open');
  } catch (error) {
    showToast(error.message);
  }
}

/** Redis 세션 목록을 최근 활동 순서로 사이드바에 다시 그린다. */
export async function refreshSessions() {
  if (!storageAvailable) return [];
  try {
    const sessions = await sessionRequest('/api/chat/sessions');
    historyList.replaceChildren();
    for (const session of sessions) {
      const button = document.createElement('button');
      button.type = 'button';
      button.className = 'history-item';
      button.dataset.sessionId = session.id;
      const icon = document.createElement('span');
      icon.className = 'chat-icon';
      icon.setAttribute('aria-hidden', 'true');
      const title = document.createElement('span');
      title.textContent = session.title;
      const time = document.createElement('time');
      time.dateTime = session.updated_at;
      time.textContent = new Intl.DateTimeFormat('ko-KR', {
        month: 'numeric', day: 'numeric',
      }).format(new Date(session.updated_at));
      button.append(icon, title, time);

      // 세션 항목을 누르면 보관 기간 안에 남아 있는 메시지를 서버에서 다시 불러온다.
      button.addEventListener('click', () => openSession(session.id));
      historyList.appendChild(button);
    }
    return sessions;
  } catch {
    // Redis 미설정 환경에서는 목록만 숨기고 기존 임시 채팅 기능은 계속 제공한다.
    storageAvailable = false;
    historyList.replaceChildren();
    return [];
  }
}

/** 앱 시작 시 최신 세션을 복원하고 답변 저장 후 사이드바를 갱신한다. */
export async function initializeSessions() {
  const sessions = await refreshSessions();
  if (sessions.length) {
    await openSession(sessions[0].id);
  } else {
    // 첫 방문에도 사용자가 별도로 새 대화를 누르지 않아도 첫 메시지부터 저장되게 한다.
    const sessionId = await createSession();
    startNewChat(sessionId);
  }

  // 채팅 모듈이 정상 답변 완료를 알리면 변경된 제목과 활동 시각을 다시 조회한다.
  window.addEventListener('chat-session-updated', refreshSessions);
}
