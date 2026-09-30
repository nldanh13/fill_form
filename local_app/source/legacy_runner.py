#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from __future__ import annotations

import csv
import hashlib
import json
import random
import re
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Set, Tuple

try:
    from playwright.sync_api import Locator, Page, sync_playwright
except Exception:  # Cho phép quản lý dữ liệu/chạy thử trước khi cài trình duyệt.
    Locator = Page = Any  # type: ignore
    sync_playwright = None  # type: ignore

ROOT = Path(__file__).resolve().parent
JOBS_CSV = ROOT / "jobs.csv"
PROFILE_JSON = ROOT / "profile.json"
ROSTER_JSON = ROOT / "roster.json"
COMMENT_BANK_JSON = ROOT / "comment_bank.json"
STAFF_LISTS_JSON = ROOT / "staff_lists.json"
DEPARTMENT_VALUES_JSON = ROOT / "department_values.json"
PROGRESS_DIR = ROOT / "progress"
HISTORY_DIR = ROOT / "history"
BROWSER_PROFILE_DIR = ROOT / ".pw_profile"
LAST_RESPONSE_HTML = ROOT / "last_submit_response.html"
LAST_PAGE_HTML = ROOT / "last_page_dump.html"

DEFAULT_SUCCESS_TEXT = "Hệ thống đã ghi lại câu trả lời của bạn"
DEFAULT_WAIT_RANGE_MS = (900, 1800)

DEFAULT_DEPARTMENT_ALIASES = {
    "CHẤN THƯƠNG CHỈNH HÌNH": "CTCH",
    "CTCH": "CTCH",
    "NGOẠI TH": "NGOẠI TH",
    "NỘI TH": "NỘI TH",
    "TMCT - TK": "TMCT - TK",
    "TIM MẠCH CAN THIỆP – TK": "TMCT - TK",
    "TIẾT NIỆU": "TIẾT NIỆU",
    "KHOA NIỆU": "TIẾT NIỆU",
    "TT TIẾT NIỆU": "TIẾT NIỆU",
    "GMHS": "GMHS",
    "GÂY MÊ HỒI SỨC": "GMHS",
    "CC - HSTC": "CC - HSTC",
    "CẤP CỨU – HSTC": "CC - HSTC",
    "PHỤ SẢN": "PHỤ SẢN",
    "UNG BƯỚU": "UNG BƯỚU",
    "MẮT - TMH": "MẮT - TMH",
}

_DEPARTMENT_VALUES_CACHE: Optional[Dict[str, Any]] = None


def load_department_values() -> Dict[str, Any]:
    global _DEPARTMENT_VALUES_CACHE
    if _DEPARTMENT_VALUES_CACHE is not None:
        return _DEPARTMENT_VALUES_CACHE

    data: Dict[str, Any] = {
        "aliases": dict(DEFAULT_DEPARTMENT_ALIASES),
        "display_values": {"_default": {}},
    }
    if DEPARTMENT_VALUES_JSON.exists():
        raw = load_json(DEPARTMENT_VALUES_JSON)
        if not isinstance(raw, dict):
            raise ConfigError("department_values.json phải là object JSON")
        aliases = raw.get("aliases") or {}
        if isinstance(aliases, dict):
            for k, v in aliases.items():
                key = str(k or "").strip().upper()
                val = str(v or "").strip().upper()
                if key and val:
                    data["aliases"][key] = val
        display_values = raw.get("display_values") or {}
        if isinstance(display_values, dict):
            cleaned_display: Dict[str, Dict[str, str]] = {}
            for form_id, mapping in display_values.items():
                if not isinstance(mapping, dict):
                    continue
                cleaned_display[str(form_id).strip()] = {
                    normalize_department_key(k, data["aliases"]): str(v).strip()
                    for k, v in mapping.items()
                    if str(k).strip() and str(v).strip()
                }
            data["display_values"] = cleaned_display or {"_default": {}}
            data["display_values"].setdefault("_default", {})
    _DEPARTMENT_VALUES_CACHE = data
    return data


def normalize_department_key(value: str, alias_map: Optional[Dict[str, str]] = None) -> str:
    clean = str(value or "").strip().upper()
    aliases = alias_map or load_department_values().get("aliases", DEFAULT_DEPARTMENT_ALIASES)
    return aliases.get(clean, clean)


def get_department_display_value(form_id: str, department: str, cfg: Optional[Dict[str, Any]] = None) -> str:
    canonical = normalize_department_name(department)
    if cfg:
        display_map = cfg.get("department_display_map") or {}
        mapped = display_map.get(canonical) or display_map.get(str(department).strip())
        if mapped:
            return str(mapped)
    values = load_department_values()
    display_values = values.get("display_values", {})
    form_map = display_values.get(str(form_id).strip(), {}) if isinstance(display_values, dict) else {}
    default_map = display_values.get("_default", {}) if isinstance(display_values, dict) else {}
    return str(form_map.get(canonical) or default_map.get(canonical) or canonical)


@dataclass
class Job:
    job_id: str
    config_path: Path
    data_path: Path
    max_success: int


@dataclass
class StaffRecord:
    name: str
    degree: str
    department: str
    list_id: str
    list_title: str


class ConfigError(RuntimeError):
    pass


def load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def save_json(path: Path, obj: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, ensure_ascii=False, indent=2), encoding="utf-8")


def normalize_department_name(value: str) -> str:
    return normalize_department_key(value)


def canonicalize_google_form_url(url: str) -> str:
    url = str(url or "").strip()
    return re.sub(r"(https://docs\.google\.com/forms)/u/\d+/", r"\1/", url)


def build_form_response_url(view_url: str) -> str:
    view_url = canonicalize_google_form_url(view_url)
    if "/viewform" in view_url:
        return view_url.split("/viewform", 1)[0] + "/formResponse"
    return view_url.rstrip("/") + "/formResponse"

def infer_roster_department_from_legacy_fields(fields: List[Dict[str, Any]]) -> str:
    for field in fields:
        if field.get("type") != "dropdown":
            continue
        source = field.get("source", {})
        if "const" not in source:
            continue
        locator = field.get("locator", {})
        label = str(locator.get("value", "")).strip().upper()
        if label in {"ĐƠN VỊ", "KHOA"}:
            return normalize_department_name(source.get("const", ""))
    return ""


