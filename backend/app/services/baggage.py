"""行李装卸业务规则：转盘矩阵、航班号检索、排序分页、登记去重与并发冲突都收在这里。"""
from __future__ import annotations

from typing import Any

from app.store import store

MODULE = "baggage"
REQUIRED_FIELDS = ["任务编号", "对应航班", "行李类型"]
OPTIONAL_FIELDS = ["装卸方向", "出发转盘", "到达转盘", "装卸班组"]
STATUS_ORDER = ["待装卸", "装卸中", "已交付", "异常中断"]
ACTION_RULES = {"开始装卸": "装卸中", "确认交付": "已交付", "登记异常": "异常中断"}
NEGATIVE_ACTIONS = []
DEFAULT_SORT = "任务编号"
SORTABLE_FIELDS = ["任务编号", "对应航班", "任务状态", "到达转盘"]
UNASSIGNED = "__unassigned__"


class BaggageService:
    def _rows(self) -> list[dict[str, Any]]:
        rows = store.rows(MODULE)
        for row in rows:
            row.setdefault("version", 1)
        return rows

    def _filter(
        self,
        rows: list[dict[str, Any]],
        *,
        keyword: str | None = None,
        status: str | None = None,
        carousel: str | None = None,
    ) -> list[dict[str, Any]]:
        result = list(rows)
        if keyword:
            kw = keyword.strip().lower()
            result = [
                row for row in result
                if kw in str(row.get("对应航班", "")).lower()
                or kw in str(row.get("任务编号", "")).lower()
            ]
        if status:
            result = [
                row for row in result
                if row.get("status") == status or row.get("任务状态") == status
            ]
        if carousel:
            target = carousel.strip()
            if target == UNASSIGNED:
                result = [row for row in result if not str(row.get("到达转盘") or "").strip()]
            else:
                result = [
                    row for row in result
                    if str(row.get("到达转盘") or "").strip() == target
                ]
        return result

    def _sort(
        self,
        rows: list[dict[str, Any]],
        sort: str | None,
        order: str | None,
    ) -> list[dict[str, Any]]:
        field = sort if sort in SORTABLE_FIELDS else DEFAULT_SORT
        reverse = (order or "asc").lower() == "desc"
        return sorted(rows, key=lambda row: str(row.get(field, "")), reverse=reverse)

    def list_entries(
        self,
        *,
        keyword: str | None = None,
        status: str | None = None,
        carousel: str | None = None,
        sort: str | None = None,
        order: str | None = None,
        page: int = 1,
        size: int = 20,
    ) -> tuple[list[dict[str, Any]], int]:
        rows = self._sort(
            self._filter(self._rows(), keyword=keyword, status=status, carousel=carousel),
            sort,
            order,
        )
        total = len(rows)
        start = max(page - 1, 0) * size
        return rows[start:start + size], total

    def matrix(
        self,
        *,
        keyword: str | None = None,
        status: str | None = None,
    ) -> tuple[list[dict[str, Any]], dict[str, Any], int]:
        """转盘矩阵：按到达转盘分组计数；缺到达转盘的记录单独成组，不参与筛选但不消失。"""
        rows = self._filter(self._rows(), keyword=keyword, status=status)
        groups: dict[str, list[dict[str, Any]]] = {}
        unassigned: list[dict[str, Any]] = []
        for row in rows:
            carousel = str(row.get("到达转盘") or "").strip()
            if carousel:
                groups.setdefault(carousel, []).append(row)
            else:
                unassigned.append(row)
        carousel_groups = [
            {"name": name, "count": len(items), "rows": items}
            for name, items in sorted(groups.items())
        ]
        return carousel_groups, {"count": len(unassigned), "rows": unassigned}, len(rows)

    def get_entry(self, entry_id: int) -> dict[str, Any] | None:
        row = store.find(MODULE, entry_id)
        if row is not None:
            row.setdefault("version", 1)
        return row

    def create_entry(self, values: dict[str, Any]) -> tuple[dict[str, Any] | None, list[str], bool]:
        """登记一条行李任务；任务编号已存在时直接返回原记录，不重复落库。"""
        missing = [field for field in REQUIRED_FIELDS if not str(values.get(field) or "").strip()]
        if missing:
            return None, missing, False
        rows = self._rows()
        task_no = str(values.get("任务编号") or "").strip()
        flight = str(values.get("对应航班") or "").strip()
        baggage_type = str(values.get("行李类型") or "").strip()
        direction = str(values.get("装卸方向") or "").strip()
        for row in rows:
            if task_no and str(row.get("任务编号") or "").strip() == task_no:
                return row, [], True
            if (
                not task_no
                and flight
                and str(row.get("对应航班") or "").strip() == flight
                and str(row.get("行李类型") or "").strip() == baggage_type
                and str(row.get("装卸方向") or "").strip() == direction
            ):
                return row, [], True
        entry: dict[str, Any] = {
            "id": max((int(row.get("id", 0)) for row in rows), default=0) + 1,
            "version": 1,
        }
        for field in REQUIRED_FIELDS + OPTIONAL_FIELDS:
            entry[field] = str(values.get(field) or "").strip() or None
        entry["status"] = STATUS_ORDER[0]
        entry["任务状态"] = STATUS_ORDER[0]
        entry["pending"] = True
        entry["abnormal"] = False
        rows.append(entry)
        return entry, [], False

    def run_action(
        self,
        entry_id: int,
        action: str,
        version: int | None = None,
    ) -> tuple[dict[str, Any] | None, str, bool]:
        """执行动作；携带的版本号与库内不一致时判定为冲突，以后落库的版本为准。"""
        entry = self.get_entry(entry_id)
        if entry is None:
            return None, f"行李任务 {entry_id} 不存在或已归档", False
        if action not in ACTION_RULES:
            return None, f"动作「{action}」不属于行李装卸可执行范围", False
        if version is not None and int(version) != int(entry.get("version", 1)):
            return entry, "该任务已被其他窗口先保存，以先落库的版本为准", True
        target = ACTION_RULES[action]
        if target not in STATUS_ORDER:
            return None, f"目标状态「{target}」不在允许的状态序列里", False
        entry["status"] = target
        entry["任务状态"] = target
        entry["pending"] = target != STATUS_ORDER[-1]
        entry["abnormal"] = action in NEGATIVE_ACTIONS
        entry["version"] = int(entry.get("version", 1)) + 1
        return entry, f"行李任务已{action}", False
