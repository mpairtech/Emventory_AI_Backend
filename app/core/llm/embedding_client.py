#from openai import OpenAI
#from app.core.config import settings

#class EmbeddingClient:
    #_client = OpenAI(api_key=settings.OPENAI_API_KEY)
    #MAX_INPUT_TOKENS = 500
    #TOKEN_APPROX_CHARS = 4

    #@staticmethod
    #def embed(text: str) -> list[float]:
       # truncated_text = text[
           # : EmbeddingClient.MAX_INPUT_TOKENS * EmbeddingClient.TOKEN_APPROX_CHARS
          
        #response = EmbeddingClient._client.embeddings.create(
            #model="text-embedding-3-small",
            #input=truncated_text
        
       # return response.data[0].embedding