import os
import time
import re
import subprocess
import sys
from google import genai
from google.genai import types
from pydantic import BaseModel

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
    Теперь собирает все подходящие строки в файле и отправляет один батч-запрос на перевод,
    затем заменяет соответствующие строки в выходном файле.
    """
    # Паттерн для захвата отступа и текста внутри ShowText(["..."])
    show_text_pattern = re.compile(r'^(\s*)ShowText\(\["(.*)"\]\)')

    print(f"Обработка файла: {os.path.basename(source_path)}")
    try:
        with open(source_path, 'r', encoding='utf-8') as f_in, \
             open(output_path, 'w', encoding='utf-8') as f_out:

            # Собираем все строки для перевода (с их контекстом) и буферизуем остальные строки
            original_entries = []  # список кортежей (index, indentation, original_text)
            all_lines = []

            for line in f_in:
                all_lines.append(line)
                match = show_text_pattern.search(line)
                if match:
                    indentation = match.group(1)
                    original_text = match.group(2)
                    original_entries.append((len(all_lines) - 1, indentation, original_text))

            if not original_entries:
                # Нечего переводить — просто скопируем файл
                for line in all_lines:
                    f_out.write(line)
                return

            # Подготовим данные для батчевого запроса: список исходных текстов в порядке появления
            texts_to_translate = [entry[2] for entry in original_entries]

            # Pydantic схема для ожидаемого JSON-ответа
            class Translations(BaseModel):
                translations: list[str]

            try:
                # Формируем инструкцию и отправляем один запрос для всего списка
                instruction = (
                    "Translate the following list of English text entries to Russian. "
                    "Return a JSON object with a single key 'translations' which is an array of translated strings in the exact same order as the input. "
                    "Do not add extra commentary or numbering.\n\n"
                )

                # Объединяем входные тексты, разделяем новой строкой и префиксуем нумерацией для устойчивости порядка
                contents_payload = instruction + "\n".join(f"{i}: {t}" for i, t in enumerate(texts_to_translate))

                response = client.models.generate_content(
                    model='gemini-3-flash-preview',
                    contents=contents_payload,
                    config=types.GenerateContentConfig(
                        response_mime_type='application/json',
                        response_schema=Translations,
                    ),
                )

                # Попытка получить парсенный результат
                parsed = None
                try:
                    parsed = response.parsed
                except Exception:
                    parsed = None

                if parsed and getattr(parsed, 'translations', None):
                    translations = parsed.translations
                else:
                    # Если структурированный парсинг не удался, попадаем в fallback: пробуем разделить по строкам
                    text_response = response.text.strip() if hasattr(response, 'text') else ''
                    # Попробуем извлечь JSON из текста
                    try:
                        import json

                        j = json.loads(text_response)
                        translations = j.get('translations', []) if isinstance(j, dict) else []
                    except Exception:
                        # Финальный fallback — построчный разбор по новой строке
                        translations = [line.strip() for line in text_response.splitlines() if line.strip()][: len(texts_to_translate)]

                # Если количества не совпадают, усечём/дополним оригиналами
                if len(translations) < len(texts_to_translate):
                    # Заполняем недостающие переводами по одному через API (медленнее, но безопасно)
                    for i in range(len(translations), len(texts_to_translate)):
                        translations.append(texts_to_translate[i])

                # Записываем файл, подставляя переводы на соответствующие позиции
                for idx, line in enumerate(all_lines):
                    # Проверяем, есть ли запись для этой строки
                    found = next((item for item in original_entries if item[0] == idx), None)
                    if found:
                        _, indentation, _ = found
                        translated_text = translations.pop(0)
                        translated_text_escaped = translated_text.replace('"', '\\"')
                        new_line = f'{indentation}ShowText(["{translated_text_escaped}"])\n'
                        f_out.write(new_line)
                    else:
                        f_out.write(line)

            except Exception as e:
                print(f"  Ошибка при батчевом переводе файла {os.path.basename(source_path)}: {e}")
                # В случае ошибки — записываем оригинал, чтобы не терять данные
                for line in all_lines:
                    f_out.write(line)

    except Exception as e:
        print(f"  Не удалось обработать файл {os.path.basename(source_path)}: {e}")


if __name__ == "__main__":
    main()
