# Bewerbungs-Assistent (Agent-Skill & Vorlage)

Ein datenschutzorientierter, universeller Agent-Skill für Bewerbungen mit strikter Trennung zwischen **Prozesslogik** (`.agents/skills/`), **anonymisierten Karrieredaten** (`karriere-profil/`) und **lokalen Personendaten / Anlagen** (`stammdaten/`, durch `.gitignore` und `.agents/permissions.json` geschützt).

## Enthaltene Komponenten
- [SKILL.md](.agents/skills/bewerbungs-assistent/SKILL.md) – Vollständiger Workflow (`Bewerbung`, `Onboarding`, `ATS-Check`, `Interview`) inkl. interaktivem Vakanz-Abgleich, Quellenprüfung, DIN 5008:2020-Vorgaben, laufendem ATS-Check und Design-Einheitlichkeitsprüfung.
- [permissions.json](.agents/permissions.json) – Sperrt direkte Lese- und Schreibzugriffe des Agenten auf `stammdaten/personendaten.json`.
- [build_bewerbung.py](scripts/build_bewerbung.py) – Exportiert Anschreiben (DIN 5008 Form B), Lebenslauf (Clean Tech Minimalism, optional mit Foto) und bereinigte Anlagen als `.docx` und `.pdf` inkl. automatischem ATS- und Design-Check.
- [version_backup.py](scripts/version_backup.py) – Lokale Versionshistorie mit Snapshot-Backups, Diff-Protokoll, Volltext-Suchfunktion und Restore.
- [personendaten.example.json](stammdaten/personendaten.example.json) – Vorlage für lokale Kontaktdaten.

## Schnellstart in einem eigenen Bewerbungs-Repository
1. Kopiere die Ordner `.agents/`, `scripts/`, `stammdaten/personendaten.example.json` und `.gitignore` in dein privates Bewerbungs-Repository.
2. Installiere die Python-Abhängigkeiten:
   ```bash
   pip install python-docx docx2pdf pymupdf pillow numpy
   ```
3. Kopiere `stammdaten/personendaten.example.json` nach `stammdaten/personendaten.json` und trage dort deine echten Kontaktdaten manuell ein (optional auch `stammdaten/bewerbungsfoto.jpg`, `stammdaten/unterschrift.png` und Zeugnis-Scans unter `stammdaten/anlagen/`).
4. Starte im Chat mit **`Onboarding`** oder direkt mit **`Bewerbung`** + Stellenanzeige.
5. Exportiere fertige Unterlagen lokal:
   ```bash
   python scripts/build_bewerbung.py bewerbungen/JJJJ-MM_Firma
   ```
