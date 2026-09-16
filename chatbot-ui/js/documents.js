import {
  documentInput, documentPreview, documentsDialog, documentStatus,
} from './dom.js';

/** 문서 API를 호출하고 성공 응답의 JSON만 반환하도록 오류 처리를 공통화한다. */
async function documentRequest(url, options) {
  const response = await fetch(url, options);
  const data = await response.json();
  if (!response.ok) {
    throw new Error(typeof data.detail === 'string' ? data.detail : '문서 요청에 실패했습니다.');
  }
  return data;
}

/** 서버에 등록된 문서 목록을 보기·삭제 동작과 함께 다시 그린다. */
async function refreshDocuments() {
  const data = await documentRequest('/api/knowledge/documents');
  const list = document.querySelector('#documentList');
  list.replaceChildren();
  if (!data.documents.length) list.textContent = '등록된 문서가 없습니다. 파일을 선택해 등록하세요.';
  for (const doc of data.documents) {
    const item = document.createElement('li');
    const label = document.createElement('span');
    label.textContent = doc.name;
    const view = document.createElement('button');
    view.type = 'button';
    view.textContent = '보기';

    // 보기 버튼을 누르면 해당 문서의 전체 내용을 서버에서 받아 미리보기에 표시한다.
    view.addEventListener('click', async () => {
      try {
        const content = await documentRequest(`/api/knowledge/documents/${doc.id}`);
        documentPreview.textContent = content.content;
        documentPreview.hidden = false;
      } catch (error) { documentStatus.textContent = error.message; }
    });
    const remove = document.createElement('button');
    remove.type = 'button';
    remove.textContent = '삭제';
    remove.setAttribute('aria-label', `${doc.name} 삭제`);

    // 삭제 버튼을 누르면 해당 문서를 제거하고 서버의 최신 문서 목록을 다시 불러온다.
    remove.addEventListener('click', async () => {
      remove.disabled = true;
      try {
        await documentRequest(`/api/knowledge/documents/${doc.id}`, { method: 'DELETE' });
        documentPreview.hidden = true;
        documentStatus.textContent = `${doc.name} 삭제 완료`;
        await refreshDocuments();
      } catch (error) {
        documentStatus.textContent = error.message;
        remove.disabled = false;
      }
    });
    item.append(label, view, remove);
    list.append(item);
  }
}

async function handleDocumentSelection() {
  const file = documentInput.files[0];
  if (!file) return;
  documentInput.disabled = true;
  documentStatus.textContent = '문서 등록 및 검색 준비 중… 처음에는 시간이 걸릴 수 있습니다.';
  try {
    const isPdf = /\.pdf$/i.test(file.name);
    let result;
    if (isPdf) {
      if (file.size > 10000000) throw new Error('PDF는 10 MB 이하로 등록하세요.');
      result = await documentRequest(`/api/knowledge/pdf?name=${encodeURIComponent(file.name)}`, {
        method: 'POST', headers: { 'Content-Type': 'application/pdf' }, body: file,
      });
    } else {
      if (file.size > 200000 || !/\.(md|txt)$/i.test(file.name)) {
        throw new Error('Markdown·TXT(200 KB 이하) 또는 PDF(10 MB 이하)를 선택하세요.');
      }
      const content = new TextDecoder('utf-8', { fatal: true }).decode(await file.arrayBuffer());
      result = await documentRequest('/api/knowledge/documents', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ name: file.name, content }),
      });
    }
    documentStatus.textContent = result.unchanged
      ? '변경된 내용이 없습니다.' : '문서 등록 완료. 문서 질문을 켜고 질문하세요.';
    if (result.empty_pages?.length) {
      documentStatus.textContent += ` 텍스트 없는 페이지(${result.empty_pages.join(', ')})는 검색에서 제외됩니다. 스캔된 부분은 OCR이 필요합니다.`;
    }
    await refreshDocuments();
  } catch (error) {
    documentStatus.textContent = error.message;
  } finally {
    documentInput.disabled = false;
    documentInput.value = '';
  }
}

/** 문서 관리 대화상자의 열기·닫기·등록 이벤트를 연결한다. */
export function initializeDocuments() {
  // 문서 관리 버튼을 누르면 대화상자를 열고 등록된 문서 목록을 최신 상태로 갱신한다.
  document.querySelector('#documentsButton').addEventListener('click', async () => {
    documentsDialog.showModal();
    try { await refreshDocuments(); } catch (error) { documentStatus.textContent = error.message; }
  });

  // 닫기 버튼을 누르면 문서 관리 대화상자를 닫는다.
  document.querySelector('#closeDocuments').addEventListener('click', () => documentsDialog.close());

  // 등록할 파일을 선택하면 형식에 맞춰 내용을 읽고 문서 등록 API를 호출한다.
  documentInput.addEventListener('change', handleDocumentSelection);
}
