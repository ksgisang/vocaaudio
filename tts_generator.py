"""
Edge TTS를 사용한 고품질 오디오 생성 모듈
Streamlit Cloud 배포를 위해 pydub 사용 (ffmpeg 대체)
"""
import os
import tempfile
import asyncio
from typing import List, Optional
from dataclasses import dataclass

# Edge TTS
try:
    import edge_tts
    HAS_EDGE_TTS = True
except ImportError:
    HAS_EDGE_TTS = False

# pydub for audio processing
try:
    from pydub import AudioSegment
    # Streamlit Cloud에서 ffmpeg 경로 설정
    import shutil
    ffmpeg_path = shutil.which("ffmpeg")
    if ffmpeg_path:
        AudioSegment.converter = ffmpeg_path
        ffprobe_path = shutil.which("ffprobe")
        if ffprobe_path:
            AudioSegment.ffprobe = ffprobe_path
    HAS_PYDUB = True
except ImportError:
    HAS_PYDUB = False


@dataclass
class TTSConfig:
    """TTS 설정"""
    english_voice: str = "en-US-AriaNeural"  # Edge TTS 영어 음성
    korean_voice: str = "ko-KR-SunHiNeural"  # Edge TTS 한국어 음성
    english_repeat: int = 2          # 영어 반복 횟수
    meaning_repeat: int = 1          # 뜻 반복 횟수
    pause_between_words: float = 2.0  # 단어 간 간격 (초)
    pause_between_repeat: float = 0.5  # 반복 간 간격 (초)
    include_pos: bool = False        # 품사 포함 여부


def get_available_voices() -> dict:
    """사용 가능한 Edge TTS 음성 목록"""
    return {
        "english": [
            "en-US-AriaNeural",      # 여성 (추천)
            "en-US-GuyNeural",       # 남성
            "en-US-JennyNeural",     # 여성
            "en-GB-SoniaNeural",     # 영국 여성
            "en-GB-RyanNeural",      # 영국 남성
        ],
        "korean": [
            "ko-KR-SunHiNeural",     # 여성 (추천)
            "ko-KR-InJoonNeural",    # 남성
        ]
    }


async def generate_speech_edge(text: str, voice: str, output_path: str) -> bool:
    """Edge TTS로 음성 파일 생성"""
    try:
        communicate = edge_tts.Communicate(text, voice)
        await communicate.save(output_path)
        return True
    except Exception as e:
        print(f"Edge TTS 오류: {e}")
        return False


def generate_silence(duration: float, output_path: str) -> bool:
    """무음 MP3 파일 생성 (pydub 사용)"""
    if not HAS_PYDUB:
        print("오류: pydub이 설치되지 않았습니다.")
        return False

    try:
        # duration은 초 단위, pydub은 밀리초 단위
        silence = AudioSegment.silent(duration=int(duration * 1000))
        silence.export(output_path, format="mp3")
        return True
    except Exception as e:
        print(f"무음 생성 오류: {e}")
        return False


def concatenate_audio_files(file_list: List[str], output_path: str) -> bool:
    """여러 오디오 파일을 하나로 합치기 (pydub 사용)"""
    if not file_list:
        return False

    if not HAS_PYDUB:
        print("오류: pydub이 설치되지 않았습니다.")
        return False

    try:
        combined = AudioSegment.empty()
        for audio_file in file_list:
            if os.path.exists(audio_file):
                segment = AudioSegment.from_mp3(audio_file)
                combined += segment

        combined.export(output_path, format="mp3")
        return True
    except Exception as e:
        print(f"오디오 합치기 오류: {e}")
        return False


async def generate_vocab_audio_async(
    vocab_list: List,
    output_path: str,
    config: Optional[TTSConfig] = None,
    progress_callback=None
) -> bool:
    """
    Edge TTS를 사용하여 어휘 오디오 생성 (비동기)
    """
    if not HAS_EDGE_TTS:
        print("오류: edge-tts가 설치되지 않았습니다.")
        print("설치: pip3 install edge-tts")
        return False

    if config is None:
        config = TTSConfig()

    temp_dir = tempfile.mkdtemp()
    audio_segments = []
    total = len(vocab_list)

    try:
        # 무음 파일 미리 생성
        silence_between_words = os.path.join(temp_dir, "silence_words.mp3")
        silence_between_repeat = os.path.join(temp_dir, "silence_repeat.mp3")

        generate_silence(config.pause_between_words, silence_between_words)
        generate_silence(config.pause_between_repeat, silence_between_repeat)

        for i, item in enumerate(vocab_list):
            if progress_callback:
                progress_callback(i + 1, total)

            # 영어 단어 음성 생성
            eng_file = os.path.join(temp_dir, f"{i:04d}_eng.mp3")
            await generate_speech_edge(item.word, config.english_voice, eng_file)

            # 한국어 뜻 음성 생성
            meaning_text = item.meaning
            if config.include_pos and hasattr(item, 'pos') and item.pos:
                meaning_text = f"{item.pos}. {item.meaning}"

            kor_file = os.path.join(temp_dir, f"{i:04d}_kor.mp3")
            await generate_speech_edge(meaning_text, config.korean_voice, kor_file)

            # 순서: 영어 x 반복횟수 -> 한국어 x 반복횟수 -> 간격
            for _ in range(config.english_repeat):
                audio_segments.append(eng_file)
                audio_segments.append(silence_between_repeat)

            for _ in range(config.meaning_repeat):
                audio_segments.append(kor_file)
                audio_segments.append(silence_between_repeat)

            # 단어 간 간격
            audio_segments.append(silence_between_words)

        # 모든 오디오 합치기
        if not concatenate_audio_files(audio_segments, output_path):
            print("오디오 합치기 실패")
            return False

        return True

    finally:
        # 임시 파일 정리
        import shutil
        shutil.rmtree(temp_dir, ignore_errors=True)


def generate_vocab_audio(
    vocab_list: List,
    output_path: str,
    config: Optional[TTSConfig] = None,
    progress_callback=None
) -> bool:
    """
    어휘 목록에서 학습용 오디오 생성 (동기 래퍼)
    Streamlit 환경에서도 작동하도록 이벤트 루프 처리
    """
    try:
        # 기존 이벤트 루프가 있는지 확인 (Streamlit 환경)
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            loop = None

        if loop and loop.is_running():
            # 이미 실행 중인 루프가 있으면 nest_asyncio 사용 또는 새 스레드에서 실행
            import concurrent.futures
            with concurrent.futures.ThreadPoolExecutor() as executor:
                future = executor.submit(
                    asyncio.run,
                    generate_vocab_audio_async(vocab_list, output_path, config, progress_callback)
                )
                return future.result()
        else:
            return asyncio.run(
                generate_vocab_audio_async(vocab_list, output_path, config, progress_callback)
            )
    except Exception as e:
        print(f"오디오 생성 오류: {e}")
        import traceback
        traceback.print_exc()
        return False


if __name__ == "__main__":
    print("Edge TTS 음성 목록:")
    voices = get_available_voices()
    print("\n영어:")
    for v in voices['english']:
        print(f"  - {v}")
    print("\n한국어:")
    for v in voices['korean']:
        print(f"  - {v}")
