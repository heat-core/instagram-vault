"""Entry point for the bundled desktop backend."""
import uvicorn
import os
from src.api import app

if __name__ == '__main__':
    uvicorn.run(app, host='127.0.0.1', port=int(os.environ.get('APP_API_PORT', '8000')), workers=1, log_level='warning')
