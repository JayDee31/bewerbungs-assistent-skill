import json
import re
import shutil
import subprocess
import sys
from datetime import date
from pathlib import Path
from docx import Document
from docx.image.image import Image as DocxImage
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Cm, Pt, RGBColor
from docx.enum.table import WD_TABLE_ALIGNMENT, WD_ALIGN_VERTICAL
from docx.enum.text import WD_ALIGN_PARAGRAPH, WD_TAB_ALIGNMENT

# Zeitgemaesse IT-Farbpalette ("Clean Tech Minimalism" / 60-30-10-Regel)
COLOR_PRIMARY = RGBColor(0x0F, 0x17, 0x2A)   # Midnight Slate (#0F172A)
COLOR_ACCENT = RGBColor(0x1E, 0x3A, 0x5F)    # Deep Navy (#1E3A5F)
COLOR_MUTED = RGBColor(0x47, 0x55, 0x69)     # Schiefergrau (#475569)
COLOR_LIGHT = RGBColor(0x64, 0x74, 0x8B)     # Gedämpftes Grau (#64748B)
HEX_ACCENT = "1E3A5F"
HEX_RULE = "CBD5E1"
HEX_CALLOUT_BG = "F8FAFC"

FONT_FAMILY = "Segoe UI"
CV_TEXT_WIDTH = Cm(17.4)      # A4 (21.0 cm) - 1.8 cm links - 1.8 cm rechts
LETTER_TEXT_WIDTH = Cm(16.5)  # DIN 5008: A4 (21.0 cm) - 2.5 cm links - 2.0 cm rechts

GERMAN_MONTHS = {
    1: "Januar",
    2: "Februar",
    3: "März",
    4: "April",
    5: "Mai",
    6: "Juni",
    7: "Juli",
    8: "August",
    9: "September",
    10: "Oktober",
    11: "November",
    12: "Dezember",
}


def load_placeholders(repo_root: Path) -> dict:
    pii_file = repo_root / "stammdaten" / "personendaten.json"
    if not pii_file.exists():
        raise FileNotFoundError(
            f"Datei {pii_file} nicht gefunden. Bitte auf Basis von personendaten.example.json anlegen."
        )
    with pii_file.open("r", encoding="utf-8") as f:
        data = json.load(f)
    today = date.today()
    data.setdefault("DATUM", f"{today.day}. {GERMAN_MONTHS[today.month]} {today.year}")
    return data


def replace_placeholders(text: str, mapping: dict) -> str:
    for key, value in mapping.items():
        text = text.replace(f"{{{{{key}}}}}", str(value))
    return text


def set_bottom_border(paragraph, color_hex: str, size_eighths: int = 8, space: int = 4) -> None:
    p_pr = paragraph._p.get_or_add_pPr()
    p_bdr = OxmlElement("w:pBdr")
    bottom = OxmlElement("w:bottom")
    bottom.set(qn("w:val"), "single")
    bottom.set(qn("w:sz"), str(size_eighths))
    bottom.set(qn("w:space"), str(space))
    bottom.set(qn("w:color"), color_hex)
    p_bdr.append(bottom)
    p_pr.append(p_bdr)


def set_top_border(paragraph, color_hex: str, size_eighths: int = 4, space: int = 6) -> None:
    p_pr = paragraph._p.get_or_add_pPr()
    p_bdr = OxmlElement("w:pBdr")
    top = OxmlElement("w:top")
    top.set(qn("w:val"), "single")
    top.set(qn("w:sz"), str(size_eighths))
    top.set(qn("w:space"), str(space))
    top.set(qn("w:color"), color_hex)
    p_bdr.append(top)
    p_pr.append(p_bdr)


def set_callout_style(paragraph, border_hex: str = HEX_ACCENT, bg_hex: str = HEX_CALLOUT_BG) -> None:
    p_pr = paragraph._p.get_or_add_pPr()
    p_bdr = OxmlElement("w:pBdr")
    left = OxmlElement("w:left")
    left.set(qn("w:val"), "single")
    left.set(qn("w:sz"), "18")
    left.set(qn("w:space"), "8")
    left.set(qn("w:color"), border_hex)
    p_bdr.append(left)
    p_pr.append(p_bdr)

    shd = OxmlElement("w:shd")
    shd.set(qn("w:val"), "clear")
    shd.set(qn("w:color"), "auto")
    shd.set(qn("w:fill"), bg_hex)
    p_pr.append(shd)


def set_run_letter_spacing(run, twips: int = 12) -> None:
    r_pr = run._r.get_or_add_rPr()
    spacing = OxmlElement("w:spacing")
    spacing.set(qn("w:val"), str(twips))
    r_pr.append(spacing)


def configure_document(
    doc: Document,
    top_cm: float = 1.4,
    bottom_cm: float = 1.2,
    left_cm: float = 1.8,
    right_cm: float = 1.8,
) -> None:
    for section in doc.sections:
        section.page_width = Cm(21.0)
        section.page_height = Cm(29.7)
        section.top_margin = Cm(top_cm)
        section.bottom_margin = Cm(bottom_cm)
        section.left_margin = Cm(left_cm)
        section.right_margin = Cm(right_cm)

    style = doc.styles["Normal"]
    style.font.name = FONT_FAMILY
    style.font.size = Pt(9.2)
    style.font.color.rgb = COLOR_PRIMARY


