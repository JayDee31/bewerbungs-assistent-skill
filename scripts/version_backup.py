import argparse
import hashlib
import json
import re
import shutil
import sys
from datetime import datetime
from pathlib import Path

BACKUP_DIR_NAME = "backups"
INDEX_FILE_NAME = "index.json"
HISTORY_MD_NAME = "VERSIONSHISTORIE.md"

SKIP_DIRS = {".git", "__pycache__", ".venv", BACKUP_DIR_NAME}
SEARCHABLE_EXTS = {".md", ".py", ".txt", ".json", ".yaml", ".yml"}
PII_BLOCKED_NAMES = {"personendaten.json"}


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def collect_repo_files(repo_root: Path) -> dict[str, Path]:
    """Sammelt alle relevanten Projektdateien (inkl. stammdaten & output fuer Backups)."""
    files: dict[str, Path] = {}
    for path in sorted(repo_root.rglob("*")):
        if not path.is_file():
            continue
        rel = path.relative_to(repo_root)
        if any(part in SKIP_DIRS for part in rel.parts):
            continue
        files[rel.as_posix()] = path
    return files


def load_index(backup_root: Path) -> dict:
    index_path = backup_root / INDEX_FILE_NAME
    if not index_path.exists():
        return {"versions": []}
    return json.loads(index_path.read_text(encoding="utf-8"))


def save_index_and_markdown(backup_root: Path, index: dict) -> None:
    index_path = backup_root / INDEX_FILE_NAME
    index_path.write_text(json.dumps(index, indent=2, ensure_ascii=False), encoding="utf-8")

    lines = [
        "# Versionshistorie & Backups",
        "",
        "Automatisch gepflegte lokale Versionshistorie (Snapshots unter `backups/`).",
        "",
        "| Version | Datum & Uhrzeit | Anlass / Beschreibung | Änderungen | Dateien gesamt |",
        "| :--- | :--- | :--- | :--- | ---: |",
    ]
    for entry in reversed(index["versions"]):
        changes = []
        if entry["added"]:
            changes.append(f"+{len(entry['added'])} neu")
        if entry["modified"]:
            changes.append(f"~{len(entry['modified'])} geändert")
        if entry["deleted"]:
            changes.append(f"-{len(entry['deleted'])} entfernt")
        change_summary = ", ".join(changes) if changes else "Initialstand"
        lines.append(
            f"| `{entry['version']}` | {entry['timestamp_display']} | {entry['reason']} | {change_summary} | {entry['file_count']} |"
        )

    lines.append("")
    lines.append("## Details pro Version")
    for entry in reversed(index["versions"]):
        lines.append("")
        lines.append(f"### {entry['version']} — {entry['timestamp_display']} ({entry['reason']})")
        lines.append(f"- **Ordner:** `{entry['folder']}`")
        if entry["added"]:
            lines.append(f"- **Neu:** {', '.join(f'`{f}`' for f in entry['added'])}")
        if entry["modified"]:
            lines.append(f"- **Geändert:** {', '.join(f'`{f}`' for f in entry['modified'])}")
        if entry["deleted"]:
            lines.append(f"- **Entfernt:** {', '.join(f'`{f}`' for f in entry['deleted'])}")

    (backup_root / HISTORY_MD_NAME).write_text("\n".join(lines) + "\n", encoding="utf-8")


