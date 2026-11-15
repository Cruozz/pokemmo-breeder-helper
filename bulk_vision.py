"""Read small symbols in bounded batch-capture regions, separately from sprites."""
from __future__ import annotations


def gender_from_tile(tile) -> str:
    import cv2
    import numpy as np
    from PIL import Image

    if tile.width<40 or tile.height<32:
        return ""
    rgb=np.asarray(tile.convert("RGB").resize((80,68),Image.Resampling.LANCZOS)).astype(np.int16)
    r,g,b=rgb[:,:,0],rgb[:,:,1],rgb[:,:,2]
    region=np.zeros((68,80),dtype=bool)
    region[34:67,3:34]=True
    masks={"F":region & (r>=120) & (b>=80) & (r-g>=35) & (b-g>=20),
           "M":region & (b>=120) & (b-r>=25) & (g-r>=10)}
    candidates=[]
    for gender,mask in masks.items():
        # A selection edge can touch a glyph after resampling. Remove long UI
        # strokes before measuring individual symbols, rather than counting ink.
        mask[:,np.count_nonzero(mask,axis=0)>=22]=False
        mask[np.count_nonzero(mask,axis=1)>=22,:]=False
        count,labels,stats,_=cv2.connectedComponentsWithStats(mask.astype("uint8"),connectivity=8)
        for index in range(1,count):
            x,y,width,height,area=(int(value) for value in stats[index])
            if not 3<=width<=14 or not 5<=height<=18 or not 5<=area<=85:
                continue
            if x<=3 or x+width>=34 or y<=34 or y+height>=67:
                continue
            if not 6<=x+width/2<=28 or not 39<=y+height/2<=64:
                continue
            aspect=width/height
            density=area/(width*height)
            if not .40<=aspect<=1.4 or not .15<=density<=.80:
                continue
            component=(labels[y:y+height,x:x+width]==index).astype("uint8")
            _,hierarchy=cv2.findContours(component,cv2.RETR_CCOMP,cv2.CHAIN_APPROX_SIMPLE)
            has_hole=hierarchy is not None and any(item[3]>=0 for item in hierarchy[0])
            if not has_hole:
                continue  # Both sex symbols contain a ring; frames/body patches do not.
            score=(2.0 if has_hole else 0.0)+min(1.0,area/15)-abs(x+width/2-17)/25
            candidates.append((score,gender))
    candidates.sort(reverse=True)
    if not candidates:
        return ""
    if any(gender!=candidates[0][1] and score>=candidates[0][0]-.45 for score,gender in candidates[1:]):
        return ""
    return candidates[0][1]


def hidden_ability_from_header(image,box,right_bound: float) -> bool | None:
    import cv2
    import numpy as np

    text_left=min(float(point[0]) for point in box)
    text_right=max(float(point[0]) for point in box)
    text_top=min(float(point[1]) for point in box)
    text_bottom=max(float(point[1]) for point in box)
    height=max(8.0,text_bottom-text_top)
    left=max(0,round(max(text_left+height*2,text_right-height*1.6)))
    right=min(image.width,round(right_bound),round(text_right+height*3))
    top=max(0,round(text_top-height*.55))
    bottom=min(image.height,round(text_bottom+height*.4))
    if right-left<height*.6 or bottom-top<height*.6:
        return None
    rgb=np.asarray(image.convert("RGB").crop((left,top,right,bottom))).astype(np.int16)
    r,g,b=rgb[:,:,0],rgb[:,:,1],rgb[:,:,2]
    # Cyan includes green/blue facets; a green shiny star is not a cyan gem.
    mask=(b>=130) & (g>=100) & (b-r>=30) & (g-r>=20) & (b>=g-20)
    count,labels,stats,_=cv2.connectedComponentsWithStats(mask.astype("uint8"),connectivity=8)
    clipped=False
    for index in range(1,count):
        x,y,width,component_height,area=(int(value) for value in stats[index])
        if area<max(7,height*.45):
            continue
        if x<=0 or y<=0 or x+width>=right-left or y+component_height>=bottom-top:
            clipped=True
            continue
        if not .5*height<=width<=1.9*height or not .45*height<=component_height<=1.65*height:
            continue
        aspect=width/component_height
        density=area/(width*component_height)
        if not .65<=aspect<=1.9 or not .20<=density<=.85:
            continue
        component=labels[y:y+component_height,x:x+width]==index
        band=max(1,round(component_height*.18))
        bottom_x=np.where(component[-band:])[1]
        if not len(bottom_x) or int(bottom_x.max()-bottom_x.min()+1)>max(4,width*.78):
            continue  # Filled squares, text and UI lines do not taper like gems.
        return True
    return None if clipped else False
