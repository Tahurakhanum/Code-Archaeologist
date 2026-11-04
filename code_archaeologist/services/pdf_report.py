"""Generate a concise, evidence-based PDF report in memory.

Charts are drawn with ReportLab's own graphics module, so no extra plotting
library is needed. All text from the repository is XML-escaped before it is
placed in a Paragraph.
"""
from io import BytesIO
from xml.sax.saxutils import escape as _xml_escape

from reportlab.graphics.charts.barcharts import HorizontalBarChart, VerticalBarChart
from reportlab.graphics.charts.linecharts import HorizontalLineChart
from reportlab.graphics.shapes import Drawing, String
from reportlab.lib import colors
from reportlab.lib.enums import TA_LEFT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import cm
from reportlab.platypus import KeepTogether, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

INK = colors.HexColor("#17233b")
ACCENT = colors.HexColor("#6558e8")
MUTED = colors.HexColor("#667085")
GRID = colors.HexColor("#dfe3eb")
CONTENT_WIDTH = A4[0] - 3.2 * cm  # page width minus left and right margins

_styles = getSampleStyleSheet()
TITLE = ParagraphStyle("ReportTitle", parent=_styles["Title"], fontName="Helvetica-Bold", fontSize=23, textColor=INK, alignment=TA_LEFT, spaceAfter=7)
HEADING = ParagraphStyle("SectionHeading", parent=_styles["Heading2"], fontName="Helvetica-Bold", fontSize=14, textColor=INK, spaceBefore=14, spaceAfter=8)
SUBHEADING = ParagraphStyle("SubHeading", parent=_styles["Heading4"], fontName="Helvetica-Bold", fontSize=10.5, textColor=INK, spaceBefore=8, spaceAfter=4)
BODY = ParagraphStyle("ReportBody", parent=_styles["BodyText"], fontSize=9.5, leading=14, textColor=colors.HexColor("#344054"))
MUTED_TEXT = ParagraphStyle("Muted", parent=BODY, textColor=MUTED, fontSize=8.5)
BULLET = ParagraphStyle("Bullet", parent=BODY, leftIndent=12, bulletIndent=2, spaceAfter=2)


