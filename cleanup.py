import os
from pymongo import MongoClient
from dotenv import load_dotenv

load_dotenv()

mongo = MongoClient(os.environ["MONGODB_URI"])
collection = mongo[os.environ["MONGODB_DB"]][os.environ["MONGODB_COLLECTION"]]

result = collection.delete_many({"repo_url": "https://github.com/test/repo"})
print(f"Deleted {result.deleted_count} test document(s).")
