from __future__ import annotations

import re
from collections import defaultdict
from dataclasses import dataclass
from urllib.parse import urlparse

from .engines import Candidate, EngineResult


@dataclass(frozen=True)
class MergedCandidate:
    platform: str
    account: str
    name: str
    source_url: str
    score: float | None
    engines: tuple[str, ...]
    confidence: bool


def normalize_text(value: str) -> str:
    value = str(value or "").strip().lower()
    value = re.sub(r"[\s_\-·•|/\\:：@]+", "", value)
    return value


def normalize_account(candidate: Candidate) -> str:
    account = normalize_text(candidate.account)
    if account:
        return account
    parsed = urlparse(candidate.source_url)
    return normalize_text(parsed.path.rsplit("/", 1)[-1] if parsed.path else "")


def _identity(candidate: Candidate) -> str:
    account = normalize_account(candidate)
    if account:
        return f"{normalize_text(candidate.platform)}:{account}"
    return normalize_text(candidate.source_url)


def merge_candidates(
    results: list[EngineResult],
    *,
    max_accounts: int = 3,
    strict_consensus: bool = True,
) -> list[MergedCandidate]:
    groups: dict[str, list[Candidate]] = defaultdict(list)
    for result in results:
        for candidate in result.candidates:
            key = _identity(candidate)
            if key:
                groups[key].append(candidate)
    merged: list[MergedCandidate] = []
    for rows in groups.values():
        rows.sort(key=lambda item: item.score if item.score is not None else 0.0, reverse=True)
        first = rows[0]
        engines = tuple(sorted({item.engine for item in rows}))
        confidence = len(engines) >= 2 or (
            not strict_consensus and bool(first.score is None or first.score >= 50)
        )
        merged.append(
            MergedCandidate(
                platform=first.platform or "未知平台",
                account=first.account or first.name,
                name=first.name,
                source_url=first.source_url,
                score=first.score,
                engines=engines,
                confidence=confidence,
            )
        )
    merged.sort(
        key=lambda item: (
            item.confidence,
            len(item.engines),
            item.score if item.score is not None else -1,
        ),
        reverse=True,
    )
    return merged[: max(1, int(max_accounts))]


def format_results(
    results: list[EngineResult],
    *,
    max_accounts: int = 3,
    strict_consensus: bool = True,
) -> str:
    merged = merge_candidates(
        results,
        max_accounts=max_accounts,
        strict_consensus=strict_consensus,
    )
    engines = [result.engine for result in results if not result.error]
    if not merged:
        if engines:
            return "未找到可靠结果。\n已完成搜索的引擎：" + "、".join(engines)
        return "反向图片搜索暂时不可用。\n可用引擎均未返回结果，请稍后再试。"
    trusted = [item for item in merged if item.confidence]
    title = "可信候选：" if trusted else "候选结果（仅供参考）："
    lines = ["图片反查完成。", "", title]
    for index, item in enumerate(merged, 1):
        lines.append(f"{index}. 平台：{item.platform}")
        lines.append(f"   账号：{item.account}")
        if item.name and item.name != item.account:
            lines.append(f"   名称：{item.name}")
        if item.score is not None:
            lines.append(f"   匹配度：{item.score:.1f}")
        if item.source_url:
            lines.append(f"   来源：{item.source_url}")
        lines.append(f"   引擎：{'、'.join(item.engines)}")
    if not trusted:
        lines.append("")
        lines.append("不同引擎未形成充分一致，请自行核对来源链接。")
    return "\n".join(lines)
