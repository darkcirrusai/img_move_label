# imports for running the image operations
import os
from PIL import Image
from utils.process_multi_cutters import process_cutter_data, get_raw_detections
import base64
import io
import json
from dotenv import load_dotenv, find_dotenv
import requests

load_dotenv(find_dotenv())


def container_predict(image_file_path, image_key):
    """Sends a prediction request to TFServing docker container REST API.
    Args:
        image_file_path: Path to a local image for the prediction request.
        image_key: Your chosen string key to identify the given image.
    Returns:
        The response of the prediction request.
    """

    with io.open(image_file_path, 'rb') as image_file:
        encoded_image = base64.b64encode(image_file.read()).decode('utf-8')

    instances = {
            'instances': [
                    {'image_bytes': {'b64': str(encoded_image)},
                     'key': str(image_key)}
            ]
    }

    url = os.getenv('MODEL_URL', 'http://0.0.0.0:8845/v1/models/cutter_detect:predict')
    response = requests.post(url, data=json.dumps(instances))
    print(response.json())
    return response.json()


def cutter_crop(pic_path: str,
                image_key: str,
                conf_thresh: float,
                target_folder: str | None = None,
                detection_only: bool = False):
    # get cutters from the pictures
    im = Image.open(pic_path)
    wide = im.width
    ht = im.height

    # collect cutter data.json
    cutter_data = {}

    # send image for inference
    prediction_response = container_predict(pic_path, image_key)

    # fix prediction key error, if no detections then return None
    try:
        temp_prediction = prediction_response['predictions'][0]
        box_list, box_list_ro, box_list_lost, box_list_nozzle = process_cutter_data(cutter_json_1=temp_prediction,
                                                                                    cutter_json_2=temp_prediction,
                                                                                    conf_thresh=conf_thresh)
    except KeyError:
        cutter_data = None
        return target_folder, cutter_data

    # NEW: Visualization Mode - return raw detections with scores
    if detection_only and target_folder == "visualize":
        raw_detections = get_raw_detections(temp_prediction, temp_prediction)
        return raw_detections

        # If detection_only mode (count stats), return counts without cropping or drawing
    if detection_only:
        return {
            'total_detections': len(box_list) + len(box_list_lost) + len(box_list_ro),
            'cutters': len(box_list),
            'lost': len(box_list_lost),
            'ring_out': len(box_list_ro)
        }

    # store cutter data.json
    for i, box in enumerate(box_list):
        # get coordinates
        top = box[0]
        left = box[1]
        bottom = box[2]
        right = box[3]

        cutter_data['cut_' + str(i) + '.jpg'] = [top, bottom, left, right]

    # store ring out and lost data.json
    if len(box_list_lost) != 0:
        for i, box in enumerate(box_list_lost):
            # get coordinates
            top = box[0]
            left = box[1]
            bottom = box[2]
            right = box[3]

            cutter_data['lost_' + str(i) + '.jpg'] = [top, bottom, left, right]

    if len(box_list_ro) != 0:
        for i, box in enumerate(box_list_ro):
            # get coordinates
            top = box[0]
            left = box[1]
            bottom = box[2]
            right = box[3]

            cutter_data['ro_' + str(i) + '.jpg'] = [top, bottom, left, right]

    if len(box_list_nozzle) != 0:
        for i, box in enumerate(box_list_nozzle):
            # get coordinates
            top = box[0]
            left = box[1]
            bottom = box[2]
            right = box[3]

            cutter_data['nozzle_' + str(i) + '.jpg'] = [top, bottom, left, right]

    # crop cutters from the images
    if len(box_list) > 0:
        crop_cutters(im, box_list, wide, ht,'cut_', target_folder)
    if len(box_list_lost) > 0:
        crop_cutters(im, box_list_lost, wide, ht,'lost_', target_folder)
    if len(box_list_ro) > 0:
        crop_cutters(im, box_list_ro, wide, ht,'ro_', target_folder)
    if len(box_list_nozzle) > 0:
        crop_cutters(im, box_list_nozzle, wide, ht,'nozzle_', target_folder)
    
    return cutter_data


def crop_cutters(im, boxes, im_wd, im_ht, name, target_folder):
    for i, box in enumerate(boxes):
        top = box[0] * im_ht
        left = box[1] * im_wd
        bottom = box[2] * im_ht
        right = box[3] * im_wd

        # crop the image
        temp = im.crop((left, top, right, bottom))

        try:
            temp.save(target_folder + '/'+ name + str(i) + '.jpg',
                      format='jpeg')
        except OSError:
            temp = temp.convert('RGB')
            temp.save(target_folder + '/'+name + str(i) + '.jpg',
                      format='jpeg')
