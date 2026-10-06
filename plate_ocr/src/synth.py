"""한국 번호판 합성기. 실제 규격(흰 긴형/노란 긴형/노란 두줄/초록 두줄)을 흉내낸다."""
import random, os
import numpy as np
import cv2
from PIL import Image, ImageDraw, ImageFont

FONT = "/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc"
FONT_IDX = 1  # CJK KR

# 실제 번호판에 쓰이는 한글 (용도 기호)
HANGUL = list("가나다라마거너더러머버서어저고노도로모보소오조구누두루무부수우주허하호바사아자배")
REGION = ["서울","부산","대구","인천","광주","대전","울산","세종","경기","강원",
          "충북","충남","전북","전남","경북","경남","제주"]

PLATE_TYPES = ("white_long", "yellow_long", "yellow_two", "green_two")

def make_text(ptype):
    """번호판 종류별 문자열 생성. 반환: (라벨문자열, 줄 리스트)"""
    h = random.choice(HANGUL)
    if ptype == "white_long":
        # 신형: 3자리 + 한글 + 4자리  /  구형: 2자리 + 한글 + 4자리
        if random.random() < 0.6:
            a = f"{random.randint(100,999)}"
        else:
            a = f"{random.randint(10,99)}"
        b = f"{random.randint(1000,9999)}"
        return a + h + b, [a + h + b]
    if ptype == "yellow_long":
        # 영업용 긴형: 2~3자리 + 한글(바사아자) + 4자리
        a = f"{random.randint(10,999)}"
        h = random.choice(list("바사아자"))
        b = f"{random.randint(1000,9999)}"
        return a + h + b, [a + h + b]
    if ptype == "yellow_two":
        # 두 줄 영업용: 위 = 지역 + 2자리, 아래 = 한글 + 4자리
        r = random.choice(REGION)
        a = f"{random.randint(10,99)}"
        h = random.choice(list("바사아자"))
        b = f"{random.randint(1000,9999)}"
        return r + a + h + b, [r + a, h + b]
    # green_two : 위 = 지역 + 2자리, 아래 = 한글 + 4자리
    r = random.choice(REGION)
    a = f"{random.randint(10,99)}"
    b = f"{random.randint(1000,9999)}"
    return r + a + h + b, [r + a, h + b]

BG = {"white_long": (245,245,245), "yellow_long": (240,200,40),
      "yellow_two": (240,200,40), "green_two": (40,120,70)}
FG = {"white_long": (20,20,20), "yellow_long": (20,20,20),
      "yellow_two": (20,20,20), "green_two": (250,250,250)}

def render(ptype, lines):
    two = ptype.endswith("two")
    W, H = (520, 110) if not two else (440, 220)
    bg, fg = BG[ptype], FG[ptype]
    img = Image.new("RGB", (W, H), bg)
    d = ImageDraw.Draw(img)
    # 테두리
    d.rectangle([3,3,W-4,H-4], outline=fg, width=3)
    size = 74 if not two else 86
    f = ImageFont.truetype(FONT, size, index=FONT_IDX)
    if not two:
        t = lines[0]
        bb = d.textbbox((0,0), t, font=f)
        d.text(((W-(bb[2]-bb[0]))/2 - bb[0], (H-(bb[3]-bb[1]))/2 - bb[1]), t, font=f, fill=fg)
    else:
        f_top = ImageFont.truetype(FONT, 58, index=FONT_IDX)
        for i, (t, ft, cy) in enumerate([(lines[0], f_top, 58), (lines[1], f, 150)]):
            bb = d.textbbox((0,0), t, font=ft)
            d.text(((W-(bb[2]-bb[0]))/2 - bb[0], cy-(bb[3]-bb[1])/2 - bb[1]), t, font=ft, fill=fg)
    return np.array(img)[:, :, ::-1].copy()  # BGR

def augment(img):
    h, w = img.shape[:2]
    # 원근 왜곡 (비스듬히 본 효과)
    m = 0.10
    src = np.float32([[0,0],[w,0],[w,h],[0,h]])
    dst = src + np.float32([[random.uniform(-m,m)*w, random.uniform(-m,m)*h] for _ in range(4)])
    M = cv2.getPerspectiveTransform(src, dst)
    img = cv2.warpPerspective(img, M, (w,h), borderMode=cv2.BORDER_REPLICATE)
    # 회전
    M = cv2.getRotationMatrix2D((w/2,h/2), random.uniform(-7,7), 1.0)
    img = cv2.warpAffine(img, M, (w,h), borderMode=cv2.BORDER_REPLICATE)
    # 밝기/대비 (어두운 주차장 대비)
    a = random.uniform(0.5, 1.35); b = random.uniform(-45, 45)
    img = np.clip(img.astype(np.float32)*a + b, 0, 255).astype(np.uint8)
    # 블러 (작은 번호판 / 흔들림)
    if random.random() < 0.6:
        k = random.choice([3,3,5,7])
        img = cv2.GaussianBlur(img, (k,k), 0)
    # 저해상도 왕복 (멀리 찍힌 번호판)
    if random.random() < 0.5:
        s = random.uniform(0.25, 0.6)
        small = cv2.resize(img, None, fx=s, fy=s, interpolation=cv2.INTER_AREA)
        img = cv2.resize(small, (w,h), interpolation=cv2.INTER_LINEAR)
    # 노이즈
    if random.random() < 0.5:
        img = np.clip(img.astype(np.int16) + np.random.normal(0, random.uniform(3,14), img.shape), 0, 255).astype(np.uint8)
    # JPEG 압축 흔적
    if random.random() < 0.4:
        q = random.randint(25, 70)
        _, enc = cv2.imencode(".jpg", img, [cv2.IMWRITE_JPEG_QUALITY, q])
        img = cv2.imdecode(enc, cv2.IMREAD_COLOR)
    return img

# 종류 비율: 계획서 A-2 샘플 구성(1000/400/300/300)을 따른다
WEIGHTS = [0.50, 0.20, 0.15, 0.15]

def sample(aug=True):
    ptype = random.choices(PLATE_TYPES, weights=WEIGHTS)[0]
    label, lines = make_text(ptype)
    img = render(ptype, lines)
    if aug:
        img = augment(img)
    return img, label, ptype

if __name__ == "__main__":
    out = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data", "preview")
    os.makedirs(out, exist_ok=True)
    random.seed(0)
    for i in range(12):
        img, label, pt = sample()
        cv2.imwrite(f"{out}/{i:02d}_{pt}_{label}.png", img)
        print(pt, label)
