"""python -m settleup  -> serves on http://127.0.0.1:8000 (SETTLEUP_DB to choose the database file)"""
import uvicorn

from .app import create_app

if __name__ == "__main__":
    uvicorn.run(create_app(), host="127.0.0.1", port=8000)
