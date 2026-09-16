// UI 제한값과 API 계약의 고정 선택값. Enum 역할의 객체는 변경하지 못하도록 고정한다.
export const ALLOWED_IMAGE_TYPES = Object.freeze(['image/png', 'image/jpeg', 'image/webp']);
export const MAX_IMAGE_BYTES = 10 * 1024 * 1024;
export const MAX_IMAGE_DIMENSION = 8000;
export const MAX_IMAGE_PIXELS = 25_000_000;
export const MAX_INPUT_HEIGHT = 130;
export const TOAST_DURATION_MS = 1800;
export const MOBILE_BREAKPOINT = 760;
export const THINKING_STORAGE_KEY = 'mori.think';

export const MessageRole = Object.freeze({
  SYSTEM: 'system', USER: 'user', ASSISTANT: 'assistant', TOOL: 'tool',
});
export const StreamEvent = Object.freeze({
  MODEL: 'model', ROUND: 'round', DELTA: 'delta', TOOL: 'tool', DONE: 'done', ERROR: 'error',
});