def add_inline_runs(paragraph, text: str, base_size: float = 9.0, base_color: RGBColor = COLOR_PRIMARY) -> None:
    parts = re.split(r"(\*\*.*?\*\*)", text)
    for part in parts:
        if not part:
            continue
        if part.startswith("**") and part.endswith("**"):
            run = paragraph.add_run(part[2:-2])
            run.bold = True
            run.font.name = FONT_FAMILY
            run.font.size = Pt(base_size)
            run.font.color.rgb = COLOR_PRIMARY
        else:
            run = paragraph.add_run(part)
            run.font.name = FONT_FAMILY
            run.font.size = Pt(base_size)
            run.font.color.rgb = base_color


def add_bullet(
    doc: Document,
    text: str,
    font_size: float = 8.6,
    space_after: float = 1.0,
    line_spacing: float = 1.08,
    color: RGBColor = COLOR_PRIMARY,
) -> None:
    p = doc.add_paragraph()
    p.paragraph_format.left_indent = Cm(0.42)
    p.paragraph_format.first_line_indent = Cm(-0.28)
    p.paragraph_format.space_before = Pt(0)
    p.paragraph_format.space_after = Pt(space_after)
    p.paragraph_format.line_spacing = line_spacing

    bullet_run = p.add_run("•  ")
    bullet_run.font.name = FONT_FAMILY
    bullet_run.font.size = Pt(font_size)
    bullet_run.font.color.rgb = COLOR_ACCENT

    add_inline_runs(p, text, base_size=font_size, base_color=color)


def is_date_range_line(line: str) -> bool:
    return bool(re.match(r"^\d{2}/\d{4}\s*[-–]\s*(\d{2}/\d{4}|heute)$", line.strip(), re.IGNORECASE))


def set_borderless_table_layout(table, col_widths_cm: tuple[float, ...] | None = None) -> None:
    tbl_pr = table._tbl.tblPr
    tbl_borders = OxmlElement("w:tblBorders")
    for edge in ("top", "left", "bottom", "right", "insideH", "insideV"):
        el = OxmlElement(f"w:{edge}")
        el.set(qn("w:val"), "none")
        el.set(qn("w:sz"), "0")
        el.set(qn("w:space"), "0")
        el.set(qn("w:color"), "auto")
        tbl_borders.append(el)
    tbl_pr.append(tbl_borders)

    tbl_mar = OxmlElement("w:tblCellMar")
    for edge in ("top", "left", "bottom", "right"):
        el = OxmlElement(f"w:{edge}")
        el.set(qn("w:w"), "0")
        el.set(qn("w:type"), "dxa")
        tbl_mar.append(el)
    tbl_pr.append(tbl_mar)

    tbl_layout = OxmlElement("w:tblLayout")
    tbl_layout.set(qn("w:type"), "fixed")
    tbl_pr.append(tbl_layout)

    if col_widths_cm:
        for idx, width_cm in enumerate(col_widths_cm):
            table.columns[idx].width = Cm(width_cm)
            table.rows[0].cells[idx].width = Cm(width_cm)


def style_picture_frame(inline_shape, border_hex: str = "94A3B8", width_pt: float = 0.75, corner_adj: int = 6500) -> None:
    """Gibt dem eingebetteten Foto dezent abgerundete Ecken und einen feinen 0.75-pt-Rahmen."""
    pic = inline_shape._inline.graphic.graphicData.pic
    sp_pr = pic.spPr

    for existing in sp_pr.findall(qn("a:prstGeom")):
        sp_pr.remove(existing)
    for existing in sp_pr.findall(qn("a:ln")):
        sp_pr.remove(existing)

    prst_geom = OxmlElement("a:prstGeom")
    prst_geom.set("prst", "roundRect")
    av_lst = OxmlElement("a:avLst")
    gd = OxmlElement("a:gd")
    gd.set("name", "adj")
    gd.set("fmla", f"val {corner_adj}")
    av_lst.append(gd)
    prst_geom.append(av_lst)
    sp_pr.append(prst_geom)

    ln = OxmlElement("a:ln")
    ln.set("w", str(int(width_pt * 12700)))
    solid_fill = OxmlElement("a:solidFill")
    srgb = OxmlElement("a:srgbClr")
    srgb.set("val", border_hex)
    solid_fill.append(srgb)
    ln.append(solid_fill)
    sp_pr.append(ln)


def add_subtle_footer(doc: Document, left_text: str) -> None:
    """Fuegt eine dezente Fusszeile mit Trennlinie und Seitennummerierung ein."""
    section = doc.sections[0]
    section.footer_distance = Cm(0.75)
    footer = section.footer
    p_ftr = footer.paragraphs[0]
    p_ftr.style = doc.styles["Normal"]
    p_ftr.paragraph_format.space_before = Pt(0)
    p_ftr.paragraph_format.space_after = Pt(0)
    p_ftr.paragraph_format.tab_stops.clear_all()
    p_ftr.paragraph_format.tab_stops.add_tab_stop(CV_TEXT_WIDTH, WD_TAB_ALIGNMENT.RIGHT)
    set_top_border(p_ftr, HEX_RULE, size_eighths=4, space=4)

    r_f_left = p_ftr.add_run(left_text)
    r_f_left.font.name = FONT_FAMILY
    r_f_left.font.size = Pt(8.0)
    r_f_left.font.color.rgb = COLOR_LIGHT

    r_f_tab = p_ftr.add_run("\t")
    r_f_tab.font.name = FONT_FAMILY
    r_f_tab.font.size = Pt(8.0)
    add_page_number_fields(p_ftr, font_size=8.0, color=COLOR_LIGHT)


