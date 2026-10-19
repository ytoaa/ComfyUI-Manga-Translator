"""Shared pixel protection for unverified detection and OCR source geometry."""
import math


def boxes(data, width, height):
    if not isinstance(data,dict):
        raise ValueError('Invalid boundary review document')
    review = data.get('boundary_review')
    if review is None:
        return []
    if not isinstance(review, dict) or review.get('schema') != 1:
        raise ValueError('Invalid boundary review metadata')
    values = review.get('protected_boxes_pixels')
    if not isinstance(values, list) or not 1 <= len(values) <= 512:
        raise ValueError('Invalid boundary protection boxes')
    output = []
    for box in values:
        if (not isinstance(box, list) or len(box) != 4 or
                any(type(v) not in (int, float) or not math.isfinite(v) for v in box) or
                not 0 <= box[0] < box[2] <= width or not 0 <= box[1] < box[3] <= height):
            raise ValueError('Boundary protection exceeds page dimensions')
        output.append([math.floor(box[0]), math.floor(box[1]), math.ceil(box[2]), math.ceil(box[3])])
    return output


def intersects(a, b):
    return max(a[0], b[0]) < min(a[2], b[2]) and max(a[1], b[1]) < min(a[3], b[3])


def padded_bounds(source, padding, limits, protected):
    """Trim optional margins only; never remove source pixels to evade protection."""
    if any(intersects(source, area) for area in protected):
        return None
    result = [max(limits[0], source[0]-padding), max(limits[1], source[1]-padding),
              min(limits[2], source[2]+padding), min(limits[3], source[3]+padding)]
    if not (result[0] <= source[0] < source[2] <= result[2] and
            result[1] <= source[1] < source[3] <= result[3]):
        return None
    for area in protected:
        if not intersects(result, area):
            continue
        candidates = []
        for coordinate, permitted, value in (
                (0, area[2] <= source[0], area[2]),
                (2, source[2] <= area[0], area[0]),
                (1, area[3] <= source[1], area[3]),
                (3, source[3] <= area[1], area[1])):
            if permitted:
                candidate = result.copy()
                candidate[coordinate] = value
                candidates.append(candidate)
        if not candidates:
            return None
        result = max(candidates, key=lambda b: (b[2]-b[0])*(b[3]-b[1]))
    return result


def clear(array, protected):
    for x0, y0, x1, y1 in protected:
        array[y0:y1, x0:x1] = 0


def restore(array, original, protected):
    for x0, y0, x1, y1 in protected:
        array[y0:y1, x0:x1] = original[y0:y1, x0:x1]
