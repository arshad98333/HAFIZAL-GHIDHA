"""Branded PDF export for decision traces (Ask + LiveOps).

One shared template, not two -- both ``/compliance/ask`` and
``/liveops/narrate`` decision traces (a 4-step or 3-step K2 reasoning chain,
grounded citations, a final answer) are structurally the same thing: a
question or scenario, a chain of reasoning steps, a final recommendation,
and a citation-fidelity verdict. Rendering them through one function is what
keeps the output "one uniform format every time" instead of two documents
that drift apart as each page evolves independently.

Uses ``reportlab`` (platypus/flowables), the standard choice for
programmatic PDF generation in Python -- justified body paragraphs,
Helvetica (a built-in PDF base-14 font, no font-embedding fragility) for a
clean, professional business-report look, and a repeated header/footer via
``BaseDocTemplate.build(..., onFirstPage=..., onLaterPages=...)`` so page 2+
of a long decision trace still carries the Arshadify branding and page
number.

Scope note: this report is always rendered in English, regardless of the
app's active UI language. GSO clause numbers and GCC-EDGE rule IDs in the
underlying data are English/Latin-script identifiers, and this repo has no
Arabic-shaping (``arabic-reshaper`` / ``python-bidi``) or bundled Unicode
Arabic font asset to render right-to-left text correctly in a PDF -- doing
that badly (mirrored/disconnected glyphs) would be worse than not doing it.
If Arabic PDF export is wanted later, that is a real added dependency +
font-asset decision, not a one-line change here.
"""

from __future__ import annotations

import io
from dataclasses import dataclass, field
from datetime import UTC, datetime

from reportlab.lib import colors
from reportlab.lib.enums import TA_JUSTIFY
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import BaseDocTemplate, Frame, PageTemplate, Paragraph, Spacer, Table, TableStyle

MAINTAINER_EMAIL = "arshad@arshadify.online"
BRAND_NAME = "Arshadify Consulting"
BRAND_NAVY = colors.HexColor("#0C447C")
BRAND_TEAL = colors.HexColor("#085041")
BRAND_GOLD = colors.HexColor("#C4A35A")
BRAND_SAND = colors.HexColor("#F5F0E8")

_PAGE_SIZE = A4
_MARGIN = 20 * mm


@dataclass
class DecisionStep:
    title: str
    output: str


@dataclass
class DecisionTraceDocument:
    """Everything the shared template needs to render one decision trace.
    ``kind`` picks the document subtitle ("Compliance Q&A" vs "LiveOps
    Truck Scenario"); everything else is generic."""

    kind: str  # "ask" | "liveops"
    title: str  # the question text, or a one-line scenario summary
    jurisdiction: str | None
    product: str | None
    meta_lines: list[str]  # extra officer-facing context (scenario facts, disclaimers, etc.)
    steps: list[DecisionStep]
    final_answer: str
    citation_eval: dict[str, object] | None
    generated_at: datetime = field(default_factory=lambda: datetime.now(UTC))


def _styles() -> dict[str, ParagraphStyle]:
    base = getSampleStyleSheet()
    styles: dict[str, ParagraphStyle] = {}
    styles["Body"] = ParagraphStyle(
        "Body",
        parent=base["Normal"],
        fontName="Helvetica",
        fontSize=10.2,
        leading=15,
        alignment=TA_JUSTIFY,
        spaceAfter=6,
        textColor=colors.HexColor("#1F2937"),
    )
    styles["Meta"] = ParagraphStyle(
        "Meta",
        parent=styles["Body"],
        fontSize=9,
        leading=13,
        textColor=colors.HexColor("#475569"),
        alignment=TA_JUSTIFY,
    )
    styles["H1"] = ParagraphStyle(
        "H1",
        parent=base["Heading1"],
        fontName="Helvetica-Bold",
        fontSize=15,
        leading=19,
        textColor=BRAND_NAVY,
        spaceAfter=4,
    )
    styles["H2"] = ParagraphStyle(
        "H2",
        parent=base["Heading2"],
        fontName="Helvetica-Bold",
        fontSize=11.5,
        leading=15,
        textColor=BRAND_NAVY,
        spaceBefore=12,
        spaceAfter=4,
    )
    styles["Disclaimer"] = ParagraphStyle(
        "Disclaimer",
        parent=styles["Body"],
        fontSize=8.3,
        leading=12,
        textColor=colors.HexColor("#64748B"),
        alignment=TA_JUSTIFY,
    )
    return styles