def render_cv_or_anlagen(
    md_text: str,
    out_docx: Path,
    photo_path: Path | None = None,
    footer_label: str | None = None,
) -> None:
    doc = Document()
    configure_document(
        doc,
        top_cm=1.15 if photo_path else 1.68,
        bottom_cm=1.05 if photo_path else 1.5,
        left_cm=1.8,
        right_cm=1.8,
    )

    lines = [ln.strip() for ln in md_text.splitlines()]
    i = 0
    header_done = False
    current_section = ""

    # Wenn ein Bewerbungsfoto vorhanden ist, Name + Kontaktzeile neben dem Foto oben rechts anordnen
    if photo_path is not None and len(lines) >= 2 and lines[0].startswith("# "):
        name_text = lines[0][2:].strip()
        contact_idx = 1
        while contact_idx < len(lines) and not lines[contact_idx]:
            contact_idx += 1
        contact_line = lines[contact_idx] if contact_idx < len(lines) and "|" in lines[contact_idx] and not lines[contact_idx].startswith("##") else ""

        tbl = doc.add_table(rows=1, cols=2)
        tbl.alignment = WD_TABLE_ALIGNMENT.CENTER
        tbl.autofit = False
        set_borderless_table_layout(tbl, col_widths_cm=(14.9, 2.5))

        left_cell, right_cell = tbl.rows[0].cells
        left_cell.vertical_alignment = WD_ALIGN_VERTICAL.CENTER
        right_cell.vertical_alignment = WD_ALIGN_VERTICAL.CENTER

        p_role_sub = left_cell.paragraphs[0]
        p_role_sub.paragraph_format.space_before = Pt(0)
        p_role_sub.paragraph_format.space_after = Pt(2.5)
        r_role_sub = p_role_sub.add_run("Lebenslauf")
        r_role_sub.bold = True
        r_role_sub.font.name = FONT_FAMILY
        r_role_sub.font.size = Pt(16.5)
        r_role_sub.font.color.rgb = COLOR_ACCENT

        parts = [part.strip() for part in contact_line.split("|") if part.strip()] if contact_line else []
        header_meta = "  ·  ".join([name_text] + parts)
        p_c = left_cell.add_paragraph()
        p_c.paragraph_format.space_before = Pt(0)
        p_c.paragraph_format.space_after = Pt(0)
        r_c = p_c.add_run(header_meta)
        r_c.font.name = FONT_FAMILY
        r_c.font.size = Pt(8.3)
        r_c.font.color.rgb = COLOR_MUTED

        p_img = right_cell.paragraphs[0]
        p_img.alignment = WD_ALIGN_PARAGRAPH.RIGHT
        p_img.paragraph_format.space_before = Pt(0)
        p_img.paragraph_format.space_after = Pt(0)
        p_img.paragraph_format.right_indent = Pt(1.5)
        p_img.paragraph_format.line_spacing = 1.0
        img = DocxImage.from_file(str(photo_path))
        aspect = img.px_height / max(img.px_width, 1)
        target_w_cm = 2.10
        target_h_cm = target_w_cm * aspect
        if target_h_cm > 2.48:
            target_h_cm = 2.48
            target_w_cm = target_h_cm / aspect
        inline_pic = p_img.add_run().add_picture(str(photo_path), width=Cm(target_w_cm), height=Cm(target_h_cm))
        style_picture_frame(inline_pic, border_hex="94A3B8", width_pt=0.75, corner_adj=6500)

        # Eine durchgehende, vollbreite Navy-Trennlinie direkt unterhalb des Kopfbereichs
        p_rule = doc.add_paragraph()
        p_rule.paragraph_format.space_before = Pt(0)
        p_rule.paragraph_format.space_after = Pt(4)
        p_rule.paragraph_format.line_spacing = Pt(3)
        r_rule = p_rule.add_run("")
        r_rule.font.size = Pt(2)
        set_bottom_border(p_rule, HEX_ACCENT, size_eighths=10, space=1)

        i = contact_idx + 1 if contact_line else 1

    while i < len(lines):
        line = lines[i]
        if not line:
            i += 1
            continue

        if line.startswith("# "):
            p = doc.add_paragraph()
            p.paragraph_format.space_before = Pt(0)
            p.paragraph_format.space_after = Pt(2.5)
            run = p.add_run(line[2:].strip())
            run.bold = True
            run.font.name = FONT_FAMILY
            run.font.size = Pt(16.5)
            run.font.color.rgb = COLOR_ACCENT
            header_done = True
            i += 1
            continue

        if header_done and i <= 3 and "|" in line and not line.startswith("##"):
            p = doc.add_paragraph()
            p.paragraph_format.space_before = Pt(0)
            p.paragraph_format.space_after = Pt(6)
            formatted_contact = line.replace(" | ", "  ·  ")
            run = p.add_run(formatted_contact)
            run.font.name = FONT_FAMILY
            run.font.size = Pt(8.3)
            run.font.color.rgb = COLOR_MUTED
            set_bottom_border(p, HEX_ACCENT, size_eighths=10, space=4)
            header_done = False
            i += 1
            continue

        header_done = False

        if line.startswith("## "):
            current_section = line[3:].strip()
            p = doc.add_paragraph()
            p.paragraph_format.space_before = Pt(5.5)
            p.paragraph_format.space_after = Pt(2.5)
            p.paragraph_format.keep_with_next = True
            run = p.add_run(current_section.upper())
            run.bold = True
            run.font.name = FONT_FAMILY
            run.font.size = Pt(8.8)
            run.font.color.rgb = COLOR_ACCENT
            set_run_letter_spacing(run, twips=14)
            set_bottom_border(p, HEX_RULE, size_eighths=4, space=2)
            i += 1
            continue

        if line.startswith("### "):
            title = line[4:].strip()
            next_non_empty = None
            j = i + 1
            while j < len(lines) and not lines[j]:
                j += 1
            if j < len(lines) and is_date_range_line(lines[j]):
                next_non_empty = lines[j]

            p = doc.add_paragraph()
            p.paragraph_format.space_before = Pt(3.5)
            p.paragraph_format.space_after = Pt(1.0)
            p.paragraph_format.keep_with_next = True
            p.paragraph_format.tab_stops.add_tab_stop(CV_TEXT_WIDTH, WD_TAB_ALIGNMENT.RIGHT)

            if " | " in title:
                role, org = title.split(" | ", 1)
                role, org = role.strip(), org.strip()
                if len(title) > 72 and next_non_empty:
                    r_role = p.add_run(role)
                    r_role.bold = True
                    r_role.font.name = FONT_FAMILY
                    r_role.font.size = Pt(9.1)
                    r_role.font.color.rgb = COLOR_PRIMARY

                    r_date = p.add_run(f"\t{next_non_empty}")
                    r_date.bold = True
                    r_date.font.name = FONT_FAMILY
                    r_date.font.size = Pt(8.3)
                    r_date.font.color.rgb = COLOR_ACCENT

                    p_org = doc.add_paragraph()
                    p_org.paragraph_format.space_before = Pt(0)
                    p_org.paragraph_format.space_after = Pt(1.0)
                    p_org.paragraph_format.keep_with_next = True
                    r_org = p_org.add_run(org)
                    r_org.font.name = FONT_FAMILY
                    r_org.font.size = Pt(8.4)
                    r_org.font.color.rgb = COLOR_MUTED
                    i = j + 1
                    continue

                r_role = p.add_run(role)
                r_role.bold = True
                r_role.font.name = FONT_FAMILY
                r_role.font.size = Pt(9.1)
                r_role.font.color.rgb = COLOR_PRIMARY

                r_sep = p.add_run("  ·  ")
                r_sep.font.name = FONT_FAMILY
                r_sep.font.size = Pt(8.8)
                r_sep.font.color.rgb = COLOR_LIGHT

                r_org = p.add_run(org)
                r_org.font.name = FONT_FAMILY
                r_org.font.size = Pt(8.7)
                r_org.font.color.rgb = COLOR_MUTED
            else:
                r_title = p.add_run(title)
                r_title.bold = True
                r_title.font.name = FONT_FAMILY
                r_title.font.size = Pt(9.1)
                r_title.font.color.rgb = COLOR_PRIMARY

            if next_non_empty:
                r_date = p.add_run(f"\t{next_non_empty}")
                r_date.bold = True
                r_date.font.name = FONT_FAMILY
                r_date.font.size = Pt(8.3)
                r_date.font.color.rgb = COLOR_ACCENT
                i = j + 1
            else:
                i += 1
            continue

        if line.startswith("- ") or line.startswith("* "):
            add_bullet(doc, line[2:].strip(), font_size=8.55, space_after=0.9, line_spacing=1.07)
            i += 1
            continue

        p = doc.add_paragraph()
        if current_section.lower() == "kurzprofil":
            p.paragraph_format.left_indent = Cm(0.28)
            p.paragraph_format.right_indent = Cm(0.15)
            p.paragraph_format.space_before = Pt(2)
            p.paragraph_format.space_after = Pt(3)
            p.paragraph_format.line_spacing = 1.12
            set_callout_style(p)
            add_inline_runs(p, line, base_size=8.8, base_color=COLOR_PRIMARY)
        else:
            p.paragraph_format.space_before = Pt(0)
            p.paragraph_format.space_after = Pt(2.0)
            p.paragraph_format.line_spacing = 1.09
            add_inline_runs(p, line, base_size=8.8, base_color=COLOR_PRIMARY)
        i += 1

    if footer_label:
        add_subtle_footer(doc, footer_label)

    doc.save(str(out_docx))


