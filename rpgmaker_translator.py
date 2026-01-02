import os
import time

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
    print("RPG Maker Game Translator")
    print("=========================")

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

def process_single_file(source_path, output_path):
    """
    Читает один файл, находит строки для перевода и записывает результат.
    """
    print(f"Обработка файла: {os.path.basename(source_path)}")
    try:
        with open(source_path, 'r', encoding='utf-8') as f_in, \
             open(output_path, 'w', encoding='utf-8') as f_out:

            lines = f_in.readlines()
            i = 0
            while i < len(lines):
                line = lines[i]

                # Ищем маркер Show Text
                if "◆Show Text" in line:
                    # Записываем саму строку-маркер
                    f_out.write(line)

                    # Переходим к следующей строке, которая содержит текст
                    i += 1
                    if i < len(lines):
                        text_to_translate = lines[i]

                        # Выводим оригинал и запрашиваем перевод
                        print(f"\nОригинал: {text_to_translate.strip()}")
                        translated_text = input("Перевод  : ")

                        # Записываем ТОЛЬКО перевод
                        f_out.write(translated_text + '\n')
                else:
                    # Если это обычная строка, просто записываем ее
                    f_out.write(line)

                i += 1
    except Exception as e:
        print(f"  Не удалось обработать файл {os.path.basename(source_path)}: {e}")


if __name__ == "__main__":
    main()
