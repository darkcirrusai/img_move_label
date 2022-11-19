
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
templates = Jinja2Templates(directory="templates/")


# 3. Welcome page
@app.get("/", response_class=HTMLResponse)
async def read_root(request: Request):
    img_list = os.listdir(image_folder)
    pic_rem = len(img_list)
    return templates.TemplateResponse("welcome.html",
                                      {"request": request, "image": img_list[0], "pic_rem": pic_rem})


@app.get("/img/{item_id}")
def move(item_id: str, request: Request):
    val = request.query_params
    label = val["label"]
    pic_name = val["name"]

    upload_path = "./sorted_files/" + label + "/" + pic_name
    image_path = 'static/cat_1/' + pic_name

    # folders for individual grade
    pic4 = len(os.listdir('sorted_files/0'))
    pic5 = len(os.listdir('sorted_files/1'))
    pic6 = len(os.listdir('sorted_files/2'))
    pic7 = len(os.listdir('sorted_files/3'))

    pic_rem = len(os.listdir('static/cat_1'))

    shutil.move(image_path, upload_path)

    img_list = os.listdir(image_folder)
    return templates.TemplateResponse("welcome.html",
                                      {"request": request, "image": img_list[0], "pic_rem": pic_rem,
                                       "pic4": pic4, "pic5": pic5, "pic6": pic6, "pic7": pic7, })
