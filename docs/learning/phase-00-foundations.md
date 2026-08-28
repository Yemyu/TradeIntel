# 第 0 阶段：项目环境与读取 CSV

## 这一步解决什么问题

正式分析贸易数据前，首先需要保证：

1. 项目使用的 Python 和其他项目互不影响；
2. 文件放在固定位置，之后能够找到；
3. Python 能把表格中的数据读进程序。

今天不学习数据库、pandas 或 AI，只完成这三个最基础的目标。

## 1. 什么是项目虚拟环境

可以把 Python 环境理解成项目自己的工具箱。

如果所有项目共用同一个工具箱，A 项目升级某个工具以后，B 项目可能突然无法运行。虚拟环境就是给 TradeShock AI 单独准备一个工具箱。

这个项目的工具箱位于：

```text
TradeIntel/.venv/
```

激活它：

```bash
source .venv/bin/activate
```

激活以后，终端前面通常会出现 `(.venv)`。执行：

```bash
python --version
```

应该看到 Python 3.12.x。

退出虚拟环境：

```bash
deactivate
```

`.venv` 不会上传到 GitHub，因为别人可以根据依赖说明重新建立自己的环境。

## 2. 当前文件夹分别做什么

```text
TradeIntel/
├── data/
│   ├── raw/       将来保存从数据源取得的原始数据
│   └── sample/    很小的学习和演示数据
├── docs/learning/ 每个阶段的中文学习说明
├── notebooks/     将来用于探索数据
├── src/           正式 Python 代码
├── tests/         将来检查代码有没有被改坏
├── .venv/         本项目独立的 Python 环境
└── README.md      项目入口说明
```

现在不要求背目录。只需要记住：数据放在 `data`，程序放在 `src`。

## 3. CSV 是什么

CSV 是用逗号分隔的纯文本表格。文件第一行通常是列名：

```text
reporter,partner,year,month,trade_value_usd
China,United States,2024,1,120000
```

Python 标准库里的 `csv.DictReader` 可以把每一行变成一个字典：

```python
{
    "reporter": "China",
    "partner": "United States",
    "year": "2024",
    "month": "1",
    "trade_value_usd": "120000",
}
```

注意：从 CSV 读取出来的数字最初也是文字，所以相加前需要使用 `int()` 转成整数。

## 4. 一个更小的示例

下面是读取 CSV 的基本形式：

```python
import csv

with open("example.csv", mode="r", encoding="utf-8") as file:
    reader = csv.DictReader(file)
    rows = list(reader)
```

- `open`：打开文件；
- `with`：使用完成后自动关闭文件；
- `DictReader`：按照第一行列名读取数据；
- `list`：把读取结果保存成列表。

## 5. 你的第一个亲手任务

打开：

```text
src/phase_00_read_csv.py
```

完成两个 TODO：

### TODO 1：读取 CSV

参考上面的小例子，但把 `"example.csv"` 换成函数收到的 `csv_path`。

### TODO 2：计算总贸易额

思路：

```text
先准备 total = 0
逐行读取 rows
取出这一行的 trade_value_usd
用 int() 把文字变成整数
加到 total
最后 return total
```

完成后，在项目根目录运行：

```bash
source .venv/bin/activate
python src/phase_00_read_csv.py
```

正确结果应包含：

```text
数据行数: 6
贸易总额: 605000 美元
```

不要直接追求运行成功。如果某一行不理解，先停在那一行，我们一起解释。

## 6. 完成标准

进入下一阶段前，你应该能用自己的话回答：

1. 为什么不把所有 Python 包都安装在系统环境里？
2. `data` 和 `src` 文件夹分别放什么？
3. 为什么 CSV 里的 `120000` 读取后需要使用 `int()`？
4. `with open(...)` 中的 `with` 帮我们做了什么？

