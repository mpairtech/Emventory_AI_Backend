from app.core.llm.gemini import GeminiClient

# Test embedding generation
test_texts = [
    "Wireless Mouse",
    "Gaming Laptop",
    "USB Cable"
]

print("Testing Gemini API...\n")

for text in test_texts:
    try:
        embedding = GeminiClient.embed(text)
        print(f"✅ Text: '{text}'")
        print(f"   Embedding dimensions: {len(embedding)}")
        print(f"   First 5 values: {embedding[:5]}")
        print()
    except Exception as e:
        print(f"❌ Error with '{text}': {str(e)}\n")