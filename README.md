# hyprlayout

用鼠标拖拽来排列 Hyprland 的显示器布局 —— 一个 GTK4 / libadwaita 图形工具，
针对 Omarchy（Lua 配置）做了适配。

拖动画布上的方块即可摆放屏幕，改动会先用 `hyprctl` **实时生效**，确认后再写回
`~/.config/hypr/monitors.lua`。

```
┌──────────────────────────────────────┬─────────────────────┐
│                                      │ Output   [eDP-1  ▾] │
│   ┌────────┐ ┌──────────────────┐    │ Enabled       [ on] │
│   │ eDP-1  │ │      DP-1        │    │ Resolution 3200x... │
│   │ 1600×  │ │   3440×1440      │    │ Refresh      120 Hz │
│   │ 1000   │ │   @50Hz          │    │ Scale         2.00  │
│   └────────┘ └──────────────────┘    │ Rotation     Normal │
│                                      │ X / Y        0 / 0  │
└──────────────────────────────────────┴─────────────────────┘
```

## 为什么不用现成的

Wayland 上常见的 `nwg-displays` 直接生成 hyprlang 语法的 `monitors.conf`，而这台机器
上的 Omarchy 用的是 **Lua 配置**（`hl.monitor({ ... })`）。本工具直接按 Hyprland 自带的
`HL.MonitorSpec`（见 `/usr/share/hypr/stubs/hl.meta.lua`）生成 Lua，并且不会破坏你
手写的其他配置。

## 功能

- **拖拽排列**：吸附到相邻屏幕的边缘/中线，落点保证不重叠、不留缝；拖动时显示对齐参考线。
- **方向键微调**：选中后方向键每次 10 逻辑像素，按住 Shift 为 100。
- **每屏参数**：启用/禁用、分辨率、刷新率、缩放（含按真实 DPI 推荐的 Auto）、旋转、
  VRR、镜像、精确 X/Y 坐标。
- **先试后存**：Apply 会立刻通过 `hyprctl` 生效，并弹出 **15 秒倒计时**确认框 ——
  不确认就自动回滚，屏幕黑掉也不会把自己锁在外面。
- **安全写盘**：写 `monitors.lua` 前先展示 unified diff，写入前自动备份
  (`monitors.lua.bak.<时间戳>`)，采用原子替换。
- **不碰你的手写配置**：只接管自己的 managed block；`output = ""` 的兜底规则和当前
  未连接显示器的规则都原样保留。
- **布局档案**：把「桌面坞站」「只用笔记本屏」存成 profile，按显示器指纹自动识别。
- **热同步**：监听 Hyprland 的 socket2，插拔显示器后画布自动刷新（若有未应用的改动
  则只提示，不覆盖你的编辑）。
- **校验提示**：重叠、屏幕之间有缝导致鼠标过不去、缩放导致非整数逻辑分辨率，都会提示。

## 运行

无需安装，直接跑：

```bash
./bin/hyprlayout          # 图形界面
```

或者装进 `~/.local/bin` 和应用菜单：

```bash
make install              # 软链 bin/hyprlayout + 安装 .desktop
make uninstall
```

依赖：Python 3.11+、`hyprctl`、PyGObject + GTK4 + libadwaita
（Omarchy 上已自带：`python-gobject gtk4 libadwaita`）。

## 命令行

GUI 之外的能力都可以脚本化，适合绑快捷键：

```bash
hyprlayout --status              # 当前布局（人类可读）
hyprlayout --dump                # 当前布局（JSON）
hyprlayout --print-lua           # 打印对应的 monitors.lua 代码块
hyprlayout --diff                # 预览写盘会产生的改动
hyprlayout --save                # 把当前布局写入 monitors.lua（自动备份）
hyprlayout --save-profile dock   # 保存当前布局为 profile
hyprlayout --apply-profile dock  # 应用 profile（脚本用，无确认倒计时）
hyprlayout --list-profiles
```

绑到 Hyprland 快捷键（`~/.config/hypr/bindings.lua`）：

```lua
o.bind("SUPER + P", "Display layout", { launch = "hyprlayout" })
o.bind("SUPER + SHIFT + P", "Dock layout", "hyprlayout --apply-profile dock")
```

## 键盘