def render_anschreiben(md_text: str, out_docx: Path, signature_path: Path | None = None) -> None:
    doc = Document()
    # DIN 5008:2020 (Form B): links 25 mm, rechts 20 mm, unten 20 mm, Briefkopfzone bis 45 mm
    configure_document(doc, top_cm=1.7, bottom_cm=2.0, left_cm=2.5, right_cm=2.0)

    blocks: list[list[str]] = []
    current: list[str] = []
    for raw_line in md_text.splitlines():
        stripped = raw_line.strip()
        if not stripped:
            if current:
                blocks.append(current)
                current = []
        else:
            current.append(stripped)
    if current:
        blocks.append(current)

    if len(blocks) < 4:
        render_cv_or_anlagen(md_text, out_docx)
        return

    sender_block = blocks[0]
    recipient_block = blocks[1]
    date_block = blocks[2]
    body_blocks = blocks[3:]

    # 1. Briefkopf in oberer 45-mm-Zone (Name + einzeilige Kontaktleiste + Akzentlinie)
    sender_name = sender_block[0]
    sender_details = "  ·  ".join(sender_block[1:])

    p_name = doc.add_paragraph()
    p_name.paragraph_format.space_before = Pt(0)
    p_name.paragraph_format.space_after = Pt(2)
    r_name = p_name.add_run(sender_name)
    r_name.bold = True
    r_name.font.name = FONT_FAMILY
    r_name.font.size = Pt(16.5)
    r_name.font.color.rgb = COLOR_ACCENT

    p_contact = doc.add_paragraph()
    p_contact.paragraph_format.space_before = Pt(0)
    p_contact.paragraph_format.space_after = Pt(34)
    r_contact = p_contact.add_run(sender_details)
    r_contact.font.name = FONT_FAMILY
    r_contact.font.size = Pt(8.3)
    r_contact.font.color.rgb = COLOR_MUTED
    set_bottom_border(p_contact, HEX_ACCENT, size_eighths=10, space=5)

    # 2. Anschriftfeld (links, ohne Leerzeilen) + 2 Leerzeilen Abstand zum rechtsbuendigen Datum
    for idx, r_line in enumerate(recipient_block):
        p_rec = doc.add_paragraph()
        p_rec.paragraph_format.space_before = Pt(0)
        p_rec.paragraph_format.space_after = Pt(1.5)
        r_rec = p_rec.add_run(r_line)
        r_rec.font.name = FONT_FAMILY
        r_rec.font.size = Pt(10.0)
        r_rec.font.color.rgb = COLOR_PRIMARY

    p_date = doc.add_paragraph()
    p_date.alignment = WD_ALIGN_PARAGRAPH.RIGHT
    p_date.paragraph_format.space_before = Pt(18)  # ca. 2 Leerzeilen nach Anschriftfeld
    p_date.paragraph_format.space_after = Pt(18)   # ca. 2 Leerzeilen vor Betreff
    r_date = p_date.add_run(" ".join(date_block))
    r_date.font.name = FONT_FAMILY
    r_date.font.size = Pt(10.0)
    r_date.font.color.rgb = COLOR_MUTED

    # 3. Betreff (2 Leerzeilen vor Anrede), Anrede (1 Leerzeile vor Text), Absaetze, Grussformel (3 Leerzeilen Unterschrift) & Anlagen
    for idx, block in enumerate(body_blocks):
        if idx == 0 and len(block) == 1 and block[0].startswith("**") and block[0].endswith("**"):
            p_subj = doc.add_paragraph()
            p_subj.paragraph_format.space_before = Pt(0)
            p_subj.paragraph_format.space_after = Pt(20)  # DIN 5008: 2 Leerzeilen nach Betreff
            r_subj = p_subj.add_run(block[0][2:-2])
            r_subj.bold = True
            r_subj.font.name = FONT_FAMILY
            r_subj.font.size = Pt(11.0)
            r_subj.font.color.rgb = COLOR_ACCENT
            continue

        if block[0].strip("*") == "Anlagen":
            prev_is_closing = idx > 0 and body_blocks[idx - 1][0].startswith("Mit freundlichen")
            p_anl_hdr = doc.add_paragraph()
            p_anl_hdr.paragraph_format.space_before = Pt(
                (10 if signature_path else 40) if prev_is_closing else 14
            )
            p_anl_hdr.paragraph_format.space_after = Pt(3)
            p_anl_hdr.paragraph_format.keep_with_next = True
            set_top_border(p_anl_hdr, HEX_RULE, size_eighths=4, space=6)
            r_anl = p_anl_hdr.add_run("ANLAGEN")
            r_anl.bold = True
            r_anl.font.name = FONT_FAMILY
            r_anl.font.size = Pt(8.5)
            r_anl.font.color.rgb = COLOR_ACCENT
            set_run_letter_spacing(r_anl, twips=12)

            for item in block[1:]:
                clean_item = item[2:].strip() if item.startswith(("- ", "* ")) else item
                add_bullet(doc, clean_item, font_size=8.4, space_after=1.1, line_spacing=1.08, color=COLOR_MUTED)
            continue

        if idx > 0 and body_blocks[idx - 1][0].startswith("Mit freundlichen"):
            p_sig = doc.add_paragraph()
            p_sig.paragraph_format.space_before = Pt(4 if signature_path else 36)
            p_sig.paragraph_format.space_after = Pt(11)
            r_sig = p_sig.add_run(" ".join(block))
            r_sig.bold = True
            r_sig.font.name = FONT_FAMILY
            r_sig.font.size = Pt(10.0)
            r_sig.font.color.rgb = COLOR_PRIMARY
            continue

        p = doc.add_paragraph()
        p.paragraph_format.space_before = Pt(0)
        is_closing = block[0].startswith("Mit freundlichen")
        has_following_sig = is_closing and (idx + 1 < len(body_blocks)) and (body_blocks[idx + 1][0].strip("*") != "Anlagen")
        if is_closing and signature_path is not None:
            p.paragraph_format.space_after = Pt(2)
        else:
            p.paragraph_format.space_after = Pt(0 if has_following_sig else (40 if is_closing else 10.5))
        p.paragraph_format.line_spacing = 1.15
        add_inline_runs(p, " ".join(block), base_size=10.0, base_color=COLOR_PRIMARY)

        if is_closing and signature_path is not None:
            p_sig_img = doc.add_paragraph()
            p_sig_img.paragraph_format.space_before = Pt(2)
            p_sig_img.paragraph_format.space_after = Pt(4 if has_following_sig else 10)
            img = DocxImage.from_file(str(signature_path))
            aspect = img.px_width / max(img.px_height, 1)
            target_h_cm = 1.45
            target_w_cm = target_h_cm * aspect
            p_sig_img.add_run().add_picture(str(signature_path), width=Cm(target_w_cm), height=Cm(target_h_cm))

    doc.save(str(out_docx))


