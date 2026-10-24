"""FastAPI application. Run: uvicorn service.api:app  (or --factory service.api:create_app)."""
from __future__ import annotations

import asyncio
import base64
import logging
import os
import time
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

import numpy as np
from fastapi import Depends, FastAPI, Header, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from .cases import CaseStore, FraudCase
from .config import ServiceConfig, load_config
from .consent import ConsentRecord, get_consent, save_consent
from .engine import CallEngine, Conflict, NotFound
from .enrol import EnrolmentStore
from .evidence import EvidenceLog, iso, verify_chain
from .models import (AppResponseIn, AppResult, AudioChunkIn, CallView, CaseActionIn,
                     ChallengeAnswerIn, StartCallRequest, ThresholdProposalIn,
                     ThresholdProposalView, TranscriptIn)
from .push import generate_prompt_token, verify_prompt_token
from .retention import RetentionManager
from .roles import (PermissionDenied, Principal, Proposal, ProposalError, Role,
                    ThresholdChangeManager, authorize)
from .scorers import ASR, MockASR, MockSpeakerScorer, MockSpoofScorer, SpeakerScorer, SpoofScorer

DEFAULT_EVIDENCE_PATH = "data/evidence.jsonl"
log = logging.getLogger(__name__)


def _proposal_view(p: Proposal) -> ThresholdProposalView:
    return ThresholdProposalView(
        proposal_id=p.proposal_id,
        layer=p.layer,
        weak=p.weak,
        strong=p.strong,
        reason=p.reason,
        proposed_by=p.proposed_by,
        approvers=list(p.approvers),
        status=p.status,
    )


def current_principal(
    x_user: Optional[str] = Header(default=None),
    x_role: Optional[str] = Header(default=None),
) -> Principal:
    if not x_user or not x_role:
        raise HTTPException(401, "X-User and X-Role headers are required")
    try:
        return Principal(x_user, Role(x_role))
    except ValueError:
        raise HTTPException(401, "unknown role")


class EnrolRequest(BaseModel):
    customer_id: str
    embedding: List[float] = Field(default_factory=list)
    model_version: str = "speechbrain-ecapa-tdnn-v1"
    sample_count: int = 3


class CaseNoteIn(BaseModel):
    note: str


class CaseResolutionIn(BaseModel):
    resolution: str  # CONFIRM_FRAUD, DISMISS
    reason: str = ""


class PromptRespondIn(BaseModel):
    action: str  # CONFIRM, DENY, REPORT


def _l2_from_env() -> Optional[SpoofScorer]:
    """Opt-in real L2: ASLI_L2_MODEL names a TorchScript model. Unset means mocks.

    A set but unusable path fails at startup rather than falling back to the mock.
    ASLI_L2_BACKEND=live selects the numpy-only live detector (ml/live_detector) instead.
    """
    if os.environ.get("ASLI_L2_BACKEND", "").lower() == "live":
        from .live_scorer import LiveDetectorSpoofScorer  # lazy: numpy only

        live = LiveDetectorSpoofScorer(model_path=os.environ.get("ASLI_L2_LIVE_MODEL"))
        try:
            live.load()  # fail fast, never fall back to the mock
        except Exception as exc:
            raise RuntimeError(f"ASLI_L2_BACKEND=live could not load the detector: {exc}") from exc
        return live
    path = os.environ.get("ASLI_L2_MODEL")
    if not path:
        return None
    if not os.path.isfile(path):
        raise RuntimeError(f"ASLI_L2_MODEL does not point to a file: {path}")
    from .scorers import AasistSpoofScorer  # lazy: torch is only needed when opted in

    scorer = AasistSpoofScorer(
        path,
        device=os.environ.get("ASLI_L2_DEVICE", "cpu"),
        model_version=f"aasist-ts:{os.path.basename(path)}",
    )
    try:
        scorer.load()  # fail fast on a bad or unloadable model
    except Exception as exc:
        raise RuntimeError(f"ASLI_L2_MODEL could not be loaded ({path}): {exc}") from exc
    return scorer


