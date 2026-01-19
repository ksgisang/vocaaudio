"""
VocaAudio - 어휘 학습 오디오 생성기 (Streamlit 웹 버전)
스마트폰 사진에서 단어를 추출하고 MP3 학습 오디오를 생성합니다.
"""
import streamlit as st
import tempfile
import os
import asyncio
from pathlib import Path

# 로컬 모듈
from pdf_parser import (VocabItem, load_vocab_from_text, parse_vocab_simple,
                        extract_text_from_image, extract_vocab_with_claude_vision,
                        extract_vocab_with_gemini_vision)
from tts_generator import generate_vocab_audio, TTSConfig, get_available_voices

# Excel 지원
try:
    import openpyxl
    HAS_EXCEL = True
except ImportError:
    HAS_EXCEL = False

# 페이지 설정
st.set_page_config(
    page_title="VocaAudio - 어휘 학습 오디오",
    page_icon="🎧",
    layout="wide"
)

# 세션 상태 초기화
if 'vocab_list' not in st.session_state:
    st.session_state.vocab_list = []
if 'ocr_text' not in st.session_state:
    st.session_state.ocr_text = ""


def get_api_key():
    """API 키 가져오기 (Streamlit secrets 또는 세션)"""
    # Streamlit Cloud secrets에서 먼저 확인
    try:
        return st.secrets.get("GOOGLE_CLOUD_API_KEY", None)
    except:
        pass
    # 세션에서 확인
    return st.session_state.get('api_key', None)


