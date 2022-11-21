
# 1. Library imports
from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
import shutil, os

UPLOAD_FOLDER = 'sorted_files'
image_folder = 'source_files'

# 2. Create app and model objects
app = FastAPI()
app.mount("/static", StaticFiles(directory="static"), name="static")
app.mount("/source_files", StaticFiles(directory="source_files"), name="source_files")
templates = Jinja2Templates(directory="templates/")


# 3. Welcome page
@app.get("/", response_class=HTMLResponse)
async def read_root(request: Request):
    img_list = os.listdir(image_folder)
    pic_rem = len(img_list)
    try:
        next_img = img_list[0]
    except IndexError:
        next_img = 'no images found in the folder'
    return templates.TemplateResponse("welcome.html",
                                      {"request": request, "image": next_img, "pic_rem": pic_rem})


@app.get("/img/{item_id}")
def move(item_id: str, request: Request):
    val = request.query_params
    label = val["label"]
    pic_name = val["name"]

    upload_path = "./sorted_files/" + label + "/" + pic_name
    image_path = 'source_files/' + pic_name

    # folders for individual grade
    postive_cat = len(os.listdir('sorted_files/0'))
    negative_cat = len(os.listdir('sorted_files/1'))

    pic_rem = len(os.listdir(image_folder))

    shutil.move(image_path, upload_path)

    img_list = os.listdir(image_folder)
    return templates.TemplateResponse("welcome.html",
                                      {"request": request, "image": img_list[0], "pic_rem": pic_rem,
                                       "pic4": postive_cat, "pic5": negative_cat})
