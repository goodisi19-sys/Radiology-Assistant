# Radiology Assistant

Portable Windows desktop editor for MRI reports, with a searchable phrase library and autocomplete.

## Features
- Report editor with Times New Roman 12 pt default
- DOCX and TXT open/save; DOCX export
- Search and insert reusable phrases
- Context autocomplete from the local phrase library
- Import DOCX/TXT templates or a ZIP containing them; phrases are stored locally in SQLite
- Category tagging, phrase usage counts, and editable report text

## Build
The GitHub Actions workflow builds a Windows executable on a Windows runner. Open **Actions → Build Windows app**, then download the `RadiologyAssistant-Windows` artifact from the completed run. Extract the ZIP and run `RadiologyAssistant.exe`.

## First launch
Use **Library → Import templates** and select DOCX/TXT files or a ZIP archive containing them. The local phrase database is created beside the executable (or in the user's application data folder when running a one-file build).

## Privacy
Do not import identifiable patient reports. Use de-identified templates only. The application stores its phrase database locally; do not share that database if it contains patient information. Keep this repository private if you add any clinical materials.

## Notes
This is a practical report-writing editor, not a replacement for Microsoft Word. Legacy binary `.doc` files should be converted to `.docx` before import.

## Проверка разработки

Полная библиотека из 497 записей требует `protocols_legacy.json`. GitHub Actions
создаёт его командой `python convert_legacy.py` (необходим antiword).
Затем выполните `python -m unittest discover -v`, `python check_catalog.py`
и `python audit_library.py`. Детали и ограничения: [AUDIT.md](AUDIT.md).
Перед миграцией старой базы создаётся резервная копия в подпапке `backups`.

## Оформление, опечатки и Google

Qwen, локальный чат и «Экспертный помощник» удалены. Движок ИИ и модель
для запуска не нужны. Вкладка Google открывает вопрос в обычном браузере;
API не используется, документ автоматически не передаётся.

При вставке, Enter, команде «Оформить текст» и сохранении: начальное тире
убирается, первая буква строки становится заглавной, строка завершается точкой.
Точки с запятой внутри строки, заголовки с двоеточием, числа, сокращения,
пустые абзацы и медицинские обозначения сохраняются.

«Проверить опечатки» (F7) использует офлайн-словарь русского языка. Исправления
выбираются вручную, доступны личный словарь и отмена Ctrl+Z. Медицинские
термины словарь может не знать; автоматических замен нет.

Быстрые строки, библиотека 497 протоколов и приоритет личных верифицированных
стандартов сохранены. Инструкция: [USER_GUIDE.md](USER_GUIDE.md).

Кнопка «Яндекс Редактор» открывает текст на локальной странице установленного
Яндекс Браузера. Его встроенный редактор используется в браузере, а кнопка
«Вернуть в программу» возвращает результат на просмотр и ручную замену.
API-ключ и локальная нейросеть не нужны. Подробности — USER_GUIDE.md.

Технические переносы DOC/ODT восстанавливаются по структуре исходных документов
перед оформлением. Все 497 записей проходят `python audit_layouts.py`; полный
`layout-audit.json` публикуется отдельным артефактом Windows Actions.
Исходные записи SQLite и личные правки сохраняются.
