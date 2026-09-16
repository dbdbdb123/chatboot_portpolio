import { THINKING_STORAGE_KEY } from './constants.js';
import {
  attachImage, form, imageInput, input, knowledgeToggle, menuButton, removeImage,
  sendButton, sidebar, thinkingToggle, toolToggle,
} from './dom.js';
import { handleChatSubmit, startNewChat } from './chat.js';
import { initializeDocuments } from './documents.js';
import { clearImage, handleImageSelection } from './image.js';
import { autoResize, loadModel, setThinking, showToast } from './ui.js';
import { createSession, initializeSessions } from './sessions.js';

/** 채팅 입력, 옵션, 사이드바 등 공통 화면 이벤트를 연결한다. */
function initializeChatUi() {
  // 사용자가 입력할 때마다 내용 길이에 맞춰 textarea 높이를 다시 계산한다.
  input.addEventListener('input', autoResize);

  // 메시지 입력창에서 Enter는 전송하고 Shift+Enter는 줄바꿈으로 처리한다.
  input.addEventListener('keydown', (event) => {
    if (event.key === 'Enter' && !event.shiftKey) {
      event.preventDefault();
      form.requestSubmit();
    }
  });

  // 도구 사용 버튼을 누르면 API 요청에 전달할 도구 활성화 상태를 전환한다.
  toolToggle.addEventListener('click', () => {
    const enabled = toolToggle.getAttribute('aria-pressed') !== 'true';
    toolToggle.setAttribute('aria-pressed', String(enabled));
    showToast(enabled ? '도구 사용이 켜졌습니다.' : '도구 사용이 꺼졌습니다.');
  });

  // Thinking 버튼을 누르면 추론 사용 상태를 전환하고 브라우저 저장소에 보존한다.
  thinkingToggle.addEventListener('click', () => {
    const enabled = thinkingToggle.getAttribute('aria-pressed') !== 'true';
    setThinking(enabled);
    try { localStorage.setItem(THINKING_STORAGE_KEY, String(enabled)); } catch { /* 현재 탭에서 유지 */ }
    showToast(enabled
      ? 'Thinking ON: 답변 전 추론을 수행합니다.'
      : 'Thinking OFF: 바로 답변을 생성합니다.');
  });

  // 문서 질문 버튼을 누르면 지식 검색 모드와 일반 대화 모드를 전환한다.
  knowledgeToggle.addEventListener('click', () => {
    const enabled = knowledgeToggle.getAttribute('aria-pressed') !== 'true';
    knowledgeToggle.setAttribute('aria-pressed', String(enabled));
    knowledgeToggle.textContent = enabled ? '문서 질문 ON' : '문서 질문 OFF';
    if (enabled) clearImage();
    attachImage.disabled = enabled;
    input.maxLength = enabled ? 800 : 2000;
    input.placeholder = enabled
      ? '등록 문서에 대해 구체적으로 질문하세요 (800자 이내)' : '무엇이든 물어보세요';
    showToast(enabled ? '등록된 문서에서 먼저 검색합니다.' : '일반 대화 모드입니다.');
  });

  // 새 대화 버튼을 누르면 진행 중 요청이 없는 경우 화면과 대화 기록을 초기화한다.
  document.querySelector('#newChat')?.addEventListener('click', async () => {
    if (sendButton.disabled) {
      showToast('응답이 끝난 뒤 새 대화를 시작해 주세요.');
      return;
    }
    // Redis가 활성화된 경우 새 세션 ID를 받고, 비활성 환경에서는 null로 임시 대화를 시작한다.
    const sessionId = await createSession();
    if (!startNewChat(sessionId)) return;
    showToast('새 대화를 시작했습니다.');
  });

  // 모바일 메뉴 버튼을 누르면 사이드바와 접근성 확장 상태를 함께 전환한다.
  menuButton.addEventListener('click', () => {
    const isOpen = sidebar.classList.toggle('open');
    menuButton.setAttribute('aria-expanded', String(isOpen));
  });
  // 설정 버튼을 누르면 아직 연결되지 않은 기능임을 토스트로 안내한다.
  document.querySelector('#settingsButton').addEventListener('click', () => {
    showToast('설정 화면은 다음 단계에서 연결할 수 있어요.');
  });
  // 도움말 버튼을 누르면 메시지 입력 단축키를 토스트로 안내한다.
  document.querySelector('#helpButton').addEventListener('click', () => {
    showToast('Enter로 전송하고 Shift+Enter로 줄을 바꿀 수 있어요.');
  });
}

/** 저장 상태를 복원하고 각 기능 모듈을 초기화한다. */
async function initializeApp() {
  try {
    setThinking(localStorage.getItem(THINKING_STORAGE_KEY) === 'true');
  } catch { /* 저장소가 차단되어도 기본 OFF로 동작한다. */ }
  initializeChatUi();
  initializeDocuments();
  // 초기 세션 ID를 확정한 뒤 전송 이벤트를 연결해 첫 메시지가 저장에서 누락되지 않게 한다.
  await initializeSessions();
  loadModel();

  // 이미지 첨부 버튼을 누르면 숨겨진 파일 선택 창을 연다.
  attachImage.addEventListener('click', () => imageInput.click());

  // 이미지 제거 버튼을 누르면 선택 데이터와 미리보기를 모두 초기화한다.
  removeImage.addEventListener('click', clearImage);

  // 파일 선택값이 바뀌면 이미지 형식과 크기를 검증하고 미리보기를 준비한다.
  imageInput.addEventListener('change', handleImageSelection);

  // 채팅 폼이 제출되면 현재 메시지와 옵션을 서버로 전송한다.
  form.addEventListener('submit', handleChatSubmit);
}

initializeApp();
