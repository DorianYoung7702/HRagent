# 猎聘 LPT Playwright 操作说明

> 面向维护 `services/fetch_worker/` 的开发者与 AI Agent。  
> 原则：**页面操作全部用 Playwright 确定性 DOM，LLM 不参与点击/解析 HTML。**

---

## 1. 整体架构

```text
FastAPI (uvicorn)
    │
    ├─ run_on_playwright_loop()     ← Windows 专用：独立 Proactor 事件循环
    │
    ├─ browser_pool.acquire_browser()  ← 同一 profile 共享一个 Chromium 进程
    │       └─ BrowserManager (launch_persistent_context + user_data_dir)
    │
    ├─ 抓取 runner.py               ← 搜索 → 弹窗简历 → 收藏 → 开聊
    ├─ login_init.py                ← 登录态初始化（独立浏览器会话）
    ├─ im_chat_runner.py            ← IM 中心发消息 / 扫回复
    └─ resume_library_nav.py        ← 控制台「跳转简历库」
```

| 组件 | 文件 | 说明 |
|------|------|------|
| 浏览器启动 | `browser.py` | `launch_persistent_context`，profile 在 `data/browser_profiles/` |
| 进程池 | `browser_pool.py` | 引用计数；抓取、IM、简历库可共用同一 Chromium |
| 事件循环 | `packages/asyncio_compat.py` | uvicorn + Windows 下必须用 `run_on_playwright_loop()` |
| 选择器配置 | `lpt_adapter.py` | **所有 LPT CSS/文案常量集中在此** |
| 页面类型检测 | `page_detector.py` | LOGIN / LIST / DETAIL |
| 主抓取流程 | `extract_popup.py` | 弹窗简历、收藏分组、立即沟通 |
| 搜索页 | `lpt_search.py` | 关键词、城市、年限筛选 |
| IM | `im_chat_runner.py` + `im_chat_adapter.py` | 「我发起的」列表匹配与发送 |
| 简历库跳转 | `resume_library_nav.py` + `resume_library_row_match.py` | 人才管理 → 简历库 → 分组 → 点姓名 |

**环境变量：**

| 变量 | 默认 | 说明 |
|------|------|------|
| `BROWSER_HEADLESS` | `true`（`.env`） | `start_api.ps1` 会设为 `false`，HR 需可见浏览器 |
| `BROWSER_PROFILE_DIR` | `./data/browser_profiles/hr_default` | 登录 Cookie 持久化目录 |

---

## 2. LPT 页面流程（当前已实现）

### 2.1 搜索抓取主路径

```text
lpt.liepin.com/search
  → 填关键词 / 目前城市 / 期望城市 / 工作年限 / 教育经历 / 其他筛选
  → 点击搜索结果卡片
  → 弹出「在线简历」浮层
  → AI 初筛（观察 / 追问 / 排除）
  → [观察/追问] 收藏 → 选分组「追问(N)」「观察(N)」→ 知道了
  → 立即沟通 / 继续沟通 → 选岗位 → IM 追问/要简历
  → 关闭浮层回到列表 → 下一张
```

### 2.2 简历库跳转路径（控制台按钮）

```text
侧栏「人才管理」→ 主区域上方「简历库」
  → 【本页左侧】点击「观察」或「候选」键（追问分组在页面上常显示为「候选」）
  → 【右侧】出现收藏的候选人 list
  → 按姓氏 + 年龄/学历/职位等匹配一行
  → 点击该行（整行）→ 弹出在线简历
```

**易错：** 必须先点「观察/候选」右侧才有 list；不要只扫表头或全页 DOM。

### 2.3 IM 路径

```text
IM 中心 → 「我发起的」
  → im_contact_match 按姓氏+年龄+学校匹配
  → 输入框发追问 / 要简历
```

---

## 3. 代码约定（必须遵守）

### 3.1 选择器放 `lpt_adapter.py`

**不要**在业务文件里硬编码一长串 CSS。新增按钮/区域时：

```python
# lpt_adapter.py
LPT_MY_NEW_BUTTON = [
    "button:has-text('新按钮')",
    "[class*='my-btn']",
    "text=新按钮",
]
```

业务代码循环尝试：

```python
from services.fetch_worker.lpt_adapter import LPT_MY_NEW_BUTTON

async def _click_my_button(page: Page) -> bool:
    for sel in LPT_MY_NEW_BUTTON:
        try:
            loc = page.locator(sel).first
            if await loc.is_visible(timeout=1500):
                await loc.click(timeout=5000)
                return True
        except Exception:
            continue
    return False
```

### 3.2 线性步骤 + 确认后再继续

`extract_popup.py` 的模式：**上一步 DOM 验证成功，才进入下一步**。失败则：

1. `_step_fail("描述")` 打日志 + SSE 事件  
2. `_save_debug_screenshot(page, "语义化文件名")`  
3. `return` 错误，**不要**用 JS `element.click()` 假装成功  

