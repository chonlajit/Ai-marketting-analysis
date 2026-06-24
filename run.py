import uvicorn
import os
import sys

if __name__ == "__main__":
    # Ensure dependencies can be imported from current path
    sys.path.insert(0, os.path.abspath(os.path.dirname(__file__)))
    
    print("==================================================")
    print("  AI Financial News Intelligence Platform Launcher ")
    print("==================================================")
    print("Starting server at http://localhost:8000")
    
    uvicorn.run("app.main:app", host="127.0.0.1", port=8000, reload=True)
