"""
PDF에서 영어 단어와 한국어 뜻을 추출하는 모듈
Google Cloud Vision API 지원 추가 (높은 인식률)
"""
import re
import io
import os
from dataclasses import dataclass
from typing import List, Optional

# PyMuPDF (선택적)
try:
    import fitz
    HAS_FITZ = True
except ImportError:
    HAS_FITZ = False

# OCR 관련 - pytesseract (fallback)
try:
    import pytesseract
    from PIL import Image, ImageEnhance
    HAS_OCR = True
except ImportError:
    HAS_OCR = False

# Google Cloud Vision API
try:
    from google.cloud import vision
    HAS_CLOUD_VISION = True
except ImportError:
    HAS_CLOUD_VISION = False

# Anthropic Claude Vision API
try:
    import anthropic
    HAS_ANTHROPIC = True
except ImportError:
    HAS_ANTHROPIC = False

# Google Gemini Vision API (무료) - 새로운 패키지
try:
    from google import genai
    from google.genai import types
    HAS_GEMINI = True
except ImportError:
    HAS_GEMINI = False


def detect_and_fix_orientation(img: 'Image.Image') -> 'Image.Image':
    """
    이미지의 방향을 감지하고 필요시 회전
    거꾸로 된 이미지(180도)를 자동으로 바로잡음
    """
    if not HAS_OCR:
        return img

    try:
        # Tesseract OSD로 방향 감지
        osd = pytesseract.image_to_osd(img, output_type=pytesseract.Output.DICT)
        rotation = osd.get('rotate', 0)

        if rotation != 0:
            # 이미지 회전 (Tesseract가 알려준 각도만큼)
            img = img.rotate(-rotation, expand=True)

        return img
    except Exception:
        # OSD 실패 시 대체 방법: 텍스트 방향 휴리스틱 체크
        # 원본과 180도 회전 이미지 모두 OCR 시도해서 더 나은 결과 선택
        try:
            # 작은 샘플로 빠르게 테스트
            test_img = img.copy()
            test_img.thumbnail((800, 800))

            # 원본 OCR
            text_original = pytesseract.image_to_string(test_img, lang='eng', config='--psm 6')
            # 영어 단어 개수 세기
            english_words_original = len(re.findall(r'\b[a-zA-Z]{2,}\b', text_original))

            # 180도 회전 후 OCR
            test_rotated = test_img.rotate(180)
            text_rotated = pytesseract.image_to_string(test_rotated, lang='eng', config='--psm 6')
            english_words_rotated = len(re.findall(r'\b[a-zA-Z]{2,}\b', text_rotated))

            # 더 많은 영어 단어가 인식된 방향 선택
            if english_words_rotated > english_words_original * 1.5:
                return img.rotate(180)

        except Exception:
            pass

        return img


@dataclass
class VocabItem:
    """어휘 항목"""
    number: int
    word: str
    meaning: str
    pos: Optional[str] = None  # 품사 (나중에 사용 가능)


def extract_text_from_pdf(pdf_path: str) -> str:
    """PDF에서 텍스트 추출"""
    doc = fitz.open(pdf_path)
    text = ""
    for page in doc:
        text += page.get_text()
    doc.close()
    return text


def extract_text_with_ocr(pdf_path: str, progress_callback=None) -> str:
    """OCR을 사용하여 스캔 PDF에서 텍스트 추출"""
    if not HAS_OCR:
        raise ImportError("OCR 기능을 사용하려면 pytesseract와 pillow를 설치하세요.")

    doc = fitz.open(pdf_path)
    text = ""
    total_pages = len(doc)

    for i, page in enumerate(doc):
        if progress_callback:
            progress_callback(i + 1, total_pages)

        # 페이지를 이미지로 변환 (해상도 300 DPI)
        mat = fitz.Matrix(300/72, 300/72)
        pix = page.get_pixmap(matrix=mat)

        # PIL Image로 변환
        img_data = pix.tobytes("png")
        img = Image.open(io.BytesIO(img_data))

        # 이미지 전처리: 그레이스케일 + 이진화
        img = img.convert('L')  # 그레이스케일
        # 이진화 (threshold)
        threshold = 180
        img = img.point(lambda x: 255 if x > threshold else 0, '1')
        img = img.convert('L')  # 다시 그레이스케일로

        # OCR 수행 (영어 + 한국어, PSM 6: 단일 블록)
        custom_config = r'--psm 6'
        page_text = pytesseract.image_to_string(img, lang='eng+kor', config=custom_config)
        text += page_text + "\n"

    doc.close()
    return text