def infer_comment_rules_from_legacy_fields(fields: List[Dict[str, Any]]) -> Dict[str, int]:
    for field in fields:
        if field.get("type") != "fill":
            continue
        source = field.get("source", {})
        block = source.get("random_comment")
        if isinstance(block, dict):
            return {
                "k_pros_min": int(block.get("k_pros_min", 2)),
                "k_pros_max": int(block.get("k_pros_max", 2)),
                "k_cons_min": int(block.get("k_cons_min", 1)),
                "k_cons_max": int(block.get("k_cons_max", 1)),
            }
    return {}


def normalize_config(raw_cfg: Dict[str, Any], config_path: Optional[Path] = None) -> Dict[str, Any]:
    cfg = dict(raw_cfg)

    if "form_id" in cfg and "score_fields" in cfg:
        cfg.setdefault("mode", "post")
        cfg.setdefault("title", cfg["form_id"])
        cfg["view_url"] = canonicalize_google_form_url(cfg["view_url"])
        cfg.setdefault("form_response_url", build_form_response_url(cfg["view_url"]))
        cfg["form_response_url"] = canonicalize_google_form_url(cfg["form_response_url"])
        if not cfg.get("roster_department"):
            cfg["roster_department"] = normalize_department_name(cfg.get("fixed_department", ""))
        else:
            cfg["roster_department"] = normalize_department_name(cfg["roster_department"])
        if not cfg.get("allowed_degrees") and cfg.get("choices_degree"):
            cfg["allowed_degrees"] = list(cfg.get("choices_degree") or [])
        cfg.setdefault("comment_rules", {})
        cfg.setdefault("department_source", "fixed")
        cfg.setdefault("list_ids", [])
        cfg.setdefault("allowed_list_ids", [])
        return cfg

    if "id" in cfg and "url" in cfg and "fields" in cfg:
        fields = list(cfg.get("fields") or [])
        score_fields = [f for f in fields if f.get("type") == "radio_in_section"]
        score_count = int(cfg.get("score_count") or len(score_fields))
        roster_department = infer_roster_department_from_legacy_fields(fields)
        comment_rules = infer_comment_rules_from_legacy_fields(fields)
        legacy_view_url = canonicalize_google_form_url(cfg["url"])
        return {
            "mode": "legacy_ui",
            "form_id": cfg["id"],
            "title": cfg.get("title") or cfg["id"],
            "view_url": legacy_view_url,
            "form_response_url": build_form_response_url(legacy_view_url),
            "success_text": cfg.get("success_text", DEFAULT_SUCCESS_TEXT),
            "legacy_fields": fields,
            "legacy_submit_button": cfg.get("submit_button", {}),
            "score_fields": (
                [f.get("section_heading", f"Câu {i}") for i, f in enumerate(score_fields, start=1)]
                if score_fields
                else [f"Câu {i}" for i in range(1, score_count + 1)]
            ),
            "score_min_percent": float(cfg.get("score_min_percent", 0)),
            "score_max_percent": float(cfg.get("score_max_percent", 100)),
            "roster_department": roster_department,
            "fixed_department": next(
                (
                    f.get("source", {}).get("const", "")
                    for f in fields
                    if f.get("type") == "dropdown"
                    and str(f.get("locator", {}).get("value", "")).strip().upper() in {"ĐƠN VỊ", "KHOA"}
                ),
                roster_department,
            ),
            "allowed_degrees": list(cfg.get("allowed_degrees") or []),
            "comment_rules": comment_rules,
            "department_source": str(cfg.get("department_source") or "fixed"),
            "list_ids": list(cfg.get("list_ids") or []),
            "allowed_list_ids": list(cfg.get("allowed_list_ids") or []),
            "multi_page": bool(cfg.get("multi_page", False)),
            "anonymous": bool(cfg.get("anonymous", False)),
        }

    name = config_path.name if config_path else "<unknown>"
    raise ConfigError(f"Config {name} không đúng schema được hỗ trợ")


def load_jobs(path: Path) -> List[Job]:
    rows: List[Job] = []
    with path.open("r", encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        fieldnames = set(reader.fieldnames or [])
        accepted_id_headers = ["job_id", "form_id"]
        id_header = next((h for h in accepted_id_headers if h in fieldnames), None)
        required = {"config_path", "data_path", "max_success"}
        if not id_header or not required.issubset(fieldnames):
            raise ConfigError(
                "jobs.csv phải có một trong các header job_id/form_id cùng với config_path, data_path, max_success"
            )
        for row in reader:
            job_id = str(row.get(id_header, "")).strip()
            if not job_id:
                continue
            rows.append(
                Job(
                    job_id=job_id,
                    config_path=(ROOT / str(row["config_path"]).strip()).resolve(),
                    data_path=(ROOT / str(row["data_path"]).strip()).resolve(),
                    max_success=int(row["max_success"]),
                )
            )
    return rows


def load_rows(path: Path) -> List[Dict[str, str]]:
    if not path.exists():
        raise ConfigError(f"Không tìm thấy file dữ liệu: {path}")
    with path.open("r", encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))


def load_progress(form_id: str) -> Dict[str, Any]:
    path = PROGRESS_DIR / f"{form_id}.json"
    if not path.exists():
        return {"success_count": 0, "submitted_keys": []}
    return load_json(path)


def save_progress(form_id: str, progress: Dict[str, Any]) -> None:
    save_json(PROGRESS_DIR / f"{form_id}.json", progress)


def make_submission_key(
    form_id: str,
    row_index: int,
    scores: List[str],
    department: str,
    list_id: str = "",
    name: str = "",
    degree: str = "",
) -> str:
    raw = (
        f"{form_id}|{department}|{list_id}|{str(name).strip()}|{str(degree).strip()}"
        f"|row={row_index}|{'-'.join(scores)}"
    )
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()


def score_percent(scores: List[str]) -> Tuple[int, int, float]:
    total = sum(int(x) for x in scores)
    maximum = len(scores) * 4
    percent = (total / maximum) * 100 if maximum else 0.0
    return total, maximum, percent


def validate_score_window(scores: List[str], cfg: Dict[str, Any]) -> Tuple[bool, int, int, float]:
    total, maximum, percent = score_percent(scores)
    min_percent = float(cfg.get("score_min_percent", 0))
    max_percent = float(cfg.get("score_max_percent", 100))
    ok = min_percent <= percent <= max_percent
    return ok, total, maximum, percent


