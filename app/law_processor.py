import requests
import xml.etree.ElementTree as ET
from urllib.parse import quote
import re
import os
import unicodedata
from collections import defaultdict

OC = os.getenv("OC", "chetera")
BASE = "http://www.law.go.kr"

def get_law_list_from_api(query):
    exact_query = f'"{query}"'
    encoded_query = quote(exact_query)
    page = 1
    laws = []
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

def get_law_text_by_mst(mst):
    url = f"{BASE}/DRF/lawService.do?OC={OC}&target=law&MST={mst}&type=XML"
    try:
        res = requests.get(url, timeout=10)
        res.encoding = 'utf-8'
        return res.content if res.status_code == 200 else None
    except:
        return None

def has_batchim(word):
    code = ord(word[-1]) - 0xAC00
    return (code % 28) != 0

def has_rieul_batchim(word):
    code = ord(word[-1]) - 0xAC00
    return (code % 28) == 8

def apply_josa_rule(orig_chunk, replace_chunk, josa):
    b_has_batchim = has_batchim(replace_chunk)
    b_has_rieul = has_rieul_batchim(replace_chunk)
    if josa is None:
        if has_batchim(orig_chunk):
            return f'“{orig_chunk}”을 “{replace_chunk}”로 한다.'
        else:
            return f'“{orig_chunk}”를 “{replace_chunk}”로 한다.'
    rules = {
        "을": lambda: f'“{orig_chunk}”을 “{replace_chunk}”{"로" if b_has_rieul else "으로"} 한다.' if has_batchim(orig_chunk) else f'“{orig_chunk}을”을 “{replace_chunk}를”로 한다.',
        "를": lambda: f'“{orig_chunk}를”을 “{replace_chunk}을”로 한다.' if has_batchim(orig_chunk) else f'“{orig_chunk}”를 “{replace_chunk}”로 한다.',
        "과": lambda: f'“{orig_chunk}”과 “{replace_chunk}”로 한다.' if has_batchim(orig_chunk) else f'“{orig_chunk}과”를 “{replace_chunk}와”로 한다.',
        "와": lambda: f'“{orig_chunk}와”를 “{replace_chunk}과”로 한다.' if has_batchim(orig_chunk) else f'“{orig_chunk}”를 “{replace_chunk}”로 한다.',
        "이": lambda: f'“{orig_chunk}”을 “{replace_chunk}”로 한다.' if has_batchim(orig_chunk) else f'“{orig_chunk}이”를 “{replace_chunk}가”로 한다.',
        "가": lambda: f'“{orig_chunk}가”를 “{replace_chunk}이”로 한다.' if has_batchim(orig_chunk) else f'“{orig_chunk}”를 “{replace_chunk}”로 한다.',
        "이나": lambda: f'“{orig_chunk}이나”를 “{replace_chunk}나”로 한다.' if not b_has_batchim else f'“{orig_chunk}”을 “{replace_chunk}”로 한다.',
        "나": lambda: f'“{orig_chunk}나”를 “{replace_chunk}이나”로 한다.' if b_has_batchim else f'“{orig_chunk}”를 “{replace_chunk}”로 한다.',
        "으로": lambda: f'“{orig_chunk}으로”를 “{replace_chunk}로”로 한다.' if not b_has_batchim or b_has_rieul else f'“{orig_chunk}”을 “{replace_chunk}”으로 한다.',
        "로": lambda: f'“{orig_chunk}로”를 “{replace_chunk}으로”로 한다.' if has_batchim(orig_chunk) and not has_rieul_batchim(orig_chunk) else f'“{orig_chunk}”를 “{replace_chunk}”로 한다.',
        "는": lambda: f'“{orig_chunk}는”을 “{replace_chunk}은”으로 한다.' if b_has_batchim else f'“{orig_chunk}”를 “{replace_chunk}”로 한다.',
        "은": lambda: f'“{orig_chunk}은”을 “{replace_chunk}는”으로 한다.' if not b_has_batchim else f'“{orig_chunk}”을 “{replace_chunk}”로 한다.',
    }
    return rules.get(josa, lambda: f'“{orig_chunk}”를 “{replace_chunk}”로 한다.')()