def find_photo_path(repo_root: Path, mapping: dict) -> Path | None:
    custom = mapping.get("FOTO")
    if custom:
        candidate = Path(str(custom))
        if not candidate.is_absolute():
            candidate = repo_root / candidate
        if candidate.exists() and candidate.is_file():
            return candidate

    stammdaten_dir = repo_root / "stammdaten"
    for ext in ("jpg", "jpeg", "png", "webp"):
        for name in (f"bewerbungsfoto.{ext}", f"foto.{ext}"):
            candidate = stammdaten_dir / name
            if candidate.exists() and candidate.is_file():
                return candidate
    return None


def find_signature_path(repo_root: Path, mapping: dict) -> Path | None:
    custom = mapping.get("UNTERSCHRIFT")
    if custom:
        candidate = Path(str(custom))
        if not candidate.is_absolute():
            candidate = repo_root / candidate
        if candidate.exists() and candidate.is_file():
            return candidate

    stammdaten_dir = repo_root / "stammdaten"
    for ext in ("png", "jpg", "jpeg", "webp"):
        for name in (f"unterschrift.{ext}", f"signature.{ext}"):
            candidate = stammdaten_dir / name
            if candidate.exists() and candidate.is_file():
                return candidate
    return None


def add_page_number_fields(paragraph, font_size: float = 8.0, color: RGBColor = COLOR_LIGHT) -> None:
    def _add_field(field_name: str) -> None:
        r_begin = paragraph.add_run()
        r_begin.font.name = FONT_FAMILY
        r_begin.font.size = Pt(font_size)
        r_begin.font.color.rgb = color
        fld_begin = OxmlElement("w:fldChar")
        fld_begin.set(qn("w:fldCharType"), "begin")
        r_begin._r.append(fld_begin)

        r_instr = paragraph.add_run()
        r_instr.font.name = FONT_FAMILY
        r_instr.font.size = Pt(font_size)
        r_instr.font.color.rgb = color
        instr = OxmlElement("w:instrText")
        instr.set(qn("xml:space"), "preserve")
        instr.text = f" {field_name} "
        r_instr._r.append(instr)

        r_sep = paragraph.add_run()
        r_sep.font.name = FONT_FAMILY
        r_sep.font.size = Pt(font_size)
        r_sep.font.color.rgb = color
        fld_sep = OxmlElement("w:fldChar")
        fld_sep.set(qn("w:fldCharType"), "separate")
        r_sep._r.append(fld_sep)

        r_val = paragraph.add_run("1")
        r_val.font.name = FONT_FAMILY
        r_val.font.size = Pt(font_size)
        r_val.font.color.rgb = color

        r_end = paragraph.add_run()
        r_end.font.name = FONT_FAMILY
        r_end.font.size = Pt(font_size)
        r_end.font.color.rgb = color
        fld_end = OxmlElement("w:fldChar")
        fld_end.set(qn("w:fldCharType"), "end")
        r_end._r.append(fld_end)

    r_prefix = paragraph.add_run("Seite ")
    r_prefix.font.name = FONT_FAMILY
    r_prefix.font.size = Pt(font_size)
    r_prefix.font.color.rgb = color
    _add_field("PAGE")
    r_mid = paragraph.add_run(" von ")
    r_mid.font.name = FONT_FAMILY
    r_mid.font.size = Pt(font_size)
    r_mid.font.color.rgb = color
    _add_field("NUMPAGES")