def create_backup(repo_root: Path, reason: str = "Manuelles Backup", force: bool = False) -> dict | None:
    """Erstellt einen neuen Snapshot unter backups/, falls Aenderungen vorliegen."""
    backup_root = repo_root / BACKUP_DIR_NAME
    backup_root.mkdir(parents=True, exist_ok=True)
    index = load_index(backup_root)

    current_files = collect_repo_files(repo_root)
    current_hashes = {rel: sha256_file(p) for rel, p in current_files.items()}

    prev_hashes: dict[str, str] = {}
    if index["versions"]:
        prev_hashes = index["versions"][-1].get("hashes", {})

    added = sorted(k for k in current_hashes if k not in prev_hashes)
    modified = sorted(k for k in current_hashes if k in prev_hashes and current_hashes[k] != prev_hashes[k])
    deleted = sorted(k for k in prev_hashes if k not in current_hashes)

    if not force and index["versions"] and not (added or modified or deleted):
        return None

    next_num = len(index["versions"]) + 1
    version_id = f"v{next_num:04d}"
    now = datetime.now()
    folder_name = f"{version_id}_{now.strftime('%Y-%m-%d_%H-%M-%S')}"
    snapshot_dir = backup_root / folder_name

    for rel, src_path in current_files.items():
        dst = snapshot_dir / rel
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src_path, dst)

    entry = {
        "version": version_id,
        "folder": folder_name,
        "timestamp": now.isoformat(timespec="seconds"),
        "timestamp_display": now.strftime("%d.%m.%Y %H:%M:%S"),
        "reason": reason.strip() or "Snapshot",
        "added": added,
        "modified": modified,
        "deleted": deleted,
        "file_count": len(current_hashes),
        "hashes": current_hashes,
    }
    index["versions"].append(entry)
    save_index_and_markdown(backup_root, index)
    return entry


def is_safe_searchable_file(rel_posix: str) -> bool:
    p = Path(rel_posix)
    if p.name in PII_BLOCKED_NAMES:
        return False
    if "/output/" in f"/{rel_posix}" or rel_posix.startswith("stammdaten/anlagen"):
        return False
    return p.suffix.lower() in SEARCHABLE_EXTS


def search_documents(
    repo_root: Path,
    query: str,
    version_filter: str | None = None,
    doc_filter: str | None = None,
    include_backups: bool = True,
    include_pdfs: bool = False,
) -> list[dict]:
    """Durchsucht aktuelle Dokumente und optional Backup-Versionen nach einem Begriff."""
    pattern = re.compile(re.escape(query), re.IGNORECASE)
    results: list[dict] = []

    def _scan_root(root: Path, version_label: str) -> None:
        for path in sorted(root.rglob("*")):
            if not path.is_file():
                continue
            rel = path.relative_to(root).as_posix()
            if any(part in SKIP_DIRS for part in Path(rel).parts):
                continue
            if doc_filter and doc_filter.lower() not in rel.lower():
                continue

            if Path(rel).suffix.lower() == ".pdf":
                if not include_pdfs:
                    continue
                try:
                    import pymupdf  # type: ignore

                    pdf_doc = pymupdf.open(path)
                    for p_idx, page in enumerate(pdf_doc, start=1):
                        for ln in page.get_text("text").splitlines():
                            if pattern.search(ln):
                                results.append(
                                    {
                                        "version": version_label,
                                        "file": rel,
                                        "line": f"Seite {p_idx}",
                                        "snippet": ln.strip()[:140],
                                    }
                                )
                except Exception:
                    continue
                continue

            if not is_safe_searchable_file(rel):
                continue

            try:
                text = path.read_text(encoding="utf-8")
            except Exception:
                continue

            for idx, ln in enumerate(text.splitlines(), start=1):
                if pattern.search(ln):
                    results.append(
                        {
                            "version": version_label,
                            "file": rel,
                            "line": idx,
                            "snippet": ln.strip()[:140],
                        }
                    )

    if not version_filter or version_filter.lower() == "current":
        _scan_root(repo_root, "aktuell")

    if include_backups or (version_filter and version_filter.lower() != "current"):
        backup_root = repo_root / BACKUP_DIR_NAME
        index = load_index(backup_root)
        for entry in reversed(index["versions"]):
            if version_filter and version_filter.lower() not in {entry["version"].lower(), "all"}:
                continue
            snap_dir = backup_root / entry["folder"]
            if snap_dir.exists():
                _scan_root(snap_dir, entry["version"])

    return results


