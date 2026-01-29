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