def extract_vocab_with_ocr_table(pdf_path: str, progress_callback=None, rotate: int = 0) -> List['VocabItem']:
    """
    표 형태의 스캔 PDF에서 직접 어휘 추출
    각 페이지를 왼쪽/오른쪽으로 나누어 처리
    자동으로 이미지 방향 감지 및 회전

    Args:
        rotate: 수동 회전 각도 (0, 90, 180, 270). 0이면 자동 감지
    """
    if not HAS_OCR:
        raise ImportError("OCR 기능을 사용하려면 pytesseract와 pillow를 설치하세요.")

    doc = fitz.open(pdf_path)
    vocab_list = []
    total_pages = len(doc)

    for page_idx, page in enumerate(doc):
        if progress_callback:
            progress_callback(page_idx + 1, total_pages)

        # 페이지를 이미지로 변환 (해상도 300 DPI)
        mat = fitz.Matrix(300/72, 300/72)
        pix = page.get_pixmap(matrix=mat)
        img_data = pix.tobytes("png")
        img = Image.open(io.BytesIO(img_data))

        # 🔄 이미지 회전
        if rotate != 0:
            # 수동 회전 지정됨
            img = img.rotate(-rotate, expand=True)
        else:
            # 자동 방향 감지 및 회전
            img = detect_and_fix_orientation(img)

        # 이미지 전처리
        img = img.convert('L')
        threshold = 180
        img = img.point(lambda x: 255 if x > threshold else 0, '1')
        img = img.convert('L')

        width, height = img.size

        # 왼쪽 절반과 오른쪽 절반 분리 처리
        for half_idx, (left, right) in enumerate([(0, width//2), (width//2, width)]):
            half_img = img.crop((left, 0, right, height))

            # OCR 수행
            custom_config = r'--psm 6'
            text = pytesseract.image_to_string(half_img, lang='eng+kor', config=custom_config)

            # 텍스트에서 단어 추출
            items = parse_ocr_vocab_text(text)
            vocab_list.extend(items)

    doc.close()

    # 번호로 정렬하고 중복 제거
    vocab_list = sorted(vocab_list, key=lambda x: x.number)
    seen = set()
    unique_list = []
    for item in vocab_list:
        if item.number not in seen:
            seen.add(item.number)
            unique_list.append(item)

    return unique_list


def parse_ocr_vocab_text(text: str) -> List['VocabItem']:
    """OCR 텍스트에서 어휘 항목 파싱 (더 유연한 패턴)"""
    vocab_list = []
    lines = text.split('\n')

    # 패턴: 숫자 + (체크박스) + 영어단어
    # 다음 줄: 품사. 한국어뜻
    i = 0
    while i < len(lines):
        line = lines[i].strip()

        # 번호와 영어 단어 찾기
        # 예: "51 O empty" 또는 "51 □ empty" 또는 "51 empty"
        match = re.match(r'^(\d+)\s*[O□☐\[\]oO]?\s*([a-zA-Z][a-zA-Z\-]*)', line)
        if match:
            number = int(match.group(1))
            word = match.group(2).strip()

            # 다음 줄에서 뜻 찾기
            meaning = ""
            if i + 1 < len(lines):
                next_line = lines[i + 1].strip()
                # 한글이 포함된 줄
                if re.search(r'[가-힣]', next_line):
                    # 품사 제거
                    meaning = re.sub(r'^[avn]\.\s*', '', next_line)
                    meaning = re.sub(r'\s+[avn]\.\s*', ', ', meaning)
                    meaning = ' '.join(meaning.split())
                    i += 1

            # 같은 줄에 뜻이 있을 수도 있음
            if not meaning:
                rest = line[match.end():].strip()
                if re.search(r'[가-힣]', rest):
                    meaning = re.sub(r'^[avn]\.\s*', '', rest)
                    meaning = re.sub(r'\s+[avn]\.\s*', ', ', meaning)
                    meaning = ' '.join(meaning.split())

            if word and len(word) > 1 and meaning:
                vocab_list.append(VocabItem(
                    number=number,
                    word=word,
                    meaning=meaning
                ))

        i += 1

    return vocab_list


def parse_vocab_table(text: str) -> List[VocabItem]:
    """
    텍스트에서 어휘 항목 파싱
    형식: 번호 □ 영어단어 품사. 한국어뜻
    """
    vocab_list = []

    # 정규식 패턴: 번호, 체크박스, 영어단어, 품사+뜻
    # 예: "51 □ empty a. 비어 있는 v. 비우다"
    pattern = r'(\d+)\s*[□☐\[\]]\s*([a-zA-Z\-]+)\s+(.+?)(?=\d+\s*[□☐\[\]]|$)'

    matches = re.findall(pattern, text, re.DOTALL)

    for match in matches:
        number = int(match[0])
        word = match[1].strip()
        meaning_raw = match[2].strip()

        # 품사 제거하고 뜻만 추출
        # 품사 패턴: a. v. n. ad. 등
        meaning_clean = re.sub(r'\b[avn](?:d)?\.?\s*', '', meaning_raw)
        # 여러 줄/공백 정리
        meaning_clean = ' '.join(meaning_clean.split())
        # 괄호 안 내용 유지, 쉼표로 구분된 여러 뜻 유지
        meaning_clean = meaning_clean.strip()

        # 품사 추출 (나중에 사용 가능)
        pos_matches = re.findall(r'\b([avn](?:d)?)\.\s*', meaning_raw)
        pos = ', '.join(pos_matches) if pos_matches else None

        if word and meaning_clean:
            vocab_list.append(VocabItem(
                number=number,
                word=word,
                meaning=meaning_clean,
                pos=pos
            ))

    return vocab_list


def extract_vocab_from_pdf(pdf_path: str) -> List[VocabItem]:
    """PDF에서 어휘 목록 추출 (메인 함수)"""
    text = extract_text_from_pdf(pdf_path)
    return parse_vocab_table(text)


# 대체 파싱 방법 (표 구조가 잘 안 읽힐 경우)
def parse_vocab_simple(text: str) -> List[VocabItem]:
    """
    간단한 파싱 방법
    OCR 텍스트에서 번호, 단어, 뜻을 추출 (여러 패턴 지원)
    """
    vocab_list = []

    # 방법 1: "번호 □ 단어" + "품사. 뜻" 패턴 (2줄 형식)
    # 예: "301 □ heal" 다음 줄 "v. 치료하다"
    pattern_two_line = re.findall(
        r'(\d+)\s*[□☐\[\]O]?\s*([a-zA-Z][a-zA-Z\-]*(?:\s*\([^)]+\))?)\s*\n\s*([avn]\.?\s*[가-힣].*?)(?=\n\d+|\n*$)',
        text, re.MULTILINE
    )
    if pattern_two_line:
        for match in pattern_two_line:
            number = int(match[0])
            word = match[1].strip()
            meaning = match[2].strip()
            # 품사 제거
            meaning = re.sub(r'^[avn]\.\s*', '', meaning)
            if word and meaning:
                vocab_list.append(VocabItem(number=number, word=word, meaning=meaning))
        if vocab_list:
            return sorted(vocab_list, key=lambda x: x.number)

    # 방법 2: "번호 단어 품사.뜻" 한 줄 패턴
    # 예: "301 heal v. 치료하다"
    pattern_one_line = re.findall(
        r'(\d+)\s*[□☐\[\]O]?\s*([a-zA-Z][a-zA-Z\-]*(?:\s*\([^)]+\))?)\s+([avn]\.\s*[가-힣][^\n]*)',
        text
    )
    if pattern_one_line:
        for match in pattern_one_line:
            number = int(match[0])
            word = match[1].strip()
            meaning = match[2].strip()
            meaning = re.sub(r'^[avn]\.\s*', '', meaning)
            if word and meaning:
                vocab_list.append(VocabItem(number=number, word=word, meaning=meaning))
        if vocab_list:
            return sorted(vocab_list, key=lambda x: x.number)

    # 방법 3: 줄 단위 상태 기반 파싱 (fallback)
    lines = [line.strip() for line in text.split('\n') if line.strip()]

    current_number = None
    current_word = None

    def save_item(number, word, meaning):
        nonlocal vocab_list
        if number is None:
            number = len(vocab_list) + 1
        if not meaning:
            meaning = "[뜻 입력 필요]"
        vocab_list.append(VocabItem(number=number, word=word, meaning=meaning))

    for line in lines:
        # 한 줄에 번호 + 단어 + 뜻이 모두 있는 경우
        full_match = re.match(r'^(\d+)\s*[□☐\[\]O]?\s*([a-zA-Z][a-zA-Z\-]*)\s+(.+)$', line)
        if full_match:
            number = int(full_match.group(1))
            word = full_match.group(2).strip()
            meaning = full_match.group(3).strip()
            # 품사 제거
            meaning = re.sub(r'^[avn]\.\s*', '', meaning)
            if re.search(r'[가-힣]', meaning):
                save_item(number, word, meaning)
                current_number = None
                current_word = None
                continue

        # 번호 + 단어만 있는 줄
        num_word_match = re.match(r'^(\d+)\s*[□☐\[\]O]?\s*([a-zA-Z][a-zA-Z\-]*)$', line)
        if num_word_match:
            if current_word:
                save_item(current_number, current_word, "")
            current_number = int(num_word_match.group(1))
            current_word = num_word_match.group(2).strip()
            continue

        # 뜻만 있는 줄 (한글 포함)
        if re.search(r'[가-힣]', line) and current_word:
            meaning = re.sub(r'^[avn]\.\s*', '', line)
            meaning = ' '.join(meaning.split())
            save_item(current_number, current_word, meaning)
            current_word = None
            current_number = None
            continue

        # 영단어만 있는 줄
        if re.match(r'^[a-zA-Z][a-zA-Z\-]*$', line):
            if current_word:
                save_item(current_number, current_word, "")
            current_word = line.strip()
            continue

    if current_word:
        save_item(current_number, current_word, "")

    return vocab_list


def load_vocab_from_text(file_path: str) -> List[VocabItem]:
    """
    텍스트/CSV 파일에서 어휘 로드
    형식: 번호,단어,뜻 또는 단어,뜻
    """
    # 파일 전체 읽기
    with open(file_path, 'r', encoding='utf-8') as f:
        text = f.read()

    # 1. 스마트 파싱 시도 (비정형 텍스트, OCR 결과 등)
    # parse_vocab_simple은 줄바꿈이 엉망인 텍스트를 처리할 수 있음
    vocab_list = parse_vocab_simple(text)
    if vocab_list:
        return vocab_list

    # 2. 기존 CSV 파싱 (백업 - 스마트 파싱 결과가 없을 때만 실행)
    vocab_list = []
    lines = text.split('\n')

    for i, line in enumerate(lines):
        line = line.strip()
        if not line or line.startswith('#'):
            continue

        parts = line.split(',', 2)  # 최대 3개로 분리

        if len(parts) >= 3:
            # 번호,단어,뜻
            try:
                number = int(parts[0])
            except ValueError:
                number = i + 1
            word = parts[1].strip()
            meaning = parts[2].strip()
        elif len(parts) == 2:
            # 단어,뜻
            number = i + 1
            word = parts[0].strip()
            meaning = parts[1].strip()
        else:
            continue

        if word and meaning:
            vocab_list.append(VocabItem(
                number=number,
                word=word,
                meaning=meaning
            ))

    return vocab_list


def extract_vocab_with_gemini_vision(image_path: str, api_key: str) -> List[VocabItem]:
    """
    Google Gemini Vision API로 이미지에서 단어 목록 직접 추출
    REST API 직접 호출 방식 (SDK 문제 우회)

    Args:
        image_path: 이미지 파일 경로
        api_key: Google AI Studio API 키

    Returns:
        VocabItem 리스트
    """
    import json
    import base64
    import requests

    # 이미지를 base64로 인코딩
    with open(image_path, 'rb') as f:
        image_data = base64.standard_b64encode(f.read()).decode('utf-8')

    # MIME 타입 결정
    ext = image_path.lower().split('.')[-1]
    mime_type = {
        'jpg': 'image/jpeg',
        'jpeg': 'image/jpeg',
        'png': 'image/png',
        'gif': 'image/gif',
        'webp': 'image/webp'
    }.get(ext, 'image/jpeg')

    prompt = """이 이미지는 영어 단어장입니다.
이미지에서 모든 영어 단어와 한국어 뜻을 추출해주세요.

다음 JSON 형식으로만 응답해주세요 (다른 텍스트 없이):
[
  {"number": 301, "word": "heal", "meaning": "치료하다"},
  {"number": 302, "word": "breath", "meaning": "숨, 호흡"},
  ...
]

주의사항:
- 번호, 영어 단어, 한국어 뜻을 정확히 추출
- 품사(n. v. a. 등)는 뜻에서 제외
- 이미지가 회전되어 있어도 올바르게 읽기
- 2단으로 된 경우 왼쪽 단부터 순서대로
- JSON만 출력하고 다른 설명은 하지 마세요"""

    # 여러 모델 시도 (순서대로)
    models_to_try = [
        'gemini-1.5-flash-latest',
        'gemini-1.5-pro-latest',
        'gemini-pro-vision',
    ]

    last_error = None

    for model_name in models_to_try:
        try:
            # REST API 직접 호출
            url = f"https://generativelanguage.googleapis.com/v1beta/models/{model_name}:generateContent?key={api_key}"

            payload = {
                "contents": [{
                    "parts": [
                        {
                            "inlineData": {
                                "mimeType": mime_type,
                                "data": image_data
                            }
                        },
                        {
                            "text": prompt
                        }
                    ]
                }],
                "generationConfig": {
                    "temperature": 0.1,
                    "maxOutputTokens": 4096
                }
            }

            response = requests.post(url, json=payload, timeout=60)
            result = response.json()

            # 에러 체크
            if 'error' in result:
                error_msg = result['error'].get('message', str(result['error']))
                # 404 에러면 다음 모델 시도
                if result['error'].get('code') == 404:
                    continue
                # 429 할당량 에러면 예외 발생
                raise Exception(f"{result['error'].get('code')} {result['error'].get('status')}. {result['error']}")

            # 응답 추출
            if 'candidates' in result and result['candidates']:
                response_text = result['candidates'][0]['content']['parts'][0]['text'].strip()

                # JSON 추출 (코드 블록 안에 있을 수 있음)
                if '```json' in response_text:
                    response_text = response_text.split('```json')[1].split('```')[0]
                elif '```' in response_text:
                    response_text = response_text.split('```')[1].split('```')[0]

                vocab_data = json.loads(response_text.strip())
                vocab_list = []
                for item in vocab_data:
                    vocab_list.append(VocabItem(
                        number=int(item.get('number', len(vocab_list) + 1)),
                        word=item.get('word', ''),
                        meaning=item.get('meaning', '')
                    ))
                return vocab_list

        except json.JSONDecodeError:
            continue
        except Exception as e:
            last_error = e
            # 404가 아닌 에러면 바로 예외 발생
            if '404' not in str(e):
                raise

    # 모든 모델 실패
    if last_error:
        raise last_error
    return []


def extract_vocab_with_claude_vision(image_path: str, api_key: str) -> List[VocabItem]:
    """
    Claude Vision API로 이미지에서 단어 목록 직접 추출
    표 형식 단어장을 정확하게 인식

    Args:
        image_path: 이미지 파일 경로
        api_key: Anthropic API 키

    Returns:
        VocabItem 리스트
    """
    import base64
    import json

    # 이미지를 base64로 인코딩
    with open(image_path, 'rb') as f:
        image_data = base64.standard_b64encode(f.read()).decode('utf-8')

    # 파일 확장자로 미디어 타입 결정
    ext = image_path.lower().split('.')[-1]
    media_type = {
        'jpg': 'image/jpeg',
        'jpeg': 'image/jpeg',
        'png': 'image/png',
        'gif': 'image/gif',
        'webp': 'image/webp'
    }.get(ext, 'image/jpeg')

    # Claude API 호출
    client = anthropic.Anthropic(api_key=api_key)

    message = client.messages.create(
        model="claude-sonnet-4-20250514",
        max_tokens=4096,
        messages=[
            {
                "role": "user",
                "content": [
                    {
                        "type": "image",
                        "source": {
                            "type": "base64",
                            "media_type": media_type,
                            "data": image_data,
                        },
                    },
                    {
                        "type": "text",
                        "text": """이 이미지는 영어 단어장입니다.
이미지에서 모든 영어 단어와 한국어 뜻을 추출해주세요.

다음 JSON 형식으로만 응답해주세요 (다른 텍스트 없이):
[
  {"number": 301, "word": "heal", "meaning": "치료하다"},
  {"number": 302, "word": "breath", "meaning": "숨, 호흡"},
  ...
]

주의사항:
- 번호, 영어 단어, 한국어 뜻을 정확히 추출
- 품사(n. v. a. 등)는 뜻에서 제외
- 이미지가 회전되어 있어도 올바르게 읽기
- 2단으로 된 경우 왼쪽 단부터 순서대로"""
                    }
                ],
            }
        ],
    )

    # 응답 파싱
    response_text = message.content[0].text.strip()

    # JSON 추출 (코드 블록 안에 있을 수 있음)
    if '```json' in response_text:
        response_text = response_text.split('```json')[1].split('```')[0]
    elif '```' in response_text:
        response_text = response_text.split('```')[1].split('```')[0]

    try:
        vocab_data = json.loads(response_text)
        vocab_list = []
        for item in vocab_data:
            vocab_list.append(VocabItem(
                number=int(item.get('number', len(vocab_list) + 1)),
                word=item.get('word', ''),
                meaning=item.get('meaning', '')
            ))
        return vocab_list
    except json.JSONDecodeError:
        # JSON 파싱 실패시 텍스트로 반환
        return []


def extract_text_with_cloud_vision(image_path: str, api_key: str = None) -> str:
    """
    Google Cloud Vision API로 이미지에서 텍스트 추출
    높은 인식률, 특히 한글+영어 혼합 텍스트에 우수

    Args:
        image_path: 이미지 파일 경로
        api_key: Google Cloud Vision API 키 (없으면 환경변수에서 읽음)

    Returns:
        추출된 텍스트
    """
    import requests
    import base64

    with open(image_path, 'rb') as f:
        image_content = base64.b64encode(f.read()).decode('utf-8')

    if api_key:
        # API 키로 직접 인증 (REST API 방식)
        url = f"https://vision.googleapis.com/v1/images:annotate?key={api_key}"
        payload = {
            "requests": [{
                "image": {"content": image_content},
                "features": [{"type": "DOCUMENT_TEXT_DETECTION"}],
                "imageContext": {
                    "languageHints": ["ko", "en"]
                }
            }]
        }

        response = requests.post(url, json=payload)
        result = response.json()

        # 에러 체크
        if 'error' in result:
            raise Exception(f"Cloud Vision API 오류: {result['error']}")

        if 'responses' in result and result['responses']:
            resp = result['responses'][0]
            if 'error' in resp:
                raise Exception(f"Cloud Vision API 오류: {resp['error']}")

            # fullTextAnnotation 사용 (더 정확한 순서)
            full_text = resp.get('fullTextAnnotation', {}).get('text', '')
            if full_text:
                return full_text

            # fallback: textAnnotations
            annotations = resp.get('textAnnotations', [])
            if annotations:
                return annotations[0].get('description', '')
        return ""

    elif HAS_CLOUD_VISION:
        # 서비스 계정 인증 (GOOGLE_APPLICATION_CREDENTIALS 환경변수)
        client = vision.ImageAnnotatorClient()

        with open(image_path, 'rb') as f:
            content = f.read()

        image = vision.Image(content=content)
        response = client.document_text_detection(image=image)

        if response.full_text_annotation:
            return response.full_text_annotation.text
        return ""

    else:
        raise ImportError("Google Cloud Vision을 사용하려면 API 키를 입력하거나 google-cloud-vision을 설치하세요.")


def extract_text_from_image(image_path: str, two_column: bool = True,
                            use_cloud_vision: bool = True, api_key: str = None) -> str:
    """
    이미지 파일(JPG, PNG 등)에서 텍스트 추출 (OCR)

    Args:
        image_path: 이미지 파일 경로
        two_column: 2단 분리 처리 여부 (pytesseract 전용)
        use_cloud_vision: Cloud Vision API 사용 여부 (기본값: True)
        api_key: Google Cloud Vision API 키

    Returns:
        추출된 텍스트
    """
    # Cloud Vision 사용 시도 (권장)
    if use_cloud_vision and (HAS_CLOUD_VISION or api_key):
        try:
            text = extract_text_with_cloud_vision(image_path, api_key)
            if text:
                return text
        except Exception as e:
            print(f"Cloud Vision 오류, pytesseract로 fallback: {e}")

    # Fallback: pytesseract
    if not HAS_OCR:
        raise ImportError("OCR 기능을 사용하려면 pytesseract와 pillow를 설치하세요.")

    from PIL import Image, ImageEnhance

    img = Image.open(image_path)

    # 전처리 1: 해상도 확대 (OCR 인식률 향상)
    base_width = 2000
    if img.width < base_width:
        w_percent = (base_width / float(img.width))
        h_size = int((float(img.height) * float(w_percent)))
        img = img.resize((base_width, h_size), Image.Resampling.LANCZOS)

    # 방향 보정
    img = detect_and_fix_orientation(img)

    # 전처리 2: 그레이스케일 및 화질 개선
    img = img.convert('L')
    img = ImageEnhance.Contrast(img).enhance(2.0)
    img = ImageEnhance.Sharpness(img).enhance(1.5)

    full_text = ""

    if two_column:
        # 2단 분리 처리 (단어장용)
        width, height = img.size
        for left, right in [(0, width // 2), (width // 2, width)]:
            crop_img = img.crop((left, 0, right, height))
            text = pytesseract.image_to_string(crop_img, lang='eng+kor', config='--psm 6')
            full_text += text + "\n"
    else:
        full_text = pytesseract.image_to_string(img, lang='eng+kor', config='--psm 6')

    return full_text


if __name__ == "__main__":
    # 테스트
    import sys
    if len(sys.argv) > 1:
        file_path = sys.argv[1]
        if file_path.endswith('.txt') or file_path.endswith('.csv'):
            vocab = load_vocab_from_text(file_path)
        else:
            vocab = extract_vocab_from_pdf(file_path)
        print(f"추출된 단어 수: {len(vocab)}")
        for item in vocab[:5]:
            print(f"{item.number}. {item.word} - {item.meaning}")
