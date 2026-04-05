"""
Run this from your project root to get a presigned URL for any R2 object.
Usage: python generate_r2_url.py
"""

import boto3
from dotenv import load_dotenv
import os

load_dotenv()

s3 = boto3.client(
    "s3",
    endpoint_url=os.getenv("R2_ENDPOINT_URL"),
    aws_access_key_id=os.getenv("R2_ACCESS_KEY_ID"),
    aws_secret_access_key=os.getenv("R2_SECRET_ACCESS_KEY"),
    region_name="auto",
)

bucket = os.getenv("R2_BUCKET_NAME")

# ── Change this to your actual audio file key in R2 ──────────────────────
object_key = "emventory-ai/harvard.wav"  # e.g. "audio/sample.mp3"
# ─────────────────────────────────────────────────────────────────────────

url = s3.generate_presigned_url(
    "get_object",
    Params={"Bucket": bucket, "Key": object_key},
    ExpiresIn=3600,  # valid for 1 hour
)

print("\n✅ Presigned URL (valid 1 hour):")
print(url)
print("\nPaste this into Postman as file_url\n")