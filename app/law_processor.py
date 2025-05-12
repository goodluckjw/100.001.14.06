import requests
import xml.etree.ElementTree as ET
from urllib.parse import quote
import re
import os
import unicodedata
from collections import defaultdict

# API 설정
OC = os.getenv("OC", "chetera")
BASE = "http://www.law.go.kr"

# 법령 목록 검색
def get_law_list_from_api(query):
    encoded_query = quote(f'"{query}"')
    page, laws = 1, []
    while True:
        url = f"{BASE}/DRF/lawSearch.do?OC={OC}&target=law&type=XML&display=100&page={page}&search=2&knd=A0002&query={encoded_query}"
        res = requests.get(url, timeout=10)
        res.encoding = 'utf-8'
        if res.status_code != 200:
            break
        root = ET.fromstring(res.content)
        for law in root.findall("law"):
            laws.append({
                "법령명": law.findtext("법령명한글", "").strip(),
                "MST": law.findtext("법령일련번호", "")
            })
        if len(root.findall("law")) < 100:
            break
        page += 1
    return laws

# 법령 본문 조회
def get_law_text_by_mst(mst):
    url = f"{BASE}/DRF/lawService.do?OC={OC}&target=law&MST={mst}&type=XML"
    try:
        res = requests.get(url, timeout=10)
        res.encoding = 'utf-8'
        return res.content if res.status_code == 200 else None
    except:
        return None

# 유틸 함수
def clean(text):
    return re.sub(r"\s+", "", text or "")

def has_batchim(word):
    return (ord(word[-1]) - 0xAC00) % 28 != 0

def has_rieul_batchim(word):
    return (ord(word[-1]) - 0xAC00) % 28 == 8

def extract_chunk_and_josa(token, searchword):
    suffixes = ["으로", "이나", "과", "와", "을", "를", "이", "가", "나", "로", "은", "는"]
    pattern = re.compile(rf'({searchword})(?:{"|".join(suffixes)})?$')
    m = pattern.match(token)
    if m:
        return m.group(1), token[len(searchword):] if token[len(searchword):] in suffixes else None
    return token, None

def group_locations(locs):
    if len(locs) == 1:
        return locs[0]
    return 'ㆍ'.join(locs[:-1]) + ' 및 ' + locs[-1]

# 조사 규칙 적용
def apply_josa_rule(orig_chunk, replace_chunk, josa):
    b_batchim = has_batchim(replace_chunk)
    b_rieul = has_rieul_batchim(replace_chunk)

    if josa is None:
        if not has_batchim(orig_chunk):
            return f'“{orig_chunk}”를 “{replace_chunk}”로 한다.' if not b_batchim or b_rieul else f'“{orig_chunk}”를 “{replace_chunk}”으로 한다.'
        else:
            return f'“{orig_chunk}”을 “{replace_chunk}”로 한다.' if not b_batchim or b_rieul else f'“{orig_chunk}”을 “{replace_chunk}”으로 한다.'

    # 추가 규칙 적용
    rules = {
        "을": lambda: f'“{orig_chunk}”을 “{replace_chunk}”로 한다.' if b_rieul else f'“{orig_chunk}”을 “{replace_chunk}”으로 한다.' if b_batchim else f'“{orig_chunk}을”을 “{replace_chunk}를”로 한다.',
        "를": lambda: f'“{orig_chunk}를”을 “{replace_chunk}을”로 한다.' if b_batchim else f'“{orig_chunk}”를 “{replace_chunk}”로 한다.',
        "과": lambda: f'“{orig_chunk}과”를 “{replace_chunk}와”로 한다.' if not b_batchim else f'“{orig_chunk}”을 “{replace_chunk}”로 한다.',
        "와": lambda: f'“{orig_chunk}와”를 “{replace_chunk}과”로 한다.' if b_batchim else f'“{orig_chunk}”를 “{replace_chunk}”로 한다.',
        "이": lambda: f'“{orig_chunk}이”를 “{replace_chunk}가”로 한다.' if not b_batchim else f'“{orig_chunk}”을 “{replace_chunk}”로 한다.',
        "가": lambda: f'“{orig_chunk}가”를 “{replace_chunk}이”로 한다.' if b_batchim else f'“{orig_chunk}”를 “{replace_chunk}”로 한다.',
        "이나": lambda: f'“{orig_chunk}이나”를 “{replace_chunk}나”로 한다.' if not b_batchim else f'“{orig_chunk}”을 “{replace_chunk}”로 한다.',
        "나": lambda: f'“{orig_chunk}나”를 “{replace_chunk}이나”로 한다.' if b_batchim else f'“{orig_chunk}”를 “{replace_chunk}”로 한다.',
        "으로": lambda: f'“{orig_chunk}으로”를 “{replace_chunk}로”로 한다.' if not b_batchim or b_rieul else f'“{orig_chunk}”을 “{replace_chunk}”으로 한다.',
        "로": lambda: f'“{orig_chunk}로”를 “{replace_chunk}으로”로 한다.' if b_batchim and not b_rieul else f'“{orig_chunk}”를 “{replace_chunk}”로 한다.',
        "는": lambda: f'“{orig_chunk}는”을 “{replace_chunk}은”으로 한다.' if b_batchim else f'“{orig_chunk}”를 “{replace_chunk}”로 한다.',
        "은": lambda: f'“{orig_chunk}은”을 “{replace_chunk}는”으로 한다.' if not b_batchim else f'“{orig_chunk}”을 “{replace_chunk}”로 한다.'
    }
    return rules.get(josa, lambda: f'“{orig_chunk}”를 “{replace_chunk}”로 한다.')()

# 검색 기능
def run_search_logic(query, unit="법률"):
    # 구현 내용 생략 (기존 코드 사용 가능)
    pass

# 개정문 생성
def run_amendment_logic(find_word, replace_word):
    amendment_results = []
    for idx, law in enumerate(get_law_list_from_api(find_word)):
        law_name = law["법령명"]
        mst = law["MST"]
        xml_data = get_law_text_by_mst(mst)
        if not xml_data:
            continue
        tree = ET.fromstring(xml_data)
        articles = tree.findall(".//조문단위")
        chunk_map = defaultdict(list)

        for article in articles:
            조번호 = article.findtext("조문번호", "").strip()
            조가지번호 = article.findtext("조문가지번호", "").strip()
            조문식별자 = f"제{조번호}조" + (f"의{조가지번호}" if 조가지번호 else "")
            조문내용 = article.findtext("조문내용", "") or ""
            tokens = re.findall(r'[가-힣A-Za-z0-9]+', 조문내용)
            for token in tokens:
                if find_word in token:
                    chunk, josa = extract_chunk_and_josa(token, find_word)
                    chunk_map[(chunk, replace_word, josa)].append(조문식별자)

        if not chunk_map:
            continue

        parts = []
        for (chunk, replacement, josa), locs in chunk_map.items():
            loc_str = group_locations(locs)
            amendment = apply_josa_rule(chunk, replacement, josa)
            parts.append(f'{loc_str} 중 {amendment}')

        prefix = chr(9312 + idx) if idx < 20 else f'({idx + 1})'
        amendment_results.append(f'{prefix} {law_name} 일부를 다음과 같이 개정한다.\n' + '\n'.join(parts))

    return amendment_results if amendment_results else ["⚠️ 개정 대상 조문이 없습니다."]
