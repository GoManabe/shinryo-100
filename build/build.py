# -*- coding: utf-8 -*-
"""診療報酬100 暗記アプリ ビルドスクリプト

  items/*.json（項目データ）＋ sources.json（出典台帳）＋ meta.json（データの版）を検査し、
  template.html に埋め込んで単一ファイルの ../index.html を生成する。
  あわせて、一覧確認用の items.csv（Excelで開ける BOM付きUTF-8）を書き出す。

  使い方:  python build.py
  検査で問題が見つかった場合は、何が問題かを表示して止まる（index.html は更新しない）。
"""
import csv, glob, io, json, os, re, sys

HERE = os.path.dirname(os.path.abspath(__file__))
OUT_HTML = os.path.abspath(os.path.join(HERE, "..", "index.html"))
OUT_CSV = os.path.join(HERE, "items.csv")

ID_RE = re.compile(r"^(NY|KS|RH|ZT|GK)-\d{3}$")
DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
STATUSES = {"draft", "active", "retired"}
SUMMARY_MAX = 50
REQ_MAX = 3


def load(name):
    with open(os.path.join(HERE, name), encoding="utf-8") as f:
        return json.load(f)


def main():
    meta = load("meta.json")
    sources = {s["src"]: s for s in load("sources.json")}
    items = []
    for path in sorted(glob.glob(os.path.join(HERE, "items", "*.json"))):
        with open(path, encoding="utf-8") as f:
            items.extend(json.load(f))

    errors, warns = [], []
    ids, orders = set(), set()
    by_id = {}
    for it in items:
        iid = it.get("id", "?")
        if not ID_RE.match(iid):
            errors.append(f"{iid}: IDの形式が不正（分野コード＋3桁）")
        if iid in ids:
            errors.append(f"{iid}: IDが重複している")
        ids.add(iid)
        by_id[iid] = it
        if it.get("field") != iid[:2]:
            errors.append(f"{iid}: field がIDの分野コードと一致しない")
        if it.get("status") not in STATUSES:
            errors.append(f"{iid}: status が不正（draft/active/retired）")
        if it.get("fy") != meta["fy"]:
            errors.append(f"{iid}: fy が {meta['fy']} ではない（古い年度の混入）")
        o = it.get("order")
        if not isinstance(o, int) or o in orders:
            errors.append(f"{iid}: order が整数でないか重複している")
        orders.add(o)
        if not it.get("name"):
            errors.append(f"{iid}: name が空")

    for it in items:
        iid = it["id"]
        if it["status"] != "active":
            continue
        for k in ("summary", "target", "kubun", "group", "priority", "updated"):
            if not it.get(k):
                errors.append(f"{iid}: 出題対象（active）なのに {k} が空")
        if it.get("updated") and not DATE_RE.match(it["updated"]):
            errors.append(f"{iid}: updated の日付形式が不正")
        if len(it.get("summary", "")) > SUMMARY_MAX:
            errors.append(f"{iid}: summary が{SUMMARY_MAX}字を超えている（{len(it['summary'])}字）")
        reqs = it.get("requirements") or []
        if not reqs:
            errors.append(f"{iid}: requirements が空")
        if len(reqs) > REQ_MAX:
            errors.append(f"{iid}: requirements が{REQ_MAX}つを超えている")
        pts = it.get("points") or []
        if not pts:
            errors.append(f"{iid}: points が空")
        for p in pts:
            has_val = isinstance(p.get("value"), (int, float))
            has_rng = isinstance(p.get("min"), (int, float)) and isinstance(p.get("max"), (int, float))
            has_txt = bool(p.get("text"))
            if not (has_val or has_rng or has_txt):
                errors.append(f"{iid}: 点数「{p.get('label')}」の値が未確認（null）のまま")
        srcs = it.get("sources") or []
        if not srcs:
            errors.append(f"{iid}: 出典がない")
        for s in srcs:
            if s.get("src") not in sources:
                errors.append(f"{iid}: 出典ID {s.get('src')} が sources.json にない")
            if not DATE_RE.match(s.get("checked", "")):
                errors.append(f"{iid}: 出典 {s.get('src')} の確認日がない")
        for sim in it.get("similar") or []:
            t = by_id.get(sim.get("id"))
            if not t:
                errors.append(f"{iid}: 類似項目 {sim.get('id')} が存在しない")
            elif t["status"] != "active":
                warns.append(f"{iid}: 類似項目 {sim['id']} はまだ出題対象外（比較モードには出ない）")
            if not sim.get("diff"):
                errors.append(f"{iid}: 類似項目 {sim.get('id')} との違い（diff）が空")

    for w in warns:
        print("注意:", w)
    if errors:
        print(f"\n検査で {len(errors)} 件の問題が見つかったため、index.html を更新しませんでした。")
        for e in errors:
            print("  ×", e)
        sys.exit(1)

    items.sort(key=lambda x: x["order"])
    active = [x for x in items if x["status"] == "active"]
    used = sorted({s["src"] for x in active for s in x["sources"]})

    keep = ("id", "name", "aliases", "kubun", "field", "group", "priority", "order", "summary", "target",
            "requirements", "points", "similar", "hook", "revNote", "r8new", "sources", "updated")
    data = {
        "meta": dict(meta, totalItems=len(items), activeItems=len(active)),
        "sources": {k: sources[k] for k in used},
        "items": [{k: x.get(k) for k in keep} for x in active],
    }
    payload = json.dumps(data, ensure_ascii=False, separators=(",", ":")).replace("</", "<\\/")

    with open(os.path.join(HERE, "template.html"), encoding="utf-8") as f:
        tpl = f.read()
    assert tpl.count("__DATA__") == 1, "template.html に __DATA__ が1つだけ必要"
    with io.open(OUT_HTML, "w", encoding="utf-8", newline="\n") as f:
        f.write(tpl.replace("__DATA__", payload))

    def pts_text(pts):
        out = []
        for p in pts or []:
            if isinstance(p.get("value"), (int, float)):
                v = f"{p['value']:,}{p.get('unit', '点')}"
            elif "min" in p:
                v = f"{p['min']:,}〜{p['max']:,}{p.get('unit', '点')}"
            else:
                v = p.get("text", "")
            out.append(f"{p.get('label', '')}：{v}")
        return " / ".join(out)

    with open(OUT_CSV, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.writer(f)
        w.writerow(["ID", "状態", "学習順", "分野", "名称", "区分番号", "優先度", "R8新", "一言概要", "対象",
                    "主な要件", "点数", "類似項目", "出典", "更新日"])
        for x in items:
            w.writerow([x["id"], x["status"], x["order"], meta["fields"][x["field"]]["label"], x["name"],
                        x["kubun"], x["priority"], "新" if x.get("r8new") else "", x.get("summary", ""),
                        x.get("target", ""), " / ".join(x.get("requirements") or []), pts_text(x.get("points")),
                        " / ".join(s["id"] for s in x.get("similar") or []),
                        " / ".join(f"{s['src']} {s.get('loc', '')}（{s.get('checked', '')}確認）" for s in x.get("sources") or []),
                        x.get("updated", "")])

    print(f"項目 {len(items)} 件（出題対象 {len(active)} 件 / 下書き {sum(1 for x in items if x['status'] == 'draft')} 件）")
    for k, v in meta["fields"].items():
        n_all = sum(1 for x in items if x["field"] == k)
        n_act = sum(1 for x in active if x["field"] == k)
        print(f"  {k} {v['label']}: 出題対象 {n_act} / 登録 {n_all} / 目標 {v['target']}")
    print("出力:", OUT_HTML, f"({os.path.getsize(OUT_HTML) / 1024:.0f} KB)")
    print("出力:", OUT_CSV)


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    main()
