from __future__ import annotations

import os
import re
import time
import xml.etree.ElementTree as ET
from dataclasses import asdict, dataclass
from datetime import date, datetime, timedelta
from html import unescape
from typing import Any

import requests


@dataclass
class Notice:
    notice_id: str
    title: str
    work_type: str = ""
    notice_org: str = ""
    demand_org: str = ""
    contract_method: str = ""
    bid_method: str = ""
    registered_date: str = ""
    close_date: str = ""
    opening_date: str = ""
    amount: str = ""
    url: str = ""
    keyword: str = ""
    raw: dict[str, Any] | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _strip_html(value: str) -> str:
    value = unescape(value or "")
    value = re.sub(r"(?i)<br\s*/?>", " ", value)
    value = re.sub(r"<[^>]+>", " ", value)
    value = re.sub(r"\s+", " ", value).strip()
    return value


def _first_value(item: dict[str, Any], candidates: list[str]) -> str:
    for key in candidates:
        if key in item and item[key] not in (None, ""):
            return str(item[key]).strip()
    return ""


def _dig_items(data: Any) -> list[dict[str, Any]]:
    """나라장터 JSON 응답에서 실제 item 목록을 찾아냅니다.

    중요:
    나라장터 JSON은 body.items가 바로 list로 내려오는 경우가 있습니다.
    기존 코드처럼 response.body.items.item만 찾으면 item 수가 0으로 나옵니다.
    """
    if isinstance(data, list):
        return [x for x in data if isinstance(x, dict)]

    if not isinstance(data, dict):
        return []

    paths = [
        ["response", "body", "items", "item"],
        ["response", "body", "items"],
        ["body", "items", "item"],
        ["body", "items"],
        ["items", "item"],
        ["items"],
        ["data"],
        ["result"],
        ["list"],
    ]

    for path in paths:
        cur: Any = data
        for key in path:
            if isinstance(cur, dict) and key in cur:
                cur = cur[key]
            else:
                cur = None
                break

        if cur is None:
            continue

        if isinstance(cur, dict):
            return [cur]

        if isinstance(cur, list):
            return [x for x in cur if isinstance(x, dict)]

    return []


def _text_of(parent: ET.Element, path: str) -> str:
    el = parent.find(path)
    if el is None:
        return ""
    return "".join(el.itertext()).strip()


def _parse_xml_items(xml_text: str) -> list[dict[str, Any]]:
    """나라장터 XML 응답에서 body/items/item 목록을 추출합니다."""
    root = ET.fromstring(xml_text)

    result_code = _text_of(root, "./header/resultCode")
    result_msg = _text_of(root, "./header/resultMsg")
    if result_code and result_code not in {"00", "000"}:
        raise RuntimeError(f"G2B API 오류: resultCode={result_code}, resultMsg={result_msg}")

    items: list[dict[str, Any]] = []
    for item_el in root.findall("./body/items/item"):
        item: dict[str, Any] = {}
        for child in list(item_el):
            tag = child.tag.split("}")[-1]
            item[tag] = unescape("".join(child.itertext()).strip())
        if item:
            items.append(item)
    return items


def _normalize_date(value: str) -> str:
    value = _strip_html(value)
    if not value:
        return ""

    value = value.replace("T", " ")
    value = value.replace(".", "-").replace("/", "-")
    value = re.sub(r"\s+", " ", value).strip()

    if re.fullmatch(r"\d{12,14}", value):
        return f"{value[:4]}-{value[4:6]}-{value[6:8]} {value[8:10]}:{value[10:12]}"

    if re.fullmatch(r"\d{8}", value):
        return f"{value[:4]}-{value[4:6]}-{value[6:8]}"

    match = re.match(r"(20\d{2})-(\d{1,2})-(\d{1,2})(?:\s+(\d{1,2}):(\d{1,2}))?", value)
    if match:
        y, m, d, hh, mm = match.groups()
        date_part = f"{y}-{int(m):02d}-{int(d):02d}"
        if hh and mm:
            return f"{date_part} {int(hh):02d}:{int(mm):02d}"
        return date_part

    return value


