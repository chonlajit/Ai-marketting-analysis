import uvicorn
import os
import sys

if __name__ == "__main__":
    # Ensure dependencies can be imported from current path
    sys.path.insert(0, os.path.abspath(os.path.dirname(__file__)))
    
    # Read port from environment variable for deployment (e.g. Render/Railway)
    port = int(os.getenv("PORT", 8000))
    # Bind to 0.0.0.0 in deployment so it can accept external connections
    host = "0.0.0.0" if os.getenv("PORT") else "127.0.0.1"
    
    print("==================================================")
    print("  AI Financial News Intelligence Platform Launcher ")
    print("==================================================")
    print(f"Starting server at http://{host}:{port}")
    
    # Disable reload in production/cloud environments
    reload_mode = False if os.getenv("PORT") else True
    
    uvicorn.run("app.main:app", host=host, port=port, reload=reload_mode)

