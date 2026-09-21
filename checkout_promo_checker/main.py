"""CLI：读取 Excel 第一列链接，排查结账页促销文案。"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

from batch import run_batch
from excel_io import default_output_path, read_links, write_results

DEFAULT_INPUT = Path("单页排查.xlsx")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="排查结账页套餐价下促销文案，并按现价/划线价测算是否合理。"
    )
    parser.add_argument(
        "-i",
        "--input",
        default=str(DEFAULT_INPUT if DEFAULT_INPUT.exists() else ""),
        help="输入 Excel（第一列为链接）",
    )
    parser.add_argument("-o", "--output", default="", help="输出 Excel 路径")
    parser.add_argument("-w", "--workers", type=int, default=4, help="并发数，默认 4")
    parser.add_argument("--limit", type=int, default=0, help="只跑前 N 条，0 表示全部")
    args = parser.parse_args(argv)

    input_path = Path(args.input) if args.input else None
    if not input_path or not input_path.exists():
        print("请指定存在的 Excel：python main.py -i 链接表.xlsx")
        print(f"默认路径不存在: {DEFAULT_INPUT}")
        return 2

    rows = read_links(input_path)
    if args.limit:
        rows = rows[: args.limit]
    if not rows:
        print("Excel 第一列没有读到链接。")
        return 2

    print(f"共 {len(rows)} 条链接，开始排查…")

    def progress(done, total, item):
        flag = "!" if item.need_review == "是" else "+"
        print(
            f"[{done}/{total}] [{flag}] {item.system_result} / 人工复核:{item.need_review}  {item.source_url}"
        )
        if item.promo_texts:
            print(f"         类型:{item.copy_type}  文案: {item.promo_text_joined[:160]}")
        if item.reason_detail:
            for line in item.reason_detail.splitlines():
                print(f"         {line}")

    results = run_batch([r["url"] for r in rows], workers=args.workers, progress=progress)
    paired = list(zip(results, [r["extra"] for r in rows]))
    extra_headers: list[str] = []
    for extra in [r["extra"] for r in rows]:
        for k in extra:
            if k not in extra_headers and k != "类型":
                extra_headers.append(k)

    out = Path(args.output) if args.output else default_output_path(HERE)
    write_results(paired, out, extra_headers=extra_headers)

    def n_sys(status):
        return sum(1 for r in results if r.system_result == status)

    review_n = sum(1 for r in results if r.need_review == "是")
    print("-" * 60)
    print(
        f"完成。测算不符 {n_sys('测算不符')} · 测算一致 {n_sys('测算一致')} · "
        f"纯文案 {n_sys('纯文案，无法按价格测算')} · 无促销文案 {n_sys('无促销文案')} · "
        f"需人工复核 {review_n} 条"
    )
    print(f"结果已写入: {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
