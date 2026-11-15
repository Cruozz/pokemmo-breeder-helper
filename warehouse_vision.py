"""Conservative Alpha outline evidence inside one warehouse thumbnail cell."""
from __future__ import annotations


def classify_alpha_icon(tile) -> bool | None:
    """True needs a red contour around the sprite; absent/unclear is distinct."""
    import cv2
    import numpy as np
    from PIL import Image

    if tile.width < 40 or tile.height < 32:
        return None
    # Canonical coordinates are local to this single cell, never the whole box.
    rgb = np.asarray(tile.convert("RGB").resize((80,68),Image.Resampling.LANCZOS)).astype(np.int16)
    r,g,b = rgb[:,:,0],rgb[:,:,1],rgb[:,:,2]
    region = np.zeros((68,80),dtype=bool)
    region[2:52,11:69] = True
    region[39:,:25] = False  # Sex glyph at the bottom left.
    region[:25,64:] = False  # Hidden-ability diamond at the top right.
    red = region & (r>=125) & (r<=230) & (g<=62) & (b<=78) & (b>=g-4) & (b-g<=35) & (r-g>=78) & (r-b>=65)
    strict = red & (abs(r-191)<=18) & (abs(g-20)<=15) & (abs(b-29)<=15)
    closed = cv2.morphologyEx(red.astype("uint8"),cv2.MORPH_CLOSE,np.ones((3,3),dtype="uint8"))
    count,labels,stats,_ = cv2.connectedComponentsWithStats(closed,8)
    # Close only tiny antialiasing gaps. Disconnected natural red patches must
    # not be combined into an invented outline; larger gaps stay unconfirmed.
    for index in range(1,count):
        original = red & (labels==index)
        pixels = int(original.sum())
        if pixels<65 or int((strict & original).sum())<20:
            continue
        ys,xs = np.where(original)
        x,y = int(xs.min()),int(ys.min())
        width,height = int(xs.max())-x+1,int(ys.max())-y+1
        if not 18<=width<=48 or not 16<=height<=43:
            continue
        if not 25<=x+width/2<=61 or x<=11 or x+width>=69 or y<=2 or y+height>=52:
            continue
        points = np.column_stack((xs,ys)).astype("int32")
        hull = cv2.convexHull(points)
        area = cv2.contourArea(hull)
        if area<240 or not .10<=pixels/area<=.52:
            continue  # A filled red body or a few eyes are not an outline.
        sectors = set((np.floor((np.arctan2(ys-(y+height/2),xs-(x+width/2))+np.pi)*8/(2*np.pi)).astype(int)%8).tolist())
        if len(sectors)==8:
            anchor_y,anchor_x = np.where(strict & original)
            anchor_sectors = set((np.floor((np.arctan2(anchor_y-(y+height/2),anchor_x-(x+width/2))+np.pi)*8/(2*np.pi)).astype(int)%8).tolist())
            if len(anchor_sectors)<7:
                continue  # Natural red shading must not supply a fake perimeter.
            inside = np.zeros_like(closed)
            cv2.drawContours(inside,[hull],-1,1,-1)
            body = (inside!=0) & ~red & ((rgb.max(axis=2)>=90) | ((rgb.max(axis=2)-rgb.min(axis=2)>=25) & (rgb.max(axis=2)>=70)))
            if int(body.sum())>=30:
                content = region & ~red & ((rgb.max(axis=2)>=90) | ((rgb.max(axis=2)-rgb.min(axis=2)>=25) & (rgb.max(axis=2)>=70)))
                content[:4] = False;content[43:] = False
                content[:,:20] = False;content[:,64:] = False
                content[(g-r>=20) & (b-r>=30)] = False  # Cyan selection / HA glyphs, including antialiasing.
                enclosure = cv2.dilate(inside,np.ones((3,3),dtype="uint8"))!=0
                if int(content.sum())>=30 and int((content & ~enclosure).sum())<=int(content.sum())*.15:
                    return True
    # Substantial red evidence without a full contour is ambiguous, never Alpha.
    if int(red.sum())>=20:
        return None
    content = region & ((rgb.max(axis=2)>=105) | ((rgb.max(axis=2)-rgb.min(axis=2)>=32) & (rgb.max(axis=2)>=75)))
    content[43:] = False
    content[:25,61:] = False
    components,_,stats,_ = cv2.connectedComponentsWithStats(content.astype("uint8"),8)
    visible = any(area>=30 and width>=8 and height>=8 and 25<=x+width/2<=61
                  for x,y,width,height,area in stats[1:components])
    return False if visible else None
