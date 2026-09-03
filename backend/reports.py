"""Real PDF report generation via ReportLab, built only from data actually
retrieved from the database — no field in any report is invented. Language is
kept to observation/candidate/anomaly terms throughout, never a certification
or diagnosis claim (see SECURITY.md / project safety-language rule).
"""
from __future__ import annotations

import time
from pathlib import Path

from reportlab.lib import colors
from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import inch
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

STYLES = getSampleStyleSheet()
TITLE_STYLE = ParagraphStyle("ReportTitle", parent=STYLES["Title"], fontSize=16)
HEADING_STYLE = ParagraphStyle("ReportHeading", parent=STYLES["Heading2"], spaceBefore=14)
NOTE_STYLE = ParagraphStyle("ReportNote", parent=STYLES["Italic"], textColor=colors.grey, fontSize=8)
BODY_STYLE = STYLES["BodyText"]

REPORTS_DIR = Path("data/reports")
REPORTS_DIR.mkdir(parents=True, exist_ok=True)

LIMITATIONS_NOTE = (
    "This report presents observations and measurements produced by the AERION-X "
    "engineering intelligence pipeline. It does not constitute an airworthiness "
    "certification, a maintenance authorization, or a confirmed defect finding. "
    "All flagged regions/anomalies/events require independent engineering review."
)


def _table(data: list[list[str]], col_widths=None) -> Table:
    t = Table(data, colWidths=col_widths)
    t.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#1a2029")),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("FONTSIZE", (0, 0), (-1, -1), 8),
        ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#cccccc")),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#f5f5f5")]),
    ]))
    return t


def _footer(story: list) -> None:
    story.append(Spacer(1, 20))
    story.append(Paragraph(LIMITATIONS_NOTE, NOTE_STYLE))
    story.append(Paragraph(f"Generated {time.strftime('%Y-%m-%d %H:%M:%S UTC', time.gmtime())} by AERION-X",
                            NOTE_STYLE))


def generate_inspection_report_pdf(inspection: dict, asset: dict | None, out_path: str | None = None) -> str:
    out_path = out_path or str(REPORTS_DIR / f"inspection_{inspection['inspection_id']}.pdf")
    doc = SimpleDocTemplate(out_path, pagesize=letter)
    story = [Paragraph("AERION-X — Inspection Report", TITLE_STYLE), Spacer(1, 10)]

    meta = [
        ["Inspection ID", inspection["inspection_id"]],
        ["Asset", f"{asset['name']} ({asset['asset_id']})" if asset else inspection["asset_id"]],
        ["Timestamp", time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(inspection["timestamp"]))],
        ["Change score", f"{inspection['change_score']:.4f}"],
        ["Mean SSIM", f"{inspection['mean_ssim']:.4f}"],
        ["Regions found", str(len(inspection["anomaly_regions"]))],
    ]
    story.append(_table(meta, col_widths=[1.8 * inch, 4 * inch]))

    story.append(Paragraph("Detected Regions (visual change candidates)", HEADING_STYLE))
    if inspection["anomaly_regions"]:
        region_rows = [["#", "Label", "BBox", "Area (px)"]]
        for i, r in enumerate(inspection["anomaly_regions"]):
            region_rows.append([str(i + 1), r["label"], str(r["bbox"]), str(r["area_px"])])
        story.append(_table(region_rows, col_widths=[0.4 * inch, 2 * inch, 2.4 * inch, 1 * inch]))
    else:
        story.append(Paragraph("No regions above the area threshold were found.", BODY_STYLE))

    story.append(Paragraph("Method", HEADING_STYLE))
    story.append(Paragraph(inspection["notes"], BODY_STYLE))

    _footer(story)
    doc.build(story)
    return out_path


def generate_event_report_pdf(events: list[dict], title: str = "Event/Incident Report", out_path: str | None = None) -> str:
    out_path = out_path or str(REPORTS_DIR / f"events_{int(time.time())}.pdf")
    doc = SimpleDocTemplate(out_path, pagesize=letter)
    story = [Paragraph(f"AERION-X — {title}", TITLE_STYLE), Spacer(1, 10),
             Paragraph(f"{len(events)} event(s)", BODY_STYLE), Spacer(1, 8)]

    if events:
        rows = [["Time", "Type", "Severity", "Tracks", "Zone", "Provenance"]]
        for e in events:
            rows.append([f"{e['timestamp']:.2f}s", e["event_type"], e["severity"],
                         str(e["track_ids"]), e["zone_id"] or "--", e["provenance"]])
        story.append(_table(rows, col_widths=[0.7 * inch, 1.6 * inch, 0.8 * inch, 1 * inch, 0.9 * inch, 1 * inch]))
    else:
        story.append(Paragraph("No events matched the report criteria.", BODY_STYLE))

    _footer(story)
    doc.build(story)
    return out_path