def _date_part(value: str) -> date | None:
    value = _normalize_date(value)
    if not value:
        return None
    value = value[:10]
    try:
        return datetime.strptime(value, "%Y-%m-%d").date()
    except ValueError:
        return None


def _datetime_value(value: str) -> datetime | None:
    """나라장터 날짜/일시 문자열을 datetime으로 변환합니다."""
    value = _normalize_date(value)
    if not value:
        return None

    formats = [
        "%Y-%m-%d %H:%M:%S",
        "%Y-%m-%d %H:%M",
        "%Y-%m-%d",
    ]

    for fmt in formats:
        try:
            return datetime.strptime(value, fmt)
        except ValueError:
            continue

    return None


def _format_amount(value: str) -> str:
    value = (value or "").strip()
    if not value:
        return ""
    try:
        num = int(float(value.replace(",", "")))
        return f"{num:,}원"
    except ValueError:
        return value


def _contains_keyword(text: str, keywords: list[str]) -> bool:
    keywords = [str(k).strip() for k in keywords if str(k).strip()]
    if not keywords:
        return True
    text_l = (text or "").lower()
    return any(k.lower() in text_l for k in keywords)


def _find_matched_keyword_in_title(title: str, keywords: list[str]) -> str:
    """공고명에 포함된 첫 번째 키워드를 반환합니다."""
    keywords = [str(k).strip() for k in keywords if str(k).strip()]
    if not keywords:
        return ""

    title_l = (title or "").lower()
    for keyword in keywords:
        if keyword.lower() in title_l:
            return keyword
    return ""


def _normalize_title_for_dedup(title: str) -> str:
    """공고명 중복 제거용 정규화 함수입니다.

    같은 공고명이 여러 페이지/조건에서 반복 수집될 경우 1건만 남기기 위해 사용합니다.
    """
    title = _strip_html(title or "")
    title = re.sub(r"\s+", " ", title).strip()
    return title.lower()


def _notice_sort_key_for_keep(notice: Notice) -> tuple[str, str, str]:
    """중복 공고명 중 어떤 항목을 남길지 판단하기 위한 정렬 키입니다.

    등록일, 마감일, 공고번호가 더 큰 값을 우선 보존합니다.
    """
    return (
        notice.registered_date or "0000-00-00",
        notice.close_date or "0000-00-00",
        notice.notice_id or "",
    )


def _is_active_notice(close_date: str, *, keep_unknown_deadline: bool = True) -> bool:
    """마감일이 지난 공고를 제외합니다.

    keep_unknown_deadline=True이면 마감일을 파싱할 수 없는 공고는 포함합니다.
    나라장터 일부 공고는 마감일 필드가 비어 내려올 수 있어 기본값은 포함으로 둡니다.
    config.yaml에서 keep_unknown_deadline: false로 두면 마감일이 없는 공고도 제외합니다.
    """
    close = _date_part(close_date)
    if close is None:
        return keep_unknown_deadline
    return close >= date.today()


def request_with_retry(api_url: str, params: dict[str, Any], max_retries: int = 3) -> requests.Response:
    last_error: Exception | None = None

    safe_params = dict(params)
    if "serviceKey" in safe_params:
        safe_params["serviceKey"] = "***"
    if "ServiceKey" in safe_params:
        safe_params["ServiceKey"] = "***"

    for attempt in range(1, max_retries + 1):
        try:
            print(f"[정보] 나라장터 API 요청 시도: {attempt}/{max_retries}")
            response = requests.get(
                api_url,
                params=params,
                timeout=30,
                headers={
                    "User-Agent": "Mozilla/5.0 GovMonitoringBot/1.0",
                    "Accept": "application/json, application/xml, text/xml, text/plain, */*",
                },
            )
            response.raise_for_status()
            return response
        except requests.exceptions.RequestException as exc:
            last_error = exc
            print(f"[경고] 나라장터 API 요청 실패: {attempt}/{max_retries} - {exc}")
            if attempt < max_retries:
                time.sleep(5 * attempt)

    raise RuntimeError(f"나라장터 API 요청이 {max_retries}회 모두 실패했습니다: {last_error}")