def find_anlagen_images(repo_root: Path) -> list[Path]:
    anlagen_dir = repo_root / "stammdaten" / "anlagen"
    if not anlagen_dir.exists():
        return []
    exts = {".jpg", ".jpeg", ".png", ".webp"}
    return sorted(
        p for p in anlagen_dir.iterdir() if p.is_file() and p.suffix.lower() in exts
    )


def render_anlagen_bundle(mapping: dict, image_paths: list[Path], out_docx: Path) -> None:
    doc = Document()
    configure_document(doc, top_cm=3.15, bottom_cm=1.6, left_cm=1.8, right_cm=1.8)
    section = doc.sections[0]
    section.header_distance = Cm(1.65)
    section.footer_distance = Cm(0.75)

    applicant_name = str(mapping.get("NAME", "")).strip()
    contact_parts = [
        str(mapping[k]).strip()
        for k in ("STRASSE", "PLZ_ORT", "TELEFON", "EMAIL")
        if mapping.get(k)
    ]
    header_meta = "  ·  ".join(([applicant_name] if applicant_name else []) + contact_parts)

    # 2-zeiliger Clean-Tech-Header gemaess Vorgabe:
    # Zeile 1: 'Anlagen' (16.5 pt fett Deep Navy)
    # Zeile 2: Name + vollstaendige Kontaktleiste einzeilig (8.3 pt) + Navy-Trennlinie
    header = section.header
    p_sub = header.paragraphs[0]
    p_sub.style = doc.styles["Normal"]
    p_sub.paragraph_format.space_before = Pt(0)
    p_sub.paragraph_format.space_after = Pt(2.5)
    r_sub = p_sub.add_run("Anlagen")
    r_sub.bold = True
    r_sub.font.name = FONT_FAMILY
    r_sub.font.size = Pt(16.5)
    r_sub.font.color.rgb = COLOR_ACCENT

    p_contact = header.add_paragraph()
    p_contact.style = doc.styles["Normal"]
    p_contact.paragraph_format.space_before = Pt(0)
    p_contact.paragraph_format.space_after = Pt(0)
    r_contact = p_contact.add_run(header_meta)
    r_contact.font.name = FONT_FAMILY
    r_contact.font.size = Pt(8.3)
    r_contact.font.color.rgb = COLOR_MUTED
    set_bottom_border(p_contact, HEX_ACCENT, size_eighths=10, space=4)

    # Dezente Fusszeile mit konsistenter Seitennummerierung
    add_subtle_footer(
        doc,
        f"{applicant_name}  ·  Bewerbungsanlagen" if applicant_name else "Bewerbungsanlagen",
    )

    max_w_cm = 16.5
    max_h_cm = 23.1

    for idx, img_path in enumerate(image_paths):
        p = doc.add_paragraph()
        p.alignment = WD_ALIGN_PARAGRAPH.CENTER
        p.paragraph_format.space_before = Pt(2)
        p.paragraph_format.space_after = Pt(0)

        img = DocxImage.from_file(str(img_path))
        aspect = img.px_height / max(img.px_width, 1)
        target_w_cm = max_w_cm
        target_h_cm = target_w_cm * aspect
        if target_h_cm > max_h_cm:
            target_h_cm = max_h_cm
            target_w_cm = target_h_cm / aspect

        p.add_run().add_picture(str(img_path), width=Cm(target_w_cm), height=Cm(target_h_cm))

        if idx < len(image_paths) - 1:
            doc.add_page_break()

    doc.save(str(out_docx))


