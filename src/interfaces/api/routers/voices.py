"""Clone Voice — create a custom AI voice from a recorded or uploaded sample.

The sample arrives as multipart (rather than the presigned-upload dance the
document pipeline uses) because it is small, single-shot, and the server needs
the bytes in hand anyway to forward them to the cloning provider.

Duration is reported by the client, which is the only party that can measure it
cheaply — decoding webm/opus server-side would mean adding ffmpeg to the image.
It is therefore treated as untrusted: the value is range-checked, and a
byte-size floor catches a caller that claims 30 seconds and sends 2KB.
"""

from __future__ import annotations

import contextlib
import uuid

from fastapi import APIRouter, File, Form, HTTPException, Response, UploadFile

from src.config.settings import get_settings
from src.domain.voice.entities import (
    ALL_GENDERS,
    SUPPORTED_LANGUAGES,
    VoiceProfile,
)
from src.interfaces.api.deps import AdminPrincipalDep, ContainerDep, PrincipalDep
from src.interfaces.api.schemas import (
    SpeakRequest,
    TranscriptionResponse,
    TranscriptionStatusResponse,
    VoiceOptionsResponse,
    VoiceProfileResponse,
)

router = APIRouter(prefix="/voices", tags=["voices"])

# Opus at the lowest realistic bitrate is roughly 6 KB/s. Anything below this
# per claimed second means the duration was overstated.
_MIN_BYTES_PER_SECOND = 1500

_GENDER_LABELS = {"female": "Female", "male": "Male", "neutral": "Neutral"}


def _to_response(profile: VoiceProfile) -> VoiceProfileResponse:
    return VoiceProfileResponse(
        id=profile.id,
        name=profile.name,
        gender=profile.gender,  # type: ignore[arg-type]
        language=profile.language,
        description=profile.description,
        duration_seconds=profile.duration_seconds,
        sample_bytes=profile.sample_bytes,
        provider=profile.provider,
        status=profile.status,  # type: ignore[arg-type]
        error=profile.error,
        created_at=profile.created_at,
    )


@router.get("/options", response_model=VoiceOptionsResponse)
async def voice_options(principal: PrincipalDep, container: ContainerDep) -> VoiceOptionsResponse:
    """Form contents plus whether cloning is actually available, so the page can
    warn up front instead of failing on submit."""
    settings = get_settings()
    return VoiceOptionsResponse(
        languages=[{"value": code, "label": label} for code, label in SUPPORTED_LANGUAGES],
        genders=[{"value": g, "label": _GENDER_LABELS[g]} for g in ALL_GENDERS],
        min_seconds=settings.voice_sample_min_seconds,
        max_seconds=settings.voice_sample_max_seconds,
        max_mb=settings.voice_sample_max_mb,
        cloning_enabled=container.voice_cloner.enabled,
        provider=container.voice_cloner.provider,
    )


@router.get("", response_model=list[VoiceProfileResponse])
async def list_voices(
    principal: PrincipalDep, container: ContainerDep
) -> list[VoiceProfileResponse]:
    async with container.unit_of_work() as uow:
        uow.set_tenant_scope(principal.tenant_id)
        profiles = await uow.voice_profiles.list_for_tenant(principal.tenant_id)
    return [_to_response(p) for p in profiles]


@router.post("", response_model=VoiceProfileResponse, status_code=201)
async def create_voice(
    principal: AdminPrincipalDep,
    container: ContainerDep,
    sample: UploadFile = File(...),
    name: str = Form(...),
    gender: str = Form("female"),
    language: str = Form("en"),
    description: str = Form(""),
    duration_seconds: float = Form(...),
) -> VoiceProfileResponse:
    settings = get_settings()
    audio = await sample.read()

    max_bytes = settings.voice_sample_max_mb * 1024 * 1024
    if len(audio) > max_bytes:
        raise HTTPException(
            status_code=413,
            detail=f"The sample must be {settings.voice_sample_max_mb} MB or smaller.",
        )
    if not audio:
        raise HTTPException(status_code=400, detail="The audio sample is empty.")

    profile = VoiceProfile(
        tenant_id=principal.tenant_id,
        name=name,
        gender=gender,  # type: ignore[arg-type]
        language=language,
        description=description,
        sample_content_type=(sample.content_type or "").split(";")[0].strip(),
        sample_bytes=len(audio),
        duration_seconds=duration_seconds,
    ).normalized()

    error = profile.validation_error(
        min_seconds=settings.voice_sample_min_seconds,
        max_seconds=settings.voice_sample_max_seconds,
    )
    if error is not None:
        raise HTTPException(status_code=400, detail=error)

    # Cross-check the client's claim against the bytes it actually sent.
    if len(audio) < duration_seconds * _MIN_BYTES_PER_SECOND:
        raise HTTPException(
            status_code=400,
            detail="That recording is shorter than reported. Please record again.",
        )

    profile.sample_storage_key = (
        f"voices/{principal.tenant_id}/{profile.id}{_extension(profile.sample_content_type)}"
    )
    await container.storage.put_bytes(
        profile.sample_storage_key, audio, profile.sample_content_type or "audio/webm"
    )

    # Clone before the first save so the row lands in its true state, rather
    # than appearing "pending" and needing a second write on the happy path.
    if container.voice_cloner.enabled:
        ok, voice_id, clone_error = await container.voice_cloner.clone(
            name=profile.name,
            audio=audio,
            content_type=profile.sample_content_type or "audio/webm",
            filename=f"{profile.id}{_extension(profile.sample_content_type)}",
            description=profile.description,
        )
        if ok:
            profile.mark_ready(container.voice_cloner.provider, voice_id)
        else:
            profile.mark_failed(clone_error)
    else:
        profile.mark_failed(
            "Voice cloning isn't configured on this server. The sample is saved — "
            "add ELEVENLABS_API_KEY and use Retry to finish."
        )

    async with container.unit_of_work() as uow:
        uow.set_tenant_scope(principal.tenant_id)
        await uow.voice_profiles.add(profile)
        await uow.commit()
    return _to_response(profile)