def load_staff_lists(roster: Dict[str, Any]) -> Dict[str, Dict[str, Any]]:
    if STAFF_LISTS_JSON.exists():
        raw = load_json(STAFF_LISTS_JSON)
        if not isinstance(raw, dict):
            raise ConfigError("staff_lists.json phải là object JSON")
    else:
        raw = {
            normalize_department_name(dept).lower().replace(" ", "_"): {
                "title": f"Danh sách {normalize_department_name(dept)}",
                "departments": [normalize_department_name(dept)],
            }
            for dept in roster.keys()
        }

    result: Dict[str, Dict[str, Any]] = {}
    for list_id, cfg in raw.items():
        if not isinstance(cfg, dict):
            raise ConfigError(f"Danh sách '{list_id}' trong staff_lists.json phải là object")
        departments = cfg.get("departments")
        if departments is None and cfg.get("department") is not None:
            departments = [cfg.get("department")]
        departments = [normalize_department_name(x) for x in (departments or []) if str(x).strip()]
        if not departments:
            raise ConfigError(f"Danh sách '{list_id}' chưa khai báo departments")
        allowed_degrees = [str(x).strip() for x in (cfg.get("allowed_degrees") or []) if str(x).strip()]
        include_names = {str(x).strip() for x in (cfg.get("include_names") or []) if str(x).strip()}
        exclude_names = {str(x).strip() for x in (cfg.get("exclude_names") or []) if str(x).strip()}
        result[str(list_id).strip()] = {
            "title": str(cfg.get("title") or list_id),
            "departments": departments,
            "allowed_degrees": allowed_degrees,
            "include_names": include_names,
            "exclude_names": exclude_names,
        }
    return result


def get_available_list_ids_for_cfg(cfg: Dict[str, Any], staff_lists: Dict[str, Dict[str, Any]]) -> List[str]:
    explicit_allowed = [str(x).strip() for x in (cfg.get("allowed_list_ids") or []) if str(x).strip()]
    if explicit_allowed:
        missing = [x for x in explicit_allowed if x not in staff_lists]
        if missing:
            raise ConfigError(
                f"Form '{cfg.get('form_id')}' đang tham chiếu allowed_list_ids không tồn tại: {', '.join(missing)}"
            )
        return explicit_allowed

    explicit_default = [str(x).strip() for x in (cfg.get("list_ids") or []) if str(x).strip()]
    missing_defaults = [x for x in explicit_default if x not in staff_lists]
    if missing_defaults:
        raise ConfigError(
            f"Form '{cfg.get('form_id')}' đang tham chiếu list_ids không tồn tại: {', '.join(missing_defaults)}"
        )

    return list(staff_lists.keys())


def get_default_list_ids_for_cfg(cfg: Dict[str, Any], available_list_ids: List[str]) -> List[str]:
    defaults = [str(x).strip() for x in (cfg.get("list_ids") or []) if str(x).strip()]
    filtered = [x for x in defaults if x in available_list_ids]
    return filtered or list(available_list_ids)


def build_staff_pool(roster: Dict[str, Any], staff_lists: Dict[str, Dict[str, Any]], selected_list_ids: List[str], cfg: Dict[str, Any]) -> List[StaffRecord]:
    allowed_degrees_cfg = {str(x).strip() for x in (cfg.get("allowed_degrees") or []) if str(x).strip()}
    allowed_list_ids = set(get_available_list_ids_for_cfg(cfg, staff_lists))
    effective_list_ids = [list_id for list_id in selected_list_ids if list_id in allowed_list_ids]
    if not effective_list_ids:
        raise ConfigError(
            f"Không có danh sách nào phù hợp cho form '{cfg.get('form_id')}'. Hãy kiểm tra allowed_list_ids hoặc lựa chọn danh sách."
        )

    pool: List[StaffRecord] = []
    seen: Set[Tuple[str, str, str, str]] = set()

    for list_id in effective_list_ids:
        if list_id not in staff_lists:
            raise ConfigError(f"Không tìm thấy danh sách '{list_id}' trong staff_lists.json")
        info = staff_lists[list_id]
        degrees_from_list = {str(x).strip() for x in info.get("allowed_degrees") or [] if str(x).strip()}
        include_names = set(info.get("include_names") or set())
        exclude_names = set(info.get("exclude_names") or set())
        title = str(info.get("title") or list_id)

        for department in info.get("departments", []):
            roster_block = roster.get(department)
            if not roster_block:
                continue
            for degree, names in roster_block.items():
                degree = str(degree).strip()
                if allowed_degrees_cfg and degree not in allowed_degrees_cfg:
                    continue
                if degrees_from_list and degree not in degrees_from_list:
                    continue
                for raw_name in names:
                    name = str(raw_name).strip()
                    if not name:
                        continue
                    if include_names and name not in include_names:
                        continue
                    if name in exclude_names:
                        continue
                    key = (name, degree, department, list_id)
                    if key in seen:
                        continue
                    seen.add(key)
                    pool.append(
                        StaffRecord(
                            name=name,
                            degree=degree,
                            department=department,
                            list_id=list_id,
                            list_title=title,
                        )
                    )

    if not pool:
        raise ConfigError(
            f"Không có nhân sự phù hợp cho form '{cfg.get('form_id')}' với danh sách đã chọn"
        )
    return pool



def sample_with_range(items: List[str], minimum: int, maximum: int) -> List[str]:
    if not items:
        return []
    lo = max(0, int(minimum))
    hi = max(lo, int(maximum))
    k = random.randint(min(lo, len(items)), min(hi, len(items)))
    return random.sample(items, k=k)