def _warn_if_uncalibrated_l2(cfg: ServiceConfig) -> None:
    """A real L2 model with placeholder Platt/thresholds gives meaningless probabilities."""
    real_l2 = os.environ.get("ASLI_L2_MODEL") or os.environ.get("ASLI_L2_BACKEND", "").lower() == "live"
    if real_l2 and cfg.layers["l2"].placeholder:
        log.warning("A real L2 (ASLI_L2_MODEL or ASLI_L2_BACKEND=live) is set but the l2 config layer is still a PLACEHOLDER (uncalibrated). "
                    "Pass config_path=service/config.calibrated.json to create_app.")


def create_app(
    config: Optional[ServiceConfig] = None,
    config_path: Optional[str] = None,
    evidence_path: Optional[str] = None,
    l1: Optional[SpeakerScorer] = None,
    l2: Optional[SpoofScorer] = None,
    asr: Optional[ASR] = None,
    clock: Callable[[], float] = time.time,
) -> FastAPI:
    cfg = config or load_config(config_path)
    _warn_if_uncalibrated_l2(cfg)
    evidence = EvidenceLog(evidence_path or os.environ.get("ASLI_EVIDENCE_LOG", DEFAULT_EVIDENCE_PATH))

    subscribers: Dict[str, List[Any]] = {}  # call_id -> [(loop, queue)]

    def notify(view: CallView) -> None:
        for loop, q in list(subscribers.get(view.call_id, [])):
            try:
                loop.call_soon_threadsafe(q.put_nowait, view.model_dump(mode="json"))
            except RuntimeError:
                pass

    engine = CallEngine(
        cfg,
        evidence,
        l1 or MockSpeakerScorer(),
        l2 or _l2_from_env() or MockSpoofScorer(),
        asr or MockASR(),
        clock=clock,
        notify=notify,
    )

    def on_threshold_event(event: str, p: Proposal) -> None:
        evidence.append(
            None,
            event,
            {
                "proposal_id": p.proposal_id,
                "layer": p.layer,
                "weak": p.weak,
                "strong": p.strong,
                "reason": p.reason,
                "proposed_by": p.proposed_by,
                "approvers": list(p.approvers),
            },
            clock(),
        )

    thresholds = ThresholdChangeManager(engine.apply_thresholds, on_threshold_event)
    enrolments = EnrolmentStore()
    retention_mgr = RetentionManager()

    @asynccontextmanager
    async def lifespan(_app: FastAPI):
        async def sweeper() -> None:
            while True:
                await asyncio.sleep(0.25)
                await run_in_threadpool(engine.sweep_deadlines)

        task = asyncio.create_task(sweeper())
        try:
            yield
        finally:
            task.cancel()

    app = FastAPI(title="Asli Awaaz call-security service", version="0.1.0", lifespan=lifespan)
    app.state.engine, app.state.evidence, app.state.thresholds = engine, evidence, thresholds

    # Mount UI static files if directory exists
    ui_dir = Path("ui")
    if ui_dir.exists():
        app.mount("/ui", StaticFiles(directory="ui", html=True), name="ui")

    # Mount hold audio clips directory for analyst playback
    clips_dir = Path("data/hold_clips")
    clips_dir.mkdir(parents=True, exist_ok=True)
    app.mount("/data/hold_clips", StaticFiles(directory=str(clips_dir)), name="hold_clips")

    @app.get("/", include_in_schema=False)
    async def _root_redirect():
        return RedirectResponse(url="/ui/")

    @app.exception_handler(NotFound)
    async def _nf(_r, exc):
        return JSONResponse({"detail": "not found"}, status_code=404)

    @app.exception_handler(Conflict)
    async def _cf(_r, exc):
        return JSONResponse({"detail": str(exc)}, status_code=409)

    @app.exception_handler(PermissionDenied)
    async def _pd(_r, exc):
        return JSONResponse({"detail": str(exc)}, status_code=403)

    @app.exception_handler(ProposalError)
    async def _pe(_r, exc):
        return JSONResponse({"detail": str(exc)}, status_code=409)

    # ------------------------------------------------------------- call flow
    @app.post("/calls", response_model=CallView, status_code=201)
    def start_call(req: StartCallRequest):
        return engine.start_call(req)

    @app.post("/calls/{call_id}/audio", response_model=CallView)
    def audio_chunk(call_id: str, body: AudioChunkIn):
        return engine.add_audio(call_id, body.pcm(), body.sample_rate)

    @app.post("/calls/{call_id}/transcript", response_model=CallView)
    def transcript(call_id: str, body: TranscriptIn):
        return engine.add_transcript(call_id, body.text)

    @app.post("/calls/{call_id}/challenge/answer", response_model=CallView)
    def challenge_answer(call_id: str, body: ChallengeAnswerIn):
        pcm = body.pcm() if body.pcm_b64 is not None else None
        return engine.answer_challenge(call_id, text=body.text, pcm=pcm, sample_rate=body.sample_rate)

    @app.post("/calls/{call_id}/app-response", response_model=CallView)
    def app_response(call_id: str, body: AppResponseIn):
        return engine.app_response(call_id, body.result)

    @app.get("/calls/{call_id}", response_model=CallView)
    def get_call(call_id: str):
        return engine.view(call_id)

    # ----------------------------------------------------------- app push & prompt
    @app.post("/calls/{call_id}/push-prompt")
    def create_push_prompt(call_id: str, who: Principal = Depends(current_principal)):
        authorize(who, Role.AGENT, Role.ANALYST)
        s = engine._get(call_id)
        token = generate_prompt_token(
            call_id=s.call_id,
            customer_id=s.customer_id,
            request_type=s.request_type.value,
            ttl_seconds=30.0,
        )
        return {"call_id": call_id, "token": token, "prompt_url": f"/ui/app/index.html?token={token}"}

    @app.get("/app/prompt/{token}")
    def get_prompt_data(token: str):
        try:
            return verify_prompt_token(token, current_time=clock())
        except ValueError as exc:
            raise HTTPException(400, str(exc))

    @app.post("/app/prompt/{token}/respond")
    def submit_prompt_response(token: str, body: PromptRespondIn):
        try:
            data = verify_prompt_token(token, current_time=clock())
        except ValueError as exc:
            raise HTTPException(400, str(exc))
        call_id = data["call_id"]
        res_map = {
            "CONFIRM": AppResult.APPROVE,
            "DENY": AppResult.DENY,
            "REPORT": AppResult.DENY,
        }
        res = res_map.get(body.action.upper(), AppResult.DENY)
        return engine.app_response(call_id, res)

    # ----------------------------------------------------------- analyst side
    @app.get("/cases")
    def list_cases(status: Optional[str] = None, who: Principal = Depends(current_principal)):
        authorize(who, Role.ANALYST, Role.FRAUD_HEAD)
        return engine.cases.list_cases(status)

    @app.post("/cases/{case_id}/assign")
    def assign_case(case_id: str, who: Principal = Depends(current_principal)):
        authorize(who, Role.ANALYST)
        c = engine.cases.assign(case_id, who.user)
        if not c:
            raise HTTPException(404, "case not found")
        return c

    @app.post("/cases/{case_id}/notes")
    def add_case_note(case_id: str, body: CaseNoteIn, who: Principal = Depends(current_principal)):
        authorize(who, Role.ANALYST)
        c = engine.cases.add_note(case_id, who.user, body.note)
        if not c:
            raise HTTPException(404, "case not found")
        return c

    @app.post("/cases/{case_id}/action")
    def resolve_case(case_id: str, body: CaseResolutionIn, who: Principal = Depends(current_principal)):
        authorize(who, Role.ANALYST)
        c = engine.cases.resolve(case_id, body.resolution, body.reason)
        if not c:
            raise HTTPException(404, "case not found")
        return c

    @app.post("/cases/{case_id}/release", response_model=CallView)
    def release(case_id: str, body: CaseActionIn = CaseActionIn(), who: Principal = Depends(current_principal)):
        return engine.release(case_id, who, body.note)

    @app.post("/cases/{case_id}/escalate", response_model=CallView)
    def escalate(case_id: str, body: CaseActionIn = CaseActionIn(), who: Principal = Depends(current_principal)):
        return engine.escalate(case_id, who, body.note)

    @app.get("/cases/{case_id}")
    def case_detail(case_id: str, who: Principal = Depends(current_principal)):
        authorize(who, Role.ANALYST, Role.FRAUD_HEAD)
        return engine.evidence_snapshot(case_id)

    @app.get("/reviews")
    def review_queue(who: Principal = Depends(current_principal)):
        authorize(who, Role.ANALYST, Role.FRAUD_HEAD)
        return engine.review_queue()

    @app.get("/audit/verify")
    def audit_verify(who: Principal = Depends(current_principal)):
        authorize(who, Role.ANALYST, Role.FRAUD_HEAD)
        r = verify_chain(evidence.path)
        return {
            "ok": r.ok,
            "records": r.records,
            "head_hash": r.head_hash,
            "bad_seq": r.bad_seq,
            "reason": r.reason,
        }

    # ----------------------------------------------------------- enrolment & consent
    @app.post("/consent")
    def record_consent(record: ConsentRecord):
        save_consent(record)
        return {"status": "saved", "speaker_id": record.speaker_id}

    @app.get("/consent/{speaker_id}")
    def get_speaker_consent(speaker_id: str):
        c = get_consent(speaker_id)
        if not c:
            raise HTTPException(404, "consent record not found")
        return c

    @app.post("/enrol")
    def enrol_customer(body: EnrolRequest):
        try:
            vec = np.array(body.embedding if body.embedding else [0.1] * 192, dtype=np.float32)
            rec = enrolments.enrol(body.customer_id, vec, body.model_version, body.sample_count)
            return {"status": "enrolled", "customer_id": rec.customer_id, "model_version": rec.model_version}
        except PermissionError as exc:
            raise HTTPException(403, str(exc))

    @app.delete("/enrol/{customer_id}")
    def withdraw_enrolment(customer_id: str):
        ok = enrolments.withdraw(customer_id)
        if not ok:
            raise HTTPException(404, "customer not enrolled")
        return {"status": "withdrawn", "customer_id": customer_id}

    @app.post("/retention/cleanup")
    def retention_cleanup(who: Principal = Depends(current_principal)):
        authorize(who, Role.FRAUD_HEAD)
        return retention_mgr.purge_expired(current_time=clock())

    # ------------------------------------------------------ threshold control
    @app.get("/config/thresholds")
    def get_thresholds(who: Principal = Depends(current_principal)):
        authorize(who, Role.ANALYST, Role.FRAUD_HEAD)
        return {
            "config_version": cfg.version,
            "placeholder": cfg.placeholder,
            "thresholds": {k: {"weak": t.weak, "strong": t.strong} for k, t in engine.thresholds.items()},
            "proposals": [_proposal_view(p) for p in thresholds.all()],
        }

    @app.post("/config/thresholds", response_model=ThresholdProposalView, status_code=201)
    def propose_threshold(body: ThresholdProposalIn, who: Principal = Depends(current_principal)):
        return _proposal_view(thresholds.propose(who, body.layer, body.weak, body.strong, body.reason))

    @app.post("/config/thresholds/{proposal_id}/approve", response_model=ThresholdProposalView)
    def approve_threshold(proposal_id: str, who: Principal = Depends(current_principal)):
        return _proposal_view(thresholds.approve(who, proposal_id))

    # --------------------------------------------------------------- websocket
    @app.websocket("/ws/agent/{call_id}")
    async def agent_ws(ws: WebSocket, call_id: str):
        q: asyncio.Queue = asyncio.Queue()
        entry = (asyncio.get_running_loop(), q)
        subscribers.setdefault(call_id, []).append(entry)
        try:
            try:
                current = await run_in_threadpool(engine.view, call_id)
            except NotFound:
                await ws.close(code=4404)
                return
            await ws.accept()
            await ws.send_json(current.model_dump(mode="json"))
            last_seq = current.seq
            while True:
                msg = await q.get()
                if msg.get("seq", 0) <= last_seq:
                    continue
                last_seq = msg["seq"]
                await ws.send_json(msg)
        except WebSocketDisconnect:
            pass
        finally:
            subs = subscribers.get(call_id, [])
            if entry in subs:
                subs.remove(entry)
            if not subs:
                subscribers.pop(call_id, None)

    @app.websocket("/ws/calls/{call_id}/stream")
    async def call_audio_stream(ws: WebSocket, call_id: str):
        await ws.accept()
        try:
            while True:
                data = await ws.receive_bytes()
                # Process audio chunk
                view = await run_in_threadpool(engine.add_audio, call_id, data, 16000)
                await ws.send_json(view.model_dump(mode="json"))
        except WebSocketDisconnect:
            pass

    return app


app = create_app()