def process_image_ocr(image_path: str, ocr_method: str, st_module) -> list:
    """이미지에서 OCR로 단어 추출하는 공통 함수"""
    if ocr_method == "Gemini Vision (무료/추천)":
        gemini_key = st.session_state.get('gemini_api_key', '')
        if not gemini_key:
            st_module.error("❌ 사이드바에서 Gemini API 키를 입력해주세요.")
            return []
        st_module.info("🤖 Gemini Vision으로 단어 추출 중...")
        return extract_vocab_with_gemini_vision(image_path, gemini_key)

    elif ocr_method == "Claude Vision":
        anthropic_key = st.session_state.get('anthropic_api_key', '')
        if not anthropic_key:
            st_module.error("❌ 사이드바에서 Anthropic API 키를 입력해주세요.")
            return []
        st_module.info("🤖 Claude Vision으로 단어 추출 중...")
        return extract_vocab_with_claude_vision(image_path, anthropic_key)

    else:
        # Google Cloud Vision
        from PIL import Image
        api_key = st.session_state.get('api_key', None)
        img = Image.open(image_path)

        if img.width > img.height:
            img = img.rotate(-90, expand=True)
            st_module.info("📐 가로 이미지 감지 - 자동 회전 적용")

        full_text = ""
        width, height = img.size

        for idx, (left, right) in enumerate([(0, width // 2), (width // 2, width)]):
            crop_img = img.crop((left, 0, right, height))
            crop_path = image_path + f"_crop{idx}.jpg"
            crop_img.save(crop_path, "JPEG", quality=95)

            text = extract_text_from_image(
                crop_path,
                two_column=False,
                use_cloud_vision=bool(api_key),
                api_key=api_key
            )
            full_text += text + "\n"

            if os.path.exists(crop_path):
                os.unlink(crop_path)

        st.session_state.ocr_text = full_text
        return parse_text_to_vocab(full_text)


def parse_text_to_vocab(text: str) -> list:
    """텍스트를 VocabItem 리스트로 변환"""
    vocab_list = []

    # 스마트 파싱 시도
    vocab_list = parse_vocab_simple(text)
    if vocab_list:
        return vocab_list

    # CSV 파싱 (백업)
    lines = text.split('\n')
    for i, line in enumerate(lines):
        line = line.strip()
        if not line or line.startswith('#'):
            continue

        parts = line.split(',', 2)
        if len(parts) >= 3:
            try:
                number = int(parts[0].strip())
            except ValueError:
                number = len(vocab_list) + 1
            word = parts[1].strip()
            meaning = parts[2].strip()
        elif len(parts) == 2:
            number = len(vocab_list) + 1
            word = parts[0].strip()
            meaning = parts[1].strip()
        else:
            continue

        if word and meaning:
            vocab_list.append(VocabItem(number=number, word=word, meaning=meaning))

    return vocab_list


def load_excel(file) -> list:
    """Excel 파일 로드"""
    if not HAS_EXCEL:
        st.error("Excel 지원을 위해 openpyxl이 필요합니다.")
        return []

    vocab_list = []
    wb = openpyxl.load_workbook(file)
    ws = wb.active

    for i, row in enumerate(ws.iter_rows(min_row=1, values_only=True), 1):
        if not row or not row[0]:
            continue

        # 헤더 건너뛰기
        if i == 1 and isinstance(row[0], str) and ('단어' in row[0] or 'word' in row[0].lower()):
            continue

        if len(row) >= 2:
            word = str(row[0]).strip() if row[0] else ""
            meaning = str(row[1]).strip() if row[1] else ""

            if word and meaning:
                vocab_list.append(VocabItem(number=len(vocab_list)+1, word=word, meaning=meaning))

    wb.close()
    return vocab_list


def main():
    st.title("🎧 VocaAudio")
    st.markdown("**어휘 학습 오디오 생성기** - 스마트폰 사진에서 단어 추출 & MP3 생성")

    # 사이드바: 설정
    with st.sidebar:
        st.header("⚙️ 설정")

        # OCR 방식 선택
        st.subheader("🔍 OCR 방식")
        ocr_method = st.radio(
            "OCR 엔진 선택",
            ["Gemini Vision (무료/추천)", "Claude Vision", "Google Cloud Vision"],
            index=0,
            help="Gemini Vision이 무료이고 표 형식 단어장 인식에 좋습니다."
        )
        st.session_state.ocr_method = ocr_method

        # API 키 설정
        if ocr_method == "Gemini Vision (무료/추천)":
            st.subheader("🔑 Google AI Studio API 키")
            gemini_key = st.text_input(
                "Gemini API 키",
                type="password",
                help="https://aistudio.google.com 에서 무료 발급"
            )
            if gemini_key:
                st.session_state.gemini_api_key = gemini_key
        elif ocr_method == "Claude Vision":
            st.subheader("🔑 Anthropic API 키")
            anthropic_key = st.text_input(
                "Anthropic API 키",
                type="password",
                help="Claude Vision 사용에 필요 (유료)"
            )
            if anthropic_key:
                st.session_state.anthropic_api_key = anthropic_key
        else:
            st.subheader("🔑 Google Cloud Vision API")
            api_key_input = st.text_input(
                "Google API 키",
                type="password",
                help="높은 OCR 인식률을 위해 권장."
            )
            if api_key_input:
                st.session_state.api_key = api_key_input

        st.divider()

        # TTS 설정
        st.subheader("🔊 음성 설정")
        voices = get_available_voices()

        eng_voice = st.selectbox(
            "영어 음성",
            voices['english'],
            index=0
        )

        kor_voice = st.selectbox(
            "한국어 음성",
            voices['korean'],
            index=0
        )

        st.divider()

        st.subheader("🔄 반복 설정")
        eng_repeat = st.slider("영어 반복 횟수", 1, 5, 2)
        meaning_repeat = st.slider("뜻 반복 횟수", 1, 5, 1)
        pause = st.slider("단어 간격 (초)", 0.5, 5.0, 2.0, 0.5)

    # 메인 영역: 탭
    tab1, tab2, tab3, tab4 = st.tabs(["📷 카메라 촬영", "🖼️ 이미지/PDF", "📝 텍스트 입력", "📋 단어 목록"])

    # 탭 1: 카메라 촬영 (스마트폰용)
    with tab1:
        st.markdown("**스마트폰 카메라로 단어장을 바로 촬영하세요**")

        camera_image = st.camera_input("카메라로 촬영", key="camera")

        if camera_image:
            if st.button("🔍 촬영 이미지에서 텍스트 추출", type="primary", key="camera_ocr"):
                with st.spinner("텍스트 추출 중..."):
                    with tempfile.NamedTemporaryFile(delete=False, suffix='.jpg') as tmp:
                        tmp.write(camera_image.getvalue())
                        tmp_path = tmp.name

                    try:
                        ocr_method = st.session_state.get('ocr_method', 'Gemini Vision (무료/추천)')
                        vocab_list = process_image_ocr(tmp_path, ocr_method, st)
                        if vocab_list:
                            st.session_state.vocab_list = vocab_list
                            st.session_state.ocr_text = "\n".join([
                                f"{v.number}. {v.word} - {v.meaning}"
                                for v in vocab_list
                            ])
                            st.success(f"✅ {len(vocab_list)}개 단어 추출 완료!")
                    except Exception as e:
                        st.error(f"OCR 오류: {e}")
                    finally:
                        if os.path.exists(tmp_path):
                            os.unlink(tmp_path)

    # 탭 2: 이미지/PDF 업로드
    with tab2:
        st.markdown("**이미지 또는 PDF 파일을 업로드하세요**")

        uploaded_file = st.file_uploader(
            "파일 선택",
            type=['jpg', 'jpeg', 'png', 'pdf'],
            help="단어장 이미지나 PDF를 업로드하면 자동으로 텍스트를 추출합니다."
        )

        if uploaded_file:
            file_ext = Path(uploaded_file.name).suffix.lower()
            is_pdf = file_ext == '.pdf'

            if not is_pdf:
                # 이미지 미리보기
                col1, col2 = st.columns(2)
                with col1:
                    st.image(uploaded_file, caption="업로드된 이미지", use_container_width=True)
                with col2:
                    extract_btn = st.button("🔍 텍스트 추출 (OCR)", type="primary", key="img_ocr")
            else:
                # PDF 안내
                st.info(f"📄 PDF 파일: {uploaded_file.name}")
                extract_btn = st.button("🔍 PDF에서 텍스트 추출", type="primary", key="pdf_ocr")

            if extract_btn:
                with st.spinner("텍스트 추출 중..."):
                    with tempfile.NamedTemporaryFile(delete=False, suffix=file_ext) as tmp:
                        tmp.write(uploaded_file.getvalue())
                        tmp_path = tmp.name

                    try:
                        ocr_method = st.session_state.get('ocr_method', 'Gemini Vision (무료/추천)')

                        if is_pdf:
                            # PDF 처리: 각 페이지를 이미지로 변환 후 OCR
                            st.info("📄 PDF 페이지를 처리 중...")
                            from pdf_parser import extract_vocab_from_pdf, extract_text_from_pdf
                            try:
                                import fitz  # PyMuPDF
                                doc = fitz.open(tmp_path)
                                all_vocab = []

                                for page_num, page in enumerate(doc):
                                    st.text(f"페이지 {page_num + 1}/{len(doc)} 처리 중...")
                                    # 페이지를 이미지로 변환
                                    mat = fitz.Matrix(2.0, 2.0)  # 2x 해상도
                                    pix = page.get_pixmap(matrix=mat)
                                    img_path = tmp_path + f"_page{page_num}.png"
                                    pix.save(img_path)

                                    # OCR 실행
                                    vocab_list = process_image_ocr(img_path, ocr_method, st)
                                    if vocab_list:
                                        all_vocab.extend(vocab_list)

                                    if os.path.exists(img_path):
                                        os.unlink(img_path)

                                doc.close()

                                if all_vocab:
                                    # 번호 재정렬
                                    for i, v in enumerate(all_vocab):
                                        v.number = i + 1
                                    st.session_state.vocab_list = all_vocab
                                    st.session_state.ocr_text = "\n".join([
                                        f"{v.number}. {v.word} - {v.meaning}"
                                        for v in all_vocab
                                    ])
                                    st.success(f"✅ {len(all_vocab)}개 단어 추출 완료!")
                                else:
                                    st.error("PDF에서 단어를 추출할 수 없습니다.")

                            except ImportError:
                                st.error("PDF 처리를 위해 PyMuPDF가 필요합니다. (pip install pymupdf)")
                        else:
                            # 이미지 처리
                            vocab_list = process_image_ocr(tmp_path, ocr_method, st)
                            if vocab_list:
                                st.session_state.vocab_list = vocab_list
                                st.session_state.ocr_text = "\n".join([
                                    f"{v.number}. {v.word} - {v.meaning}"
                                    for v in vocab_list
                                ])
                                st.success(f"✅ {len(vocab_list)}개 단어 추출 완료!")
                            else:
                                st.error("단어를 추출할 수 없습니다. 이미지를 확인해주세요.")

                    except Exception as e:
                        st.error(f"오류: {e}")
                        import traceback
                        st.code(traceback.format_exc())
                    finally:
                        if os.path.exists(tmp_path):
                            os.unlink(tmp_path)

            # 추출된 텍스트 표시
            if st.session_state.ocr_text:
                st.text_area("추출된 텍스트", st.session_state.ocr_text, height=300)

    # 탭 3: 텍스트 입력
    with tab3:
        st.markdown("**직접 텍스트를 입력하거나 붙여넣으세요**")
        st.caption("형식: `번호,단어,뜻` 또는 `단어,뜻` (줄바꿈으로 구분)")

        text_input = st.text_area(
            "텍스트 입력",
            height=300,
            placeholder="1,apple,사과\n2,banana,바나나\n3,orange,오렌지"
        )

        col1, col2 = st.columns(2)
        with col1:
            if st.button("📥 텍스트 파싱"):
                if text_input.strip():
                    st.session_state.vocab_list = parse_text_to_vocab(text_input)
                    st.success(f"✅ {len(st.session_state.vocab_list)}개 단어 파싱 완료!")
                else:
                    st.warning("텍스트를 입력해주세요.")

        with col2:
            uploaded_txt = st.file_uploader(
                "텍스트/Excel 파일",
                type=['txt', 'csv', 'xlsx'],
                key="text_file"
            )
            if uploaded_txt:
                ext = Path(uploaded_txt.name).suffix.lower()
                if ext == '.xlsx':
                    st.session_state.vocab_list = load_excel(uploaded_txt)
                else:
                    content = uploaded_txt.read().decode('utf-8')
                    st.session_state.vocab_list = parse_text_to_vocab(content)
                st.success(f"✅ {len(st.session_state.vocab_list)}개 단어 로드 완료!")

    # 탭 4: 단어 목록
    with tab4:
        st.markdown(f"**총 {len(st.session_state.vocab_list)}개 단어**")

        if st.session_state.vocab_list:
            # 데이터프레임으로 표시 (편집 가능)
            import pandas as pd

            df = pd.DataFrame([
                {"번호": v.number, "단어": v.word, "뜻": v.meaning}
                for v in st.session_state.vocab_list
            ])

            edited_df = st.data_editor(
                df,
                use_container_width=True,
                num_rows="dynamic",
                column_config={
                    "번호": st.column_config.NumberColumn("번호", width="small"),
                    "단어": st.column_config.TextColumn("단어", width="medium"),
                    "뜻": st.column_config.TextColumn("뜻", width="large"),
                }
            )

            # 편집된 내용 반영
            if st.button("💾 변경사항 저장"):
                st.session_state.vocab_list = [
                    VocabItem(number=int(row['번호']), word=row['단어'], meaning=row['뜻'])
                    for _, row in edited_df.iterrows()
                    if row['단어'] and row['뜻']
                ]
                st.success("저장되었습니다!")
                st.rerun()

        else:
            st.info("아직 단어가 없습니다. 이미지를 업로드하거나 텍스트를 입력해주세요.")

    # 하단: MP3 생성
    st.divider()
    st.header("🎵 MP3 생성")

    col1, col2, col3 = st.columns([2, 2, 1])

    with col1:
        output_filename = st.text_input("파일명", value="vocab_audio.mp3")

    with col2:
        st.markdown("")  # 여백

    with col3:
        generate_btn = st.button(
            "🎵 MP3 생성",
            type="primary",
            disabled=len(st.session_state.vocab_list) == 0
        )

    if generate_btn:
        if not st.session_state.vocab_list:
            st.warning("먼저 단어를 입력해주세요.")
        else:
            progress_bar = st.progress(0)
            status_text = st.empty()

            def progress_callback(current, total):
                progress = current / total
                progress_bar.progress(progress)
                status_text.text(f"생성 중... {current}/{total}")

            with st.spinner("오디오 생성 중..."):
                config = TTSConfig(
                    english_voice=eng_voice,
                    korean_voice=kor_voice,
                    english_repeat=eng_repeat,
                    meaning_repeat=meaning_repeat,
                    pause_between_words=pause
                )

                # 임시 파일에 생성
                with tempfile.NamedTemporaryFile(delete=False, suffix='.mp3') as tmp:
                    tmp_path = tmp.name

                try:
                    success = generate_vocab_audio(
                        st.session_state.vocab_list,
                        tmp_path,
                        config,
                        progress_callback=progress_callback
                    )

                    if success:
                        progress_bar.progress(1.0)
                        status_text.text("완료!")

                        # 다운로드 버튼
                        with open(tmp_path, 'rb') as f:
                            audio_bytes = f.read()

                        st.success("✅ MP3 생성 완료!")
                        st.audio(audio_bytes, format='audio/mp3')
                        st.download_button(
                            label="📥 MP3 다운로드",
                            data=audio_bytes,
                            file_name=output_filename,
                            mime="audio/mpeg"
                        )
                    else:
                        st.error("오디오 생성에 실패했습니다.")

                except Exception as e:
                    st.error(f"오류 발생: {e}")

                finally:
                    if os.path.exists(tmp_path):
                        os.unlink(tmp_path)


if __name__ == "__main__":
    main()