def build_comment(bank: Dict[str, Any], form_id: str, cfg: Optional[Dict[str, Any]] = None) -> str:
    block = bank.get(form_id)
    if not block:
        return (
            "Thực hiện tương đối tốt kỹ thuật. Cần tiếp tục duy trì và hoàn thiện quy trình "
            "để bảo đảm an toàn người bệnh."
        )

    strengths = list(block.get("strengths") or block.get("pros") or [])
    limitations = list(block.get("limitations") or block.get("cons") or [])
    rules = dict((cfg or {}).get("comment_rules") or {})

    if rules:
        picked_s = sample_with_range(
            strengths,
            rules.get("k_pros_min", 2),
            rules.get("k_pros_max", 2),
        )
        picked_l = sample_with_range(
            limitations,
            rules.get("k_cons_min", 1),
            rules.get("k_cons_max", 1),
        )
    else:
        picked_s = random.sample(strengths, k=min(2, len(strengths))) if strengths else []
        picked_l = random.sample(limitations, k=min(1, len(limitations))) if limitations else []

    parts: List[str] = []
    if picked_s:
        parts.append("Ưu điểm: " + " ".join(picked_s))
    if picked_l:
        parts.append("Nhược điểm: " + " ".join(picked_l))
    return "\n".join(parts).strip()

def load_staff_usage_counts(form_id: str) -> Dict[Tuple[str, str, str], int]:
    path = HISTORY_DIR / f"{form_id}.csv"
    counts: Dict[Tuple[str, str, str], int] = {}
    if not path.exists():
        return counts
    try:
        with path.open("r", encoding="utf-8-sig", newline="") as f:
            reader = csv.DictReader(f)
            for row in reader:
                name = str(row.get("name", "")).strip()
                department = normalize_department_name(row.get("department", ""))
                list_id = str(row.get("list_id", "")).strip()
                if not name:
                    continue
                key = (list_id, department, name)
                counts[key] = counts.get(key, 0) + 1
    except Exception:
        return counts
    return counts


def choose_staff_from_pool(
    pool: List[StaffRecord],
    used_staff_keys_in_run: Optional[Set[Tuple[str, str, str]]] = None,
    staff_usage_counts: Optional[Dict[Tuple[str, str, str], int]] = None,
) -> StaffRecord:
    if not pool:
        raise ConfigError("Pool nhân sự đang rỗng")

    usage = staff_usage_counts or {}

    def key_of(staff: StaffRecord) -> Tuple[str, str, str]:
        return (staff.list_id, staff.department, staff.name)

    candidates = pool
    if used_staff_keys_in_run is not None:
        fresh_pool = [staff for staff in pool if key_of(staff) not in used_staff_keys_in_run]
        if fresh_pool:
            candidates = fresh_pool

    min_used = min(usage.get(key_of(staff), 0) for staff in candidates)
    least_used = [staff for staff in candidates if usage.get(key_of(staff), 0) == min_used]
    staff = random.choice(least_used)

    if used_staff_keys_in_run is not None:
        used_staff_keys_in_run.add(key_of(staff))
    usage[key_of(staff)] = usage.get(key_of(staff), 0) + 1
    return staff


def filter_staff_pool_for_row(
    pool: List[StaffRecord],
    form_id: str,
    row_index: int,
    scores: List[str],
    submitted_keys: Set[str],
) -> List[StaffRecord]:
    available: List[StaffRecord] = []
    seen_keys: Set[str] = set()
    for staff in pool:
        submission_key = make_submission_key(
            form_id,
            row_index,
            scores,
            staff.department,
            staff.list_id,
            staff.name,
            staff.degree,
        )
        if submission_key in submitted_keys or submission_key in seen_keys:
            continue
        seen_keys.add(submission_key)
        available.append(staff)
    return available


def select_indices_or_all(choice: str, total: int, empty_means_all: bool = True) -> Optional[List[int]]:
    raw = str(choice or "").strip()
    if not raw:
        return list(range(1, total + 1)) if empty_means_all else None
    lowered = raw.lower()
    if lowered in {"all", "a", "*"}:
        return list(range(1, total + 1))

    parts = [p.strip() for p in raw.split(",") if p.strip()]
    selected: List[int] = []
    seen: Set[int] = set()
    for part in parts:
        if not part.isdigit():
            return None
        idx = int(part)
        if idx < 1 or idx > total:
            return None
        if idx not in seen:
            seen.add(idx)
            selected.append(idx)
    return selected or None


def prompt_additional_runs(form_title: str, current_success: int) -> int:
    print(f"\nForm: {form_title}")
    print(f"Đã nộp trước đó: {current_success}")
    print("Nhập số lượt muốn chạy thêm.")
    print("  - Nhập 0 để bỏ qua form này")

    while True:
        raw = input("Muốn chạy thêm bao nhiêu lượt? ").strip()
        if raw.isdigit():
            return int(raw)
        print("[WARN] Vui lòng nhập số nguyên >= 0.")


def select_lists_interactively(selected_jobs: List[Tuple[Job, Dict[str, Any]]], staff_lists: Dict[str, Dict[str, Any]]) -> Dict[str, List[str]]:
    if not selected_jobs:
        return {}

    common_allowed: Optional[Set[str]] = None
    combined_defaults: List[str] = []
    for _, cfg in selected_jobs:
        allowed = set(get_available_list_ids_for_cfg(cfg, staff_lists))
        common_allowed = allowed if common_allowed is None else (common_allowed & allowed)
        combined_defaults.extend(get_default_list_ids_for_cfg(cfg, list(allowed)))

    available_ids = [list_id for list_id in staff_lists.keys() if list_id in (common_allowed or set())]
    if not available_ids:
        raise ConfigError(
            "Các form đã chọn không có danh sách chung để chạy cùng nhau. Hãy chọn ít form hơn hoặc nới allowed_list_ids trong config."
        )

    default_ids: List[str] = []
    seen_defaults: Set[str] = set()
    for list_id in combined_defaults:
        if list_id in available_ids and list_id not in seen_defaults:
            seen_defaults.add(list_id)
            default_ids.append(list_id)
    if not default_ids:
        default_ids = list(available_ids)

    print("\nDanh sách có thể áp dụng:")
    for idx, list_id in enumerate(available_ids, start=1):
        info = staff_lists[list_id]
        departments = ", ".join(info.get("departments", []))
        marker = " [mặc định]" if list_id in default_ids else ""
        print(f"  {idx}. {info.get('title')} [{departments}] | id={list_id}{marker}")

    print("\nNhập lựa chọn danh sách:")
    print("  - Nhấn Enter để chọn tất cả")
    print("  - Nhập số, ví dụ: 1")
    print("  - Nhập nhiều số, ví dụ: 1,2")
    print("  - Nhập 'all' để dùng tất cả danh sách")

    while True:
        choice = input("Chọn danh sách cần dùng: " )
        selected_indices = select_indices_or_all(choice, len(available_ids), empty_means_all=True)
        if selected_indices:
            selected = [available_ids[i - 1] for i in selected_indices]
            print(f"[INFO] Đã chọn {len(selected)} danh sách dùng chung cho {len(selected_jobs)} form.")
            return {job.job_id: list(selected) for job, _ in selected_jobs}
        print("[WARN] Lựa chọn không hợp lệ. Hãy nhập lại theo dạng 1 hoặc 1,2 hoặc all, hoặc nhấn Enter để chọn tất cả.")


