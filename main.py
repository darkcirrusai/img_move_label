#!/usr/bin/env python3
# -*- coding: utf-8 -*-

# 1. Library imports
from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
import shutil, os

UPLOAD_FOLDER = 'uploads'
image_folder = 'static/cat_1'

# 2. Create app and model objects
app = FastAPI()
app.mount("/static", StaticFiles(directory="static"), name="static")
templates = Jinja2Templates(directory="templates/")

#3. Welcome page
@app.get("/", response_class=HTMLResponse)
async def read_root(request:Request):
    img_list = os.listdir(image_folder)
    pic_rem = len(img_list)
    return templates.TemplateResponse("welcome.html", 
    {"request": request, "image":img_list[0], "pic_rem":pic_rem})

@app.get("/img/{item_id}")
def move(item_id: str, request: Request):
    val = request.query_params
    label = val["label"]
    pic_name = val["name"]

    upload_path = "./uploads/"+label+"/"+pic_name
    image_path = 'static/sample_img/'+pic_name

    pic_rem = len(os.listdir('static/sample_img'))

    shutil.move(image_path, upload_path)
    
    img_list = os.listdir(image_folder)
    return templates.TemplateResponse("welcome.html", 
    {"request": request, "image":img_list[0], "pic_rem":pic_rem})