def run_ats_check(pdf_path: Path, doc_name: str, md_text: str) -> list[str]:
    """Prueft das erzeugte PDF auf ATS-Konformitaet, ohne Klardaten auszugeben."""
    warnings: list[str] = []
    try:
        import pymupdf  # type: ignore
    except Exception:
        return ["pymupdf nicht verfuegbar – erweiterter PDF-ATS-Check uebersprungen."]

    try:
        doc = pymupdf.open(pdf_path)
        full_text = "\n".join(page.get_text("text") for page in doc)
    except Exception as exc:
        return [f"PDF-Textextraktion fehlgeschlagen: {exc}"]

    if len(full_text.strip()) < 100:
        warnings.append("Kein ausreichender durchsuchbarer Textlayer im PDF erkannt.")
    if "\ufffd" in full_text:
        warnings.append("Fehlerhafte Zeichenkodierung (U+FFFD) im PDF-Rohtext gefunden.")
    if re.search(r"\{\{[A-Z0-9_]+\}\}", full_text):
        warnings.append("Nicht ersetzter Platzhalter ({{...}}) im PDF gefunden.")

    if doc_name == "lebenslauf.md":
        upper_lines = [ln.strip() for ln in full_text.splitlines() if ln.strip().isupper()]
        expected = ["KURZPROFIL", "BERUFSERFAHRUNG", "AUSBILDUNG", "KENNTNISSE"]
        positions = []
        for key in expected:
            idx = next((i for i, ln in enumerate(upper_lines) if key in ln), -1)
            if idx == -1:
                warnings.append(f"Sektionsueberschrift '{key}' nicht im ATS-Rohtext gefunden.")
            positions.append(idx)
        valid_pos = [p for p in positions if p >= 0]
        if valid_pos != sorted(valid_pos):
            warnings.append("Logische Lesereihenfolge der Lebenslauf-Sektionen gestört.")

        mm_yyyy = re.findall(r"\b\d{2}/\d{4}\b", full_text)
        if len(mm_yyyy) < 2:
            warnings.append("Zu wenige Datumsangaben im ATS-Standardformat MM/JJJJ gefunden.")

        if "|" in md_text and re.search(r"^\|.+\|$", md_text, re.MULTILINE):
            warnings.append("Markdown-Tabelle im Lebenslauf erkannt (nicht ATS-sicher).")

    if doc_name == "anschreiben.md":
        cliches = [
            "hiermit bewerbe ich mich",
            "mit großem interesse",
            "leidenschaftlich",
            "teamplayer",
            "dynamisches umfeld",
        ]
        lower_text = full_text.lower()
        for phrase in cliches:
            if phrase in lower_text:
                warnings.append(f"KI-/Floskel-Begriff im Anschreiben erkannt: '{phrase}'.")

    return warnings


def run_design_consistency_check(out_dir: Path) -> list[str]:
    """Vergleicht Schriftarten, Kopfzeilen-Groessen/-Abstaende und Trennlinien ueber alle PDFs hinweg."""
    try:
        import pymupdf  # type: ignore
    except Exception:
        return []

    targets = ["anschreiben.pdf", "lebenslauf.pdf", "anlagenverzeichnis.pdf", "anlagen.pdf"]
    metrics: dict[str, dict] = {}

    for fname in targets:
        fpath = out_dir / fname
        if not fpath.exists():
            continue
        doc = pymupdf.open(fpath)
        page = doc[0]
        fonts = set()
        spans = []
        for blk in page.get_text("dict")["blocks"]:
            if blk["type"] != 0:
                continue
            for ln in blk["lines"]:
                for sp in ln["spans"]:
                    if sp["text"].strip():
                        fonts.add(sp["font"].split(",")[0])
                        spans.append((round(sp["bbox"][1], 1), round(sp["size"], 1), f"#{sp['color']:06X}"))
        drawings = page.get_drawings()
        accent_line = drawings[0]["rect"] if drawings else None
        top_span = min(spans, key=lambda s: s[0]) if spans else None
        metrics[fname] = {
            "fonts": sorted(fonts),
            "h1_y": top_span[0] if top_span else None,
            "h1_size": top_span[1] if top_span else None,
            "h1_color": top_span[2] if top_span else None,
            "contact_size": next((s[1] for s in spans if s[2] == "#475569"), None),
            "line_x0": round(accent_line.x0, 1) if accent_line else None,
            "line_x1": round(accent_line.x1, 1) if accent_line else None,
        }

    notes: list[str] = []
    all_fonts = {f for m in metrics.values() for f in m["fonts"]}
    if len(all_fonts) > 1:
        notes.append(f"Mehrere Schriftfamilien erkannt: {', '.join(sorted(all_fonts))}")

    h1_sizes = {k: m["h1_size"] for k, m in metrics.items() if m["h1_size"] is not None}
    if len(set(h1_sizes.values())) > 1:
        detail = ", ".join(f"{k}: {v} pt" for k, v in h1_sizes.items())
        notes.append(f"Unterschiedliche Kopfzeilen-Titelgroessen ({detail})")

    h1_colors = {k: m["h1_color"] for k, m in metrics.items() if m["h1_color"] is not None}
    if len(set(h1_colors.values())) > 1:
        detail = ", ".join(f"{k}: {v}" for k, v in h1_colors.items())
        notes.append(f"Unterschiedliche Kopfzeilen-Titelfarben ({detail})")

    contact_sizes = {k: m["contact_size"] for k, m in metrics.items() if m["contact_size"] is not None}
    if len(set(contact_sizes.values())) > 1:
        detail = ", ".join(f"{k}: {v} pt" for k, v in contact_sizes.items())
        notes.append(f"Unterschiedliche Kontaktzeilen-Schriftgroessen ({detail})")

    h1_ys = {k: m["h1_y"] for k, m in metrics.items() if m["h1_y"] is not None}
    if len(h1_ys) > 1 and (max(h1_ys.values()) - min(h1_ys.values()) > 5.0):
        detail = ", ".join(f"{k}: y={v} pt" for k, v in h1_ys.items())
        notes.append(f"Abweichende vertikale Kopfzeilen-Position ({detail})")

    return notes