def _kind_subtitle(kind: str) -> str:
    return {
        "ask": "Compliance Q&A Decision Trace",
        "liveops": "LiveOps Truck Scenario Decision Trace",
    }.get(kind, "Decision Trace")


def _escape(text: str) -> str:
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def _paragraphs(text: str, style: ParagraphStyle) -> list[Paragraph]:
    """Splits on blank lines so multi-paragraph model output renders as
    separate justified paragraphs instead of one run-on block."""
    text = _escape(text or "").replace("\r\n", "\n")
    blocks = [b.strip() for b in text.split("\n\n") if b.strip()]
    if not blocks:
        blocks = ["(no content)"]
    return [Paragraph(b.replace("\n", "<br/>"), style) for b in blocks]


def _header_footer(canvas, doc, doc_data: DecisionTraceDocument) -> None:
    canvas.saveState()
    width, height = _PAGE_SIZE

    # Header band
    canvas.setFillColor(BRAND_NAVY)
    canvas.rect(0, height - 22 * mm, width, 22 * mm, stroke=0, fill=1)
    canvas.setFillColor(colors.white)
    canvas.setFont("Helvetica-Bold", 14)
    canvas.drawString(_MARGIN, height - 13 * mm, BRAND_NAME)
    canvas.setFont("Helvetica", 8.5)
    canvas.setFillColor(BRAND_GOLD)
    canvas.drawString(_MARGIN, height - 18.5 * mm, "GCC Cold-Chain Compliance AI · GSO-Aligned Decision Support")
    canvas.setFillColor(colors.white)
    canvas.setFont("Helvetica", 8.5)
    canvas.drawRightString(width - _MARGIN, height - 13 * mm, _kind_subtitle(doc_data.kind))
    canvas.drawRightString(
        width - _MARGIN,
        height - 18.5 * mm,
        doc_data.generated_at.strftime("%Y-%m-%d %H:%M UTC"),
    )

    # Footer band
    canvas.setStrokeColor(colors.HexColor("#E2E8F0"))
    canvas.line(_MARGIN, 14 * mm, width - _MARGIN, 14 * mm)
    canvas.setFont("Helvetica", 7.6)
    canvas.setFillColor(colors.HexColor("#64748B"))
    canvas.drawString(_MARGIN, 9.5 * mm, f"Maintainer: {MAINTAINER_EMAIL}")
    canvas.drawCentredString(
        width / 2,
        9.5 * mm,
        "Decision support only -- not legal advice. A licensed QA/compliance authority makes the final call.",
    )
    canvas.drawRightString(width - _MARGIN, 9.5 * mm, f"Page {doc.page}")
    canvas.restoreState()


def _citation_table(citation_eval: dict[str, object], styles: dict[str, ParagraphStyle]) -> Table:
    all_verified = bool(citation_eval.get("all_verified"))
    verified_rules = citation_eval.get("verified_rule_ids") or []
    unverified_rules = citation_eval.get("unverified_rule_ids") or []
    verified_gso = citation_eval.get("verified_gso_codes") or []
    unverified_gso = citation_eval.get("unverified_gso_codes") or []

    def joined(items) -> str:
        return ", ".join(str(i) for i in items) if items else "-- none --"

    rows = [
        [
            Paragraph("<b>Citation check</b>", styles["Body"]),
            Paragraph(
                "<b>PASS -- all citations grounded</b>"
                if all_verified
                else "<b>REVIEW -- unverified citations found</b>",
                styles["Body"],
            ),
        ],
        [Paragraph("Verified rule IDs", styles["Meta"]), Paragraph(_escape(joined(verified_rules)), styles["Meta"])],
        [
            Paragraph("Unverified rule IDs", styles["Meta"]),
            Paragraph(_escape(joined(unverified_rules)), styles["Meta"]),
        ],
        [
            Paragraph("Verified GSO clauses", styles["Meta"]),
            Paragraph(_escape(joined(f"GSO {g}" for g in verified_gso)), styles["Meta"]),
        ],
        [
            Paragraph("Unverified GSO clauses", styles["Meta"]),
            Paragraph(_escape(joined(f"GSO {g}" for g in unverified_gso)), styles["Meta"]),
        ],
    ]
    table = Table(rows, colWidths=[45 * mm, 115 * mm])
    table.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, 0), BRAND_SAND if all_verified else colors.HexColor("#FDF3E7")),
                ("BACKGROUND", (0, 1), (-1, -1), colors.white),
                ("BOX", (0, 0), (-1, -1), 0.6, colors.HexColor("#E2E8F0")),
                ("INNERGRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#EEF2F6")),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("SPAN", (0, 0), (1, 0)),
                ("LEFTPADDING", (0, 0), (-1, -1), 6),
                ("RIGHTPADDING", (0, 0), (-1, -1), 6),
                ("TOPPADDING", (0, 0), (-1, -1), 4),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
            ]
        )
    )
    return table