| 按键 | 作用 |
| --- | --- |
| 方向键 / Shift+方向键 | 移动选中的屏幕 10 / 100 逻辑像素 |
| Tab | 在画布上切换选中的屏幕 |
| Ctrl+Return | Apply |
| Ctrl+S | 保存到 monitors.lua |
| Ctrl+R | 从 Hyprland 重新读取 |
| Ctrl+Z | 丢弃改动（等于重新读取） |
| Ctrl+Q | 退出 |

## 两层「生效」的区别

Hyprland 里改显示器有两种途径，本工具都用上了：

1. `hyprctl eval 'hl.monitor({ … })'` —— **立刻生效但不持久**，`hyprctl reload` 或重启
   Hyprland 后就会回到配置文件的状态。Apply 走的是这条路，所以试错零成本。
2. `~/.config/hypr/monitors.lua` —— **持久生效**。确认满意后写盘，Hyprland 保存即自动
   重载。

所以：Apply 只是试，勾上「Also write …」或 Ctrl+S 才是存。

两条路发的是**同一段 Lua**（`MonitorState.lua_call()`），所以预览的 diff 就是实际运行的东西。

### 版本兼容

Hyprland 0.56 的 Lua 配置改变了运行时接口，这里都做了自动回退：

| 操作 | Lua 配置（0.56+） | 旧 hyprlang |
| --- | --- | --- |
| 应用布局 | `hyprctl eval 'hl.monitor({…})'` | `hyprctl --batch 'keyword monitor …'` |
| 定位屏幕 | `hyprctl dispatch 'hl.dsp.focus{monitor="DP-1"}'` | `dispatch focusmonitor DP-1` |
| 移动光标 | `hyprctl dispatch 'hl.dsp.cursor.move{x=…, y=…}'` | `dispatch movecursor x y` |

注意 `hyprctl` 即使拒绝请求也返回 exit code 0（Lua 配置下 `keyword` 会回
`can't work with non-legacy parsers`），所以成功与否只能看回复文本 —— 代码里就是这么判断的。

## 逻辑像素

Hyprland 的坐标是**逻辑**像素：分辨率先按 `transform` 旋转、再除以 `scale`。
本机为例 —— eDP-1 是 3200×2000@scale 2，占 1600×1000 逻辑像素；DP-1 是
3440×1440@scale 1，放在 x=1600 处正好贴住。画布和坐标输入框里的数字都是逻辑像素。

非整数逻辑分辨率（例如 3200 / 1.3）Hyprland 会自行微调 scale，界面会给出提示；
Scale 旁的 **Auto** 按钮会按 EDID 上报的物理尺寸算真实 DPI，并优先挑能整除的缩放值。

## 项目结构

```
hyprlayout/
├── bin/hyprlayout        # 免安装启动脚本
├── hyprlayout/
│   ├── model.py          # Mode / MonitorState / Rect：几何与 hyprctl 解析
│   ├── hypr.py           # hyprctl 调用 + socket2 事件监听
│   ├── snapping.py       # 边缘吸附、推开重叠、校验、自动排列
│   ├── luawriter.py      # monitors.lua 生成、合并、diff、备份写入
│   ├── profiles.py       # 布局档案（JSON）
│   ├── canvas.py         # 拖拽画布（DrawingArea + Cairo）
│   ├── window.py         # 主窗口与侧栏
│   ├── app.py            # Adw.Application
│   └── cli.py            # 命令行入口
└── tests/                # 94 个测试，只用标准库 unittest（无需 pytest）
```

## 测试

```bash
make test                 # 等价于 python3 -m unittest discover -t . -s tests
```

- 纯逻辑层（几何、吸附、Lua 生成、profile）不需要显示器就能跑。
- `test_canvas.py` 直接驱动拖拽管线（按下 → 移动 → 释放、方向键微调、重叠推开、
  两种主题下的重绘），需要显示器；无显示器时自动 skip。
- `test_window.py` 会读取真实的 `hyprctl monitors`，验证「有改动才允许 Apply」、
  校验横幅、侧栏联动等；它**只读**，不会应用也不会写任何文件。

## 已知边界

- `hyprctl keyword` 只作用于当前运行的 Hyprland 实例；跨会话持久化只有写文件一条路。
- 未连接的显示器不会出现在界面里（`hyprctl monitors all` 也不报），它们在
  `monitors.lua` 里的规则会被原样保留。
- HDR / ICC / 色彩管理等 `HL.MonitorSpec` 字段暂未接入界面，写盘时也不会动你手写的这些行。

## 许可

MIT，见 [LICENSE](LICENSE)。
