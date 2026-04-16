# check for duplicate detections


def iou(box1, box2):
    # determine the (x, y)-coordinates of the intersection rectangle
    x_a = max(box1[0], box2[0])
    y_a = max(box1[1], box2[1])
    x_b = min(box1[2], box2[2])
    y_b = min(box1[3], box2[3])

    # compute the area of intersection rectangle
    intersection = abs(max((x_b - x_a, 0)) * max((y_b - y_a), 0))
    if intersection == 0:
        return 0
    # compute the area of both the prediction and ground-truth
    # rectangles
    box1_area = abs((box1[2] - box1[0]) * (box1[3] - box1[1]))
    box2_area = abs((box2[2] - box2[0]) * (box2[3] - box2[1]))

    # compute the intersection over union, union is sum of areas of two boxes - intersection
    int_over_union = intersection / float(box1_area + box2_area - intersection)

    # return the intersection over union value
    return int_over_union


def iou_check(cutter_list):
    # record indices of duplicates
    for i in cutter_list:
        for j in cutter_list:
            if i == j:
                continue
            elif iou(i, j) > 0.5:
                try:
                    cutter_list.remove(j)
                except ValueError:
                    pass
    coord_count = [cutter_list.count(cutter_list[i]) for i in range(len(cutter_list))]

    # take coordinate count and delete duplicates
    for i in range(len(coord_count)):
        try:
            if coord_count[i] > 1:
                cutter_list.remove(cutter_list[i])
                coord_count = [cutter_list.count(cutter_list[i]) for i in range(len(cutter_list))]
        except IndexError:
            pass

    return cutter_list
