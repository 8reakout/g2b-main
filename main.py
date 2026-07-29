from __future__ import annotations

import html
import json
from datetime import datetime
from pathlib import Path
from typing import Any

import yaml
from dotenv import load_dotenv

from email_notifier import send_html_email
from g2b_fetch import Notice, fetch_g2b_notices


BASE_DIR = Path(__file__).resolve().parent


def load_config() -> dict[str, Any]:
    config_path = BASE_DIR / "config.yaml"
    if not config_path.exists():
        config_path = BASE_DIR / "config.example.yaml"

    with config_path.open("r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def load_seen_ids(path: Path) -> set[str]:
    if not path.exists():
        return set()
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return set()
    if isinstance(data, list):
        return {str(x) for x in data}
    return set()


def save_seen_ids(path: Path, ids: set[str]) -> None:
    path.write_text(
        json.dumps(sorted(ids), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def save_latest(path: Path, notices: list[Notice]) -> None:
    path.write_text(
        json.dumps([n.to_dict() for n in notices], ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def _e(value: str) -> str:
    return html.escape(value or "")


def _link(url: str, label: str = "상세보기") -> str:
    if not url:
        return "-"
    return f'<a href="{_e(url)}" target="_blank">{_e(label)}</a>'


def build_html(notices: list[Notice], new_ids: set[str], config: dict[str, Any]) -> str:
    generated_at = datetime.now().strftime("%Y-%m-%d %H:%M")
    keywords = ", ".join(config["g2b"].get("keywords", [])) or "전체"
    new_count = sum(1 for n in notices if n.notice_id in new_ids)

    rows = []
    for idx, n in enumerate(notices, start=1):
        is_new = n.notice_id in new_ids
        badge = '<span class="badge new">NEW</span>' if is_new else '<span class="badge old">EXISTING</span>'
        title = _e(n.title)
        if n.url:
            title = f'<a href="{_e(n.url)}" target="_blank">{title}</a>'

        notice_date = (n.registered_date or "-")[:10]
        rows.append(
            f"""
            <tr>
              <td class="num">{idx}</td>
              <td><div class="title">{title}</div></td>
              <td class="org">{_e(n.demand_org or n.notice_org or '-')}</td>
              <td class="contract">{_e(n.contract_method or '-')}</td>
              <td class="date">{_e(notice_date)}</td>
              <td class="amount">{_e(n.amount or '-')}</td>              
            </tr>
            """
        )

    if not rows:
        rows.append('<tr><td colspan="7" class="empty">조건에 맞는 나라장터 입찰공고가 없습니다.</td></tr>')

    return f"""
<!doctype html>
<html lang="ko">
<head>
<meta charset="utf-8">
<title>나라장터 입찰공고 알림</title>
<style>
  body {{ font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", "Malgun Gothic", sans-serif; color:#222; }}
  .wrap {{ max-width: 1200px; margin: 0 auto; }}
  .summary {{ background:#f6f8fa; border:1px solid #d0d7de; border-radius:8px; padding:16px; margin-bottom:16px; }}
  table {{
    border-collapse: collapse;
    width: 100%;
    font-size: 13px;
    table-layout: fixed;
  }}
  th, td {{
    border:1px solid #d0d7de;
    padding:8px;
    vertical-align: middle;
    word-break: keep-all;
  }}
  th {{
    background:#f6f8fa;
    white-space: nowrap;
  }}
  .num {{
    text-align:center;
    width:60px;
    white-space: nowrap;
  }}
  .title {{
    font-weight:600;
    line-height:1.4;
    word-break: keep-all;
  }}
  .org {{
    width:180px;
    word-break: keep-all;
  }}
  .contract {{
    width:90px;
    text-align:center;
    white-space: nowrap;
  }}
  .date {{
    width:110px;
    text-align:center;
    white-space: nowrap;
  }}
  .amount {{
    width:120px;
    text-align:right;
    white-space: nowrap;
  }}
  .link {{
    width:70px;
    text-align:center;
    white-space: nowrap;
  }}
  .sub {{ color:#666; font-size:12px; margin-top:4px; }}
  .badge {{ display:inline-block; padding:3px 7px; border-radius:999px; font-size:11px; font-weight:700; }}
  .new {{ background:#dbeafe; color:#1d4ed8; }}
  .old {{ background:#f3f4f6; color:#6b7280; }}
  .empty {{ text-align:center; padding:24px; color:#666; }}
</style>
</head>
<body>
<div class="wrap">
  <h2>나라장터 입찰공고 알림</h2>
  <div class="summary">
    <div><b>생성일시:</b> {_e(generated_at)}</div>
    <div><b>검색 키워드:</b> {_e(keywords)}</div>
    <div><b>전체 공고:</b> {len(notices)}건 / <b>신규 공고:</b> {new_count}건</div>
  </div>
  <table>
    <thead>
      <tr>
        <th>No</th>
        <th>공고명</th>
        <th>수요/공고기관</th>
        <th>계약방법</th>
        <th>공고일자</th>
        <th>금액</th>        
      </tr>
    </thead>
    <tbody>
      {''.join(rows)}
    </tbody>
  </table>
</div>
</body>
</html>
"""


def main() -> None:
    load_dotenv(BASE_DIR / ".env")
    config = load_config()

    state_cfg = config.get("state", {})
    seen_file = BASE_DIR / state_cfg.get("seen_file", "seen_bid_ids.json")
    latest_file = BASE_DIR / state_cfg.get("latest_file", "latest_bids.json")
    html_file = BASE_DIR / "g2b_bid_latest.html"

    seen_ids = load_seen_ids(seen_file)
    notices = fetch_g2b_notices(config)

    current_ids = {n.notice_id for n in notices}
    new_ids = current_ids - seen_ids

    save_latest(latest_file, notices)
    html_body = build_html(notices, new_ids, config)
    html_file.write_text(html_body, encoding="utf-8")

    subject = f"[나라장터 입찰공고] 신규 {len(new_ids)}건 / 전체 {len(notices)}건"
    send_html_email(subject, html_body, attachment_path=str(html_file))

    save_seen_ids(seen_file, seen_ids | current_ids)

    print(f"[정보] 신규 공고 수: {len(new_ids)}")
    print(f"[정보] 전체 공고 수: {len(notices)}")
    print(f"[정보] HTML 저장: {html_file}")


if __name__ == "__main__":
    main()
