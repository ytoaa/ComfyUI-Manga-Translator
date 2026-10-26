"""Opt-in local evidence bundle; no inference, network calls or credentials."""
import hashlib
import io
import json
from pathlib import Path
import uuid
import zipfile
import numpy as np
from PIL import Image
from .limits import MAX_SOURCE_PIXELS, MAX_DOCUMENT_CHARACTERS
from .mask_nodes import _mask_metadata


def save(original, detector, regions, directory):
    from .workflow_native import VERSION
    h,w=original.shape[:2]
    if original.shape!=(h,w,3) or w*h>MAX_SOURCE_PIXELS or not np.isfinite(original).all():
        raise ValueError('Invalid reproduction source pixels')
    if (detector.get('protocol'),detector.get('image_width'),detector.get('image_height'))!=(1,w,h):
        raise ValueError('Reproduction detector belongs to another page')
    if not isinstance(regions,str) or len(regions)>MAX_DOCUMENT_CHARACTERS:
        raise ValueError('Invalid reproduction region document')
    # Keep the model's native geometry/masks, not service URLs, tokens or state.
    keys=('protocol','image_width','image_height','detections','mask_fragments','boundary_review',
          'detail_detection','detection_audit','model','revision')
    payload={key:detector[key] for key in keys if key in detector}
    rows=payload.get('detections',[])+payload.get('mask_fragments',[])
    if len(rows)>1024:raise ValueError('Reproduction observation budget exceeds 1024')
    for row in rows:
        if row.get('mask') is not None:_mask_metadata(row['mask'],w,h)
    raw=json.dumps(payload,ensure_ascii=False,allow_nan=False).encode()
    if len(raw)>128*1024*1024:raise ValueError('Reproduction detector JSON exceeds 128 MiB')
    root=Path(directory)/'manga_translator'/'reproduction';root.mkdir(parents=True,exist_ok=True)
    destination=root/f'page_{uuid.uuid4().hex}.zip';temporary=destination.with_suffix('.tmp')
    metadata={'schema':1,'version':VERSION,'page_size':[w,h],
              'scope':'original_float_pixels_and_raw_detection_not_model_quality_certificate','files':{}}
    try:
        with zipfile.ZipFile(temporary,'w',zipfile.ZIP_DEFLATED) as archive:
            with archive.open('original.npy','w',force_zip64=True) as member:
                np.save(member,np.asarray(original,np.float32),allow_pickle=False)
            png=io.BytesIO();Image.fromarray((np.clip(original,0,1)*255).round().astype('uint8')).save(png,format='PNG')
            archive.writestr('original.png',png.getvalue())
            archive.writestr('detection.json',raw)
            archive.writestr('regions.json',regions.encode())
            for name in archive.namelist():
                digest=hashlib.sha256()
                with archive.open(name) as member:
                    for chunk in iter(lambda:member.read(1024*1024),b''):digest.update(chunk)
                metadata['files'][name]=digest.hexdigest()
            archive.writestr('manifest.json',json.dumps(metadata,ensure_ascii=False,indent=2))
        temporary.replace(destination)
    finally:
        temporary.unlink(missing_ok=True)
    digest=hashlib.sha256()
    with destination.open('rb') as stream:
        for chunk in iter(lambda:stream.read(1024*1024),b''):digest.update(chunk)
    return {'path':str(destination),'sha256':digest.hexdigest(),
            'contains':['original_pixels','raw_detection_masks','resolved_regions'],
            'automatic_upload':False}