```python
def _step_log(msg: str) -> None:
    print(f"[步骤] {msg}", flush=True)
    emit("info", msg, category="extract")

def _step_done(msg: str) -> None:
    print(f"[完成] {msg}", flush=True)
    emit("success", msg, category="extract")

def _step_fail(msg: str) -> None:
    print(f"[失败] {msg}", flush=True)
    emit("error", msg, category="extract")
```

### 3.3 真实点击，优先 Playwright locator

| 方式 | 何时用 |
|------|--------|
| `locator.click()` | 首选 |
| `locator.click(position={x, y})` | 文字对但元素不可点（如整行分组） |
| `page.evaluate("...")` | 批量扫 DOM、找 z-index 最高浮层 |
| JS `element.click()`  alone | **避免**作唯一手段 |

收藏分组示例：必须点到 **「追问(N)」整行左侧文字**，不要点到「增加标签」或侧边栏「分组列表」。

### 3.4 浮层 / 弹窗识别

在线简历、收藏简历、选岗位等均为**多层浮层**。用 `_TOPMOST_OVERLAY_JS` 思路：按 z-index × 面积取最上层，再在 scope 内找按钮。

弹窗容器常量：`LPT_POPUP_CONTAINER`、`LPT_COLLECT_FOLDER_MODAL`。

### 3.5 调试截图

失败时自动保存到 **`data/debug/{name}.png`**（已在 `.gitignore`）。

命名规范：`{动作}_{原因}`，例如：

- `collect_folder_modal_missing`
- `communicate_button_missing`
- `im_tab_initiated_fail`

本地复现后对照截图改选择器。

### 3.6 从 API 调用 Playwright

```python
from packages.asyncio_compat import run_on_playwright_loop

async def my_api_handler():
    result = await run_on_playwright_loop(my_playwright_coro())
    return result
```

**不要**在 FastAPI 主事件循环里直接 `await page.goto()`（Windows uvicorn 会 subprocess 失败）。

后台 fire-and-forget 任务用：

```python
from packages.background_tasks import spawn
spawn(run_on_playwright_loop(my_coro()))
```

### 3.7 浏览器会话复用

| 场景 | 模式 |
|------|------|
| 单次抓取 | `new_page()` → 用完 `page.close()` → `release_browser()` |
| IM / 多标签 | `browser_pool.acquire_browser()`，抓取与 IM 各开 tab |
| 简历库跳转 | `resume_library_viewer.py` 持有一个长寿命 tab，不关闭 |
| 登录向导 | `login_init.py` 独立 `_browser` / `_page`，完成后 `close()` |

---

## 4. 如何人工加一段新逻辑

下面以 **「在收藏成功后多点一个自定义按钮」** 为例，说明标准步骤。

### 步骤 1：在真实浏览器里确认 UI

1. 运行 `.\scripts\login_liepin.ps1` 或控制台登录  
2. 手动走到目标页面，F12 看元素文案、class、是否在 iframe 内  
3. 确认按钮精确文案（LPT 常用：**立即沟通** 而非「立即开聊」）

### 步骤 2：在 `lpt_adapter.py` 加选择器

```python
LPT_AFTER_COLLECT_EXTRA = [
    "button:has-text('你要点的文案')",
]
```

### 步骤 3：写单步 async 函数

建议放在 **`extract_popup.py`**（若在弹窗流程内）或新建 **`my_feature_nav.py`**（若独立流程）。

```python
async def _click_after_collect_extra(page: Page) -> bool:
    from services.fetch_worker.lpt_adapter import LPT_AFTER_COLLECT_EXTRA

    for sel in LPT_AFTER_COLLECT_EXTRA:
        try:
            loc = page.locator(sel).first
            if await loc.is_visible(timeout=2000):
                await loc.click(timeout=5000)
                _step_done("已点击 xxx")
                return True
        except Exception:
            continue
    _step_fail("未找到 xxx 按钮")
    await _save_debug_screenshot(page, "after_collect_extra_miss")
    return False
```

### 步骤 4：插入调用链

在 `extract_popup.py` 找到收藏流程函数（如 `_complete_chat_collect_flow`），在 **「知道了」点成功之后** 插入：

```python
if not await _click_after_collect_extra(page):
    return False  # 或按业务决定是否软失败
```

**关键：** 插入位置要在注释写清的顺序里，例如：

```text
收藏 → 分组弹窗 → 点追问(N) → 知道了 → 【你的新步骤】 → 立即沟通
```

### 步骤 5：纯匹配逻辑与 DOM 分离

若新功能是 **列表行匹配**（类似 IM / 简历库），逻辑放独立模块：

- DOM 扫描 / 点击 → `xxx_nav.py`  
- 字段打分 / 姓名匹配 → `xxx_row_match.py` + `tests/test_xxx_row_match.py`  

```python
# tests/test_xxx_row_match.py — 不需要启动浏览器
def test_pick_best_row():
    profile = ...
    rows = [...]
    best, score = pick_best_resume_library_row(profile, rows)
    assert best.name == "张**"
```

### 步骤 6：如需控制台触发 → 加 API + 前端

1. **API**（`apps/api/routes/workflows.py` 或 `browser_setup.py`）  
2. 内部 `await run_on_playwright_loop(...)`  
3. **前端** `api/index.ts` + 组件按钮  