def generate_sensor_report_pdf(stream: dict, readings: list[dict], anomalies: list[dict], out_path: str | None = None) -> str:
    out_path = out_path or str(REPORTS_DIR / f"sensor_{stream['stream_id'].replace(':', '_')}.pdf")
    doc = SimpleDocTemplate(out_path, pagesize=letter)
    story = [Paragraph("AERION-X — Sensor/Anomaly Report", TITLE_STYLE), Spacer(1, 10)]

    values = [r["value"] for r in readings]
    meta = [
        ["Stream", stream["stream_id"]],
        ["Signal", f"{stream['signal_name']} ({stream['unit']})"],
        ["Provenance", stream["provenance"]],
        ["Samples", str(len(readings))],
        ["Min / Max", f"{min(values):.3f} / {max(values):.3f}" if values else "--"],
        ["Mean", f"{sum(values)/len(values):.3f}" if values else "--"],
        ["Anomalies detected", str(len(anomalies))],
    ]
    story.append(_table(meta, col_widths=[1.8 * inch, 4 * inch]))

    story.append(Paragraph("Anomalies", HEADING_STYLE))
    if anomalies:
        rows = [["Time", "Value", "Score", "Threshold", "Algorithm", "Reason"]]
        for a in anomalies:
            rows.append([f"{a['timestamp']:.2f}", f"{a['value']:.3f}", f"{a['score']:.2f}",
                         f"{a['threshold']:.2f}", a["algorithm"], a["reason"][:60]])
        story.append(_table(rows, col_widths=[0.6 * inch, 0.7 * inch, 0.6 * inch, 0.7 * inch, 1 * inch, 2 * inch]))
    else:
        story.append(Paragraph("No anomalies detected in this stream.", BODY_STYLE))

    _footer(story)
    doc.build(story)
    return out_path


def generate_asset_history_report_pdf(graph: dict, out_path: str | None = None) -> str:
    asset = graph["asset"]
    out_path = out_path or str(REPORTS_DIR / f"asset_{asset['asset_id']}.pdf")
    doc = SimpleDocTemplate(out_path, pagesize=letter)
    story = [Paragraph("AERION-X — Asset History Report", TITLE_STYLE), Spacer(1, 10)]

    meta = [["Asset ID", asset["asset_id"]], ["Type", asset["asset_type"]], ["Name", asset["name"]],
            ["Sensor streams", str(len(graph["sensor_streams"]))], ["Inspections", str(len(graph["inspections"]))],
            ["Events", str(len(graph["events"]))], ["Anomalies", str(len(graph["anomalies"]))]]
    story.append(_table(meta, col_widths=[1.8 * inch, 4 * inch]))

    story.append(Paragraph("Inspection History", HEADING_STYLE))
    if graph["inspections"]:
        rows = [["Time", "Change score", "Mean SSIM", "Regions"]]
        for insp in graph["inspections"]:
            rows.append([time.strftime("%Y-%m-%d %H:%M", time.localtime(insp["timestamp"])),
                         f"{insp['change_score']:.4f}", f"{insp['mean_ssim']:.4f}", str(len(insp["anomaly_regions"]))])
        story.append(_table(rows, col_widths=[1.6 * inch, 1.3 * inch, 1.3 * inch, 1 * inch]))
    else:
        story.append(Paragraph("No inspections recorded for this asset.", BODY_STYLE))

    story.append(Paragraph("Event History (most recent)", HEADING_STYLE))
    if graph["events"]:
        rows = [["Time", "Type", "Severity"]]
        for e in graph["events"][:25]:
            rows.append([f"{e['timestamp']:.2f}s", e["event_type"], e["severity"]])
        story.append(_table(rows, col_widths=[1 * inch, 2 * inch, 1 * inch]))
    else:
        story.append(Paragraph("No events recorded for this asset.", BODY_STYLE))

    _footer(story)
    doc.build(story)
    return out_path