def _build_params(config: dict[str, Any], page_no: int) -> dict[str, Any]:
    gcfg = config["g2b"]
    params_cfg = dict(gcfg.get("params", {}))

    service_key = (
        os.getenv("G2B_SERVICE_KEY")
        or os.getenv("DATA_GO_KR_SERVICE_KEY")
        or gcfg.get("service_key", "")
    ).strip()
    if not service_key:
        raise ValueError("G2B_SERVICE_KEY 또는 DATA_GO_KR_SERVICE_KEY 값이 없습니다.")

    lookback_days = int(gcfg.get("lookback_days", 30))
    today = date.today()
    begin = today - timedelta(days=lookback_days)

    num_of_rows = int(params_cfg.get("numOfRows", 100))
    if num_of_rows > 100:
        print(f"[경고] numOfRows={num_of_rows}는 너무 클 수 있어 100으로 조정합니다.")
        num_of_rows = 100

    params: dict[str, Any] = {
        "serviceKey": service_key,
        "pageNo": page_no,
        "numOfRows": num_of_rows,
        "type": str(params_cfg.get("type", "json")),
        "inqryDiv": str(params_cfg.get("inqryDiv", "1")),
        "inqryBgnDt": params_cfg.get("inqryBgnDt") or begin.strftime("%Y%m%d0000"),
        "inqryEndDt": params_cfg.get("inqryEndDt") or today.strftime("%Y%m%d2359"),
    }

    # 중요: bidNtceNm 키워드 검색조건은 넣지 않습니다.
    # API에서 먼저 목록을 가져온 뒤 Python에서 공고명 포함 여부를 필터링합니다.
    for key, value in params_cfg.items():
        if key == "bidNtceNm":
            continue
        if key not in params and value not in (None, ""):
            params[key] = value

    return params


def _convert_item_to_notice(
    item: dict[str, Any],
    work_type: str,
    matched_keyword: str,
    config: dict[str, Any],
) -> Notice | None:
    gcfg = config["g2b"]
    active_only = bool(gcfg.get("active_only", True))
    include_keywords = [str(x).strip() for x in gcfg.get("include_keywords", []) if str(x).strip()]
    exclude_keywords = [str(x).strip() for x in gcfg.get("exclude_keywords", []) if str(x).strip()]

    title = _strip_html(_first_value(item, ["bidNtceNm", "bidNm", "ntceNm", "title", "공고명"]))
    if not title:
        return None

    combined_text = " ".join(str(v) for v in item.values() if v is not None)
    if include_keywords and not _contains_keyword(combined_text, include_keywords):
        return None
    if exclude_keywords and _contains_keyword(combined_text, exclude_keywords):
        return None

    bid_no = _first_value(item, ["bidNtceNo", "bidNo", "입찰공고번호"])
    bid_ord = _first_value(item, ["bidNtceOrd", "bidOrd", "차수"])
    notice_id = "-".join(x for x in [bid_no, bid_ord] if x) or _first_value(item, ["id", "seq", "link"])

    registered_date = _normalize_date(_first_value(item, ["bidNtceDt", "ntceDt", "rgstDt", "등록일"]))
    # 입찰/제안 마감일시. 일부 공고는 bidClseDt가 비어 있고
    # 입찰참가자격등록마감일시 또는 공동수급협정마감일시만 내려오는 경우가 있어 보조 필드까지 확인합니다.
    close_date = _normalize_date(
        _first_value(
            item,
            [
                "bidClseDt",
                "bidClseDate",
                "bidNtceClseDt",
                "clseDt",
                "prposRcptClseDt",
                "proposalClseDt",
                "cmmnSpldmdAgrmntClseDt",
                "bidQlfctRgstDt",
                "마감일",
                "입찰마감일시",
                "제안서마감일시",
            ],
        )
    )
    opening_date = _normalize_date(_first_value(item, ["opengDt", "openDt", "개찰일시"]))

    opening_dt = _datetime_value(opening_date)

    # 개찰일시(opengDt)가 API 실행일보다 이전 날짜이면 제외합니다.
    # 예: 오늘이 2026-07-29일 때 opengDt가 2026-07-28이면 제외,
    #     2026-07-29 또는 이후이면 포함합니다.
    if opening_dt is not None and opening_dt.date() < date.today():
        return None

    keep_unknown_deadline = bool(gcfg.get("keep_unknown_deadline", True))
    if active_only and not _is_active_notice(close_date, keep_unknown_deadline=keep_unknown_deadline):
        return None

    url = _first_value(item, ["bidNtceDtlUrl", "bidNtceUrl", "detailUrl", "url", "link"])
    url = unescape(url or "").strip()

    if not notice_id:
        notice_id = f"{title}|{close_date}|{url}"

    amount = _format_amount(_first_value(item, ["asignBdgtAmt", "presmptPrce", "budget", "추정가격", "배정예산액"]))

    return Notice(
        notice_id=notice_id,
        title=title,
        work_type=work_type,
        notice_org=_strip_html(_first_value(item, ["ntceInsttNm", "ntceInsttName", "공고기관"])),
        demand_org=_strip_html(_first_value(item, ["dminsttNm", "dmndInsttNm", "수요기관"])),
        contract_method=_strip_html(_first_value(item, ["cntrctCnclsMthdNm", "cntrctMthdNm", "계약방법"])),
        bid_method=_strip_html(_first_value(item, ["bidMethdNm", "bidMthdNm", "입찰방식"])),
        registered_date=registered_date,
        close_date=close_date,
        opening_date=opening_date,
        amount=amount,
        url=url,
        keyword=matched_keyword,
        raw=item,
    )