def build_pdf_report(analysis, result: dict, notes: list | None = None) -> BytesIO:
    buffer = BytesIO()
    document = SimpleDocTemplate(buffer, pagesize=A4, leftMargin=1.6 * cm, rightMargin=1.6 * cm, topMargin=1.8 * cm, bottomMargin=1.6 * cm,
                                 title=f"Code Archaeologist report: {analysis['repository_name']}", author="Code Archaeologist")
    story = [Paragraph("Code Archaeologist", _styles["Heading3"]),
             Paragraph(f"Repository Analysis: {escape(analysis['repository_name'])}", TITLE),
             Paragraph(f"Generated from saved analysis data. Source: {escape(analysis['source_type'])}. Created: {escape(analysis['created_at'])} UTC.", MUTED_TEXT),
             Spacer(1, 10)]

    story += [Paragraph("Repository overview", HEADING), _table([
        ["Total files", str(result.get("total_files", 0))], ["Source files", str(result.get("source_files", 0))],
        ["Analyzed commits", str(result.get("total_commits", 0))],
        ["Contributors", str(result.get("total_contributors", len(result.get("contributors", []))))],
        ["Detected functions/classes/components", str(len(result.get("entities", [])))],
    ])]
    story += [Paragraph("Codebase structure", HEADING), Paragraph(_file_type_summary(result.get("file_types", [])), BODY)]

    # Charts (only when Git history is available)
    activity = result.get("commit_activity")
    if activity:
        story.append(KeepTogether([Paragraph(f"Commit activity (per {escape(activity['granularity'])})", SUBHEADING),
                                   _line_chart(activity["labels"], activity["counts"])]))
    contributors = result.get("contributors", [])
    if contributors:
        story.append(KeepTogether([Paragraph("Commits per contributor", SUBHEADING),
                                   _vertical_bars([c["name"] for c in contributors[:8]], [c["commits"] for c in contributors[:8]])]))
    files = result.get("frequently_modified_files", [])
    if files:
        story.append(KeepTogether([Paragraph("Most frequently modified files", SUBHEADING),
                                   _horizontal_bars([_short_path(f["path"]) for f in files[:8]], [f["changes"] for f in files[:8]])]))

    story += [Paragraph("Contributor analysis", HEADING),
              Paragraph("Commit counts show authorship of changes, not effort, expertise, or ownership.", MUTED_TEXT),
              _table([["Contributor", "Commits"]] + [[item["name"], str(item["commits"])] for item in contributors] or [["No Git contributor data available", ""]], header=True)]
    areas = result.get("developer_areas", [])
    if areas:
        story += [Paragraph("Who worked on which part", SUBHEADING),
                  _table([["Contributor", "Files", "Example areas"]] + [[d["name"], str(d["file_count"]), ", ".join(d["files"][:6])] for d in areas[:8]], header=True, wide=True)]
    story += [Paragraph("Frequently modified files", HEADING),
              _table([["File", "Observed changes"]] + [[item["path"], str(item["changes"])] for item in files] or [["No Git change data available", ""]], header=True)]

    story += [Paragraph("Maintenance signals", HEADING),
              Paragraph("The following are investigation signals, not confirmed bugs, ownership claims, or measures of contributor effort.", MUTED_TEXT)]
    risks = result.get("risks", [])
    if risks:
        story.append(_table([["File", "Signal", "Evidence"]] + [[risk["file"], risk["reason"], risk["evidence"]] for risk in risks], header=True, wide=True))
    else:
        story.append(Paragraph("No maintenance signals were recorded from the available evidence.", BODY))

    connected = sorted((e for e in result.get("entities", []) if e.get("called_by")), key=lambda e: len(e["called_by"]), reverse=True)[:8]
    if connected:
        story += [Paragraph("Most-connected code", HEADING),
                  Paragraph("Functions, components, and classes referenced by the most other detected code (name-based matches). Changes here may have wide impact.", MUTED_TEXT),
                  _table([["Code", "Kind", "Location", "Used by"]] + [[e.get("display_name", e["name"]), e["kind"], f"{e['path']}:{e['start_line']}", str(len(e["called_by"]))] for e in connected], header=True, wide=True)]

    story += [Paragraph("Recent code evolution", HEADING)]
    recent = result.get("recent_commits", [])
    if recent:
        story.append(_table([["Commit", "Message", "Author", "Time"]] + [[item["hash"], item["message"], item["author"], item["timestamp"]] for item in recent[:8]], header=True, wide=True))
    else:
        story.append(Paragraph(escape(result.get("history_note", "No commit history was available.")), BODY))

    if notes:
        story += [Paragraph("Investigation answers", HEADING),
                  Paragraph(f"The {len(notes)} most recent saved question(s). Verified facts and hypotheses are kept separate.", MUTED_TEXT)]
        for note in notes:
            story += _note_flowables(note)

    story += [Paragraph("Recommendations", HEADING)]
    story += [Paragraph(escape(text), BULLET, bulletText="•") for text in _recommendations(result, connected)]
    document.build(story, onFirstPage=_footer, onLaterPages=_footer)
    buffer.seek(0)
    return buffer


def escape(text) -> str:
    """XML-escape text for a Paragraph and drop characters the built-in PDF fonts cannot draw (e.g. emoji)."""
    return _xml_escape(str(text).encode("cp1252", errors="ignore").decode("cp1252"))


def _axis_font(axis) -> None:
    axis.labels.fontName = "Helvetica"


