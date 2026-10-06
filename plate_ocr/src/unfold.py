"""두 줄 번호판을 한 줄로 펴서 CTC가 읽을 수 있게 만든다.

두 줄 판은 세로로 눌리면 윗줄·아랫줄 글자가 같은 x 칸에 겹친다.
가로세로비로 두 줄인지 판별해(두 줄 ~2.0, 긴형 ~4.7) 위/아래를 잘라
좌우로 이어 붙이면 한 줄짜리와 같은 형태가 된다.
실제 파이프라인에서도 검출기 박스의 비율로 같은 판별이 가능하다.
"""
import os
import cv2, numpy as np

RATIO_TH = 3.0      # 이보다 작으면 두 줄로 본다
TOP_FRAC = 0.42     # 윗줄이 차지하는 세로 비율 (지역명 줄이 더 작다)

def unfold(img):
    """두 줄로 보이면 위/아래를 좌우로 이어 붙인 이미지를 반환."""
    h, w = img.shape[:2]
    if w / h >= RATIO_TH:
        return img
    cut = int(h * TOP_FRAC)
    top, bot = img[:cut], img[cut:]
    # 두 조각의 높이를 아래쪽에 맞추고 가로로 연결
    th = bot.shape[0]
    top = cv2.resize(top, (int(top.shape[1] * th / top.shape[0]), th),
                     interpolation=cv2.INTER_AREA)
    return np.hstack([top, bot])

if __name__ == "__main__":
    import sys, random
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    import synth
    random.seed(5); np.random.seed(5)
    rows = []
    for pt in ("yellow_two", "green_two"):
        tiles = []
        for _ in range(3):
            lab, lines = synth.make_text(pt)
            img = synth.augment(synth.render(pt, lines))
            g = cv2.cvtColor(unfold(img), cv2.COLOR_BGR2GRAY)
            g = cv2.resize(g, (160, 32), interpolation=cv2.INTER_AREA)
            g = cv2.resize(g, (480, 96), interpolation=cv2.INTER_NEAREST)
            tiles.append(cv2.copyMakeBorder(g, 3, 3, 3, 3, cv2.BORDER_CONSTANT, value=128))
        rows.append(np.hstack(tiles))
    out = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data", "preview", "unfolded.png")
    cv2.imwrite(out, np.vstack(rows))
    print("saved unfolded.png")
