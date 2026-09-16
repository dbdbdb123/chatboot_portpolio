import { StreamEvent } from './constants.js';

/** SSE 응답을 이벤트별로 파싱해 콜백에 전달하고 오류·미완료 종료를 감지한다. */
export async function readChatStream(response, onEvent) {
  if (!response.body) throw new Error('스트리밍 응답을 읽을 수 없습니다.');
  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = '';
  let completed = false;
  try {
    while (!completed) {
      // 네트워크 청크는 SSE 이벤트 중간에서 나뉠 수 있으므로 버퍼에 누적한다.
      const { value, done } = await reader.read();
      buffer += decoder.decode(value, { stream: !done });
      let boundary;
      while ((boundary = buffer.indexOf('\n\n')) !== -1) {
        const frame = buffer.slice(0, boundary);
        buffer = buffer.slice(boundary + 2);
        const lines = frame.split('\n');
        const type = lines.find(line => line.startsWith('event:'))?.slice(6).trim();
        const data = lines
          .filter(line => line.startsWith('data:'))
          .map(line => line.slice(5).trimStart())
          .join('\n');
        if (!data) continue;
        const payload = JSON.parse(data);
        if (type === StreamEvent.ERROR) throw new Error(payload.detail);
        onEvent(type, payload);
        if (type === StreamEvent.DONE) {
          completed = true;
          break;
        }
      }
      if (done && !completed) throw new Error('응답 연결이 중단되었습니다. 다시 시도해 주세요.');
    }
  } finally {
    await reader.cancel().catch(() => {});
    reader.releaseLock();
  }
}
