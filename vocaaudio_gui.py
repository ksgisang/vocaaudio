#!/usr/bin/env python3
"""
VocaAudio - 어휘 학습 오디오 생성기 (GUI 버전)
PDF/텍스트에서 어휘를 추출하고 MP3 학습 오디오를 생성합니다.
"""
import tkinter as tk
from tkinter import ttk, filedialog, messagebox, scrolledtext
import threading
import os
import re
from pathlib import Path

# 로컬 모듈
from pdf_parser import VocabItem, load_vocab_from_text, parse_vocab_simple, extract_text_from_image
from tts_generator import generate_vocab_audio, TTSConfig, get_available_voices

# Excel 지원
try:
    import openpyxl
    HAS_EXCEL = True
except ImportError:
    HAS_EXCEL = False


class VocaAudioApp:
    def __init__(self, root):
        self.root = root
        self.root.title("VocaAudio - 어휘 학습 오디오 생성기")
        self.root.geometry("800x700")
        self.root.minsize(700, 600)

        # 데이터
        self.vocab_list = []
        self.is_generating = False

        # UI 생성
        self.create_ui()

    def create_ui(self):
        """UI 구성"""
        # 메인 노트북 (탭)
        self.notebook = ttk.Notebook(self.root)
        self.notebook.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)

        # 탭 1: 텍스트 입력
        self.tab_text = ttk.Frame(self.notebook)
        self.notebook.add(self.tab_text, text="📝 텍스트 입력")
        self.create_text_input_tab()

        # 탭 2: 파일 불러오기
        self.tab_file = ttk.Frame(self.notebook)
        self.notebook.add(self.tab_file, text="📁 파일 불러오기")
        self.create_file_tab()

        # 탭 3: 단어 목록
        self.tab_words = ttk.Frame(self.notebook)
        self.notebook.add(self.tab_words, text="📋 단어 목록")
        self.create_words_tab()

        # 하단: 설정 및 생성 버튼
        self.create_bottom_panel()

    def create_text_input_tab(self):
        """텍스트 입력 탭"""
        frame = ttk.Frame(self.tab_text, padding=10)
        frame.pack(fill=tk.BOTH, expand=True)

        # 안내 레이블
        ttk.Label(frame, text="Google 렌즈로 복사한 텍스트를 붙여넣으세요:",
                  font=('', 12)).pack(anchor=tk.W)
        ttk.Label(frame, text="형식: 번호,단어,뜻 또는 단어,뜻 (줄바꿈으로 구분)",
                  foreground='gray').pack(anchor=tk.W)

        # 텍스트 입력 영역
        self.text_input = scrolledtext.ScrolledText(frame, height=20, font=('Courier', 11))
        self.text_input.pack(fill=tk.BOTH, expand=True, pady=(10, 0))

        # 예시 텍스트
        example = """# 예시 (이 줄은 삭제하고 입력하세요)
1,instant,즉각적인
2,fix,해결하다, 고치다
3,stationery,문구류"""
        self.text_input.insert(tk.END, example)

        # 버튼 프레임
        btn_frame = ttk.Frame(frame)
        btn_frame.pack(fill=tk.X, pady=(10, 0))

        ttk.Button(btn_frame, text="텍스트 파싱",
                   command=self.parse_text_input).pack(side=tk.LEFT, padx=5)
        ttk.Button(btn_frame, text="지우기",
                   command=lambda: self.text_input.delete(1.0, tk.END)).pack(side=tk.LEFT)

    def create_file_tab(self):
        """파일 불러오기 탭"""
        frame = ttk.Frame(self.tab_file, padding=10)
        frame.pack(fill=tk.BOTH, expand=True)

        # 안내
        ttk.Label(frame, text="지원 파일 형식:", font=('', 12)).pack(anchor=tk.W)
        ttk.Label(frame, text="• TXT, CSV: 번호,단어,뜻 형식", foreground='gray').pack(anchor=tk.W)
        ttk.Label(frame, text="• Excel (.xlsx): 첫 번째 시트, A열=단어, B열=뜻", foreground='gray').pack(anchor=tk.W)
        ttk.Label(frame, text="• 이미지 (.jpg, .png): 스마트폰 촬영 사진 등 (OCR)", foreground='gray').pack(anchor=tk.W)

        # 파일 선택 영역
        file_frame = ttk.LabelFrame(frame, text="파일 선택", padding=20)
        file_frame.pack(fill=tk.X, pady=20)

        self.file_path_var = tk.StringVar()
        ttk.Entry(file_frame, textvariable=self.file_path_var, width=60).pack(side=tk.LEFT, padx=5)
        ttk.Button(file_frame, text="찾아보기...", command=self.browse_file).pack(side=tk.LEFT, padx=5)
        ttk.Button(file_frame, text="불러오기", command=self.load_file).pack(side=tk.LEFT, padx=5)

        # 옵션: 2단 분리
        self.two_column_var = tk.BooleanVar(value=True)
        ttk.Checkbutton(file_frame, text="이미지 2단 분리 (단어장용)", 
                        variable=self.two_column_var).pack(side=tk.LEFT, padx=10)

        # 드래그 앤 드롭 안내
        drop_frame = ttk.LabelFrame(frame, text="또는 파일을 여기에 드래그", padding=50)
        drop_frame.pack(fill=tk.BOTH, expand=True, pady=10)
        ttk.Label(drop_frame, text="📂 파일을 드래그하여 놓으세요",
                  font=('', 14), foreground='gray').pack(expand=True)

    def create_words_tab(self):
        """단어 목록 탭"""
        frame = ttk.Frame(self.tab_words, padding=10)
        frame.pack(fill=tk.BOTH, expand=True)

        # 상단 정보
        self.words_info_var = tk.StringVar(value="단어 0개")
        ttk.Label(frame, textvariable=self.words_info_var, font=('', 12, 'bold')).pack(anchor=tk.W)

        # 트리뷰 (테이블)
        columns = ('번호', '단어', '뜻')
        self.words_tree = ttk.Treeview(frame, columns=columns, show='headings', height=15)

        self.words_tree.heading('번호', text='번호')
        self.words_tree.heading('단어', text='단어')
        self.words_tree.heading('뜻', text='뜻')

        self.words_tree.column('번호', width=50, anchor=tk.CENTER)
        self.words_tree.column('단어', width=150)
        self.words_tree.column('뜻', width=400)

        # 스크롤바
        scrollbar = ttk.Scrollbar(frame, orient=tk.VERTICAL, command=self.words_tree.yview)
        self.words_tree.configure(yscrollcommand=scrollbar.set)

        self.words_tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, pady=(10, 0))
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y, pady=(10, 0))

        # 더블 클릭 이벤트 바인딩 (수정 기능)
        self.words_tree.bind("<Double-1>", self.on_item_double_click)

    def create_bottom_panel(self):
        """하단 설정 및 생성 패널"""
        bottom = ttk.Frame(self.root)
        bottom.pack(fill=tk.X, padx=10, pady=10)

        # 설정 프레임
        settings = ttk.LabelFrame(bottom, text="⚙️ 설정", padding=10)
        settings.pack(fill=tk.X)

        # 설정 행 1
        row1 = ttk.Frame(settings)
        row1.pack(fill=tk.X, pady=2)

        ttk.Label(row1, text="영어 반복:").pack(side=tk.LEFT)
        self.repeat_var = tk.IntVar(value=2)
        ttk.Spinbox(row1, from_=1, to=5, width=5, textvariable=self.repeat_var).pack(side=tk.LEFT, padx=(5, 20))

        ttk.Label(row1, text="뜻 반복:").pack(side=tk.LEFT)
        self.meaning_repeat_var = tk.IntVar(value=1)
        ttk.Spinbox(row1, from_=1, to=5, width=5, textvariable=self.meaning_repeat_var).pack(side=tk.LEFT, padx=(5, 20))

        ttk.Label(row1, text="단어 간격(초):").pack(side=tk.LEFT)
        self.pause_var = tk.DoubleVar(value=2.0)
        ttk.Spinbox(row1, from_=0.5, to=5.0, increment=0.5, width=5, textvariable=self.pause_var).pack(side=tk.LEFT, padx=5)

        # 설정 행 2: 음성 선택
        row2 = ttk.Frame(settings)
        row2.pack(fill=tk.X, pady=2)

        voices = get_available_voices()

        ttk.Label(row2, text="영어 음성:").pack(side=tk.LEFT)
        self.eng_voice_var = tk.StringVar(value="en-US-AriaNeural")
        eng_combo = ttk.Combobox(row2, textvariable=self.eng_voice_var, values=voices['english'], width=20)
        eng_combo.pack(side=tk.LEFT, padx=(5, 20))

        ttk.Label(row2, text="한국어 음성:").pack(side=tk.LEFT)
        self.kor_voice_var = tk.StringVar(value="ko-KR-SunHiNeural")
        kor_combo = ttk.Combobox(row2, textvariable=self.kor_voice_var, values=voices['korean'], width=20)
        kor_combo.pack(side=tk.LEFT, padx=5)

        # 진행 상황
        progress_frame = ttk.Frame(bottom)
        progress_frame.pack(fill=tk.X, pady=(10, 0))

        self.progress_var = tk.DoubleVar(value=0)
        self.progress_bar = ttk.Progressbar(progress_frame, variable=self.progress_var, maximum=100)
        self.progress_bar.pack(fill=tk.X, side=tk.LEFT, expand=True)

        self.progress_label = ttk.Label(progress_frame, text="", width=15)
        self.progress_label.pack(side=tk.LEFT, padx=10)

        # 생성 버튼
        btn_frame = ttk.Frame(bottom)
        btn_frame.pack(fill=tk.X, pady=(10, 0))

        self.generate_btn = ttk.Button(btn_frame, text="🎵 MP3 생성",
                                        command=self.generate_audio, style='Accent.TButton')
        self.generate_btn.pack(side=tk.RIGHT, padx=5)

        ttk.Button(btn_frame, text="미리듣기 (처음 3개)",
                   command=self.preview_audio).pack(side=tk.RIGHT, padx=5)

    def parse_text_input(self):
        """텍스트 입력 파싱"""
        text = self.text_input.get(1.0, tk.END).strip()
        if not text:
            messagebox.showwarning("경고", "텍스트를 입력해주세요.")
            return

        self.vocab_list = self.parse_text_to_vocab(text)

        if self.vocab_list:
            self.update_words_display()
            self.notebook.select(self.tab_words)
            messagebox.showinfo("완료", f"{len(self.vocab_list)}개 단어를 파싱했습니다.")
        else:
            messagebox.showerror("오류", "단어를 파싱할 수 없습니다.\n형식을 확인해주세요.")

    def parse_text_to_vocab(self, text: str) -> list:
        """텍스트를 VocabItem 리스트로 변환"""
        vocab_list = []
        
        # 1. 스마트 파싱 시도 (비정형 텍스트, OCR 결과 등)
        vocab_list = parse_vocab_simple(text)
        if vocab_list:
            return vocab_list

        # 2. 기존 CSV 파싱 (백업)
        lines = text.split('\n')

        for i, line in enumerate(lines):
            line = line.strip()
            if not line or line.startswith('#'):
                continue

            # 쉼표로 분리
            parts = line.split(',', 2)

            if len(parts) >= 3:
                # 번호,단어,뜻
                try:
                    number = int(parts[0].strip())
                except ValueError:
                    number = len(vocab_list) + 1
                word = parts[1].strip()
                meaning = parts[2].strip()
            elif len(parts) == 2:
                # 단어,뜻
                number = len(vocab_list) + 1
                word = parts[0].strip()
                meaning = parts[1].strip()
            else:
                continue

            if word and meaning:
                vocab_list.append(VocabItem(number=number, word=word, meaning=meaning))

        return vocab_list

    def browse_file(self):
        """파일 찾아보기"""
        filetypes = [
            ("지원 파일", "*.txt *.csv *.xlsx *.jpg *.jpeg *.png *.pdf"),
            ("이미지 파일", "*.jpg *.jpeg *.png"),
            ("텍스트 파일", "*.txt"),
            ("CSV 파일", "*.csv"),
            ("Excel 파일", "*.xlsx"),
            ("PDF 파일", "*.pdf"),
            ("모든 파일", "*.*")
        ]
        filename = filedialog.askopenfilename(filetypes=filetypes)
        if filename:
            self.file_path_var.set(filename)

    def load_file(self):
        """파일 불러오기"""
        filepath = self.file_path_var.get().strip()
        if not filepath:
            messagebox.showwarning("경고", "파일을 선택해주세요.")
            return

        if not os.path.exists(filepath):
            messagebox.showerror("오류", "파일을 찾을 수 없습니다.")
            return

        ext = Path(filepath).suffix.lower()

        try:
            if ext in ['.txt', '.csv']:
                self.vocab_list = load_vocab_from_text(filepath)
            elif ext == '.xlsx':
                self.vocab_list = self.load_excel(filepath)
            elif ext in ['.jpg', '.jpeg', '.png']:
                messagebox.showinfo("알림", "이미지에서 텍스트를 추출합니다.\n추출 후 [텍스트 입력] 탭에서 내용을 확인하세요.")
                self.root.update() # UI 갱신
                
                # 텍스트 추출
                text = extract_text_from_image(filepath, two_column=self.two_column_var.get())
                
                # 텍스트 입력 탭으로 이동하여 표시
                self.text_input.delete(1.0, tk.END)
                self.text_input.insert(tk.END, text)
                self.notebook.select(self.tab_text)
                
                # 자동 파싱 시도
                self.parse_text_input()
                return # 여기서 종료 (파싱 결과 메시지는 parse_text_input에서 처리)
            else:
                messagebox.showerror("오류", f"지원하지 않는 파일 형식입니다: {ext}")
                return

            if self.vocab_list:
                self.update_words_display()
                self.notebook.select(self.tab_words)
                messagebox.showinfo("완료", f"{len(self.vocab_list)}개 단어를 불러왔습니다.")
            else:
                messagebox.showerror("오류", "단어를 불러올 수 없습니다.\n파일 형식을 확인해주세요.")

        except Exception as e:
            messagebox.showerror("오류", f"파일 로드 실패:\n{str(e)}")

    def load_excel(self, filepath: str) -> list:
        """Excel 파일 로드"""
        if not HAS_EXCEL:
            messagebox.showerror("오류", "Excel 지원을 위해 openpyxl을 설치해주세요.\npip3 install openpyxl")
            return []

        vocab_list = []
        wb = openpyxl.load_workbook(filepath)
        ws = wb.active

        for i, row in enumerate(ws.iter_rows(min_row=1, values_only=True), 1):
            if not row or not row[0]:
                continue

            # 첫 번째 행이 헤더인지 확인
            if i == 1 and isinstance(row[0], str) and ('단어' in row[0] or 'word' in row[0].lower()):
                continue

            if len(row) >= 2:
                word = str(row[0]).strip() if row[0] else ""
                meaning = str(row[1]).strip() if row[1] else ""

                if word and meaning:
                    vocab_list.append(VocabItem(number=len(vocab_list)+1, word=word, meaning=meaning))

        wb.close()
        return vocab_list

    def on_item_double_click(self, event):
        """단어 목록 더블 클릭 시 수정 창 띄우기"""
        item_id = self.words_tree.selection()
        if not item_id:
            return
        
        item_values = self.words_tree.item(item_id[0])['values']
        # values는 (번호, 단어, 뜻) 튜플
        number, word, meaning = item_values
        
        # 팝업 창 생성
        self.open_edit_popup(item_id[0], number, word, meaning)

    def open_edit_popup(self, item_id, number, word, meaning):
        """수정 팝업 창"""
        popup = tk.Toplevel(self.root)
        popup.title("단어 수정")
        popup.geometry("400x250")
        
        frame = ttk.Frame(popup, padding=20)
        frame.pack(fill=tk.BOTH, expand=True)
        
        ttk.Label(frame, text=f"번호: {number}").pack(anchor=tk.W, pady=(0, 10))
        
        ttk.Label(frame, text="단어:").pack(anchor=tk.W)
        word_entry = ttk.Entry(frame, width=40)
        word_entry.insert(0, word)
        word_entry.pack(fill=tk.X, pady=(0, 10))
        
        ttk.Label(frame, text="뜻:").pack(anchor=tk.W)
        meaning_entry = ttk.Entry(frame, width=40)
        meaning_entry.insert(0, meaning)
        meaning_entry.pack(fill=tk.X, pady=(0, 20))
        
        def save():
            new_word = word_entry.get().strip()
            new_meaning = meaning_entry.get().strip()
            
            # 데이터 업데이트
            # self.vocab_list에서 해당 번호의 아이템을 찾아 수정 (번호는 고유하다고 가정하거나 인덱스 사용)
            # 여기서는 간단히 리스트를 순회하며 번호가 일치하는 것을 찾음 (번호가 중복될 수 있으니 주의 필요하지만 현재 로직상 순차적임)
            # 더 정확하게는 Treeview의 index를 이용
            idx = self.words_tree.index(item_id)
            if 0 <= idx < len(self.vocab_list):
                self.vocab_list[idx].word = new_word
                self.vocab_list[idx].meaning = new_meaning
                
                # Treeview 업데이트
                self.words_tree.item(item_id, values=(number, new_word, new_meaning))
                popup.destroy()
        
        ttk.Button(frame, text="저장", command=save).pack()

    def update_words_display(self):
        """단어 목록 표시 업데이트"""
        # 기존 항목 삭제
        for item in self.words_tree.get_children():
            self.words_tree.delete(item)

        # 새 항목 추가
        for item in self.vocab_list:
            self.words_tree.insert('', tk.END, values=(item.number, item.word, item.meaning))

        self.words_info_var.set(f"단어 {len(self.vocab_list)}개")

    def preview_audio(self):
        """미리듣기 (처음 3개)"""
        if not self.vocab_list:
            messagebox.showwarning("경고", "먼저 단어를 입력하거나 불러와주세요.")
            return

        preview_list = self.vocab_list[:3]
        self.generate_audio_thread(preview_list, is_preview=True)

    def generate_audio(self):
        """MP3 생성"""
        if not self.vocab_list:
            messagebox.showwarning("경고", "먼저 단어를 입력하거나 불러와주세요.")
            return

        # 저장 경로 선택
        filepath = filedialog.asksaveasfilename(
            defaultextension=".mp3",
            filetypes=[("MP3 파일", "*.mp3")],
            initialfile="vocab_audio.mp3"
        )

        if not filepath:
            return

        self.generate_audio_thread(self.vocab_list, filepath=filepath)

    def generate_audio_thread(self, vocab_list, filepath=None, is_preview=False):
        """별도 스레드에서 오디오 생성"""
        if self.is_generating:
            messagebox.showwarning("경고", "이미 생성 중입니다.")
            return

        self.is_generating = True
        self.generate_btn.config(state=tk.DISABLED)

        def progress_callback(current, total):
            percent = (current / total) * 100
            self.progress_var.set(percent)
            self.progress_label.config(text=f"{current}/{total}")
            self.root.update_idletasks()

        def generate():
            try:
                config = TTSConfig(
                    english_voice=self.eng_voice_var.get(),
                    korean_voice=self.kor_voice_var.get(),
                    english_repeat=self.repeat_var.get(),
                    meaning_repeat=self.meaning_repeat_var.get(),
                    pause_between_words=self.pause_var.get()
                )

                if is_preview:
                    import tempfile
                    filepath_to_use = tempfile.mktemp(suffix='.mp3')
                else:
                    filepath_to_use = filepath

                success = generate_vocab_audio(
                    vocab_list,
                    filepath_to_use,
                    config,
                    progress_callback=progress_callback
                )

                self.root.after(0, lambda: self.on_generate_complete(success, filepath_to_use, is_preview))

            except Exception as e:
                self.root.after(0, lambda: self.on_generate_error(str(e)))

        thread = threading.Thread(target=generate)
        thread.daemon = True
        thread.start()

    def on_generate_complete(self, success, filepath, is_preview):
        """생성 완료 처리"""
        self.is_generating = False
        self.generate_btn.config(state=tk.NORMAL)
        self.progress_var.set(0)
        self.progress_label.config(text="")

        if success:
            if is_preview:
                # 미리듣기: 바로 재생
                os.system(f'open "{filepath}"')
                messagebox.showinfo("미리듣기", "미리듣기 파일을 재생합니다.")
            else:
                # 전체 생성: 완료 메시지
                size_mb = os.path.getsize(filepath) / (1024 * 1024)
                result = messagebox.askyesno(
                    "완료",
                    f"MP3 파일이 생성되었습니다!\n\n"
                    f"📁 {filepath}\n"
                    f"📦 {size_mb:.1f} MB\n\n"
                    f"파일을 열어보시겠습니까?"
                )
                if result:
                    os.system(f'open "{filepath}"')
        else:
            messagebox.showerror("오류", "오디오 생성에 실패했습니다.")

    def on_generate_error(self, error_msg):
        """생성 오류 처리"""
        self.is_generating = False
        self.generate_btn.config(state=tk.NORMAL)
        self.progress_var.set(0)
        self.progress_label.config(text="")
        messagebox.showerror("오류", f"오류 발생:\n{error_msg}")


def main():
    root = tk.Tk()

    # 스타일 설정
    style = ttk.Style()
    style.theme_use('clam')  # macOS에서 보기 좋은 테마

    app = VocaAudioApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()
