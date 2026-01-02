import os
import time
import re
import subprocess
import sys
from google import genai

# Глобальная переменная для хранения клиента, чтобы избежать повторной инициализации
client = None

def install_dependencies():
    """Устанавливает зависимости из requirements.txt, если они еще не установлены."""
    try:
        # Проверяем официальную библиотеку google-genai (рекомендуемый пакет)
        from google import genai as _genai
    except ImportError:
        print("Установка необходимых библиотек...")
        # Попробуем установить официальную библиотеку напрямую
        subprocess.check_call([sys.executable, "-m", "pip", "install", "google-genai"])
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
    global client
    try:
        api_key = input("Пожалуйста, введите ваш Google AI API ключ (или нажмите Enter для использования переменной окружения): ")

        # Создаём клиент. Предпочтительно использовать переменную окружения GEMINI_API_KEY,
        # но разрешаем пользователю ввести ключ вручную для удобства.
        if api_key and api_key.strip():
            client = genai.Client(api_key=api_key.strip())
        else:
            client = genai.Client()

        # Простая проверка: запрос версии моделей (легковесный способ проверить подключение)
        try:
            _ = client.models.list()
        except Exception:
            # Не фатальная ошибка — клиент всё равно создан, но мы информируем пользователя
            print("Клиент создан, но не удалось получить список моделей (проверьте ключ и сетевое подключение).")

        print("Клиент Gemini успешно настроен.")

    except Exception as e:
        print(f"Ошибка при настройке клиента Gemini: {e}")
        print("Пожалуйста, убедитесь, что установлен пакет 'google-genai' и вы используете верный Python-интерпретатор.")
        print("Если конфликтует пакет 'google', удалите его: pip uninstall google")
        sys.exit(1)

def translate_text(text):
    """Отправляет текст в Gemini API и возвращает перевод, соблюдая RPM."""
    global client
    if not client:
        print("Ошибка: клиент Gemini не был инициализирован.")
        return text # Возвращаем оригинал в случае ошибки

    try:
        # Пауза для соблюдения лимита 60 запросов в минуту
        time.sleep(4)

        prompt = f"Translate the following English text to Russian. Preserve any special characters and formatting like '\\.' or '\\!'. Do not add any extra text, comments, or quotation marks around the translation. Original text: '{text}'"

        # Вызов через официальный клиент
        response = client.models.generate_content(
            model='gemini-3-flash-preview',
            contents=prompt,
        )

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