# --- Sections ----------------------------------------------------------------------------
def _note_flowables(note: dict) -> list:
    answer = note["answer"]
    parts = [Paragraph(f"Q: {escape(note['question'])}", SUBHEADING),
             Paragraph(f"{escape(note['entity_label'] or '')} · {escape(note['created_at'])} UTC · {'AI-generated' if answer.get('mode') == 'ai' else 'rule-based'}", MUTED_TEXT)]
    if answer.get("mode") == "ai" and answer.get("text"):
        parts.append(Paragraph(escape(answer["text"]).replace("\n", "<br/>"), BODY))
    else:
        for label, items in (("Verified facts", answer.get("facts", [])), ("Hypotheses", answer.get("hypotheses", []))):
            if items:
                parts.append(Paragraph(f"<b>{label}</b>", BODY))
                parts += [Paragraph(escape(item), BULLET, bulletText="•") for item in items[:8]]
    evidence = answer.get("evidence", [])[:5]
    if evidence:
        parts.append(Paragraph("<b>Evidence:</b> " + "; ".join(escape(f"{e['label']} ({e['detail']})") for e in evidence), MUTED_TEXT))
    return [KeepTogether(parts[:4]), *parts[4:], Spacer(1, 6)]


def _recommendations(result: dict, connected: list) -> list[str]:
    tips = []
    risks = result.get("risks", [])
    if risks:
        tips.append(f"Start with {risks[0]['file']} ({risks[0]['reason'].lower()}): review its recent diffs and make sure it has tests.")
    if any(r["reason"] == "Knowledge concentration" for r in risks):
        tips.append("Some files were only changed by one person; pair reviews or documentation can spread that knowledge.")
    if connected:
        tips.append(f"{connected[0].get('display_name', connected[0]['name'])} is referenced by {len(connected[0]['called_by'])} other parts; changes to it deserve extra testing.")
    if not result.get("total_commits"):
        tips.append("This analysis had no Git history. Analyze the GitHub repository (or a ZIP that includes .git) to see contributors and change hotspots.")
    tips.append("Treat every signal here as a prompt for further review, not a final conclusion.")
    return tips


def _file_type_summary(file_types: list) -> str:
    if not file_types:
        return "No source files were recorded."
    return "Most common file types: " + ", ".join(f"{escape(extension)} ({count})" for extension, count in file_types) + "."


