import os
import time
import re
import subprocess
import sys
import google.genai as genai

# Глобальная переменная для хранения модели, чтобы избежать повторной инициализации
model = None

def install_dependencies():
    """Устанавливает зависимости из requirements.txt, если они еще не установлены."""
    try:
        import google.genai
    except ImportError:
        print("Установка необходимых библиотек...")
        subprocess.check_call([sys.executable, "-m", "pip", "install", "-r", "requirements.txt"])
        print("Библиотеки успешно установлены.")

def get_source_folder():
    """Запрашивает у пользователя путь к папке с исходными файлами и проверяет его."""
    while True:
        folder_path = input("Пожалуйста, введите путь к папке с файлами для перевода: ")
        if not os.path.exists(folder_path):
            print(f"Ошибка: Указанный путь не существует: '{folder_path}'")
        elif not os.path.isdir(folder_path):
            print(f"Ошибка: Указанный путь не является папкой: '{folder_path}'")
        else:
            print(f"Папка найдена: '{folder_path}'")
            return folder_path

def main():
    """
    Главная функция для запуска скрипта перевода.
    """
    install_dependencies()
    print("RPG Maker Game Translator")
    print("=========================")

    # Настройка Gemini API
    configure_gemini()

    source_folder = get_source_folder()

    # Создаем папку для перевода
    parent_dir = os.path.dirname(os.path.abspath(source_folder))
    translation_folder = os.path.join(parent_dir, f"{os.path.basename(source_folder)}_RU")
    os.makedirs(translation_folder, exist_ok=True)
    print(f"Папка для переведенных файлов создана: '{translation_folder}'")

    process_files(source_folder, translation_folder)

    print("\nРабота завершена.")

def process_files(source_dir, output_dir):
    """
    Рекурсивно обходит исходную директорию, находит .txt файлы,
    и обрабатывает их для перевода.
    """
    for root, _, files in os.walk(source_dir):
        for file in files:
            if file.endswith(".txt"):
                source_file_path = os.path.join(root, file)

                # Создаем соответствующую структуру папок в папке назначения
                relative_path = os.path.relpath(source_file_path, source_dir)
                output_file_path = os.path.join(output_dir, relative_path)
                os.makedirs(os.path.dirname(output_file_path), exist_ok=True)

                process_single_file(source_file_path, output_file_path)

def configure_gemini():
    """Запрашивает API ключ и настраивает модель Gemini."""
    global model
    try:
        api_key = input("Пожалуйста, введите ваш Google AI API ключ: ")
        genai.configure(api_key=api_key)
        model = genai.GenerativeModel('gemini-pro')
        print("Модель Gemini успешно настроена.")
    except Exception as e:
        print(f"Ошибка при настройке Gemini: {e}")
        print("Пожалуйста, убедитесь, что у вас правильный API ключ и установлены все зависимости.")
        sys.exit(1)

def translate_text(text):
    """Отправляет текст в Gemini API и возвращает перевод, соблюдая RPM."""
    global model
    if not model:
        print("Ошибка: Модель Gemini не была инициализирована.")
        return text # Возвращаем оригинал в случае ошибки

    try:
        # Пауза для соблюдения лимита 60 запросов в минуту
        time.sleep(1.5)

        prompt = f"Translate the following English text to Russian. Preserve any special characters and formatting like '\\.' or '\\!'. Do not add any extra text, comments, or quotation marks around the translation. Original text: '{text}'"
        response = model.generate_content(prompt)

        translated = response.text.strip()
        print(f"  Переведено: '{text}' -> '{translated}'")
        return translated

    except Exception as e:
        print(f"  Ошибка при переводе текста '{text}': {e}")
        return text # Возвращаем оригинал в случае ошибки

def process_single_file(source_path, output_path):
    """
    Читает один файл, находит строки для перевода с помощью регулярных выражений и записывает результат.
    """
    # Паттерн для захвата отступа и текста внутри ShowText(["..."])
    show_text_pattern = re.compile(r'^(\s*)ShowText\(\["(.*)"\]\)')

    print(f"Обработка файла: {os.path.basename(source_path)}")
    try:
        with open(source_path, 'r', encoding='utf-8') as f_in, \
             open(output_path, 'w', encoding='utf-8') as f_out:

            for line in f_in:
                match = show_text_pattern.search(line)
                if match:
                    indentation = match.group(1)  # Захватываем отступ
                    original_text = match.group(2)

                    # Выполняем перевод через Gemini API
                    translated_text = translate_text(original_text)

                    # Собираем строку обратно с переведенным текстом
                    # Убедимся, что кавычки внутри текста экранированы
                    translated_text_escaped = translated_text.replace('"', '\\"')
                    new_line = f'{indentation}ShowText(["{translated_text_escaped}"])\n'
                    f_out.write(new_line)
                else:
                    f_out.write(line)

    except Exception as e:
        print(f"  Не удалось обработать файл {os.path.basename(source_path)}: {e}")


if __name__ == "__main__":
    main()
