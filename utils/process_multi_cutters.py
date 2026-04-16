"""
process cutter from two sources
"""
from utils.iou import iou_check


def process_cutter_data(cutter_json_1, cutter_json_2, conf_thresh=0.5):
    """
    takes cutter detection from two sources and returns the best detections
    """
    box_list = []
    box_list_lost = []
    box_list_nozzle = []
    box_list_ro = []

    # get list of detections from json
    detect_multiclass_score = (cutter_json_1['detection_multiclass_scores'] +
                               cutter_json_2['detection_multiclass_scores'])
    detect_boxs = cutter_json_1['detection_boxes'] + cutter_json_2['detection_boxes']

    # get list of detections from json
    for bbox, conf in zip(detect_boxs, detect_multiclass_score):
        if conf[3] > conf_thresh:
            box_list.append(bbox)
        elif conf[2] > conf_thresh:
            box_list_lost.append(bbox)
        elif conf[1] > conf_thresh:
            box_list_nozzle.append(bbox)
        elif conf[4] > conf_thresh:
            box_list_ro.append(bbox)
        else:
            continue

    # remove multiple detections
    box_list = iou_check(box_list)
    if len(box_list_lost) != 0:
        box_list_lost = iou_check(box_list_lost)
    if len(box_list_ro) != 0:
        box_list_ro = iou_check(box_list_ro)

    return box_list, box_list_ro, box_list_lost, box_list_nozzle


def get_raw_detections(cutter_json_1, cutter_json_2):
    """
    Extracts all detections with their confidence scores and class names.
    Returns a list of dictionaries.
    """
    detections = []
    
    # Combined lists
    # Note: Assuming structure matches process_cutter_data logic for consistency
    # Indices based on process_cutter_data:
    # 1: Nozzle
    # 2: Lost
    # 3: Cutter (Normal)
    # 4: Ring Out
    
    detect_multiclass_score = (cutter_json_1['detection_multiclass_scores'] +
                               cutter_json_2['detection_multiclass_scores'])
    detect_boxs = cutter_json_1['detection_boxes'] + cutter_json_2['detection_boxes']

    class_map = {
        1: "Lost",
        2: "Cutter",
        3: "Nozzle",
        4: "Ring Out"
    }

    for bbox, conf_scores in zip(detect_boxs, detect_multiclass_score):
        # Find the max score and its index to determine the most likely class
        # conf_scores is a list of scores for each class
        # We start checking from index 1 as 0 is usually background
        
        best_class_idx = -1
        best_score = 0.0
        
        for idx in range(1, 5):
            if idx < len(conf_scores) and conf_scores[idx] > best_score:
                best_score = conf_scores[idx]
                best_class_idx = idx
        
        if best_class_idx != -1:
            # Ensure coordinates are pure floats to avoid serialization issues
            try:
                def to_float(x):
                    # Handle dict-like objects if they slip through (e.g. from some weird JSON parsers)
                    if isinstance(x, dict) and 'parsedValue' in x:
                        return float(x['parsedValue'])
                    return float(x)
                clean_box = [to_float(x) for x in bbox]
            except (ValueError, TypeError):
                clean_box = bbox

            detections.append({
                "box": clean_box, # [ymin, xmin, ymax, xmax]
                "score": float(best_score),
                "label": class_map.get(best_class_idx, "Unknown"),
                "class_id": best_class_idx
            })

    return detections


def clean_coordinates(blade_coordinates: list,
                      cutter_coordinates: list):
    """
    Compare blade area with detected cutters and remove the ones that are outside the blade
    """
    y_min,x_min,y_max,x_max = blade_coordinates

    # Create a new list to store the filtered cutter coordinates
    filtered_cutter_coordinates = []

    # remove cutters that are outside the blade area
    for cutter in cutter_coordinates:
        # find x and y coordinates of the cutter
        x1 = cutter[1] + (cutter[3] - cutter[1]) / 2
        y1 = cutter[0] + (cutter[2] - cutter[0]) / 2

        if x_min < x1 < x_max and y_min < y1 < y_max:
            filtered_cutter_coordinates.append(cutter)
        else:
            pass

    return filtered_cutter_coordinates