def extract_chunk_and_josa(text, searchword):
    josa_list = ["으로", "이나", "과", "와", "을", "를", "이", "가", "나", "로", "은", "는"]
    pattern = re.compile(rf'({re.escape(searchword)})(?P<josa>{"|".join(josa_list)})?')
    match = pattern.search(text)
    if match:
        return match.group(1), match.group("josa")
    return searchword, None

def group_locations(locs):
    if len(locs) == 1:
        return locs[0]
    return 'ㆍ'.join(locs[:-1]) + ' 및 ' + locs[-1]

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
            조문식별자 = f"제{조번호}조" if not 조가지번호 else f"제{조번호}조의{조가지번호}"
            조문내용 = article.findtext("조문내용", "")
            tokens = re.findall(r'[가-힣A-Za-z0-9]+', 조문내용)
            for token in tokens:
                if find_word in token:
                    chunk, josa = extract_chunk_and_josa(token, find_word)
                    바꿀덩어리 = chunk.replace(find_word, replace_word)
                    chunk_map[(chunk, 바꿀덩어리, josa)].append(조문식별자)
        if not chunk_map:
            continue
        parts = []
        for (chunk, 바꿀덩어리, josa), loc_list in chunk_map.items():
            loc_str = group_locations(loc_list)
            amendment = apply_josa_rule(chunk, 바꿀덩어리, josa)
            parts.append(f'{loc_str} 중 {amendment}')
        prefix = chr(9312 + idx) if idx < 20 else f'({idx + 1})'
        amendment_results.append(f'{prefix} {law_name} 일부를 다음과 같이 개정한다.\n' + '\n'.join(parts))
    return amendment_results if amendment_results else ["⚠️ 개정 대상 조문이 없습니다."]


def run_search_logic(query, unit="법률"):
    result_dict = {}
    keyword_clean = clean(query)

    for law in get_law_list_from_api(query):
        mst = law["MST"]
        xml_data = get_law_text_by_mst(mst)
        if not xml_data:
            continue

        tree = ET.fromstring(xml_data)
        articles = tree.findall(".//조문단위")
        law_results = []

        for article in articles:
            조번호 = article.findtext("조문번호", "").strip()
            조가지번호 = article.findtext("조문가지번호", "").strip()
            조문식별자 = make_article_number(조번호, 조가지번호)
            조문내용 = article.findtext("조문내용", "") or ""
            항들 = article.findall("항")
            출력덩어리 = []
            조출력 = keyword_clean in clean(조문내용)
            첫_항출력됨 = False

            if 조출력:
                출력덩어리.append(highlight(조문내용, query))

            for 항 in 항들:
                항번호 = normalize_number(항.findtext("항번호", "").strip())
                항내용 = 항.findtext("항내용", "") or ""
                항출력 = keyword_clean in clean(항내용)
                항덩어리 = []
                하위검색됨 = False

                for 호 in 항.findall("호"):
                    호내용 = 호.findtext("호내용", "") or ""
                    호출력 = keyword_clean in clean(호내용)
                    if 호출력:
                        하위검색됨 = True
                        항덩어리.append("&nbsp;&nbsp;" + highlight(호내용, query))

                    for 목 in 호.findall("목"):
                        for m in 목.findall("목내용"):
                            if m.text and keyword_clean in clean(m.text):
                                줄들 = [line.strip() for line in m.text.splitlines() if line.strip()]
                                줄들 = [highlight(line, query) for line in 줄들]
                                if 줄들:
                                    하위검색됨 = True
                                    항덩어리.append(
                                        "<div style='margin:0;padding:0'>" +
                                        "<br>".join("&nbsp;&nbsp;&nbsp;&nbsp;" + line for line in 줄들) +
                                        "</div>"
                                    )

                if 항출력 or 하위검색됨:
                    if not 조출력 and not 첫_항출력됨:
                        출력덩어리.append(f"{highlight(조문내용, query)} {highlight(항내용, query)}")
                        첫_항출력됨 = True
                    elif not 첫_항출력됨:
                        출력덩어리.append(highlight(항내용, query))
                        첫_항출력됨 = True
                    else:
                        출력덩어리.append(highlight(항내용, query))
                    출력덩어리.extend(항덩어리)

            if 출력덩어리:
                law_results.append("<br>".join(출력덩어리))

        if law_results:
            result_dict[law["법령명"]] = law_results

    return result_dict