def _extract_items_from_response(response: requests.Response, debug_response: bool = False) -> list[dict[str, Any]]:
    text = response.text.strip()

    if debug_response:
        safe_url = re.sub(r"(serviceKey=)[^&]+", r"\1***", response.url)
        print("[디버그] 요청 URL:", safe_url)
        print("[디버그] 응답 앞부분:", text[:1200])

    if text.startswith("<"):
        return _parse_xml_items(text)

    try:
        data = response.json()
    except Exception as exc:
        raise RuntimeError(
            "나라장터 API 응답이 JSON/XML 형식이 아닙니다. 응답 앞부분: " + text[:500]
        ) from exc

    return _dig_items(data)


def _operation_candidates(operation: str) -> list[str]:
    operation = operation.strip().lstrip("/")
    candidates = [operation]
    if operation and not operation.endswith("PPSSrch"):
        candidates.append(operation + "PPSSrch")
    return candidates


def fetch_g2b_notices(config: dict[str, Any]) -> list[Notice]:
    """나라장터 입찰공고 목록을 가져온 뒤 공고명 기준 키워드 포함 여부로 필터링합니다."""
    gcfg = config["g2b"]
    base_url = gcfg.get("api_base_url", "").strip().rstrip("/")
    if not base_url:
        raise ValueError("config.yaml의 g2b.api_base_url 값이 비어 있습니다.")

    keywords = [str(x).strip() for x in gcfg.get("keywords", []) if str(x).strip()]
    max_pages = int(gcfg.get("max_pages", 5))
    debug_response = bool(gcfg.get("debug_response", False))

    work_types = gcfg.get("work_types", [])
    if not work_types:
        raise ValueError("config.yaml의 g2b.work_types 값이 비어 있습니다.")

    all_notices: list[Notice] = []

    for work_type in work_types:
        if work_type.get("enabled") is False:
            continue

        work_type_name = str(work_type.get("name", "")).strip()
        operation = str(work_type.get("operation", "")).strip().lstrip("/")
        if not operation:
            continue

        work_type_raw_item_count = 0
        work_type_match_count = 0

        for operation_name in _operation_candidates(operation):
            api_url = f"{base_url}/{operation_name}"
            operation_raw_count = 0
            operation_match_count = 0

            for page_no in range(1, max_pages + 1):
                params = _build_params(config, page_no=page_no)

                print(
                    f"[정보] 나라장터 {work_type_name} 목록 조회 시작: "
                    f"operation={operation_name}, pageNo={page_no}, numOfRows={params['numOfRows']}"
                )

                try:
                    response = request_with_retry(api_url, params=params, max_retries=3)
                    items = _extract_items_from_response(response, debug_response=debug_response)
                except Exception as exc:
                    print(f"[경고] 나라장터 {work_type_name} operation={operation_name} pageNo={page_no} 조회 실패: {exc}")
                    break

                operation_raw_count += len(items)
                work_type_raw_item_count += len(items)

                print(
                    f"[정보] 나라장터 {work_type_name} operation={operation_name} "
                    f"pageNo={page_no} 원본 item 수: {len(items)}"
                )

                if not items:
                    print("[정보] 응답 item이 없어 해당 업무구분의 다음 페이지 조회를 중단합니다.")
                    break

                page_count = 0
                for item in items:
                    title = _strip_html(_first_value(item, ["bidNtceNm", "bidNm", "ntceNm", "title", "공고명"]))
                    matched_keyword = _find_matched_keyword_in_title(title, keywords)

                    # keywords가 설정된 경우 공고명에 키워드가 포함된 것만 남깁니다.
                    if keywords and not matched_keyword:
                        continue

                    notice = _convert_item_to_notice(item, work_type_name, matched_keyword, config)
                    if notice is not None:
                        all_notices.append(notice)
                        page_count += 1

                operation_match_count += page_count
                work_type_match_count += page_count

                print(
                    f"[정보] 나라장터 {work_type_name} operation={operation_name} "
                    f"pageNo={page_no} 공고명 키워드 필터 후 공고 수: {page_count}"
                )

                if len(items) < int(params["numOfRows"]):
                    print("[정보] 마지막 페이지로 판단되어 해당 업무구분의 조회를 중단합니다.")
                    break

            print(
                f"[정보] 나라장터 {work_type_name} operation={operation_name} "
                f"원본 {operation_raw_count}건 / 키워드 매칭 {operation_match_count}건"
            )

            # 기본 operation에서 원본 item이 있으면 PPSSrch 보조 operation은 중복 조회 방지를 위해 생략합니다.
            if operation_raw_count > 0:
                break

        if work_type_raw_item_count == 0:
            print(
                f"[경고] 나라장터 {work_type_name} 업무구분에서 원본 item이 0건입니다. "
                "api_base_url, operation, 인증키, 조회기간, numOfRows 값을 확인하세요."
            )
        else:
            print(
                f"[정보] 나라장터 {work_type_name} 업무구분 합계: "
                f"원본 {work_type_raw_item_count}건 / 키워드 매칭 {work_type_match_count}건"
            )

    # 1차: 공고번호 기준 중복 제거
    deduped_by_id: dict[str, Notice] = {}
    duplicate_id_count = 0

    for notice in all_notices:
        if notice.notice_id in deduped_by_id:
            duplicate_id_count += 1
            # 같은 공고번호가 다시 들어오면 더 최신으로 보이는 항목을 남깁니다.
            if _notice_sort_key_for_keep(notice) > _notice_sort_key_for_keep(deduped_by_id[notice.notice_id]):
                deduped_by_id[notice.notice_id] = notice
        else:
            deduped_by_id[notice.notice_id] = notice

    # 2차: 공고명 기준 중복 제거
    # 같은 공고명이 여러 번 수집되면 HTML/메일에는 1건만 표시합니다.
    deduped_by_title: dict[str, Notice] = {}
    duplicate_title_count = 0

    for notice in deduped_by_id.values():
        title_key = _normalize_title_for_dedup(notice.title)

        if not title_key:
            continue

        if title_key in deduped_by_title:
            duplicate_title_count += 1
            # 같은 공고명이라도 등록일/마감일이 더 최신인 항목을 남깁니다.
            if _notice_sort_key_for_keep(notice) > _notice_sort_key_for_keep(deduped_by_title[title_key]):
                deduped_by_title[title_key] = notice
            continue

        deduped_by_title[title_key] = notice

    notices = sorted(
        deduped_by_title.values(),
        key=lambda n: (n.registered_date or "0000-00-00", n.title),
        reverse=True,
    )

    print(f"[정보] 나라장터 공고번호 중복 제외 수: {duplicate_id_count}")
    print(f"[정보] 나라장터 공고명 중복 제외 수: {duplicate_title_count}")
    print(f"[정보] 나라장터 공고번호 기준 수집 수: {len(deduped_by_id)}")
    print(f"[정보] 나라장터 최종 수집 공고 수: {len(notices)}")
    return notices
