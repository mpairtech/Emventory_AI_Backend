from __future__ import annotations

import os
import logging
import tempfile
from app.core.config import settings
from app.core.exceptions import (
    SpeechToTextError,
    AudioProcessingError,
    UnsupportedAudioFormatError,
    AudioFileTooLargeError,
)
from pathlib import Path
from functools import lru_cache
from typing import Any, Optional, Tuple

logger = logging.getLogger(__name__)

@lru_cache(maxsize=1)
def _load_speech_deps() -> Tuple[Any, Any, Any, Any, Any, Any]:
    """
    Lazily import heavy ML deps on first speech use.

    This keeps `uvicorn app.main:app --reload` startup fast and prevents
    TensorFlow import issues from crashing the whole API process.
    """
    # Prevent Transformers from trying to use TensorFlow/Flax if present.
    # (On Windows, TensorFlow is commonly installed but broken/incompatible.)
    os.environ.setdefault("TRANSFORMERS_NO_TF", "1")
    os.environ.setdefault("TRANSFORMERS_NO_FLAX", "1")

    try:
        # NOTE: Avoid importing `AutoProcessor` here. Recent Transformers versions can
        # import TensorFlow via image processing utilities when `AutoProcessor` is used,
        # and a broken TensorFlow install on Windows will crash the import.
        from transformers import AutoModelForSpeechSeq2Seq, WhisperProcessor, pipeline  # type: ignore
    except Exception as e:  # pragma: no cover
        msg = str(e)
        if "pywrap_tensorflow" in msg or "_pywrap_tensorflow_internal" in msg or "Failed to load the native TensorFlow runtime" in msg:
            hint = "TensorFlow is installed but broken on Windows. Fix: `pip uninstall -y tensorflow`."
        elif "c10.dll" in msg or "WinError 1114" in msg:
            hint = (
                "PyTorch failed to load native DLLs. Fix: install Microsoft Visual C++ Redistributable "
                "2015-2022 (x64), then restart your terminal/uvicorn."
            )
        else:
            hint = "Check your ML dependencies (transformers/torch) in this venv."
        raise SpeechToTextError(
            "Speech dependencies failed to import (transformers). " + hint
        ) from e

    try:
        import torch  # type: ignore
    except Exception as e:  # pragma: no cover
        raise SpeechToTextError(
            "Speech dependencies failed to import (torch). "
            "Install PyTorch to enable speech-to-text."
        ) from e

    try:
        import librosa  # type: ignore
        import numpy as np  # type: ignore
    except Exception as e:  # pragma: no cover
        raise SpeechToTextError(
            "Speech dependencies failed to import (librosa/numpy). "
            "Install audio processing dependencies to enable speech-to-text."
        ) from e

    return AutoModelForSpeechSeq2Seq, WhisperProcessor, pipeline, torch, librosa, np

