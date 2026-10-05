# 网页界面

[English](README.md) | **简体中文**

本目录保存双语项目展示、本地聊天工作台和图表报告共用的HTML、CSS及JavaScript。公开网站读取四个已保存案例；本地服务支持用户配置模型后提问，或只查询数据。安装和模型设置见[本地运行说明](../../docs/LOCAL_RUN.zh-CN.md)。

## 文件

| 文件 | 用途 |
|---|---|
| `index.html`、`style.css` | 页面结构与样式 |
| `app.js` | 导航、语言切换、地球动效及固定政策图表 |
| `live.js` | 本地工作台、模型设置及后端请求 |
| `report-view.js` | 共用的报告渲染与打印 |
| `cases.js`、`cases/index.json`、`cases/*.json` | 四个导出案例及目录 |
| `data.json` | 五种政策示例商品在2026年2月至7月的已保存进口金额 |
| `vendor/` | 打包的地球组件与许可文件 |

## 预览公开构建

在仓库根目录使用Python 3.12：

```bash
PYTHONPATH=src:. python3 -S scripts/build_github_pages.py --output tmp/pages-preview/site
PYTHONPATH=src:. python3 -S scripts/build_github_pages.py --verify tmp/pages-preview/site
python3 -m http.server 8790 --bind 127.0.0.1 --directory tmp/pages-preview/site
```

打开 [http://127.0.0.1:8790/](http://127.0.0.1:8790/)。输出目录已存在时换一个新目录。便携构建只使用标准库和仓库内的案例，核验公开资产清单，并从输出中移除本地工作台及 `live.js`。它不需要私有会话、贸易数据包或模型凭据。[Pages工作流](../../.github/workflows/pages.yml)使用同一个构建器。

检查构建与界面：

```bash
PYTHONPATH=src:.:tests python3 -S -m unittest test_github_pages_build
node --test tests/*.test.cjs
```

Node检查使用DOM替身；检查范围和前提见[测试说明](../../docs/TESTING.zh-CN.md)。

## 运行本地工作台

按本地运行说明准备并核验贸易数据包后：

```bash
.venv/bin/python scripts/run_web.py --trade-data-root .local/trade-data-bundle-1
```

打开 [http://127.0.0.1:8765/preview/](http://127.0.0.1:8765/preview/)。本地后端提供界面并执行查询。看已保存案例不会提交新问题；助手提问使用已配置的平台。数据查询模式不需要模型密钥。

## 组件与数据

地球使用已打包的 [COBE 0.6.5模块](https://esm.sh/cobe@0.6.5/es2022/cobe.bundle.mjs)。分发资产时保留 [COBE许可](vendor/COBE-LICENSE)和 [Phenomenon许可](vendor/PHENOMENON-LICENSE)。页面从本地加载模块。布局和SVG报告图表由本项目实现；地球是视觉示意，不表示测量得到的贸易流。

仓库内的案例文件和 `data.json` 已完成导出。重建原始导出需要对应的已保存来源记录，与便携Pages构建分开。当前数据范围、来源及下载方法见[数据说明](../../data/README.zh-CN.md)。