def extract_scores(row: Dict[str, str], count: int) -> List[str]:
    scores: List[str] = []
    for i in range(1, count + 1):
        key = f"cau{i}"
        if key not in row:
            raise ConfigError(f"Thiếu cột '{key}' trong file CSV dữ liệu")
        value = str(row[key]).strip()
        if value not in {"0", "1", "2", "3", "4"}:
            raise ConfigError(f"Giá trị '{value}' ở cột '{key}' không hợp lệ. Chỉ chấp nhận 0-4")
        scores.append(value)
    return scores


def build_payload(
    cfg: Dict[str, Any],
    profile: Dict[str, Any],
    name: str,
    degree: str,
    department: str,
    comment: str,
    scores: List[str],
    hidden: Optional[Dict[str, str]] = None,
) -> Dict[str, str]:
    payload: Dict[str, str] = {}
    email_field = cfg.get("email_field")
    email_value = cfg.get("email_value") or profile.get("email")
    if email_field and email_value:
        payload[email_field] = str(email_value)

    payload[cfg["name_field"]] = name
    payload[cfg["comment_field"]] = comment
    payload[cfg["degree_field"]] = degree
    if cfg.get("department_field"):
        department_source = str(cfg.get("department_source") or "fixed").strip().lower()
        payload[cfg["department_field"]] = resolve_source_value({"roster": "department"}, profile, name, degree, department, comment, {}, cfg) if department_source == "staff" else str(cfg.get("fixed_department") or department)

    score_fields = cfg["score_fields"]
    if len(score_fields) != len(scores):
        raise ConfigError(
            f"score_fields có {len(score_fields)} mục nhưng CSV có {len(scores)} điểm"
        )
    for field, value in zip(score_fields, scores):
        payload[field] = str(value)

    if hidden:
        for key in ("fvv", "fbzx", "pageHistory"):
            if hidden.get(key):
                payload[key] = hidden[key]

    return payload


def detect_login_needed(page: Page) -> bool:
    url = page.url.lower()
    if "accounts.google.com" in url:
        return True
    body = page.locator("body")
    try:
        text = body.inner_text(timeout=2500)
    except Exception:
        return False
    text = text.lower()
    login_signals = [
        "to continue, sign in",
        "để tiếp tục, hãy đăng nhập",
        "choose an account",
        "use your google account",
    ]
    return any(s in text for s in login_signals)


def can_access_form(page: Page) -> bool:
    url = page.url.lower()
    if "docs.google.com/forms" not in url:
        return False
    selectors = [
        'input[name="fbzx"]',
        'input[name="fvv"]',
        'div[role="list"]',
        'form',
        'div.freebirdFormviewerViewFormContentWrapper',
    ]
    for selector in selectors:
        try:
            if page.locator(selector).count() > 0:
                return True
        except Exception:
            continue
    return False


def ensure_access(page: Page, view_url: str) -> None:
    view_url = canonicalize_google_form_url(view_url)
    page.goto(view_url, wait_until="domcontentloaded")
    page.wait_for_timeout(1500)
    if can_access_form(page):
        return
    if not detect_login_needed(page):
        raise RuntimeError(f"Không mở được form. URL hiện tại: {page.url}")
    print("\n[INFO] Form yêu cầu đăng nhập Google trên trình duyệt Chromium vừa mở.")
    print("[INFO] Hãy đăng nhập xong rồi quay lại terminal nhấn Enter để tiếp tục...")
    input()
    page.goto(view_url, wait_until="domcontentloaded")
    page.wait_for_timeout(1500)
    if can_access_form(page):
        return
    if detect_login_needed(page):
        raise RuntimeError(f"Vẫn chưa truy cập được form sau khi đăng nhập. URL hiện tại: {page.url}")
    raise RuntimeError(f"Không mở được form sau khi tải lại. URL hiện tại: {page.url}")


def scrape_hidden_fields(page: Page) -> Dict[str, str]:
    result: Dict[str, str] = {}
    for name in ["fvv", "fbzx", "pageHistory"]:
        try:
            value = page.locator(f'input[name="{name}"]').first.get_attribute("value", timeout=1200)
        except Exception:
            value = None
        if value:
            result[name] = value
    return result


def submit_with_page_fetch(page: Page, form_response_url: str, payload: Dict[str, str]) -> Tuple[int, str]:
    js = """
    async ({ url, payload }) => {
      const body = new URLSearchParams();
      for (const [k, v] of Object.entries(payload)) {
        body.append(k, String(v));
      }
      const resp = await fetch(url, {
        method: 'POST',
        body,
        credentials: 'include',
        headers: {
          'Content-Type': 'application/x-www-form-urlencoded;charset=UTF-8'
        },
        redirect: 'follow'
      });
      const text = await resp.text();
      return { status: resp.status, text };
    }
    """
    data = page.evaluate(js, {"url": form_response_url, "payload": payload})
    return int(data.get("status", 0)), data.get("text", "")


def append_history(form_id: str, row: Dict[str, Any]) -> None:
    path = HISTORY_DIR / f"{form_id}.csv"
    path.parent.mkdir(parents=True, exist_ok=True)
    exists = path.exists()
    with path.open("a", encoding="utf-8-sig", newline="") as f:
        fieldnames = [
            "submitted_at",
            "row_index",
            "name",
            "degree",
            "department",
            "list_id",
            "list_title",
            "score_total",
            "score_max",
            "score_percent",
            "scores",
            "mode",
        ]
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        if not exists:
            writer.writeheader()
        writer.writerow(row)


