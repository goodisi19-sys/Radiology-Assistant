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
