"""批量排查。"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Callable

from checker import CheckResult, check_one


def run_batch(
    urls: list[str],
    workers: int = 4,
    progress: Callable[[int, int, CheckResult], None] | None = None,
) -> list[CheckResult]:
    n = len(urls)
    results: list[CheckResult | None] = [None] * n
    if n == 0:
        return []

    workers = max(1, min(workers, n))
    done = 0
    with ThreadPoolExecutor(max_workers=workers) as pool:
        fmap = {pool.submit(check_one, url): i for i, url in enumerate(urls)}
        for fut in as_completed(fmap):
            i = fmap[fut]
            try:
                results[i] = fut.result()
            except Exception as e:
                results[i] = CheckResult(
                    source_url=urls[i],
                    note=f"内部错误: {e}",
                    system_result="无法检测",
                    need_review="是",
                )
            done += 1
            if progress:
                progress(done, n, results[i])  # type: ignore[arg-type]
    return [r for r in results if r is not None]