def resolve_source_value(
    source: Dict[str, Any],
    profile: Dict[str, Any],
    name: str,
    degree: str,
    department: str,
    comment: str,
    row: Dict[str, str],
    cfg: Optional[Dict[str, Any]] = None,
) -> str:
    if "profile" in source:
        return str(profile.get(source["profile"], ""))
    if "roster" in source:
        roster_key = str(source["roster"])
        if roster_key in {"name", "nguoi_thuc_hien"}:
            return name
        if roster_key in {"trinh_do", "degree"}:
            return degree
        if roster_key in {"department", "khoa", "don_vi"}:
            form_id = str((cfg or {}).get("form_id") or "")
            return get_department_display_value(form_id, department, cfg)
        raise ConfigError(f"Nguồn roster '{roster_key}' chưa được hỗ trợ")
    if "const" in source:
        return str(source["const"])
    if "column" in source:
        key = str(source["column"])
        return str(row.get(key, ""))
    if "random_comment" in source:
        return comment
    raise ConfigError(f"Source không hỗ trợ: {source}")


def find_question_container(page: Page, title: str) -> Locator:
    title = str(title or "").strip()
    if not title:
        raise ConfigError("Thiếu title cho locator kiểu question")

    heading = page.get_by_role("heading", name=title, exact=True).first
    try:
        heading.wait_for(timeout=4000)
    except Exception:
        heading = page.get_by_text(title, exact=True).first
        heading.wait_for(timeout=4000)

    return heading.locator(
        "xpath=ancestor::*[contains(@class,'Qr7Oae') or contains(@class,'geS5n') or contains(@class,'AgroKb')][1]"
    )


def resolve_locator(page: Page, locator_cfg: Dict[str, Any]) -> Locator:
    by = str(locator_cfg.get("by", "")).strip().lower()
    value = str(locator_cfg.get("value", "")).strip()
    if by == "css":
        return page.locator(value).first
    if by == "label":
        return page.get_by_label(value).first
    if by == "role":
        role = str(locator_cfg.get("role", "")).strip()
        if not role:
            raise ConfigError(f"Thiếu role trong locator: {locator_cfg}")
        return page.get_by_role(role, name=value, exact=True).first
    if by == "question":
        container = find_question_container(page, locator_cfg.get("question", value))
        control = str(locator_cfg.get("control", "text")).strip().lower()
        if control in {"text", "textbox", "input"}:
            return container.locator("input:not([type='hidden']):not([disabled]), textarea:not([disabled])").first
        if control in {"textarea", "comment"}:
            return container.locator("textarea:not([disabled]), input:not([type='hidden']):not([disabled])").first
        if control in {"dropdown", "listbox", "select"}:
            return container.get_by_role("listbox").first
        raise ConfigError(f"Control question chưa hỗ trợ: {control}")
    raise ConfigError(f"Kiểu locator chưa hỗ trợ: {by}")


def fill_text_field(page: Page, locator_cfg: Dict[str, Any], value: str) -> None:
    locator = resolve_locator(page, locator_cfg)
    locator.wait_for(timeout=8000)
    locator.click(timeout=8000)
    locator.fill(value, timeout=8000)


def choose_dropdown(page: Page, locator_cfg: Dict[str, Any], value: str) -> None:
    locator = resolve_locator(page, locator_cfg)
    locator.wait_for(timeout=8000)
    locator.click(timeout=8000)

    value = str(value)
    try:
        option = page.locator(f'[role="option"][data-value="{value}"]').first
        option.wait_for(timeout=5000)
        option.click(timeout=5000)
        return
    except Exception:
        pass

    option = page.get_by_role("option", name=value, exact=True).first
    option.wait_for(timeout=8000)
    option.click(timeout=8000)


def answer_radio_groups_in_order(page: Page, scores: List[str]) -> None:
    groups = page.get_by_role("radiogroup")
    count = groups.count()
    if count < len(scores):
        raise RuntimeError(
            f"Không tìm đủ nhóm câu hỏi dạng radio. Tìm thấy {count}, cần {len(scores)}"
        )
    for i, value in enumerate(scores):
        group = groups.nth(i)
        radio = group.get_by_role("radio", name=str(value), exact=True).first
        radio.wait_for(timeout=8000)
        try:
            radio.check(timeout=8000, force=True)
        except Exception:
            radio.click(timeout=8000, force=True)


def click_next_button(page: Page) -> None:
    fallbacks = [
        page.get_by_role("button", name="Tiếp"),
        page.get_by_role("button", name="Tiếp"),
        page.get_by_role("button", name="Next"),
        page.get_by_text("Tiếp", exact=True),
        page.get_by_text("Next", exact=True),
    ]
    for locator in fallbacks:
        try:
            locator.first.wait_for(timeout=3000)
            locator.first.click(timeout=5000)
            page.wait_for_timeout(900)
            return
        except Exception:
            continue
    raise RuntimeError("Không tìm thấy nút Tiếp/Next của form nhiều phần")


def click_submit_button(page: Page, submit_button_cfg: Dict[str, Any]) -> None:
    try:
        locator = resolve_locator(page, submit_button_cfg)
        locator.wait_for(timeout=6000)
        locator.click(timeout=6000)
        return
    except Exception:
        pass

    fallbacks = [
        page.get_by_role("button", name="Gửi"),
        page.get_by_role("button", name="Gửi"),
        page.get_by_role("button", name="Submit"),
        page.get_by_text("Gửi", exact=True),
        page.get_by_text("Submit", exact=True),
    ]
    for locator in fallbacks:
        try:
            locator.first.wait_for(timeout=3000)
            locator.first.click(timeout=3000)
            return
        except Exception:
            continue

    raise RuntimeError("Không tìm thấy nút Gửi/Submit trên form")


def wait_submit_success(page: Page, success_text: str, timeout_ms: int = 15000) -> bool:
    patterns = [
        success_text,
        "Câu trả lời của bạn đã được ghi lại",
        "Đã ghi lại câu trả lời của bạn",
        "Gửi ý kiến phản hồi khác",
        "Gửi phản hồi khác",
        "Gửi câu trả lời khác",
        "Chỉnh sửa câu trả lời của bạn",
        "Submit another response",
        "Your response has been recorded",
        "Edit your response",
        "Hệ thống đã ghi lại câu trả lời của bạn",
    ]
    deadline = time.time() + (timeout_ms / 1000.0)
    while time.time() < deadline:
        try:
            current_url = page.url or ""
        except Exception:
            current_url = ""
        if "usp=form_confirm" in current_url or "formResponse" not in current_url and "viewform" in current_url:
            try:
                body_html = page.content()
            except Exception:
                body_html = ""
            if (
                "data-form-submission-timestamp" in body_html
                or "Câu trả lời của bạn đã được ghi lại" in body_html
                or "Gửi ý kiến phản hồi khác" in body_html
                or "Your response has been recorded" in body_html
            ):
                return True
        try:
            text = page.locator("body").inner_text(timeout=2000)
        except Exception:
            text = ""
        text_lower = text.lower()
        if any(p.lower() in text_lower for p in patterns if p):
            return True
        page.wait_for_timeout(300)
    return False


