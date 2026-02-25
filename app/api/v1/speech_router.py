from fastapi import APIRouter, Depends, HTTPException, status, UploadFile, File, Form
from sqlalchemy.orm import Session
import httpx
from urllib.parse import urlparse
from app.api.v1.schemas import CloudinaryVoiceSearchRequest
from app.db.session import get_db
from app.modules.speech.huggingface_service import huggingface_speech_service
from app.modules.search.service import SearchService
from app.api.v1.router import verify_api_key
from app.core.exceptions import (
    SpeechToTextError,
    AudioProcessingError,
    UnsupportedAudioFormatError,
    AudioFileTooLargeError,
    SearchServiceException,
)
import logging

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/speech", tags=["Speech Search"])


@router.get("/model-info")
async def get_model_info(_: None = Depends(verify_api_key)):
    try:
        info = huggingface_speech_service.get_model_info()
        return info
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/transcribe")
async def transcribe_audio(
    audio: UploadFile = File(..., description="Audio file (WAV, MP3, FLAC, OGG, WEBM, M4A)"),
    language_code: str = Form(None, description="Language: en, es, fr, de, etc."),
    _: None = Depends(verify_api_key),
):
    try:
        audio_data = await audio.read()

        if not audio_data:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Empty audio file"
            )

        logger.info(f"Received audio: {audio.filename} ({len(audio_data)} bytes)")

        transcript = huggingface_speech_service.transcribe_audio(
            audio_data=audio_data,
            filename=audio.filename or "audio.mp3",
            language_code=language_code
        )

        if not transcript:
            return {
                "transcript": "",
                "message": "No speech detected",
                "suggestion": "Try speaking more clearly or checking your microphone"
            }

        return {
            "transcript": transcript,
            "language": language_code or "auto-detected",
            "model": huggingface_speech_service.model_name,
            "message": "Transcription successful (100% free)",
            "next_step": "Use this text with /search/rag endpoint"
        }

    except AudioFileTooLargeError as e:
        raise HTTPException(status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, detail=str(e))

    except UnsupportedAudioFormatError as e:
        raise HTTPException(status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE, detail=str(e))

    except (SpeechToTextError, AudioProcessingError) as e:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"Speech processing error: {str(e)}"
        )

    except Exception as e:
        logger.error(f"Transcription error: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Transcription failed"
        )


@router.post("/voice-search")
async def voice_search(
    audio: UploadFile = File(..., description="Audio file with search query"),
    org_id: str = Form(None, description="Organization ID filter"),
    language_code: str = Form(None, description="Language code (auto-detect if not specified)"),
    _: None = Depends(verify_api_key),
    db: Session = Depends(get_db),
):
    try:
        audio_data = await audio.read()

        if not audio_data:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Empty audio file"
            )

        logger.info(f"Voice search - processing: {audio.filename}")

        transcript = huggingface_speech_service.transcribe_audio(
            audio_data=audio_data,
            filename=audio.filename or "audio.mp3",
            language_code=language_code
        )

        if not transcript:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="No speech detected. Please try again."
            )

        logger.info(f"Voice search - transcript: '{transcript}'")

        result = SearchService.rag_search(db, transcript, org_id=org_id)

        return {
            "transcript": transcript,
            "query": transcript,
            "answer": result["answer"],
            "sources": result["sources"],
            "metadata": {
                "model": huggingface_speech_service.model_name,
                "language": language_code or "auto-detected",
                "org_id": org_id,
                "cost": "FREE"
            }
        }

    except AudioFileTooLargeError as e:
        raise HTTPException(status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, detail=str(e))

    except UnsupportedAudioFormatError as e:
        raise HTTPException(status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE, detail=str(e))

    except (SpeechToTextError, AudioProcessingError) as e:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"Speech error: {str(e)}"
        )

    except SearchServiceException as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Search error: {str(e)}"
        )

    except Exception as e:
        logger.error(f"Voice search error: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Voice search failed"
        )


@router.post("/cloudinary-voice-search")
async def cloudinary_voice_search(
    request: CloudinaryVoiceSearchRequest,
    _: None = Depends(verify_api_key),
    db: Session = Depends(get_db),
):
    try:
        # 1. Validate Cloudinary URL
        parsed = urlparse(request.cloudinary_url)
        if "cloudinary.com" not in parsed.netloc:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="URL must be a valid Cloudinary URL"
            )

        # 2. Download audio from Cloudinary
        logger.info(f"Downloading audio from Cloudinary: {request.cloudinary_url}")
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.get(request.cloudinary_url)
            if response.status_code != 200:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=f"Failed to download audio: HTTP {response.status_code}"
                )
            audio_data = response.content

        if not audio_data:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Downloaded audio is empty"
            )

        # 3. Extract filename for format detection
        filename = parsed.path.split("/")[-1] or "audio.mp3"
        logger.info(f"Downloaded {len(audio_data)} bytes, filename: {filename}")

        # 4. Transcribe using HuggingFace
        transcript = huggingface_speech_service.transcribe_audio(
            audio_data=audio_data,
            filename=filename,
            language_code=request.language_code
        )

        if not transcript:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="No speech detected in audio"
            )

        logger.info(f"Transcript: '{transcript}'")

        # 5. Run RAG search using existing pipeline
        result = SearchService.rag_search(db, transcript, org_id=request.org_id)

        return {
            "transcript": transcript,
            "query": transcript,
            "answer": result["answer"],
            "sources": result["sources"],
            "metadata": {
                "cloudinary_url": request.cloudinary_url,
                "model": huggingface_speech_service.model_name,
                "language": request.language_code or "auto-detected",
                "org_id": request.org_id,
            }
        }

    except (AudioFileTooLargeError, UnsupportedAudioFormatError,
            SpeechToTextError, AudioProcessingError, SearchServiceException):
        raise

    except HTTPException:
        raise

    except Exception as e:
        logger.error(f"Cloudinary voice search error: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Cloudinary voice search failed"
        )