def restore_version(repo_root: Path, version_id: str, doc_filter: str | None = None) -> list[str]:
    """Stellt eine fruehere Version (komplett oder fuer ein bestimmtes Dokument) wieder her."""
    backup_root = repo_root / BACKUP_DIR_NAME
    index = load_index(backup_root)
    match = next((e for e in index["versions"] if e["version"].lower() == version_id.lower()), None)
    if not match:
        raise ValueError(f"Version '{version_id}' nicht in {backup_root / INDEX_FILE_NAME} gefunden.")

    snap_dir = backup_root / match["folder"]
    if not snap_dir.exists():
        raise FileNotFoundError(f"Backup-Ordner fehlt: {snap_dir}")

    create_backup(repo_root, reason=f"Sicherheits-Backup vor Restore von {match['version']}", force=True)

    restored: list[str] = []
    for src in sorted(snap_dir.rglob("*")):
        if not src.is_file():
            continue
        rel = src.relative_to(snap_dir).as_posix()
        if doc_filter and doc_filter.lower() not in rel.lower():
            continue
        dst = repo_root / rel
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dst)
        restored.append(rel)
    return restored


def main() -> None:
    parser = argparse.ArgumentParser(description="Versionshistorie, Backup und Dokumentensuche")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_snap = sub.add_parser("snapshot", help="Neuen Backup-Snapshot erstellen")
    p_snap.add_argument("reason", nargs="?", default="Manuelles Backup", help="Beschreibung der Aenderung")
    p_snap.add_argument("--force", action="store_true", help="Snapshot auch ohne Aenderungen anlegen")

    p_hist = sub.add_parser("history", help="Versionshistorie anzeigen")
    p_hist.add_argument("--limit", type=int, default=20, help="Maximale Anzahl Eintraege")

    p_search = sub.add_parser("search", help="Dokumente und Versionen durchsuchen")
    p_search.add_argument("query", help="Suchbegriff")
    p_search.add_argument("--version", default=None, help="z. B. current, v0001 oder all")
    p_search.add_argument("--doc", default=None, help="Dateipfad-Filter, z. B. anschreiben.md")
    p_search.add_argument("--current-only", action="store_true", help="Nur aktuellen Stand durchsuchen")
    p_search.add_argument("--pdfs", action="store_true", help="Auch PDF-Texte lokal mit durchsuchen")

    p_rest = sub.add_parser("restore", help="Version oder einzelnes Dokument wiederherstellen")
    p_rest.add_argument("version", help="Versions-ID, z. B. v0001")
    p_rest.add_argument("--doc", default=None, help="Optional nur passende Dateipfade wiederherstellen")

    args = parser.parse_args()
    repo_root = Path(__file__).resolve().parent.parent

    if args.cmd == "snapshot":
        entry = create_backup(repo_root, reason=args.reason, force=args.force)
        if entry:
            print(f"Backup erstellt: {entry['version']} ({entry['folder']}) — {entry['file_count']} Dateien")
        else:
            print("Keine Aenderungen seit dem letzten Backup erkannt.")

    elif args.cmd == "history":
        index = load_index(repo_root / BACKUP_DIR_NAME)
        versions = index["versions"][-args.limit :]
        if not versions:
            print("Noch keine Versionen vorhanden.")
            return
        for entry in reversed(versions):
            print(
                f"{entry['version']} | {entry['timestamp_display']} | {entry['reason']} | "
                f"+{len(entry['added'])} ~{len(entry['modified'])} -{len(entry['deleted'])} | {entry['file_count']} Dateien"
            )

    elif args.cmd == "search":
        hits = search_documents(
            repo_root,
            query=args.query,
            version_filter=args.version,
            doc_filter=args.doc,
            include_backups=not args.current_only,
            include_pdfs=args.pdfs,
        )
        if not hits:
            print(f"Keine Treffer fuer '{args.query}'.")
            return
        print(f"Treffer fuer '{args.query}': {len(hits)}")
        for h in hits[:50]:
            print(f"[{h['version']}] {h['file']}:{h['line']} -> {h['snippet']}")

    elif args.cmd == "restore":
        restored = restore_version(repo_root, version_id=args.version, doc_filter=args.doc)
        print(f"Wiederhergestellt aus {args.version}: {len(restored)} Datei(en)")


if __name__ == "__main__":
    main()