@router.post("/{voice_id}/retry", response_model=VoiceProfileResponse)
async def retry_clone(
    voice_id: uuid.UUID, principal: AdminPrincipalDep, container: ContainerDep
) -> VoiceProfileResponse:
    """Re-send a stored sample to the provider.

    This is why the sample is kept in object storage: a clone that failed
    because the provider was down (or unconfigured) is recoverable without
    asking the user to record themselves again.
    """
    async with container.unit_of_work() as uow:
        uow.set_tenant_scope(principal.tenant_id)
        profile = await uow.voice_profiles.get(principal.tenant_id, voice_id)
    if profile is None:
        raise HTTPException(status_code=404, detail="Voice not found")
    if not container.voice_cloner.enabled:
        raise HTTPException(
            status_code=400,
            detail="Voice cloning isn't configured on this server (ELEVENLABS_API_KEY).",
        )
    if not profile.sample_storage_key:
        raise HTTPException(status_code=400, detail="This voice has no stored sample to retry.")

    try:
        audio = await container.storage.get_bytes(profile.sample_storage_key)
    except Exception as exc:  # noqa: BLE001 — storage miss must not 500 the page
        raise HTTPException(
            status_code=404, detail=f"The stored sample could not be read: {exc}"
        ) from exc

    ok, provider_voice_id, error = await container.voice_cloner.clone(
        name=profile.name,
        audio=audio,
        content_type=profile.sample_content_type or "audio/webm",
        filename=f"{profile.id}{_extension(profile.sample_content_type)}",
        description=profile.description,
    )
    if ok:
        profile.mark_ready(container.voice_cloner.provider, provider_voice_id)
    else:
        profile.mark_failed(error)

    async with container.unit_of_work() as uow:
        uow.set_tenant_scope(principal.tenant_id)
        await uow.voice_profiles.update(profile)
        await uow.commit()
    return _to_response(profile)


@router.post("/{voice_id}/speak")
async def speak(
    voice_id: uuid.UUID,
    body: SpeakRequest,
    principal: PrincipalDep,
    container: ContainerDep,
) -> Response:
    """Render text in a cloned voice, returning audio the browser can play.

    Used both by the preview button and by the voice-call panel when an
    assistant has a cloned voice assigned.
    """
    async with container.unit_of_work() as uow:
        uow.set_tenant_scope(principal.tenant_id)
        profile = await uow.voice_profiles.get(principal.tenant_id, voice_id)
    if profile is None:
        raise HTTPException(status_code=404, detail="Voice not found")
    if not profile.is_usable():
        raise HTTPException(
            status_code=400,
            detail=profile.error or "This voice isn't ready yet.",
        )

    ok, audio, error = await container.voice_cloner.synthesize(
        profile.provider_voice_id, body.text
    )
    if not ok:
        raise HTTPException(status_code=502, detail=error)
    return Response(
        content=audio,
        media_type="audio/mpeg",
        # Same text in the same voice always renders the same; let the browser
        # skip a paid round-trip when a line repeats.
        headers={"Cache-Control": "private, max-age=3600"},
    )