class HuggingFaceSpeechService:
    """
    Free, offline speech-to-text using Hugging Face Transformers.
    Uses OpenAI Whisper models by default.
    """
    
    def __init__(self):
        self.model_name = settings.SPEECH_MODEL_NAME
        self.device = settings.SPEECH_DEVICE
        self.pipe = None
        
        # Lazy loading - model loads on first use
        logger.info(f"HuggingFace Speech Service initialized (model will load on first use)")
    
    def _load_model(self):
        """Load model on first use (lazy loading)"""
        if self.pipe is not None:
            return
        
        try:
            AutoModelForSpeechSeq2Seq, AutoProcessor, pipeline, torch, _, _ = _load_speech_deps()

            logger.info(f"Loading Hugging Face model: {self.model_name}")
            logger.info(f"Device: {self.device}")
            logger.info("First load will download model (~150MB-1.5GB depending on model size)")
            
            # Determine device
            device_map = self.device
            torch_dtype = torch.float32
            
            if self.device == "cuda" and torch.cuda.is_available():
                torch_dtype = torch.float16
                logger.info("Using GPU acceleration")
            elif self.device == "cuda":
                logger.warning("CUDA requested but not available, falling back to CPU")
                device_map = "cpu"
            
            # Load model and processor
            model = AutoModelForSpeechSeq2Seq.from_pretrained(
                self.model_name,
                torch_dtype=torch_dtype,
                low_cpu_mem_usage=True,
                use_safetensors=True,
                cache_dir=settings.SPEECH_MODEL_CACHE_DIR
            )
            
            model.to(device_map)
            
            processor = AutoProcessor.from_pretrained(
                self.model_name,
                cache_dir=settings.SPEECH_MODEL_CACHE_DIR
            )
            
            # Create pipeline
            self.pipe = pipeline(
                "automatic-speech-recognition",
                model=model,
                tokenizer=processor.tokenizer,
                feature_extractor=processor.feature_extractor,
                max_new_tokens=128,
                chunk_length_s=30,
                batch_size=16,
                return_timestamps=False,
                torch_dtype=torch_dtype,
                device=device_map,
            )
            
            logger.info(f"Model loaded successfully: {self.model_name}")
            
        except Exception as e:
            logger.error(f"Failed to load model: {e}", exc_info=True)
            # Helpful hint for the most common Windows failure mode seen in logs.
            msg = str(e)
            if "pywrap_tensorflow" in msg or "_pywrap_tensorflow_internal" in msg or "Failed to load the native TensorFlow runtime" in msg:
                raise SpeechToTextError(
                    "Speech model load failed because TensorFlow is installed but cannot load on Windows. "
                    "Fix: uninstall TensorFlow from this venv (recommended) or install a compatible Windows TensorFlow. "
                    "Example: `pip uninstall -y tensorflow` (then restart uvicorn)."
                ) from e
            raise SpeechToTextError(f"Failed to load speech model: {str(e)}")
    
    def _validate_audio_file(self, audio_data: bytes, filename: str) -> str:
        """Validate audio file size and format"""
        # Check file size
        file_size_mb = len(audio_data) / (1024 * 1024)
        if len(audio_data) > settings.MAX_AUDIO_SIZE_BYTES:
            raise AudioFileTooLargeError(
                f"Audio file too large: {file_size_mb:.2f}MB. "
                f"Maximum allowed: {settings.SPEECH_MAX_AUDIO_SIZE_MB}MB"
            )
        
        # Check file extension
        extension = Path(filename).suffix.lower().lstrip('.')
        
        if not extension:
            raise UnsupportedAudioFormatError("No file extension found")
        
        if extension not in settings.SPEECH_SUPPORTED_FORMATS:
            raise UnsupportedAudioFormatError(
                f"Unsupported format: .{extension}. "
                f"Supported: {', '.join(settings.SPEECH_SUPPORTED_FORMATS)}"
            )
        
        logger.info(f"Audio validated: {filename} ({file_size_mb:.2f}MB, format: {extension})")
        return extension
    
    def _process_audio(self, audio_data: bytes, filename: str) -> Any:
        """
        Convert audio to format expected by Whisper (16kHz mono).
        Handles various input formats.
        """
        temp_file = None
        try:
            _, _, _, _, librosa, _ = _load_speech_deps()

            # Save to temporary file
            with tempfile.NamedTemporaryFile(
                delete=False, 
                suffix=Path(filename).suffix
            ) as f:
                f.write(audio_data)
                temp_file = f.name
            
            # Load audio using librosa (handles format conversion)
            audio_array, sample_rate = librosa.load(
                temp_file,
                sr=16000,  # Resample to 16kHz (required by Whisper)
                mono=True   # Convert to mono
            )
            
            logger.info(f"Audio processed: {len(audio_array)} samples at 16kHz")
            return audio_array
            
        except Exception as e:
            logger.error(f"Audio processing failed: {e}")
            raise AudioProcessingError(f"Failed to process audio: {str(e)}")
        
        finally:
            # Clean up temp file
            if temp_file and os.path.exists(temp_file):
                try:
                    os.remove(temp_file)
                except:
                    pass
    
    def transcribe_audio(
        self, 
        audio_data: bytes, 
        filename: str,
        language_code: Optional[str] = None
    ) -> str:
        """
        Transcribe audio to text using Hugging Face Whisper model.
        
        Args:
            audio_data: Raw audio file bytes
            filename: Original filename (used to detect format)
            language_code: ISO language code (e.g., 'en', 'es', 'fr')
                          If None, uses auto-detection
        
        Returns:
            Transcribed text string
        
        Raises:
            AudioFileTooLargeError: If audio exceeds size limit
            UnsupportedAudioFormatError: If format is not supported
            SpeechToTextError: If transcription fails
        """
        try:
            # Load model on first use
            self._load_model()
            
            # Validate audio file
            self._validate_audio_file(audio_data, filename)
            
            # Process audio to numpy array
            audio_array = self._process_audio(audio_data, filename)
            
            # Prepare transcription parameters
            generate_kwargs = {}
            
            # Set language if specified (or let model auto-detect)
            if language_code:
                # Extract base language code (en-US → en)
                lang = language_code.split('-')[0].lower()
                generate_kwargs["language"] = lang
                logger.info(f"Transcribing in language: {lang}")
            else:
                logger.info("Auto-detecting language")
            
            # Transcribe
            logger.info(f"Starting transcription: {filename}")
            result = self.pipe(
                audio_array,
                generate_kwargs=generate_kwargs
            )
            
            # Extract transcript
            transcript = result["text"].strip()
            
            if not transcript:
                logger.warning("No speech detected in audio")
                return ""
            
            logger.info(f"Transcription successful: '{transcript[:100]}...' ({len(transcript)} chars)")
            return transcript
            
        except (AudioFileTooLargeError, UnsupportedAudioFormatError, AudioProcessingError):
            # Re-raise known exceptions
            raise
        
        except Exception as e:
            logger.error(f"Transcription failed: {e}", exc_info=True)
            raise SpeechToTextError(f"Transcription error: {str(e)}")
    
    def get_model_info(self) -> dict:
        """Return information about the loaded model"""
        return {
            "model_name": self.model_name,
            "device": self.device,
            "loaded": self.pipe is not None,
            "supported_languages": [
                "en", "es", "fr", "de", "it", "pt", "nl", "ru", "zh", "ja", "ko",
                "ar", "hi", "tr", "pl", "uk", "vi", "th", "id", "ms", "fa"
                # Whisper supports 99 languages total
            ]
        }

# Singleton instance
huggingface_speech_service = HuggingFaceSpeechService()