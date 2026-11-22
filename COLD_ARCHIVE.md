# 冻结签读的冷盘归档

夜班仓按 `README.md` 接班和签存。冷盘归档的输入是一个已经存在的 `FrozenSignoff`，包括历史签读。重新登记现场复核不会改变它。归档时由夜班库固定请求，由介质决定槽是否真正封成。档案员可拿走冷盘，在没有源仓和夜班库的核读机上领取签读。

## Python 接口

新增 `review.signoff.archive(connection, archive_id, signoff_id, medium)`。`connection` 由原 `open_mirror` 打开。两个号沿用项目的非空 UTF-8 文本约定。首次受理将归档号与签读号、`medium.medium_id` 持久绑定。同号异绑报 `NameConflict`，不得向介质发令。未知签读报 `MissingRecord`，不得占用归档号。介质身份按标识比较，关闭重挂后的句柄仍可续办。每个介质由一个夜班库串行发令，设备可独立结清已经接收的命令。夜班库与介质各有提交边界。

返回 `('pending', None)`、`('full', None)` 或 `('sealed', receipt)`。`receipt` 是 `(archive_id, signoff_id, medium_id, slot)`，槽号从零起。仍可能封成的原令应报 `pending`，并保留空槽。只有上一已接收的写令确定烧损、且本号无成件时，才可以向别的空槽补写。无法排除本号旧令仍会封成时允许保守等待。无未决资格且无成件、无空槽时返回 `full`。实际成件后，同参重投返回同一收执。设备和夜班仓可以各自重开。

新增 `review.lookup.read_archive(medium, archive_id)`，返回与原签读同型并等值的 `FrozenSignoff`，包括原号、日表刊次、原序行、出处、合计、缺测数和当时的复核结论。此入口仅使用介质。归档身份和整个签读正文都须通过完整性核对。只有确切归档号的真实封成件有出账资格。无可辨认的指定封成件报 `MissingRecord`，可辨认的指定坏件或归属矛盾报 `InvalidInput`。成件字节格式由归档和核读共同约定，须能从冷盘独立解析。

## 写一次介质模拟器

`archive_medium.create_medium(path, medium_id, slot_count)` 建立空盘并返回句柄。`open_medium(path, read_only=False)` 重开已有盘，调用方负责 `close()`。生产代码通过 `medium_id`、`slot_count`、`status(slot)`、`read_slot(slot)`、`write(slot, body)` 使用介质。槽号为 `0` 到 `slot_count - 1`。状态分别为 `empty`、`writing`、`sealed`、`burned`。`read_slot` 在空槽返回 `None`，其余返回实存字节。在写时也可能读到完整候选字节。状态询问和字节读取是独立观察，介质可以在两次调用之间结清写令。

`write` 接受非空 `bytes`，只允许空槽。普通调用成功返回 `None` 时，槽已封成。夹具调用 `hold_next_write()` 后，下一次获接纳的写入会先持久变为 `writing` 再抛出 `ReplyLost`。即使原写入者已经退出，设备控制端仍可重开介质并用 `finish(slot, 'sealed')` 原样封成，或用 `finish(slot, 'burned')` 留下烧损前缀。两种终态均不可再写。`damage(slot)` 模拟已封成记录的字节损坏，供冷读核验。模拟器将应用记录当作不透明字节，接受不同空槽写入相同字节。

## 样例和验收入口

用 `samples/observations.json` 的全四行刊发刊次 9，装入夜班底账，给 R 登记「已核对」并冻结签读 F。之后把现场对 R 的结论改录。归档 F 后，冷读仍须得到原序 R、S、Z、M，升数依次为 7、11、0、缺测，出处行号为 21、22、23、24，合计 18 L、缺测一行，R 的冻结结论仍为「已核对」。

- 两槽盘的首写收令失答。退出归档调用进程并重开，首槽仍在写时同号重投须待定，另一槽保持空闲。设备随后封成首槽，同号复领取首槽收执且全盘只有一份成件。关闭源仓与夜班库后，以只读介质句柄核读 F。
- 对照让首槽烧损。只有烧损后才换空槽，同号在新槽封成后可领首执。若盘中只有烧损的首槽，则返回无空槽及空收执。已受理号改绑签读或介质应拒绝，盘面不变。
- 分别只提供在写、烧损、另一归档号的封成件、损坏封成件，原号均不得出账。

`python3 -B archive_medium.py` 核对夹具本身，`README.md` 的命令继续运行原业务。交付时沿用 `.pointwise-runtime.json` 的 v1 CLI 运行清单，保留空 `setup`。`verify` 的命令参数数组运行完整原回归并核对上述新业务，任一核对失败须以非零退出。`demo` 的命令参数数组演示失答后卸盘读回样例签读，打印实际槽位、原序读值、出处和冻结核账结果。
