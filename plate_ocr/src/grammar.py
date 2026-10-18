"""한국 번호판 유한상태 문법과 그것을 지키는 CTC 빔서치 디코더.

번호판은 형식이 고정돼 있다.
    일반   : 숫자{2,3} 한글 숫자{4}        예) 12가3456, 123가4567
    지역명 : <지역> 숫자{1,3} 한글 숫자{4}  예) 서울12가3456, 서울4도9472

greedy 디코딩은 이 규칙을 전혀 모르기 때문에 `07누8596 → 08누596`처럼
자릿수가 깨진 출력을 그대로 낸다. 문법을 아는 디코더는 그런 경로를
애초에 탐색하지 않으므로, 같은 모델·같은 가중치로도 결과가 좋아진다.

상태 = (지역명 사용, 한글 앞 숫자 개수, 한글 지나감, 한글 뒤 숫자 개수)
"""
import numpy as np

DIGIT, HANGUL, REGION = 0, 1, 2
START = (0, 0, 0, 0)


def token_types(tokens):
    """charset.tokens(인덱스 0 = 토큰 1번) → 토큰별 종류 배열"""
    t = np.empty(len(tokens), np.int8)
    for i, s in enumerate(tokens):
        t[i] = REGION if s.startswith("<") else (DIGIT if s.isdigit() else HANGUL)
    return t


def step(state, kind):
    """상태 + 토큰 종류 → 다음 상태 (불가능하면 None)"""
    r, k, h, m = state
    if not h:
        if kind == REGION:
            return (1, 0, 0, 0) if state == START else None
        if kind == DIGIT:
            return (r, k + 1, 0, 0) if k < 3 else None
        # HANGUL: 지역명은 숫자 1개부터, 일반은 2개부터 허용
        return (r, k, 1, 0) if k >= (1 if r else 2) else None
    if kind == DIGIT and m < 4:
        return (r, k, 1, m + 1)
    return None


def accepting(state):
    return state[3] == 4


def allowed_mask(state, types, n_classes):
    """이 상태에서 이어붙일 수 있는 토큰만 True (blank 제외)"""
    mask = np.zeros(n_classes, bool)
    for kind in (DIGIT, HANGUL, REGION):
        if step(state, kind) is not None:
            mask[1:][types == kind] = True
    return mask


def _logsumexp2(a, b):
    m = max(a, b)
    return m + np.log(np.exp(a - m) + np.exp(b - m)) if m > -1e30 else m


def beam_decode(logp, types, beam=10, topk=6, use_grammar=True):
    """CTC prefix beam search. logp: (T, C) 로그확률, 0번이 blank.

    반환: (토큰 인덱스 리스트, 그 문자열의 로그확률)
    use_grammar=False 면 제약 없는 평범한 빔서치 (비교용).
    """
    NEG = -1e30
    C = logp.shape[1]
    # prefix(tuple) → [lp_blank, lp_nonblank, state]
    beams = {(): [0.0, NEG, START]}
    for t in range(logp.shape[0]):
        row = logp[t]
        order = np.argsort(row)[::-1]
        nxt = {}
        for pre, (pb, pnb, st) in beams.items():
            # 상위 후보는 '그 상태에서 허용되는 토큰 중에서' 고른다.
            # 먼저 자르고 나중에 거르면, 허용 토큰이 상위권 밖일 때 정답 경로가 막힌다.
            if use_grammar:
                m = allowed_mask(st, types, C)
                if pre:
                    # 같은 글자 반복을 접두사에 흡수하는 것은 글자를 늘리지 않으므로
                    # 문법과 무관하게 항상 허용해야 한다. 막으면 `333` → `33`으로 깨진다.
                    m[pre[-1]] = True
                cand = [c for c in order if m[c]][:topk]
            else:
                cand = list(order[:topk])
            total = _logsumexp2(pb, pnb)
            # 1) blank
            e = nxt.setdefault(pre, [NEG, NEG, st])
            e[0] = _logsumexp2(e[0], row[0] + total)
            for c in cand:
                if c == 0:
                    continue
                if pre and c == pre[-1]:
                    # 2) 같은 글자 반복 → 합쳐짐 (prefix 유지)
                    e = nxt.setdefault(pre, [NEG, NEG, st])
                    e[1] = _logsumexp2(e[1], row[c] + pnb)
                    # blank를 거친 경우에만 글자가 하나 더 늘어난다
                    ns = step(st, types[c - 1]) if use_grammar else st
                    if ns is not None:
                        e2 = nxt.setdefault(pre + (c,), [NEG, NEG, ns])
                        e2[1] = _logsumexp2(e2[1], row[c] + pb)
                else:
                    ns = step(st, types[c - 1]) if use_grammar else st
                    if ns is None:
                        continue
                    e2 = nxt.setdefault(pre + (c,), [NEG, NEG, ns])
                    e2[1] = _logsumexp2(e2[1], row[c] + total)
        beams = dict(sorted(nxt.items(), key=lambda kv: -_logsumexp2(kv[1][0], kv[1][1]))[:beam])

    best, best_lp = (), NEG
    for pre, (pb, pnb, st) in beams.items():
        if use_grammar and not accepting(st):
            continue
        lp = _logsumexp2(pb, pnb)
        if lp > best_lp:
            best, best_lp = pre, lp
    if not best:                                          # 문법을 만족하는 경로가 없으면 무제약 결과
        for pre, (pb, pnb, st) in beams.items():
            lp = _logsumexp2(pb, pnb)
            if lp > best_lp:
                best, best_lp = pre, lp
    return list(best), best_lp