def dump_page_html(page: Page, out_path: Path) -> None:
    try:
        html = page.content()
        out_path.write_text(html, encoding="utf-8")
    except Exception:
        pass


def page_shows_captcha(page: Page) -> bool:
    checks = [
        page.locator("text=reCAPTCHA"),
        page.locator("iframe[src*='recaptcha']"),
        page.locator(".g-recaptcha"),
    ]
    for loc in checks:
        try:
            if loc.count() > 0:
                return True
        except Exception:
            continue
    try:
        text = page.locator("body").inner_text(timeout=1500).lower()
    except Exception:
        text = ""
    return "captcha" in text or "i'm not a robot" in text


def submit_legacy_form(
    page: Page,
    cfg: Dict[str, Any],
    profile: Dict[str, Any],
    row: Dict[str, str],
    name: str,
    degree: str,
    department: str,
    comment: str,
    scores: List[str],
    on_captcha_wait: Optional[Callable[[], bool]] = None,
) -> None:
    page.goto(cfg["view_url"], wait_until="domcontentloaded")
    page.wait_for_timeout(1200)
    ensure_access(page, cfg["view_url"])

    fields = list(cfg.get("legacy_fields") or [])
    for field in fields:
        field_type = field.get("type")
        source = field.get("source", {})
        optional = bool(field.get("optional", False))
        if field_type == "radio_in_section":
            continue
        value = resolve_source_value(source, profile, name, degree, department, comment, row, cfg)
        locator_cfg = field.get("locator", {})
        try:
            if field_type == "fill":
                fill_text_field(page, locator_cfg, value)
            elif field_type == "dropdown":
                choose_dropdown(page, locator_cfg, value)
            else:
                raise ConfigError(f"Legacy field type chưa hỗ trợ: {field_type}")
        except Exception:
            if optional:
                print(f"[INFO] Bỏ qua field optional: {field.get('debug_name') or locator_cfg}")
                continue
            raise

    if cfg.get("multi_page"):
        score_cursor = 0
        page_number = 1
        while score_cursor < len(scores):
            groups = page.get_by_role("radiogroup")
            visible_count = groups.count()
            if visible_count <= 0:
                raise RuntimeError(f"Phần {page_number} không có câu hỏi chấm điểm")
            remaining = len(scores) - score_cursor
            if visible_count > remaining:
                raise RuntimeError(
                    f"Phần {page_number} có {visible_count} câu nhưng chỉ còn {remaining} điểm"
                )
            answer_radio_groups_in_order(
                page,
                scores[score_cursor : score_cursor + visible_count],
            )
            score_cursor += visible_count
            if score_cursor < len(scores):
                click_next_button(page)
                page_number += 1
        click_submit_button(
            page,
            cfg.get("legacy_submit_button")
            or {"by": "role", "role": "button", "value": "Gửi"},
        )
    else:
        answer_radio_groups_in_order(page, scores)
        click_submit_button(page, cfg.get("legacy_submit_button") or {"by": "role", "role": "button", "value": "Gửi"})

    if wait_submit_success(page, cfg.get("success_text", DEFAULT_SUCCESS_TEXT), timeout_ms=12000):
        return

    if page_shows_captcha(page):
        print("[INFO] Form đang yêu cầu xác minh reCAPTCHA. Hãy giải trên cửa sổ Chromium rồi bấm Gửi.")
        if on_captcha_wait is None:
            input("[INFO] Xong thì quay lại terminal nhấn Enter để tiếp tục...")
            if wait_submit_success(page, cfg.get("success_text", DEFAULT_SUCCESS_TEXT), timeout_ms=30000):
                return
        else:
            # Chạy từ giao diện web: không có terminal để nhấn Enter, nên chờ người
            # dùng giải CAPTCHA và bấm Gửi, kiểm tra lại mỗi vài giây.
            deadline = time.time() + int(cfg.get("captcha_wait_seconds", 600))
            while time.time() < deadline:
                if on_captcha_wait():
                    raise RuntimeError("Đã dừng khi đang chờ giải CAPTCHA")
                if wait_submit_success(page, cfg.get("success_text", DEFAULT_SUCCESS_TEXT), timeout_ms=5000):
                    return
            raise RuntimeError("Hết thời gian chờ giải CAPTCHA")

    dump_page_html(page, LAST_PAGE_HTML)
    raise RuntimeError(f"Timeout chờ xác nhận submit. Đã lưu HTML tại: {LAST_PAGE_HTML}")