def count_pdf_pages(pdf_path: Path) -> int | None:
    try:
        raw = pdf_path.read_bytes()
        matches = re.findall(rb"/Type\s*/Page(?!s)\b", raw)
        return len(matches) if matches else None
    except Exception:
        return None


def convert_to_pdf(docx_path: Path, out_dir: Path) -> Path | None:
    pdf_path = out_dir / f"{docx_path.stem}.pdf"

    soffice = shutil.which("soffice")
    if soffice:
        try:
            subprocess.run(
                [soffice, "--headless", "--convert-to", "pdf", "--outdir", str(out_dir), str(docx_path)],
                check=True,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            print(f"PDF erstellt (LibreOffice): {pdf_path}")
            return pdf_path
        except Exception:
            pass

    try:
        from docx2pdf import convert  # type: ignore
        convert(str(docx_path), str(pdf_path))
        print(f"PDF erstellt (Word/docx2pdf): {pdf_path}")
        return pdf_path
    except Exception:
        pass

    print(
        f"Hinweis: Weder LibreOffice noch docx2pdf/Word verfuegbar – PDF fuer {docx_path.name} uebersprungen."
    )
    return None


def build(target_dir: Path) -> None:
    repo_root = Path(__file__).resolve().parent.parent
    mapping = load_placeholders(repo_root)
    photo_path = find_photo_path(repo_root, mapping)
    signature_path = find_signature_path(repo_root, mapping)
    out_dir = target_dir / "output"
    out_dir.mkdir(parents=True, exist_ok=True)

    for name in ["anschreiben.md", "lebenslauf.md", "anlagenverzeichnis.md"]:
        src = target_dir / name
        if not src.exists():
            continue
        raw = src.read_text(encoding="utf-8")
        merged = replace_placeholders(raw, mapping)
        out_docx = out_dir / f"{src.stem}.docx"

        if name == "anschreiben.md":
            render_anschreiben(merged, out_docx, signature_path=signature_path)
        elif name == "lebenslauf.md":
            render_cv_or_anlagen(merged, out_docx, photo_path=photo_path)
        elif name == "anlagenverzeichnis.md":
            applicant_name = str(mapping.get("NAME", "")).strip()
            lbl = f"{applicant_name}  ·  Anlagenverzeichnis" if applicant_name else "Anlagenverzeichnis"
            render_cv_or_anlagen(merged, out_docx, footer_label=lbl)
        else:
            render_cv_or_anlagen(merged, out_docx)

        print(f"DOCX erstellt: {out_docx}")
        pdf_path = convert_to_pdf(out_docx, out_dir)
        if pdf_path and pdf_path.exists():
            pages = count_pdf_pages(pdf_path)
            if pages is not None:
                print(f"Seitenanzahl ({pdf_path.name}): {pages}")
                if name in {"anschreiben.md", "lebenslauf.md"} and pages > 1:
                    print(f"WARNUNG: {pdf_path.name} ueberschreitet die 1-Seiten-Grenze ({pages} Seiten)!")
            if name in {"anschreiben.md", "lebenslauf.md"}:
                ats_warnings = run_ats_check(pdf_path, name, merged)
                if ats_warnings:
                    for w in ats_warnings:
                        print(f"ATS-WARNUNG ({pdf_path.name}): {w}")
                else:
                    print(f"ATS-Check ({pdf_path.name}): OK")

    anlagen_images = find_anlagen_images(repo_root)
    if anlagen_images:
        out_anlagen_docx = out_dir / "anlagen.docx"
        render_anlagen_bundle(mapping, anlagen_images, out_anlagen_docx)
        print(f"DOCX erstellt: {out_anlagen_docx}")
        anlagen_pdf = convert_to_pdf(out_anlagen_docx, out_dir)
        if anlagen_pdf and anlagen_pdf.exists():
            pages = count_pdf_pages(anlagen_pdf)
            if pages is not None:
                print(f"Seitenanzahl ({anlagen_pdf.name}): {pages}")

    design_notes = run_design_consistency_check(out_dir)
    if design_notes:
        print("Design-Einheitlichkeits-Check (Hinweise):")
        for note in design_notes:
            print(f"  - {note}")
    else:
        print("Design-Einheitlichkeits-Check: OK")

    try:
        from version_backup import create_backup

        snap = create_backup(repo_root, reason=f"Build {target_dir.name}")
        if snap:
            print(f"Backup & Version erstellt: {snap['version']} ({snap['folder']})")
    except Exception as exc:
        print(f"Hinweis: Automatisches Backup uebersprungen ({exc})")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Verwendung: python scripts/build_bewerbung.py bewerbungen/JJJJ-MM_Firma")
        sys.exit(1)
    build(Path(sys.argv[1]).resolve())
