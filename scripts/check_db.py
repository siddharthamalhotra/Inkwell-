from pymongo import MongoClient
from dotenv import load_dotenv
import os

load_dotenv()
m = MongoClient(os.environ["MONGODB_URI"])
col = m[os.environ["MONGODB_DB"]][os.environ["MONGODB_COLLECTION"]]

count = col.count_documents({})
print(f"Total docs in collection: {count}")

for doc in col.find({}, {"_id": 0, "embedding": 0}):
    section = doc.get("section", "?")
    repo = doc.get("repo_url", "?")
    text = doc.get("text", "")[:100].replace("\n", " ")
    print(f"  [{section}] {repo}")
    print(f"    {text}...")
    print()
