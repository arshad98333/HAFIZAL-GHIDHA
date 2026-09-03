"""Branded PDF export -- ``POST /export/decision-trace.pdf``.

One endpoint shared by the Ask page and the LiveOps page: both post the
same generic ``DecisionTraceExportRequest`` shape (title, optional
jurisdiction/product, free-form meta lines, the reasoning steps already
shown on screen, the final answer, and the citation-fidelity eval), and get
back the same branded, uniformly-formatted PDF regardless of which feature
produced it. See ``cold_chain/api/pdf_export.py`` for the template itself
and why it is intentionally one shared function, not two.

No K2 call happens here and nothing is persisted -- this is a pure
render-what-you-already-have step, so it needs no Mongo/K2 dependency and
cannot itself be rate-limited by K2's low RPM ceiling.
"""

from __future__ import annotations

from fastapi import APIRouter
from starlette.responses import Response

from cold_chain.api.pdf_export import DecisionStep, DecisionTraceDocument, render_decision_trace_pdf
from cold_chain.api.schemas import DecisionTraceExportRequest

router = APIRouter(prefix="/export", tags=["export"])


@router.post("/decision-trace.pdf")
def export_decision_trace_pdf(req: DecisionTraceExportRequest) -> Response:
    doc = DecisionTraceDocument(
        kind=req.kind,
        title=req.title,
        jurisdiction=req.jurisdiction,
        product=req.product,
        meta_lines=list(req.meta_lines),
        steps=[DecisionStep(title=s.title, output=s.output) for s in req.steps],
        final_answer=req.final_answer,
        citation_eval=req.citation_eval,
    )
    pdf_bytes = render_decision_trace_pdf(doc)
    filename = f"gcc-coldchain-{req.kind}-decision-trace.pdf"
    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
