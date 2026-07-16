import os

# Defaults para o Settings importar sem .env completo (não sobrescreve valores reais)
os.environ.setdefault("BASE_URL", "http://localhost:8000")
os.environ.setdefault("MONGO_URI", "mongodb://localhost:27017")
os.environ.setdefault("MONGO_DB", "test_db")
os.environ.setdefault("DROP_CODE", "test-drop-code")
os.environ.setdefault("USE_FORM", "false")