简历库跳转可参考：

- 后端：`resume_library_viewer.py` + `POST .../resume-library`  
- 前端：`CandidateList.vue` 的 `jumpToResumeLibrary`

### 步骤 7：本地验证

```powershell
# 终端 1：启动 API（可见浏览器）
.\scripts\start_console_prod.ps1

# 终端 2：跑相关单测
python -m pytest tests/test_resume_library_row_match.py -q

# 终端 3：可选脚本快速试页面
python scripts/run_liepin_demo.py   # 若存在
```

观察：

- 控制台 SSE 日志（`[步骤]` / `[完成]` / `[失败]`）  
- `data/debug/*.png`  
- 猎聘浏览器是否真实跳转  

### 步骤 8：常见坑检查清单

- [ ] 是否误点侧栏同名文字（收藏分组要排除「分组列表」「未分组」）  
- [ ] 是否用了 Windows Store 假 Python（应用执行别名要关）  
- [ ] 抓取进行中是否与简历库跳转抢同一 profile（等抓取结束再跳）  
- [ ] 新步骤是否 `await page.wait_for_timeout(500~1500)` 等 UI 稳定  
- [ ] 失败是否保存截图 + 明确 `RuntimeError` 消息  

---

## 5. 模块速查：改哪里

| 你想改… | 主要文件 |
|---------|----------|
| 搜索关键词/城市/年限 | `lpt_search.py`, `lpt_city_picker.py`, `lpt_adapter.py` |
| 点卡片、抽弹窗简历 | `extract_popup.py`, `extract_detail.py` |
| 收藏 / 追问分组 / 知道了 | `extract_popup.py`（`_click_collect_*` 系列） |
| 立即沟通 / 选岗位 | `extract_popup.py`（`_click_communicate_*`, `_select_job_*`） |
| 翻页 | `lpt_pagination.py`, `runner.py` |
| IM 发消息 / 匹配联系人 | `im_chat_runner.py`, `im_contact_match.py`, `im_chat_adapter.py` |
| 登录 / profile | `login_init.py`, `scripts/login_liepin.ps1` |
| 跳转简历库 | `resume_library_nav.py`, `resume_library_viewer.py` |
| 选择器常量 | **`lpt_adapter.py`**（首选） |
| 旧版列表页（非 LPT 弹窗） | `extract_list.py`, `liepin_adapter.py` |

---

## 6. 最小 Playwright 片段模板

### 6.1 独立调试脚本

```python
"""scripts/debug_my_lpt_step.py — 本地快速试一步 DOM"""
import asyncio
from services.fetch_worker.browser import BrowserManager
from services.fetch_worker.lpt_adapter import LPT_SEARCH_URL

async def main():
    mgr = BrowserManager(profile_name="hr_default")
    await mgr.start()
    page = await mgr.new_page()
    await page.goto(LPT_SEARCH_URL, wait_until="domcontentloaded")
    await page.wait_for_timeout(2000)
    # TODO: 在这里调用你要测的 async 函数
    await page.screenshot(path="data/debug/manual_test.png")
    await mgr.close()

if __name__ == "__main__":
    asyncio.run(main())
```

### 6.2 在已有 page 上加点文本

```python
async def _click_by_label(page, labels: list[str]) -> bool:
    for label in labels:
        try:
            loc = page.get_by_text(label, exact=False).first
            if await loc.is_visible(timeout=2000):
                await loc.click(timeout=5000)
                await page.wait_for_timeout(800)
                return True
        except Exception:
            continue
    return False
```

### 6.3 扫描表格行（简历库同类）

```python
rows = await page.evaluate("""() => {
    const norm = s => (s || '').replace(/\\s+/g, ' ').trim();
    return [...document.querySelectorAll('tr')].map((tr, i) => ({
        index: i,
        cells: [...tr.querySelectorAll('td')].map(td => norm(td.innerText)),
    })).filter(r => r.cells.length >= 3);
}""")
```

---

## 7. 与 TECHNICAL.md 的关系

- 架构、API 列表、Agent 说明 → [TECHNICAL.md](./TECHNICAL.md)  
- **本文档** → Playwright 专章：怎么点页面、怎么加步骤、怎么调试  

新增 Playwright 能力时，建议：

1. 更新本文档对应流程图  
2. 在 `lpt_adapter.py` 补选择器  
3. 补 `tests/test_*` 纯逻辑单测（能测的部分）  

---

## 8. 猎聘文案对照（易错）

| 界面位置 | 正确文案 | 错误/旧文案 |
|----------|----------|-------------|
| 弹窗发起沟通 | **立即沟通** / **继续沟通** | 立即开聊 |
| 收藏后分组 | **追问(N)** / **观察(N)** 整行 | 增加标签、侧栏分组列表 |
| 收藏确认 | **知道了** | — |
| 侧栏 | **人才管理** → 上方 **简历库** | — |

---

*文档版本：2026-06-10，与 `resume_library_nav`、`extract_popup` 收藏流程同步。*
