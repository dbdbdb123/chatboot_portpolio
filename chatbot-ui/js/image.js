import {
  ALLOWED_IMAGE_TYPES, MAX_IMAGE_BYTES, MAX_IMAGE_DIMENSION, MAX_IMAGE_PIXELS,
} from './constants.js';
import {
  attachImage, imageAttachment, imageInput, imageName, imagePreview, removeImage,
} from './dom.js';
import { showToast } from './ui.js';

let selectedImage = null;
let readingImage = false;

export function getSelectedImage() { return selectedImage; }
export function isReadingImage() { return readingImage; }

/** 선택한 파일을 미리보기와 API 전송에 사용할 Data URL로 읽는다. */
function readImageDataUrl(file) {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => resolve(reader.result);
    reader.onerror = () => reject(new Error('이미지를 읽을 수 없습니다.'));
    reader.readAsDataURL(file);
  });
}

/** 읽는 동안 첨부·제거 버튼을 잠가 중복 조작을 막는다. */
function setImageReading(reading) {
  readingImage = reading;
  attachImage.disabled = reading;
  removeImage.disabled = reading;
}

/** 선택한 이미지 데이터와 파일 입력값, 미리보기를 초기화한다. */
export function clearImage() {
  selectedImage = null;
  imageInput.value = '';
  imagePreview.removeAttribute('src');
  imageAttachment.hidden = true;
}

/** 첨부 이미지의 형식·크기·해상도를 검증하고 미리보기를 준비한다. */
export async function handleImageSelection() {
  const file = imageInput.files[0];
  if (!file) return;
  if (!ALLOWED_IMAGE_TYPES.includes(file.type) || !file.size || file.size > MAX_IMAGE_BYTES) {
    showToast('PNG·JPEG·WebP 이미지 1장, 최대 10MB까지 첨부할 수 있습니다.');
    imageInput.value = '';
    return;
  }
  setImageReading(true);
  try {
    const dataUrl = await readImageDataUrl(file);
    const preview = new Image();
    preview.src = dataUrl;
    await preview.decode();
    if (Math.max(preview.naturalWidth, preview.naturalHeight) > MAX_IMAGE_DIMENSION
        || preview.naturalWidth * preview.naturalHeight > MAX_IMAGE_PIXELS) {
      throw new Error('가로·세로 8000px, 총 2500만 픽셀 이하 이미지를 선택해 주세요.');
    }
    selectedImage = {
      name: file.name, mime_type: file.type, data_base64: dataUrl.split(',')[1],
    };
    imagePreview.src = dataUrl;
    imageName.textContent = file.name;
    imageAttachment.hidden = false;
  } catch (error) {
    showToast(error.message || '올바른 이미지 파일이 아닙니다.');
    imageInput.value = '';
  } finally {
    setImageReading(false);
  }
}