# --- Charts ------------------------------------------------------------------------------
def _line_chart(labels: list[str], values: list[int]) -> Drawing:
    drawing = Drawing(CONTENT_WIDTH, 150)
    chart = HorizontalLineChart()
    chart.x, chart.y, chart.width, chart.height = 30, 28, CONTENT_WIDTH - 45, 112
    chart.data = [values]
    step = max(1, len(labels) // 8)  # show about 8 date labels so they do not overlap
    chart.categoryAxis.categoryNames = [label if index % step == 0 else "" for index, label in enumerate(labels)]
    chart.categoryAxis.labels.fontSize = 6.5
    chart.categoryAxis.labels.boxAnchor = "n"
    chart.valueAxis.valueMin = 0
    chart.valueAxis.valueMax = max(max(values), 1)
    chart.valueAxis.valueStep = max(1, round(chart.valueAxis.valueMax / 4))
    chart.valueAxis.labels.fontSize = 7
    chart.valueAxis.visibleGrid, chart.valueAxis.gridStrokeColor = True, GRID
    chart.lines[0].strokeColor, chart.lines[0].strokeWidth = ACCENT, 1.6
    _axis_font(chart.categoryAxis), _axis_font(chart.valueAxis)
    drawing.add(chart)
    return drawing


def _vertical_bars(labels: list[str], values: list[int]) -> Drawing:
    drawing = Drawing(CONTENT_WIDTH, 160)
    chart = VerticalBarChart()
    chart.x, chart.y, chart.width, chart.height = 30, 40, CONTENT_WIDTH - 45, 110
    chart.data = [values]
    chart.categoryAxis.categoryNames = [_clip(label, 16) for label in labels]
    chart.categoryAxis.labels.fontSize = 7
    chart.categoryAxis.labels.angle, chart.categoryAxis.labels.boxAnchor, chart.categoryAxis.labels.dy = 20, "ne", -2
    _value_axis(chart, values)
    chart.bars[0].fillColor, chart.bars[0].strokeColor = ACCENT, None
    drawing.add(chart)
    return drawing


def _horizontal_bars(labels: list[str], values: list[int]) -> Drawing:
    height = 24 + 18 * len(values)
    drawing = Drawing(CONTENT_WIDTH, height)
    chart = HorizontalBarChart()
    chart.x, chart.y, chart.width, chart.height = 170, 14, CONTENT_WIDTH - 190, height - 22
    chart.data = [list(reversed(values))]  # largest at the top
    chart.categoryAxis.categoryNames = list(reversed(labels))
    chart.categoryAxis.labels.fontSize, chart.categoryAxis.labels.boxAnchor = 7, "e"
    _value_axis(chart, values)
    chart.bars[0].fillColor, chart.bars[0].strokeColor = ACCENT, None
    drawing.add(chart)
    if not values:
        drawing.add(String(10, 10, "No data", fontSize=8))
    return drawing


def _value_axis(chart, values: list[int]) -> None:
    _axis_font(chart.categoryAxis), _axis_font(chart.valueAxis)
    chart.valueAxis.valueMin = 0
    chart.valueAxis.valueMax = max(max(values or [1]), 1)
    chart.valueAxis.valueStep = max(1, round(chart.valueAxis.valueMax / 4))
    chart.valueAxis.labels.fontSize = 7
    chart.valueAxis.visibleGrid, chart.valueAxis.gridStrokeColor = True, GRID


def _short_path(path: str) -> str:
    parts = path.split("/")
    return _clip("…/" + "/".join(parts[-2:]) if len(parts) > 2 else path, 34)


def _clip(text: str, limit: int) -> str:
    return text if len(text) <= limit else text[:limit - 1] + "…"


# --- Tables and page decoration ----------------------------------------------------------
def _table(rows: list[list[str]], header: bool = False, wide: bool = False):
    cell_style = ParagraphStyle("TableCell", parent=_styles["BodyText"], fontName="Helvetica", fontSize=8, leading=10, textColor=INK)
    header_style = ParagraphStyle("TableHeader", parent=cell_style, fontName="Helvetica-Bold", textColor=colors.white)
    safe_rows = [[Paragraph(escape(str(cell)).replace("\n", "<br/>"), header_style if header and row_index == 0 else cell_style)
                  for cell in row] for row_index, row in enumerate(rows)]
    widths = ([4.0 * cm, 3.0 * cm, 8.0 * cm] if wide and len(rows[0]) == 3 else [2.0 * cm, 5.0 * cm, 3.0 * cm, 5.0 * cm] if wide else None)
    if wide and len(rows[0]) == 4 and rows[0][0] == "Code":
        widths = [4.5 * cm, 2.3 * cm, 7.0 * cm, 1.8 * cm]
    table = Table(safe_rows, colWidths=widths, repeatRows=1 if header else 0, hAlign="LEFT")
    commands = [("GRID", (0, 0), (-1, -1), 0.25, GRID), ("VALIGN", (0, 0), (-1, -1), "TOP"), ("FONTNAME", (0, 0), (-1, -1), "Helvetica"),
                ("FONTSIZE", (0, 0), (-1, -1), 8), ("LEFTPADDING", (0, 0), (-1, -1), 6), ("RIGHTPADDING", (0, 0), (-1, -1), 6),
                ("TOPPADDING", (0, 0), (-1, -1), 5), ("BOTTOMPADDING", (0, 0), (-1, -1), 5)]
    if header:
        commands += [("BACKGROUND", (0, 0), (-1, 0), INK), ("TEXTCOLOR", (0, 0), (-1, 0), colors.white), ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold")]
    table.setStyle(TableStyle(commands))
    return table


def _footer(canvas, document):
    canvas.saveState()
    canvas.setFont("Helvetica", 8)
    canvas.setFillColorRGB(0.4, 0.44, 0.5)
    canvas.drawString(46, 25, "Code Archaeologist - Evidence-based repository report")
    canvas.drawRightString(canvas._pagesize[0] - 46, 25, f"Page {document.page}")
    canvas.restoreState()
