import os
import time
import re
import subprocess
import sys
from google import genai
from google.genai import types
from pydantic import BaseModel
import json

# Глобальная переменная для хранения клиента, чтобы избежать повторной инициализации
client = None

# Утилиты для маскировки управляющих последовательностей (\i[...], \c[...], \\., \\# и т.п.)
control_pattern = re.compile(r'(\\[A-Za-z]+(?:\[[^\]]*\])?|\\.)')


def mask_control_sequences(s: str):
    tokens: list[str] = []

    def repl(m):
        tokens.append(m.group(0))
        return f"__CTRL{len(tokens)-1}__"

    masked = control_pattern.sub(repl, s)
    return masked, tokens


def unmask_control_sequences(s: str, tokens: list[str]):
    for i, t in enumerate(tokens):
        s = s.replace(f"__CTRL{i}__", t)
    return s


def is_cyrillic(s: str) -> bool:
    return bool(re.search(r"[\u0400-\u04FF]", s))

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


def batch_translate(all_texts: list[str], batch_sz: int = 10000) -> list[str]:
    """Переводит список маскированных строк пакетами.
    Возвращает список переводов в том же порядке, что и входной список.
    """
    # подготовим пары (global_idx, text)
    all_with_idx = list(enumerate(all_texts))
    results_map: dict[int, str] = {}
    i = 0
    total = len(all_with_idx)
    base_batch = batch_sz
    current_batch = batch_sz
    reduced_batch = max(1, base_batch // 2)
    reduced_counter = 0  # number of upcoming chunks to use reduced batch size

    while i < total:
        chunk = all_with_idx[i:i+current_batch]
        instruction = (
            "Translate the following list of English text entries to Russian. "
            "Preserve all special formatting tokens and control sequences exactly as they appear, including backslash-escaped sequences such as \\i[...], \\#, \\. and any other markup or tags (do NOT translate or modify these tokens). "
            "Return a JSON object that maps each original numeric index (as a string) to its translated string, for example: {\"0\": \"...\", \"1\": \"...\"}. "
            "Do not add extra commentary, numbering, or surrounding quotation marks.\n\n"
        )
        contents_payload = instruction + "\n".join(f"{idx}: {text}" for idx, text in chunk)

        attempts = 0
        success = False
        saw_429 = False
        while attempts < 2 and not success:
            try:
                response = client.models.generate_content(
                    model='gemini-3-flash-preview',
                    contents=contents_payload,
                )
                text_response = response.text.strip() if hasattr(response, 'text') else ''
                try:
                    j = json.loads(text_response)
                    if isinstance(j, dict):
                        for k, v in j.items():
                            try:
                                ik = int(k)
                            except Exception:
                                continue
                            results_map[ik] = v
                        # check all present
                        if all(idx in results_map for idx, _ in chunk):
                            success = True
                            break
                except Exception:
                    pass

                lines = [ln.strip() for ln in text_response.splitlines() if ln.strip()]
                if len(lines) >= len(chunk):
                    for (idx, _), line in zip(chunk, lines):
                        results_map[idx] = line
                    success = True
                    break

            except Exception as e:
                s = str(e).lower()
                if '429' in s or 'too many requests' in s or 'rate' in s:
                    # rate limited
                    saw_429 = True
                    print(f'Получен 429 при батче, ожидаю 60 секунд и попробую снова... (начиная с {i})')
                    time.sleep(60)
                    # retry once after delay
                else:
                    print(f'Ошибка при переводе батча (начиная с {i}), попытка {attempts+1}: {e}')
            attempts += 1

        if saw_429 and not success:
            # second 429 or still failing -> reduce batch size to half of base_batch for next two chunks
            if reduced_batch < current_batch:
                print(f'Уменьшаю размер батча с {current_batch} до {reduced_batch} для следующих 2 попыток.')
                current_batch = reduced_batch
                reduced_counter = 2
            else:
                # cannot reduce further, fallback to per-item
                pass

        if not success:
            # fallback: per-item requests
            for idx, text in chunk:
                try:
                    single_resp = client.models.generate_content(
                        model='gemini-3-flash-preview',
                        contents=f"Translate to Russian, preserve control tokens exactly: {text}",
                    )
                    results_map[idx] = single_resp.text.strip() if hasattr(single_resp, 'text') else text
                except Exception as e:
                    print(f'Не удалось перевести элемент {idx} по-отдельности: {e}')
                    results_map[idx] = text

        # advance by chunk length (was current_batch)
        i += len(chunk)

        # if we were using reduced batch, decrement counter and possibly restore
        if reduced_counter > 0:
            reduced_counter -= 1
            if reduced_counter == 0:
                print(f'Восстанавливаю размер батча до базового {base_batch}.')
                current_batch = base_batch

    # build final list
    final = [results_map.get(idx, '') for idx, _ in all_with_idx]
    return final

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

    # Запрос у пользователя, какие категории обрабатывать
    categories_input = input("Выберите категории для обработки (maps, other, all). Для нескольких укажите через запятую [all]: ")
    if not categories_input or categories_input.strip().lower() in ('all', ''):
        categories = ['maps', 'other']
    else:
        categories = [c.strip().lower() for c in categories_input.split(',') if c.strip()]
        # Нормализуем и фильтруем только допустимые
        categories = [c for c in categories if c in ('maps', 'other')]
        if not categories:
            print("Невалидный ввод, будут обработаны обе категории: maps и other.")
            categories = ['maps', 'other']

    # Создаем папку для перевода
    parent_dir = os.path.dirname(os.path.abspath(source_folder))
    translation_folder = os.path.join(parent_dir, f"{os.path.basename(source_folder)}_RU")
    os.makedirs(translation_folder, exist_ok=True)
    print(f"Папка для переведенных файлов создана: '{translation_folder}'")

    log_path = process_files(source_folder, translation_folder, categories)

    print("\nРабота завершена.")

    # Спросим, хочет ли пользователь попытаться перевести отсутствующие строки прямо сейчас
    try:
        choice = input("Перевести отсутствующие строки сейчас? (y/N): ").strip().lower()
    except Exception:
        choice = 'n'
    if choice == 'y':
        if log_path and os.path.exists(log_path):
            retry_from_log(log_path)
        else:
            print('Файл лога не найден, повторная попытка невозможна.')

def process_files(source_dir, output_dir, categories=None):
    """
    Собирает все строки ShowText во всех .txt файлах исходной директории,
    батчит их (по batch_size) и переводит одной/несколькими группами,
    затем записывает соответствующие выходные файлы в output_dir,
    сохраняя структуру папок.
    """
    # Настройки батчинга — можно менять при больших объёмах
    # По умолчанию обрабатываем большие группы по 10_000 строк.
    # При превышении квот (429) сначала попытаемся ещё раз тот же батч через 60s;
    # если снова 429 — временно уменьшаем батч до половины (5_000) для следующих 2 чанков,
    # затем восстанавливаем исходный размер.
    batch_size = 10000

    # Словарь: путь -> { all_lines: [...], entries: [(line_idx, indentation, original_text), ...] }
    files_data: dict[str, dict] = {}
    texts_to_translate: list[str] = []

    # Сбор всех данных
    if categories is None:
        categories = ['maps', 'other']

    for root, _, files in os.walk(source_dir):
        for file in files:
            if not file.endswith('.txt'):
                continue

            source_file_path = os.path.join(root, file)
            relative_path = os.path.relpath(source_file_path, source_dir)

            # Определяем верхний компонент пути (maps или other и т.д.)
            parts = relative_path.split(os.sep)
            top_component = parts[0] if parts else ''
            # Обрабатываем только выбранные категории
            if top_component.lower() not in categories:
                continue
            category = top_component.lower() if top_component else 'other'

            # Формируем путь вывода так, чтобы внутри output_dir были подпапки по category
            # и сохранялась структура внутри этой подпапки
            rel_inside = os.path.relpath(source_file_path, os.path.join(source_dir, top_component)) if top_component else relative_path
            output_file_path = os.path.join(output_dir, category, rel_inside)
            os.makedirs(os.path.dirname(output_file_path), exist_ok=True)

            with open(source_file_path, 'r', encoding='utf-8') as f:
                all_lines = f.readlines()

            # Немного более надёжный шаблон: не жадный захват текста внутри кавычек,
            # поддержка экранированных кавычек внутри строки
            show_text_pattern = re.compile(r'^(\s*)ShowText\(\["((?:\\"|[^"])*)"\]\)')
            # Для файлов, находящихся в подпапке 'maps', строки формата "Speaker:\#text"
            is_map_file = top_component.lower() == 'maps'
            maps_pattern = re.compile(r'^(.*?:\\#)(.*)') if is_map_file else None

            entries = []
            for idx, line in enumerate(all_lines):
                # Сначала проверяем ShowText
                match = show_text_pattern.search(line)
                if match:
                    indentation = match.group(1)
                    original_text = match.group(2)
                    # Пропускаем, если уже русская строка
                    if is_cyrillic(original_text):
                        continue
                    masked, tokens = mask_control_sequences(original_text)
                    # Записываем тип 'show' для последующей подстановки
                    entries.append((idx, 'show', indentation, original_text, masked, tokens))
                    texts_to_translate.append(masked)
                    continue

                # Если это файл внутри папки maps, проверяем формат диалога Speaker:\#...
                if is_map_file and maps_pattern is not None:
                    m2 = maps_pattern.search(line)
                    if m2:
                        prefix = m2.group(1)  # включаем 'Speaker:\#'
                        original_text = m2.group(2)
                        if is_cyrillic(original_text):
                            continue
                        masked, tokens = mask_control_sequences(original_text)
                        entries.append((idx, 'maps', prefix, original_text, masked, tokens))
                        texts_to_translate.append(masked)
                        continue

                # Для файлов в 'other' — если строка содержит заметный текст (буквы/цифры),
                # считаем её подлежащей переводу целиком, за исключением управляющих последовательностей.
                if not is_map_file and top_component.lower() == 'other':
                    # Игнорируем пустые строки и строки, состоящие только из управляющих символов
                    if re.search(r'[A-Za-z0-9]', line):
                        # Сохраняем ведущие пробелы как префикс
                        m_ws = re.match(r'^(\s*)(.*)$', line)
                        leading = m_ws.group(1)
                        body = m_ws.group(2).rstrip('\n')
                        if is_cyrillic(body):
                            continue
                        masked, tokens = mask_control_sequences(body)
                        # Добавляем как 'otherline' — будем заменять весь body на перевод
                        entries.append((idx, 'otherline', leading, body, masked, tokens))
                        texts_to_translate.append(masked)
                        continue

            files_data[source_file_path] = {
                'relative_path': relative_path,
                'output_path': output_file_path,
                'all_lines': all_lines,
                'entries': entries,
            }

    if not texts_to_translate:
        print('Не найдено строк для перевода во всей папке.')
        return

    pass

    # Выполняем перевод всех собранных текстов батчами
    print(f'Запрошено переводов: {len(texts_to_translate)}. Выполняю батчевые запросы...')
    all_translations = batch_translate(texts_to_translate, batch_size)

    # Лог записей для возможности повторной обработки
    log_records: list[dict] = []

    # Применяем переводы обратно к файлам
    t_idx = 0
    for source_path, info in files_data.items():
        all_lines = info['all_lines']
        entries = info['entries']
        output_path = info['output_path']

        for (line_idx, kind, prefix, original_text, masked, tokens) in entries:
            translated = all_translations[t_idx] if t_idx < len(all_translations) else ''
            # Восстанавливаем управляющие последовательности
            translated_unmasked = unmask_control_sequences(translated, tokens) if translated else ''
            translated_escaped = translated_unmasked.replace('"', '\\"') if translated_unmasked else ''

            rec = {
                'index': t_idx,
                'source_path': source_path,
                'output_path': output_path,
                'line_idx': line_idx,
                'kind': kind,
                'prefix': prefix,
                'original': original_text,
                'masked': masked,
                'tokens': tokens,
                'translated': translated_unmasked,
                'status': 'ok' if translated_unmasked else 'missing',
            }
            log_records.append(rec)
            t_idx += 1

            if kind == 'show':
                if translated_escaped:
                    all_lines[line_idx] = f'{prefix}ShowText(["{translated_escaped}"])\n'
            elif kind == 'maps':
                if translated_unmasked:
                    all_lines[line_idx] = f'{prefix}{translated_unmasked}\n'
            elif kind == 'otherline':
                if translated_unmasked:
                    all_lines[line_idx] = f'{prefix}{translated_unmasked}\n'

        # Записываем итоговый файл
        with open(output_path, 'w', encoding='utf-8') as f_out:
            f_out.writelines(all_lines)

    print('Батчевый перевод всех файлов завершён.')

    # Сохраняем лог переводов
    log_path = os.path.join(output_dir, 'translate_log.json')
    try:
        with open(log_path, 'w', encoding='utf-8') as lf:
            json.dump(log_records, lf, ensure_ascii=False, indent=2)
        print(f'Лог переводов сохранён: {log_path}')
    except Exception as e:
        print(f'Не удалось сохранить лог: {e}')

    return log_path
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


def retry_from_log(log_path: str, batch_size: int = 2000):
    """Повторно переводит отсутствующие элементы из лога.
    Обновляет файлы-вывода и сам лог.
    """
    try:
        with open(log_path, 'r', encoding='utf-8') as lf:
            records = json.load(lf)
    except Exception as e:
        print(f"Не удалось загрузить лог {log_path}: {e}")
        return

    # Собираем записи, которые помечены как missing
    missing = [r for r in records if r.get('status') != 'ok']
    if not missing:
        print('Нет отсутствующих переводов в логе.')
        return

    print(f'Найдено {len(missing)} отсутствующих переводов. Попытка перевода...')

    masked_texts = [r['masked'] for r in missing]
    translated_masked = batch_translate(masked_texts, batch_size)

    # Применяем переводы по очереди
    for rec, tr_mask in zip(missing, translated_masked):
        tr_unmasked = unmask_control_sequences(tr_mask, rec.get('tokens', [])) if tr_mask else ''
        rec['translated'] = tr_unmasked
        rec['status'] = 'ok' if tr_unmasked else 'missing'

        # Записываем в файл-выход
        out_path = rec['output_path']
        try:
            with open(out_path, 'r', encoding='utf-8') as f:
                lines = f.readlines()

            line_idx = rec['line_idx']
            kind = rec['kind']
            prefix = rec['prefix']
            if kind == 'show':
                escaped = rec['translated'].replace('"', '\\"') if rec['translated'] else ''
                if escaped:
                    lines[line_idx] = f"{prefix}ShowText([\"{escaped}\"])\n"
            elif kind in ('maps', 'otherline'):
                if rec['translated']:
                    lines[line_idx] = f"{prefix}{rec['translated']}\n"

            with open(out_path, 'w', encoding='utf-8') as f:
                f.writelines(lines)
        except Exception as e:
            print(f"Не удалось обновить файл {out_path}: {e}")

    # Сохраняем обновлённый лог
    try:
        with open(log_path, 'w', encoding='utf-8') as lf:
            json.dump(records, lf, ensure_ascii=False, indent=2)
        print(f'Лог обновлён: {log_path}')
    except Exception as e:
        print(f'Не удалось сохранить обновлённый лог: {e}')

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
                    "Preserve all special formatting tokens and control sequences exactly as they appear, including backslash-escaped sequences such as \\i[...], \\#, \\. and any other markup or tags (do NOT translate or modify these tokens). "
                    "Return a JSON object with a single key 'translations' which is an array of translated strings in the exact same order as the input. "
                    "Do not add extra commentary, numbering, or surrounding quotation marks.\n\n"
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
