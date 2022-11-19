#!/usr/bin/env python3
# -*- coding: utf-8 -*-

# 1. Library imports
import uvicorn
from fastapi import FastAPI

# 2. Create app and model objects
app = FastAPI()

# 1. Run the API with uvicorn
#    Will run on http://127.0.0.1:8000
if __name__ == '__main__':
    uvicorn.run('main:app', host='127.0.0.1', port=8000, reload=True)