def run_job(
    page: Page,
    job: Job,
    cfg: Dict[str, Any],
    profile: Dict[str, Any],
    roster: Dict[str, Any],
    bank: Dict[str, Any],
    staff_lists: Dict[str, Dict[str, Any]],
    selected_list_ids: List[str],
) -> None:
    rows = load_rows(job.data_path)
    progress = load_progress(cfg["form_id"])
    submitted_keys = set(progress.get("submitted_keys", []))
    success_count = int(progress.get("success_count", 0))

    print(f"\n=== JOB: {job.job_id} ===")
    print(f"Form: {cfg.get('title', cfg['form_id'])}")
    print(f"Mode: {cfg.get('mode')}")

    additional_runs = prompt_additional_runs(
        cfg.get("title", cfg["form_id"]),
        success_count,
    )

    if additional_runs <= 0:
        print("[SKIP] Bạn chọn 0 lượt, bỏ qua form này.")
        return

    target_success = success_count + additional_runs
    print(f"[INFO] Mục tiêu lần này: chạy thêm {additional_runs} lượt (từ {success_count} -> {target_success}).")

    if cfg.get("mode") == "post":
        ensure_access(page, cfg["view_url"])
        hidden = scrape_hidden_fields(page)
    else:
        hidden = None
        ensure_access(page, cfg["view_url"])

    score_count = len(cfg["score_fields"])
    success_text = cfg.get("success_text", DEFAULT_SUCCESS_TEXT)
    staff_pool = build_staff_pool(roster, staff_lists, selected_list_ids, cfg)
    used_staff_keys_in_run: Set[Tuple[str, str, str]] = set()
    staff_usage_counts = load_staff_usage_counts(cfg["form_id"])

    for idx, row in enumerate(rows, start=1):
        if success_count >= target_success:
            break

        scores = extract_scores(row, score_count)
        ok, total, maximum, percent = validate_score_window(scores, cfg)
        if not ok:
            print(f"[ROW {idx}] Bỏ qua: tổng={total}/{maximum} ({percent:.2f}%) ngoài ngưỡng.")
            continue

        row_staff_pool = filter_staff_pool_for_row(staff_pool, cfg["form_id"], idx, scores, submitted_keys)
        if not row_staff_pool:
            print(f"[ROW {idx}] Bỏ qua: dòng dữ liệu này đã nộp cho tất cả danh sách đã chọn.")
            continue

        staff = choose_staff_from_pool(
            row_staff_pool,
            used_staff_keys_in_run=used_staff_keys_in_run,
            staff_usage_counts=staff_usage_counts,
        )
        submission_key = make_submission_key(
            cfg["form_id"],
            idx,
            scores,
            staff.department,
            staff.list_id,
            staff.name,
            staff.degree,
        )

        name, degree = staff.name, staff.degree
        department_value = staff.department
        comment = build_comment(bank, cfg["form_id"], cfg)

        try:
            if cfg.get("mode") == "post":
                payload = build_payload(cfg, profile, name, degree, department_value, comment, scores, hidden=hidden)
                status, html = submit_with_page_fetch(page, cfg["form_response_url"], payload)
                success = status in (200, 302) and (
                    success_text.lower() in html.lower()
                    or "submit another response" in html.lower()
                    or "gửi câu trả lời khác" in html.lower()
                )
                if not success:
                    LAST_RESPONSE_HTML.write_text(html, encoding="utf-8")
                    raise RuntimeError(f"Submit thất bại. HTTP={status}. Đã lưu phản hồi tại: {LAST_RESPONSE_HTML}")
            else:
                submit_legacy_form(page, cfg, profile, row, name, degree, department_value, comment, scores)
        except Exception as exc:
            print(f"[ROW {idx}] LỖI submit | {exc}")
            break

        success_count += 1
        submitted_keys.add(submission_key)
        progress["success_count"] = success_count
        progress["submitted_keys"] = sorted(submitted_keys)
        save_progress(cfg["form_id"], progress)
        append_history(
            cfg["form_id"],
            {
                "submitted_at": time.strftime("%Y-%m-%d %H:%M:%S"),
                "row_index": idx,
                "name": name,
                "degree": degree,
                "department": department_value,
                "list_id": staff.list_id,
                "list_title": staff.list_title,
                "score_total": total,
                "score_max": maximum,
                "score_percent": f"{percent:.2f}",
                "scores": "-".join(scores),
                "mode": cfg.get("mode", "post"),
            },
        )
        print(
            f"[ROW {idx}] OK | {name} | {degree} | {department_value} | {total}/{maximum} ({percent:.2f}%) | "
            f"{success_count}/{job.max_success} | list={staff.list_id}"
        )

        wait_ms = int(cfg.get("submit_delay_ms", random.randint(*DEFAULT_WAIT_RANGE_MS)))
        page.wait_for_timeout(wait_ms)


def select_jobs_interactively(jobs: List[Tuple[Job, Dict[str, Any]]]) -> List[Tuple[Job, Dict[str, Any]]]:
    if not jobs:
        raise ConfigError("jobs.csv không có job nào để chạy")

    print("\nDanh sách form có thể chạy:")
    for idx, (job, cfg) in enumerate(jobs, start=1):
        title = str(cfg.get("title", job.job_id))
        mode = str(cfg.get("mode", "post"))
        print(f"  {idx}. {title} | id={job.job_id} | mode={mode}")

    print("\nNhập lựa chọn:")
    print("  - Nhập số, ví dụ: 1")
    print("  - Nhập nhiều số, ví dụ: 1,2")
    print("  - Nhập 'all' để chạy tất cả form")
    print("  - Nhấn Enter để chọn tất cả")

    while True:
        choice = input("Chọn form cần điền: ")
        selected_indices = select_indices_or_all(choice, len(jobs), empty_means_all=True)
        if selected_indices:
            return [jobs[i - 1] for i in selected_indices]
        print("[WARN] Lựa chọn không hợp lệ. Hãy nhập lại theo dạng 1 hoặc 1,2 hoặc all, hoặc nhấn Enter để chọn tất cả.")
def main() -> None:
    random.seed()
    if not JOBS_CSV.exists():
        raise SystemExit("Không tìm thấy jobs.csv")
    profile = load_json(PROFILE_JSON) if PROFILE_JSON.exists() else {}
    roster = load_json(ROSTER_JSON)
    bank = load_json(COMMENT_BANK_JSON) if COMMENT_BANK_JSON.exists() else {}
    staff_lists = load_staff_lists(roster)
    jobs = load_jobs(JOBS_CSV)
    resolved_jobs = [(job, normalize_config(load_json(job.config_path), job.config_path)) for job in jobs]
    jobs_to_run = select_jobs_interactively(resolved_jobs)
    selected_lists_by_job = select_lists_interactively(jobs_to_run, staff_lists)

    BROWSER_PROFILE_DIR.mkdir(parents=True, exist_ok=True)
    with sync_playwright() as p:
        context = p.chromium.launch_persistent_context(
            user_data_dir=str(BROWSER_PROFILE_DIR),
            headless=False,
            viewport={"width": 1400, "height": 900},
        )
        page = context.new_page()
        try:
            for job, cfg in jobs_to_run:
                run_job(
                    page,
                    job,
                    cfg,
                    profile,
                    roster,
                    bank,
                    staff_lists,
                    selected_lists_by_job.get(job.job_id, []),
                )
        finally:
            context.close()


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\nDừng theo yêu cầu người dùng.")
        sys.exit(130)
