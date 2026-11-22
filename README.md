# 青溪流域监测日账

青溪流域监测中心的白班收到测站现场记录，按原采集顺序接纳观测并正式刊发日表。夜班用固定交班件在隔离仓接续已收刊次，核对读值和原据，再供值班长按号领取签读。

## 运行

使用 Python 3.11 标准库和随 Python 提供的 SQLite。从项目根目录执行。控制台在物化时提供 `check_project.py`，它运行 `tests` 包的完整回归。

```sh
python3 -B check_project.py
python3 -B -m unittest discover -v -s tests -t .
python3 -B demo.py
```

演示使用 `samples/observations.json` 和两份临时 SQLite 仓。样例的四条原序读值为 7 L、11 L、0 L 与缺测，正式账为 18 L、缺测一行。演示随后建立已实收的刊次 10，刊次 11 正式撤下 R，刊次 12 原样恢复 R。关闭源仓后办理 10→12。夜班账应为 R 待复核、S 已复核、合计 18 L。演示还核对原回执复领及刊次 10 冻结账，并输出实际计算和手算对照。

## 一天的操作

1. 用 `source_store.open_source(path)` 和 `mirror.storage.open_mirror(path)` 分别打开两个库，调用方负责关闭连接。打开或显式重复初始化可保留既有站批、判单、正式刊次、前沿、回执和复核。对新夜班库，用 `mirror.acceptance.bootstrap_mirror(mirror, official_ledger)` 成套装入已核对的合法正式起点。重复装入同一个当前底账可重领当前底账。已接续的前沿拒绝被旧底账覆盖。
2. 用 `intake.batches.import_batch(source, day, batch_id, rows)` 接纳站批，返回固定批次和入库原序行。`get_batch(source, batch_id)` 按批号核对。每条输入为含 `row_id`、`liters`、`source` 的字典。出处含 `station`、`document` 与正整数 `line`。`day` 是一个日表标识，`row_id` 在同一日表内唯一。全批重投按原始顺序、读值、日表及出处比对。同值异行分别计量。
3. 用 `publication.drafts.stage_decisions(source, day, decisions)` 暂存一组 `QualityDecision(row_id, included)`。它返回该日表现有待刊意见。未知、异表或重复行使本次暂存整体失败。后续判单可改写此前待刊意见，已刊账继续按正式结果读取。
4. 用 `publication.issues.publish_issue(source, day, issue)` 正式刊发。刊次为同表严格递增的正整数，允许跳号。它把待刊意见应用到前刊入选集合，首次刊发以空集合起算。新观测须有入选判单才能进入正式账。成功后本次待刊意见已用毕，未变更的入选行保持原样。可用 `publication.history.read_issue(source, day, issue)` 和 `read_head_issue(source, day)` 分别领取指定刊次和当前正式头部。
5. 用 `dispatch.packages.dispatch_package(source, package_id, day, start, target)` 固定 V1 交班件，返回可传输的 UTF-8 JSON 字节。起止必须为同表正式刊次且目标晚于起点。同号同参返回原字节，即使正式头部后来推进。交班区间只计算真实刊次，未刊草稿不参与。`dispatch.codec.decode_v1(body)` 可读取件号、区间、目标账及资格依据。
6. 夜班断开源仓后，用 `mirror.acceptance.accept_package(mirror, body)` 实收。新件必须从该日表本地前沿接续。同次提交目标明细和统计、适用复核、前沿及唯一回执。已办同号同件返回原回执，判断同件时忽略 JSON 空白及对象字段排列。同号异件或未办的迟到件拒绝。`mirror.frontiers.read_frontier` 查询当前刊次，`mirror.materialization.read_current_ledger` 和 `read_received_ledger` 查询当前或已实收的固定投影，`mirror.history.find_receipt` 可查已实收回执。
7. 用 `review.decisions.record_review(mirror, day, issue, row_id, conclusion)` 登记非空现场结论。复核要求指定当前实收刊次及当前入选行。同一行在区间内每次正式刊发都入选时，其本地结论继续适用。期间正式撤下过的行在重新入选后为待复核，旧结论仍可从原冻结签读核对。
8. 用 `review.signoff.create_signoff(mirror, signoff_id, day, issue)` 签存当前实收账。`FrozenSignoff.ledger.rows`、`conclusions` 与 `states` 按同一顺序对齐，空结论对应 `pending`。同号同参且刊次仍为当前时可复领该号原签读，历史签读通过 `review.lookup.read_signoff(mirror, signoff_id)` 领取。新实收、复核修改和重开均不改变旧签读。

## 计量、交接和失败边界

Python 接口中的读值、合计和刊次都是精确整数。负值、布尔值、非整数读值及非法出处拒绝。`None` 表示显式缺测，仍可入选。合计只累加实测，缺测单独计数。空入选集合两项统计均为零。按站批接纳顺序与批内位置排序，重新入选仍使用原位置。SQLite 和 V1 在需要精确往返的地方以规范十进制字符串表示整数，跨过 SQLite 整数存储范围的升数仍可精确计算。例如 V1 的 `"liters":"7"` 由解码接口返回整数 `7`，`null` 则返回 `None`。

V1 外层字段为 `version`、`package_id`、`day`、`start`、`target`、`ledger` 与 `evidence`。来件包含目标原序明细、原据、统计、起点投影摘要和按目标顺序列出的持续入选身份。隔离仓校验外层、目标、读值、原序和统计，核对证据所绑定的本地起点及行身份。摘要及结构校验用于核对交接内容，发布方由现场交接流程确定。

业务错误使用 `ledger_core` 中的 `InvalidInput`、`MissingRecord`、`NameConflict` 和 `WrongFrontier`。`read_head_issue`、`read_frontier` 和 `find_receipt` 在尚无相应记录时返回 `None`。公开写操作各自拥有本地事务，调用时连接须处于事务之外。`publish_issue` 与 `accept_package` 的可选 `before_commit` 回调在本次新写入完成后、提交前运行。回调可检查本次事务内结果或抛出异常，抛出时全部写入回滚。已办交班件复领不运行该回调。其它低层写入函数由各入口在同一事务内调用。