def render_decision_trace_pdf(doc_data: DecisionTraceDocument) -> bytes:
    """Renders one decision trace to PDF bytes, uniform format every time:
    branded header/footer on every page, justified Helvetica body text,
    the question/scenario, every reasoning step, the final answer boxed,
    and the citation-fidelity verdict as the last section."""
    styles = _styles()
    buf = io.BytesIO()

    frame = Frame(
        _MARGIN,
        16 * mm,
        _PAGE_SIZE[0] - 2 * _MARGIN,
        _PAGE_SIZE[1] - 16 * mm - 26 * mm,
        id="body",
    )

    doc = BaseDocTemplate(
        buf,
        pagesize=_PAGE_SIZE,
        leftMargin=_MARGIN,
        rightMargin=_MARGIN,
        topMargin=26 * mm,
        bottomMargin=16 * mm,
        title=f"{_kind_subtitle(doc_data.kind)} — {BRAND_NAME}",
        author=BRAND_NAME,
    )
    doc.addPageTemplates(
        [
            PageTemplate(
                id="trace",
                frames=[frame],
                onPage=lambda canvas, d: _header_footer(canvas, d, doc_data),
            )
        ]
    )

    story: list = []
    story.append(Paragraph(_escape(doc_data.title), styles["H1"]))

    meta_bits = []
    if doc_data.jurisdiction:
        meta_bits.append(f"Jurisdiction: {doc_data.jurisdiction}")
    if doc_data.product:
        meta_bits.append(f"Product: {doc_data.product}")
    if meta_bits:
        story.append(Paragraph(_escape(" · ".join(meta_bits)), styles["Meta"]))
    for line in doc_data.meta_lines:
        story.append(Paragraph(_escape(line), styles["Meta"]))
    story.append(Spacer(1, 6))

    for step in doc_data.steps:
        story.append(Paragraph(_escape(step.title), styles["H2"]))
        story.extend(_paragraphs(step.output, styles["Body"]))

    story.append(Paragraph("Final Recommendation", styles["H2"]))
    # Render the final answer as its own bordered block (single-cell table)
    # so it visually stands out from the step-by-step reasoning above it.
    final_para_flow = _paragraphs(doc_data.final_answer, styles["Body"])
    final_block = Table([[final_para_flow]], colWidths=[_PAGE_SIZE[0] - 2 * _MARGIN])
    final_block.setStyle(
        TableStyle(
            [
                ("BOX", (0, 0), (-1, -1), 0.8, BRAND_NAVY),
                ("BACKGROUND", (0, 0), (-1, -1), BRAND_SAND),
                ("LEFTPADDING", (0, 0), (-1, -1), 10),
                ("RIGHTPADDING", (0, 0), (-1, -1), 10),
                ("TOPPADDING", (0, 0), (-1, -1), 8),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 8),
            ]
        )
    )
    story.append(final_block)
    story.append(Spacer(1, 10))

    if doc_data.citation_eval is not None:
        story.append(Paragraph("Citation Fidelity Check", styles["H2"]))
        story.append(_citation_table(doc_data.citation_eval, styles))
        story.append(Spacer(1, 8))

    story.append(
        Paragraph(
            "Generated by the GCC Cold-Chain Compliance AI reasoning chain. Every rule ID and GSO clause cited above "
            "is cross-checked against this system's loaded guardrail pack and law citations; unverified citations "
            "are flagged, not silently trusted. This document is decision support for a food-safety compliance "
            "officer and does not replace review by a licensed QA/compliance authority.",
            styles["Disclaimer"],
        )
    )

    doc.build(story)
    return buf.getvalue()
