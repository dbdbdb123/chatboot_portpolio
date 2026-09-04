// UI 제한값과 API 계약의 고정 선택값. Enum 역할의 객체는 변경하지 못하도록 고정한다.
const ALLOWED_IMAGE_TYPES = Object.freeze(['image/png', 'image/jpeg', 'image/webp']);
const MAX_IMAGE_BYTES = 10 * 1024 * 1024;
const MAX_IMAGE_DIMENSION = 8000;
const MAX_IMAGE_PIXELS = 25_000_000;
const MAX_INPUT_HEIGHT = 130;
const TOAST_DURATION_MS = 1800;
const MOBILE_BREAKPOINT = 760;
const THINKING_STORAGE_KEY = 'mori.think';

const MessageRole = Object.freeze({
  SYSTEM: 'system', USER: 'user', ASSISTANT: 'assistant', TOOL: 'tool',
});
const StreamEvent = Object.freeze({
  MODEL: 'model', ROUND: 'round', DELTA: 'delta', TOOL: 'tool', DONE: 'done', ERROR: 'error',
});
