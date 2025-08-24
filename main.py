import tkinter as tk
from tkinter import filedialog, messagebox, scrolledtext
import google.generativeai as genai
import json
import os
import time
import threading

class TranslatorApp:
    def __init__(self, root):
        self.root = root
        self.root.title("JSON Translator for Gemini")
        self.root.geometry("700x650")

        # --- Переменные ---
        self.file_path = tk.StringVar()
        self.target_language_code = tk.StringVar(value="ru") # Изменено на код языка
        self.translation_mode = tk.StringVar(value="chunk")
        self.chunk_size = tk.IntVar(value=10)
        self.api_key = tk.StringVar()
        self.auto_translate = tk.BooleanVar(value=False) # Переменная для галочки

        # --- Создание виджетов ---
        self.create_widgets()

    def create_widgets(self):
        # Фрейм для API ключа
        api_frame = tk.LabelFrame(self.root, text="1. Gemini API Key", padx=10, pady=10)
        api_frame.pack(fill="x", padx=10, pady=5)
        
        tk.Label(api_frame, text="Введите ваш API ключ:").pack(side="left", padx=5)
        api_key_entry = tk.Entry(api_frame, textvariable=self.api_key, width=50, show="*")
        api_key_entry.pack(side="left", fill="x", expand=True)

        # Фрейм для выбора файла
        file_frame = tk.LabelFrame(self.root, text="2. Выберите lang.json файл", padx=10, pady=10)
        file_frame.pack(fill="x", padx=10, pady=5)

        file_entry = tk.Entry(file_frame, textvariable=self.file_path, width=70, state="readonly")
        file_entry.pack(side="left", fill="x", expand=True, padx=5)
        browse_button = tk.Button(file_frame, text="Обзор...", command=self.browse_file)
        browse_button.pack(side="left")

        # Фрейм для настроек перевода
        options_frame = tk.LabelFrame(self.root, text="3. Настройки перевода", padx=10, pady=10)
        options_frame.pack(fill="x", padx=10, pady=5)

        # Обновлено: теперь просим код языка
        tk.Label(options_frame, text="Код языка (ru, es, de):").grid(row=0, column=0, sticky="w", padx=5, pady=2)
        tk.Entry(options_frame, textvariable=self.target_language_code).grid(row=0, column=1, sticky="w", padx=5)

        tk.Label(options_frame, text="Режим перевода:").grid(row=1, column=0, sticky="w", padx=5, pady=2)
        tk.Radiobutton(options_frame, text="Пакетами (чанками)", variable=self.translation_mode, value="chunk", command=self.toggle_chunk_entry).grid(row=1, column=1, sticky="w", padx=5)
        tk.Radiobutton(options_frame, text="Построчно", variable=self.translation_mode, value="line", command=self.toggle_chunk_entry).grid(row=1, column=2, sticky="w", padx=5)
        
        tk.Label(options_frame, text="Размер пакета:").grid(row=2, column=0, sticky="w", padx=5, pady=2)
        self.chunk_entry = tk.Entry(options_frame, textvariable=self.chunk_size, width=5)
        self.chunk_entry.grid(row=2, column=1, sticky="w", padx=5)

        # НОВИНКА: Галочка для авто-перевода
        auto_translate_check = tk.Checkbutton(self.root, text="Начинать перевод без подтверждения", variable=self.auto_translate)
        auto_translate_check.pack(pady=(10, 5))

        # Кнопка запуска
        self.translate_button = tk.Button(self.root, text="Начать перевод", command=self.start_translation_thread, font=("Helvetica", 12, "bold"))
        self.translate_button.pack(pady=5)

        # Окно логов
        log_frame = tk.LabelFrame(self.root, text="Лог выполнения", padx=10, pady=10)
        log_frame.pack(fill="both", expand=True, padx=10, pady=5)
        self.log_area = scrolledtext.ScrolledText(log_frame, wrap=tk.WORD, state="disabled")
        self.log_area.pack(fill="both", expand=True)

    def toggle_chunk_entry(self):
        if self.translation_mode.get() == "chunk":
            self.chunk_entry.config(state="normal")
        else:
            self.chunk_entry.config(state="disabled")

    def browse_file(self):
        filename = filedialog.askopenfilename(
            title="Выберите lang.json",
            filetypes=(("JSON files", "*.json"), ("All files", "*.*"))
        )
        if filename:
            self.file_path.set(filename)

    def log(self, message):
        self.log_area.config(state="normal")
        self.log_area.insert(tk.END, message + "\n")
        self.log_area.config(state="disabled")
        self.log_area.see(tk.END)

    def start_translation_thread(self):
        # Проверки перед запуском
        if not self.api_key.get():
            messagebox.showerror("Ошибка", "Пожалуйста, введите ваш Gemini API ключ.")
            return
        if not self.file_path.get():
            messagebox.showerror("Ошибка", "Пожалуйста, выберите файл для перевода.")
            return
        if not self.target_language_code.get().strip():
            messagebox.showerror("Ошибка", "Пожалуйста, введите код языка для перевода.")
            return
            
        # НОВИНКА: Логика подтверждения
        if not self.auto_translate.get():
            confirmed = messagebox.askyesno(
                "Подтверждение",
                f"Вы уверены, что хотите перевести файл на язык с кодом '{self.target_language_code.get()}'?"
            )
            if not confirmed:
                return  # Пользователь нажал "Нет", выходим

        self.translate_button.config(state="disabled", text="В процессе...")
        self.log_area.config(state="normal")
        self.log_area.delete(1.0, tk.END)
        self.log_area.config(state="disabled")
        
        thread = threading.Thread(target=self.run_translation)
        thread.daemon = True
        thread.start()

    def run_translation(self):
        try:
            self.log("Конфигурация Gemini API...")
            genai.configure(api_key=self.api_key.get())
            model = genai.GenerativeModel('gemini-pro')

            self.log(f"Чтение файла: {self.file_path.get()}")
            with open(self.file_path.get(), 'r', encoding='utf-8') as f:
                data = json.load(f)

            strings_with_paths = self.get_all_strings(data)
            paths = [p for p, _ in strings_with_paths]
            strings_to_translate = [s for _, s in strings_with_paths]
            self.log(f"Найдено {len(strings_to_translate)} строк для перевода.")

            # Используем код языка для запроса к API
            target_lang = self.target_language_code.get()
            mode = self.translation_mode.get()
            translated_strings = []

            if mode == 'line':
                self.log("Начало построчного перевода...")
                for i, string in enumerate(strings_to_translate):
                    translated = self.translate_text(model, string, target_lang)
                    translated_strings.append(translated)
                    self.log(f"({i+1}/{len(strings_to_translate)}) '{string}' -> '{translated}'")
                    time.sleep(1)

            elif mode == 'chunk':
                chunk_s = self.chunk_size.get()
                self.log(f"Начало перевода пакетами по {chunk_s} строк...")
                for i in range(0, len(strings_to_translate), chunk_s):
                    chunk = strings_to_translate[i:i+chunk_s]
                    translated_chunk = self.translate_chunk(model, chunk, target_lang)
                    translated_strings.extend(translated_chunk)
                    self.log(f"Переведен пакет {i//chunk_s + 1}...")
                    time.sleep(2)

            self.log("Сборка переведенного JSON файла...")
            final_translations = list(zip(paths, translated_strings))
            translated_data = self.build_translated_json(data, final_translations)
            
            # Обновлено: Формирование имени файла
            original_dir = os.path.dirname(self.file_path.get())
            lang_code = self.target_language_code.get().lower()
            output_filename = os.path.join(original_dir, f'lang_{lang_code}.json')

            with open(output_filename, 'w', encoding='utf-8') as f:
                json.dump(translated_data, f, ensure_ascii=False, indent=2)
            
            self.log("="*30)
            self.log("ПЕРЕВОД УСПЕШНО ЗАВЕРШЕН!")
            self.log(f"Файл сохранен как: {output_filename}")
            messagebox.showinfo("Готово!", f"Перевод завершен!\nФайл сохранен как:\n{output_filename}")

        except Exception as e:
            self.log(f"ОШИБКА: {e}")
            messagebox.showerror("Произошла ошибка", f"Детали ошибки:\n{e}")
        finally:
            self.translate_button.config(state="normal", text="Начать перевод")
            
    # --- Вспомогательные функции (остаются без изменений) ---
    # ... (здесь находятся функции get_all_strings, build_translated_json, 
    # translate_text, translate_chunk из предыдущего ответа) ...
    def get_all_strings(self, data):
        strings = []
        def recurse(obj, path):
            if isinstance(obj, dict):
                for key, value in obj.items(): recurse(value, path + [key])
            elif isinstance(obj, list):
                for i, item in enumerate(obj): recurse(item, path + [i])
            elif isinstance(obj, str): strings.append((path, obj))
        recurse(data, [])
        return strings

    def build_translated_json(self, original_data, translations):
        translated_data = json.loads(json.dumps(original_data))
        for path, translated_string in translations:
            temp = translated_data
            for key in path[:-1]: temp = temp[key]
            temp[path[-1]] = translated_string
        return translated_data

    def translate_text(self, model, text, target_language):
        try:
            prompt = f"Translate the following text to the language with code '{target_language}'. Respond with only the translated text, without any additional explanations or original text.: '{text}'"
            response = model.generate_content(prompt)
            return response.text.strip().strip("'\"")
        except Exception as e:
            self.log(f"Ошибка при переводе текста: {e}")
            return text

    def translate_chunk(self, model, chunk, target_language):
        try:
            numbered_lines = "\n".join([f"{i+1}. {line}" for i, line in enumerate(chunk)])
            prompt = f"""Translate the following numbered list of texts to the language with code '{target_language}'.
            Maintain the original numbering in your response. Respond ONLY with the translated numbered list.
            
            {numbered_lines}
            """
            response = model.generate_content(prompt)
            translated_lines = response.text.strip().split('\n')
            cleaned_translations = [line.split('. ', 1)[1] if '. ' in line else line for line in translated_lines]

            if len(cleaned_translations) == len(chunk):
                return cleaned_translations
            else:
                self.log("Предупреждение: Количество строк не совпадает. Возвращаю оригинал.")
                return chunk
        except Exception as e:
            self.log(f"Ошибка при переводе чанка: {e}")
            return chunk

if __name__ == "__main__":
    root = tk.Tk()
    app = TranslatorApp(root)
    root.mainloop()
