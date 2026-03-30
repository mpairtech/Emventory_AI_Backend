from google import genai

client = genai.Client(api_key="AIzaSyBOQ1rpYk9CIIbxQKxaoFD0MK3edPefxnU")

print("=== EMBEDDING MODELS ===")
for model in client.models.list():
    if "embed" in model.name.lower():
        print(model.name)

print("\n=== ALL MODELS ===")
for model in client.models.list():
    print(model.name)