import os
from dotenv import load_dotenv
from pymongo import MongoClient
from pymongo.errors import ServerSelectionTimeoutError

load_dotenv()

uri = os.environ.get("MONGODB_URI")
print(f"URI starts with: {uri[:30] if uri else 'NOT SET'}")

try:
    m = MongoClient(uri, serverSelectionTimeoutMS=5000)
    print(f"Databases: {m.list_database_names()}")
    print(f"Version: {m.admin.command('buildInfo')['version']}")
except ServerSelectionTimeoutError as e:
    print(f"TIMEOUT - check Network Access (0.0.0.0/0) and password")
    print(f"Detail: {e}")
except Exception as e:
    print(f"ERROR: {type(e).__name__}: {e}")