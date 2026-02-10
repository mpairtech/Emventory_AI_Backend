class SearchServiceException(Exception):
    pass

class EmbeddingGenerationError(SearchServiceException):
    pass

class VectorSearchError(SearchServiceException):
    pass

class DatabaseError(SearchServiceException):
    pass

class LLMGenerationError(SearchServiceException):
    pass

class RateLimitError(SearchServiceException):
    pass

class ProductNotFoundError(SearchServiceException):
    pass
# ADD THESE NEW EXCEPTIONS:
class SpeechServiceException(SearchServiceException):
    """Base exception for speech services"""
    pass

class AudioProcessingError(SpeechServiceException):
    """Raised when audio file processing fails"""
    pass

class SpeechToTextError(SpeechServiceException):
    """Raised when speech-to-text conversion fails"""
    pass

class UnsupportedAudioFormatError(SpeechServiceException):
    """Raised when audio format is not supported"""
    pass

class AudioFileTooLargeError(SpeechServiceException):
    """Raised when audio file exceeds size limit"""
    pass