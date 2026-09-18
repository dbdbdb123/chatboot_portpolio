// 구조화된 sources를 우선 사용하고, 현재 백엔드의 문자열 형식은 호환 경로로만 해석한다.
const SOURCE_SECTION_MARKER = '\n\n검색한 문서:\n';

function normalizeSources(sources) {
  if (!Array.isArray(sources)) return [];
  return sources.map((source) => {
    if (typeof source === 'string') return source.trim();
    if (!source || typeof source !== 'object') return '';
    return String(source.label || source.text || source.name || '').trim();
  }).filter(Boolean);
}

export function parseMessageContent(content, sources) {
  const text = typeof content === 'string' ? content : '';
  const structuredSources = normalizeSources(sources);
  if (structuredSources.length) return { answer: text, sources: structuredSources };

  const markerIndex = text.indexOf(SOURCE_SECTION_MARKER);
  if (markerIndex === -1) return { answer: text, sources: [] };
  return {
    answer: text.slice(0, markerIndex),
    sources: text.slice(markerIndex + SOURCE_SECTION_MARKER.length)
      .split('\n')
      .map(line => line.trim())
      .filter(Boolean),
  };
}
