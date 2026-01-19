#!/usr/bin/env python3
"""
VocaAudio Local - PDF 어휘를 MP3 학습 오디오로 변환

사용법:
    python vocaaudio.py input.pdf [output.mp3]
    python vocaaudio.py input.pdf -o output.mp3 --repeat 3 --pause 2.5
"""
import argparse
import sys
import os
from pathlib import Path

from pdf_parser import extract_vocab_from_pdf, parse_vocab_simple, extract_text_from_pdf, extract_text_with_ocr, extract_vocab_with_ocr_table, load_vocab_from_text, HAS_OCR
from tts_generator import generate_vocab_audio, TTSConfig, get_available_voices


def print_progress(current: int, total: int):
    """진행 상황 출력"""
    percent = (current / total) * 100
    bar_length = 30
    filled = int(bar_length * current / total)
    bar = '█' * filled + '░' * (bar_length - filled)
    print(f'\r처리 중: [{bar}] {current}/{total} ({percent:.1f}%)', end='', flush=True)


def main():
    parser = argparse.ArgumentParser(
        description='PDF 어휘를 MP3 학습 오디오로 변환',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog='''
예시:
  python vocaaudio.py vocab.pdf
  python vocaaudio.py vocab.pdf -o my_vocab.mp3
  python vocaaudio.py vocab.pdf --repeat 3 --pause 2.5
  python vocaaudio.py vocab.pdf --include-pos
        '''
    )

    parser.add_argument('pdf_file', nargs='?', help='입력 PDF 파일 경로')
    parser.add_argument('-o', '--output', help='출력 MP3 파일 경로 (기본: input_vocab.mp3)')
    parser.add_argument('--repeat', type=int, default=2, help='영어 단어 반복 횟수 (기본: 2)')
    parser.add_argument('--meaning-repeat', type=int, default=1, help='뜻 반복 횟수 (기본: 1)')
    parser.add_argument('--pause', type=float, default=2.0, help='단어 간 간격 초 (기본: 2.0)')
    parser.add_argument('--include-pos', action='store_true', help='품사 포함')
    parser.add_argument('--eng-voice', default='en-US-AriaNeural', help='영어 음성 (기본: en-US-AriaNeural)')
    parser.add_argument('--kor-voice', default='ko-KR-SunHiNeural', help='한국어 음성 (기본: ko-KR-SunHiNeural)')
    parser.add_argument('--list-voices', action='store_true', help='사용 가능한 음성 목록 출력')
    parser.add_argument('--preview', action='store_true', help='추출된 단어 미리보기 (오디오 생성 안함)')
    parser.add_argument('--simple-parse', action='store_true', help='간단한 파싱 방법 사용')
    parser.add_argument('--ocr', action='store_true', help='스캔 PDF용 OCR 사용')
    parser.add_argument('--rotate', type=int, choices=[0, 90, 180, 270], default=0, help='이미지 회전 각도 (0, 90, 180, 270)')

    args = parser.parse_args()

    # 음성 목록 출력
    if args.list_voices:
        print("사용 가능한 음성:")
        voices = get_available_voices()
        print("\n영어 음성:")
        for v in voices['english'][:10]:
            print(f"  - {v}")
        print("\n한국어 음성:")
        for v in voices['korean']:
            print(f"  - {v}")
        return 0

    # 입력 파일 확인
    if not args.pdf_file:
        print("오류: 입력 파일을 지정해주세요.")
        print("사용법: python vocaaudio.py input.txt  (또는 .pdf)")
        return 1

    input_path = Path(args.pdf_file)
    if not input_path.exists():
        print(f"오류: 파일을 찾을 수 없습니다: {input_path}")
        return 1

    # 파일 타입 확인
    file_ext = input_path.suffix.lower()
    is_text_file = file_ext in ['.txt', '.csv']
    is_pdf_file = file_ext == '.pdf'

    if not is_text_file and not is_pdf_file:
        print(f"오류: 지원하지 않는 파일 형식입니다: {file_ext}")
        print("지원 형식: .txt, .csv, .pdf")
        return 1

    # 출력 파일 경로
    if args.output:
        output_path = Path(args.output)
    else:
        output_path = input_path.with_name(f"{input_path.stem}_vocab.mp3")

    print(f"📄 입력 파일: {input_path}")
    print(f"🎵 출력 파일: {output_path}")
    print()

    # 어휘 추출
    if is_text_file:
        print("📖 텍스트 파일에서 어휘 로드 중...")
    else:
        print("📖 PDF에서 어휘 추출 중...")
    try:
        # 텍스트 파일인 경우 바로 로드
        if is_text_file:
            vocab_list = load_vocab_from_text(str(input_path))
        # OCR 모드 (표 형태 스캔 PDF용)
        elif args.ocr:
            if not HAS_OCR:
                print("오류: OCR을 사용하려면 pytesseract와 pillow를 설치하세요.")
                print("  pip3 install pytesseract pillow")
                return 1
            if args.rotate:
                print(f"  🔄 이미지 {args.rotate}도 회전 적용")
            print("  🔍 OCR로 표 인식 중... (시간이 걸릴 수 있습니다)")
            def ocr_progress(current, total):
                print(f"\r  OCR 진행: {current}/{total} 페이지", end='', flush=True)
            # 표 형태 전용 OCR 함수 사용 (회전 옵션 전달)
            vocab_list = extract_vocab_with_ocr_table(str(input_path), progress_callback=ocr_progress, rotate=args.rotate)
            print()  # 줄바꿈
        elif args.simple_parse:
            text = extract_text_from_pdf(str(input_path))
            vocab_list = parse_vocab_simple(text)
        else:
            vocab_list = extract_vocab_from_pdf(str(input_path))

        # 첫 번째 방법 실패 시 두 번째 방법 시도
        if len(vocab_list) == 0 and not args.ocr:
            print("  기본 파싱 실패, 대체 방법 시도 중...")
            text = extract_text_from_pdf(str(input_path))
            vocab_list = parse_vocab_simple(text)

        # 여전히 실패하고 OCR 사용 가능하면 OCR 시도
        if len(vocab_list) == 0 and HAS_OCR and not args.ocr:
            print("  텍스트 추출 실패, OCR 시도 중...")
            def ocr_progress(current, total):
                print(f"\r  OCR 진행: {current}/{total} 페이지", end='', flush=True)
            vocab_list = extract_vocab_with_ocr_table(str(input_path), progress_callback=ocr_progress)
            print()

    except Exception as e:
        print(f"오류: PDF 파싱 실패 - {e}")
        return 1

    if not vocab_list:
        print("오류: 어휘를 찾을 수 없습니다.")
        if HAS_OCR:
            print("팁: --ocr 옵션을 시도해보세요.")
        else:
            print("팁: OCR 설치 후 --ocr 옵션을 사용해보세요.")
        return 1

    print(f"✅ {len(vocab_list)}개 단어 추출 완료")
    print()

    # 미리보기
    print("추출된 단어 (처음 10개):")
    print("-" * 50)
    for item in vocab_list[:10]:
        print(f"  {item.number}. {item.word} - {item.meaning}")
    if len(vocab_list) > 10:
        print(f"  ... 외 {len(vocab_list) - 10}개")
    print("-" * 50)
    print()

    if args.preview:
        print("미리보기 모드 - 오디오 생성을 건너뜁니다.")
        return 0

    # TTS 설정
    config = TTSConfig(
        english_voice=args.eng_voice,
        korean_voice=args.kor_voice,
        english_repeat=args.repeat,
        meaning_repeat=args.meaning_repeat,
        pause_between_words=args.pause,
        include_pos=args.include_pos
    )

    print(f"🔊 오디오 설정:")
    print(f"   - 영어 음성: {config.english_voice}")
    print(f"   - 한국어 음성: {config.korean_voice}")
    print(f"   - 영어 반복: {config.english_repeat}회")
    print(f"   - 뜻 반복: {config.meaning_repeat}회")
    print(f"   - 단어 간격: {config.pause_between_words}초")
    print(f"   - 품사 포함: {'예' if config.include_pos else '아니오'}")
    print()

    # 오디오 생성
    print("🎙️ 오디오 생성 중...")
    success = generate_vocab_audio(
        vocab_list,
        str(output_path),
        config,
        progress_callback=print_progress
    )

    print()  # 진행바 줄바꿈

    if success:
        file_size = output_path.stat().st_size / (1024 * 1024)
        print()
        print(f"✅ 완료! 오디오 파일이 생성되었습니다.")
        print(f"   📁 {output_path}")
        print(f"   📦 파일 크기: {file_size:.1f} MB")
        print()
        print("💡 팁: 스마트폰으로 전송하려면 AirDrop 또는 클라우드를 사용하세요.")
        return 0
    else:
        print()
        print("❌ 오디오 생성 실패")
        print("   ffmpeg가 설치되어 있는지 확인하세요:")
        print("   brew install ffmpeg")
        return 1


if __name__ == "__main__":
    sys.exit(main())
