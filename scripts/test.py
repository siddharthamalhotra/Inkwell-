import os
from dotenv import load_dotenv
load_dotenv()

from anthropic import Anthropic
from pymongo import MongoClient

# Test Anthropic
client = Anthropic()
r = client.messages.create(
    model=os.environ.get("ANTHROPIC_MODEL", "claude-sonnet-4-6"),
    max_tokens=20,
    messages=[{"role": "user", "content": "say ok"}]
)
print(f"Anthropic: {r.content[0].text}")

# Test Mongo
m = MongoClient(os.environ["MONGODB_URI"])
print(f"Mongo databases: {m.list_database_names()}")