@router.get("/{voice_id}/sample")
async def get_sample(
    voice_id: uuid.UUID, principal: PrincipalDep, container: ContainerDep
) -> Response:
    """Play back the original recording — how a user checks what they uploaded."""
    async with container.unit_of_work() as uow:
        uow.set_tenant_scope(principal.tenant_id)
        profile = await uow.voice_profiles.get(principal.tenant_id, voice_id)
    if profile is None or not profile.sample_storage_key:
        raise HTTPException(status_code=404, detail="No sample stored for this voice")
    try:
        audio = await container.storage.get_bytes(profile.sample_storage_key)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=404, detail="The stored sample is missing.") from exc
    return Response(content=audio, media_type=profile.sample_content_type or "audio/webm")


@router.delete("/{voice_id}", status_code=204)
async def delete_voice(
    voice_id: uuid.UUID, principal: AdminPrincipalDep, container: ContainerDep
) -> None:
    """Remove the voice, its stored sample, and its vendor-side copy.

    Assistants using it fall back to the browser's default voice (the FK is
    ON DELETE SET NULL) rather than breaking.
    """
    async with container.unit_of_work() as uow:
        uow.set_tenant_scope(principal.tenant_id)
        profile = await uow.voice_profiles.get(principal.tenant_id, voice_id)
        if profile is None:
            return
        await uow.voice_profiles.delete(principal.tenant_id, voice_id)
        await uow.commit()

    # Best-effort external cleanup, after the row is gone: a vendor or storage
    # error must not leave the user unable to delete their own recording.
    await container.voice_cloner.delete(profile.provider_voice_id)
    if profile.sample_storage_key:
        # An orphaned object costs pennies; a delete the user can't complete
        # costs them their own recording.
        with contextlib.suppress(Exception):
            await container.storage.delete(profile.sample_storage_key)


def _extension(content_type: str) -> str:
    return {
        "audio/webm": ".webm",
        "audio/ogg": ".ogg",
        "audio/mpeg": ".mp3",
        "audio/mp3": ".mp3",
        "audio/mp4": ".m4a",
        "audio/m4a": ".m4a",
        "audio/x-m4a": ".m4a",
        "audio/wav": ".wav",
        "audio/x-wav": ".wav",
        "audio/wave": ".wav",
        "audio/flac": ".flac",
    }.get(content_type, ".webm")


# --- Dictation -------------------------------------------------------------
#
# Speak instead of type, on any text field in the console. Lives on this router
# because it is the same capability the rest of the file is about — a
# microphone pointed at a provider — and because a caller already holding a
# voice token should not need to discover a second prefix for it.
#
# Registered *after* /{voice_id} routes with a literal two-segment path, so the
# uuid-typed parameter routes cannot shadow it.


@router.get("/transcribe/status", response_model=TranscriptionStatusResponse)
async def transcription_status(
    principal: PrincipalDep, container: ContainerDep
) -> TranscriptionStatusResponse:
    """What the mic button needs to decide its path before it is pressed.

    Without this the button would have to record first and discover only on
    upload that the server cannot transcribe — having already taken the
    microphone and thrown away what the user said.
    """
    t = container.transcriber
    return TranscriptionStatusResponse(
        enabled=t.enabled,
        provider=t.provider,
        model=t.model,
        max_seconds=get_settings().stt_max_seconds,
    )


@router.post("/transcribe", response_model=TranscriptionResponse)
async def transcribe(
    principal: PrincipalDep,
    container: ContainerDep,
    audio: UploadFile = File(...),
    language: str = Form(""),
) -> TranscriptionResponse:
    """One recorded clip in, its text out.

    Not admin-gated: dictation is a typing aid, and every field it fills is one
    the caller can already write to by hand.

    Nothing is persisted. The clip exists for the duration of this request —
    it is a keystroke, not a document, and storing every half-spoken sentence
    someone dictated would be a liability with no reader.
    """
    settings = get_settings()
    if not container.transcriber.enabled:
        raise HTTPException(
            status_code=503,
            detail="Server dictation isn't configured on this server.",
        )

    clip = await audio.read()
    if not clip:
        raise HTTPException(status_code=400, detail="The recording is empty.")

    max_bytes = settings.stt_max_mb * 1024 * 1024
    if len(clip) > max_bytes:
        raise HTTPException(
            status_code=413,
            detail=f"That recording is larger than {settings.stt_max_mb} MB. "
            "Dictate in shorter passes.",
        )

    ok, text, error = await container.transcriber.transcribe(
        clip,
        content_type=(audio.content_type or "").split(";")[0].strip() or "audio/webm",
        filename=audio.filename or "dictation.webm",
        # Trimmed rather than validated against a list: Whisper takes any
        # ISO-639-1 code, and an unknown one is ignored by the provider.
        language=(language or "").strip()[:8],
    )
    if not ok:
        # 422, not 500: the request was well-formed and the failure is about
        # the audio or the vendor, which is what the message says.
        raise HTTPException(status_code=422, detail=error)

    return TranscriptionResponse(text=text, provider=container.transcriber.provider)
