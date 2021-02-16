#!/usr/bin/env python3
# -*- coding: utf-8 -*-

# 1. Library imports
from starlette.responses import FileResponse
from fastapi import FastAPI, Request, File, UploadFile
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
import shutil, os
from pathlib import Path

UPLOAD_FOLDER = 'uploads'
image_folder = 'static/sample_img'

# 2. Create app and model objects
app = FastAPI()
app.mount("/static", StaticFiles(directory="static"), name="static")
templates = Jinja2Templates(directory="templates/")

#3. Welcome page
@app.get("/", response_class=HTMLResponse)
async def read_root(request:Request):
    img_list = os.listdir(image_folder)
    return templates.TemplateResponse("welcome.html", 
    {"request": request, "image":img_list[0], "resp":"None"})


@app.post("/0")
async def move_zero(request:Request):
    '''
    tmp_uploads_path = './uploads/0/'

    if not os.path.exists(tmp_uploads_path):
        os.makedirs(tmp_uploads_path)

    p = Path(tmp_uploads_path + file.filename)
    #shutil.move(Request.query_params, p)
    
    img_list = os.listdir(image_folder)
    return templates.TemplateResponse("welcome.html", 
    {"request": request, "image":img_list[0], "resp":response})'''
    bod = request.body
    
    return {"body":bod}