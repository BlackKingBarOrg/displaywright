# displaywright

显示器在哪里，屏幕上画着什么。一个窗口两件事。

一个给 [Omarchy](https://omarchy.org/) 和 Hyprland 用的 GTK4 / libadwaita 工具，
两半共享同一份「你的桌面长什么样」：

- **显示器排布** —— 拖拽摆放输出、吸附对齐，设置分辨率、刷新率、缩放和旋转。
  改动先用 `hyprctl` 实时生效，确认后写回 Lua 版 `monitors.lua`。
- **壁纸** —— 每块屏一张图，Windows 有的填充方式全都有。由一个替换掉内置背景
  渲染器的 `omarchy-shell` 插件负责绘制，所以每块屏永远只有一个 surface。

*[English](README.md)*

![显示器页：左侧可拖拽的显示器画布，右侧逐屏参数](docs/screenshot-displays.png)

![壁纸页：同一套排布，每块屏内绘制着各自的壁纸；下方是填充方式控件和图片库](docs/screenshot-wallpapers.png)

## 为什么合成一个 app

这本来就是同一个问题问了两遍。两半都要输出列表，都要它在逻辑像素下的几何，
都把桌面画成一组可点击的矩形，都要监听 Hyprland 的事件 socket 等着插拔显示器。
拆成两个程序跑，就会得到两个答案：壁纸工具里那块屏，还停在排布工具已经把它
挪走的位置上。

现在只有一个 `hyprctl` 读取器、一个事件监听、一套几何模型、一个画布。在任一页
选中的显示器，切到另一页还是选中的。把它拖到新位置，壁纸预览就跟过去 —— 并且
会明说排布还没应用，因为确实还没有。

合并还顺手了结了两个工具之间的一场分歧。`hyprctl` 报告的是旋转屏的**模式**，
而不是面板实际显示的尺寸：竖过来的 2560×1440 仍然报 `2560x1440`。两个工具里有
一个在用之前先把这个数字转了一遍，凭空造出一个任何显示器都不提供的
`1440x2560` 模式。合到一起之后，这种分歧再也藏不住了。

## 显示器排布

- **拖拽排列**：吸附到相邻屏幕的边缘/中线，落点保证不重叠、不留缝；拖动时显示对齐参考线。
- **方向键微调**：选中后方向键每次 10 逻辑像素，按住 Shift 为 100。吸附阈值会缩到半步，
  保证微调一定挪得动。
- **每屏参数**：启用/禁用、分辨率、刷新率、缩放（含按 EDID 真实 DPI 推荐的 Auto）、旋转、
  VRR、镜像、精确 X/Y 坐标。
- **先试后存**：Apply 会立刻通过 `hyprctl` 生效，并弹出 **15 秒倒计时**确认框 ——
  不确认就自动回滚，屏幕黑掉也不会把自己锁在外面。
- **安全写盘**：写 `monitors.lua` 前先展示 unified diff，写入前自动备份
  (`monitors.lua.bak.<时间戳>`)，采用原子替换。
- **不碰你的手写配置**：只接管自己的 managed block；`output = ""` 的兜底规则和当前
  未连接显示器的规则都原样保留。
- **安全地关掉笔记本屏**：接着外接屏时可以关掉内置屏；一旦没有外接屏，它会自己回来 ——
  **不管 app 有没有在运行**。详见下文。
- **布局档案**：把「桌面坞站」「只用笔记本屏」存成 profile，按显示器指纹自动识别。
- **校验提示**：重叠、屏幕之间有缝导致鼠标过不去、缩放导致非整数逻辑分辨率，都会提示。

### 为什么不用 nwg-displays

Wayland 上常见的 `nwg-displays` 直接生成 hyprlang 语法的 `monitors.conf`，而 Omarchy
用的是 **Lua 配置**；Hyprland 0.56 在 Lua 配置下还会直接拒绝 `hyprctl keyword`，而那正是
大多数工具用来实时生效的手段。displaywright 两头都说 Lua：

- 按 Hyprland 自带的 `HL.MonitorSpec`（见 `/usr/share/hypr/stubs/hl.meta.lua`）生成
  `hl.monitor({ ... })`；
- 用 `hyprctl eval` 应用改动，在旧 hyprlang 版本上自动回退到 `keyword`；
- 不会破坏你手写的其他配置。

## 壁纸

Omarchy 的桌面背景由 `omarchy-shell` 内部渲染，而那个渲染器**所有屏幕共用同一张图，
并且永远是裁剪填充** —— 既不能分屏设置，也没有填充方式可选。displaywright 把它换掉，
换成一个两样都支持的渲染器。

- **每块屏一张图。** 没动过的屏幕继续跟随 Omarchy 主题背景，所以刚装完看起来和原版
  Omarchy 一模一样。
- **Windows 有的填充方式全都有**，而且行为和 Windows 一致 —— 包括在缩放屏幕上，
  而这正是大多数工具把「居中」和「平铺」做错的地方。
- **预览不是估算。** 页面上方的显示器排布就是显示器页用的同一个画布，图片走的是
  **渲染器同一套算法**，所以「居中」到底会变成什么样，你在下决定之前就能看见。
- **跨屏拼接**，按你真实的布局切割，并且在屏幕没对齐时如实告诉你代价。
- **一个文件夹，装着你选过的图。** 挑中的图都会被复制进 `~/Pictures/Displaywright`，
  图库显示的就是这个文件夹。既不会因为你清空 `~/Downloads` 而丢壁纸，图库里也不会
  混进一堆截图。
- **纯色**也可以，不一定要图片。
- **改完即生效。** 这一页没有「应用」按钮；壁纸落下的那一刻就看得见，换一张就等于撤销。
  （显示器页刻意相反：难看的壁纸只是难看，错误的排布是一块你点不回来的黑屏。）
- **主题照常工作。** `omarchy-theme-bg-set`、SUPER + CTRL + SPACE 背景切换器、整主题切换，
  全都和以前一样，连配色过渡都在。

### 为什么不用 swaybg / hyprpaper / waypaper

**swaybg / hyprpaper / wpaperd** 都想自己独占背景层。但 Omarchy 的 shell 已经占着这一层了，
而且它还顺带管着主题切换 —— 给整个 shell 换配色的那个 IPC 调用，是搭在背景过渡里一起发过来的。
在上面再叠一个背景守护进程，结果只能二选一：要么两个 surface 在同一个 Wayland 图层上打架，
要么主题切换坏掉。**waypaper** 只是上面这些守护进程的前端，所以问题原封不动地继承了。

displaywright 反过来做：它**本身就是**背景渲染器，以普通 Omarchy shell 插件的身份安装。

### 填充方式

| displaywright | Windows | 行为 |
|---|---|---|
| `fill` | 填充 | 放大到铺满屏幕，超出部分裁掉。默认。 |
| `fit` | 适应 | 缩放到整张图可见，留白处显示背衬色。 |
| `stretch` | 拉伸 | 无视宽高比，强行拉满。 |
| `tile` | 平铺 | 按图片自身分辨率从左上角开始重复。 |
| `center` | 居中 | 按图片自身分辨率画在正中，四周是背衬色。 |
| `span` | 跨区 | 一张图同时铺过所有屏幕。 |

**居中和平铺是按设备像素定义的**，不是布局像素。在 200% 缩放的笔记本屏上 —— 物理
3200×2000，逻辑 1600×1000 —— 一张 800×600 的图被居中后，占据的正好是 800×600 个真实
像素，和 Windows 上一样。不做这层换算的工具会把它画成两倍大。

### 跨屏，以及它的代价

跨屏是把一张图铺满所有显示器的包围盒，每块屏显示自己压着的那一块。只有屏幕严丝合缝时
才没有损失。下面这两块就不是：

```
eDP-1  1600×1000 位于 0,56       包围盒 4160×1882
DP-1   2560×1440 位于 1600,-826  图像只有 68% 落在屏幕上
```

剩下 32% 掉进了两块屏之间的空隙里，没有任何东西能把它画出来。displaywright 会直接把这个
数字告诉你，而不是让你自己发现。这套几何是渲染器根据**实时**显示器列表算的，所以挪动
显示器会重新切割图片，不需要窗口开着。

## 依赖

- Hyprland（在 0.56 上测试；旧 hyprlang 版本走回退路径）
- Omarchy 4.x，带 `omarchy-shell`（Quickshell）—— 壁纸渲染器需要
- Python 3.11+
- PyGObject + GTK4 + libadwaita
- 视频壁纸需要 `qt6-multimedia-ffmpeg`，生成缩略图需要 `ffmpeg`

Arch / Omarchy：`sudo pacman -S --needed python-gobject gtk4 libadwaita`

显示器排布这一半在任何 Hyprland 上都能用，只有壁纸渲染器需要 Omarchy。

## 安装

无需构建，直接跑：

```bash
git clone https://github.com/BlackKingBarOrg/displaywright
cd displaywright
./bin/displaywright
```

或者装进 `~/.local/bin` 和应用菜单：

```bash
make install     # 软链 bin/displaywright + 安装 .desktop
make plugin      # 壁纸渲染器，装进 omarchy-shell
make uninstall
```

`make plugin` 单独一步，是因为它会改变由哪个插件占据桌面背景层。可以用 `make unplugin` 撤销。

如果你只想要壁纸渲染器、不要窗口，插件也单独发布了一份供 `omarchy plugin add` 使用 ——
见[只装渲染器](#只装渲染器)。

绑到 Hyprland 快捷键（`~/.config/hypr/bindings.lua`）：

```lua
o.bind("SUPER + P", "Displays and wallpapers", { launch = "displaywright" })
o.bind("SUPER + SHIFT + P", "Dock layout", "displaywright layout profile-apply dock")
```

### 从 wallwright / hyprlayout 迁移

displaywright 就是这两个工具合并来的。一条命令把东西都搬过来：

```bash
displaywright migrate
```

它会把 `~/Pictures/Wallwright` 改名为 `~/Pictures/Displaywright` 并改写指向它的路径，
把 `~/.config/wallwright/config.json` 搬成 `~/.config/displaywright/wallpapers.json`，
搬走 `~/.config/hyprlayout/profiles.json` 和缩略图缓存，然后装上新渲染器、把 wallwright
的那个从 `shell.json` 里清掉 —— 背景层上挂两个插件等于每次开机抛硬币。已经存在的目标
一律不覆盖，跑第二遍什么都不做。

在你执行它之前，旧的 `~/.config/wallwright/config.json` 仍然会被读取，所以中间不会突然
少东西。`monitors.lua` 里 hyprlayout 留下的 managed block 也能被识别并原地改写，不会在
下面再多出一块。

### 只装渲染器

壁纸这一半就是一个标准的 Omarchy shell 插件，单独发布了一个仓库，好让 `manifest.json`
待在仓库根目录 —— 这是 `omarchy plugin add` 的硬要求：

```bash
omarchy plugin add https://github.com/BlackKingBarOrg/displaywright-shell-plugin.git --enable
omarchy plugin disable omarchy.background
```

第二行不是可选的，而且 `omarchy plugin add` **不会**替你做（原因见下）。之后要手改
`~/.config/displaywright/wallpapers.json`，因为图片选择器在窗口里。想连窗口一起要的话，
`make plugin`（或 `displaywright renderer install`）会一次把两步都做掉，更省事。

那个仓库是用 `make publish-plugin` 从这里的 `plugin/` 生成的，所以 issue 和 PR 请提到本仓库。

### 安装渲染器到底改了什么

两个文件，都是最小改动：

- `~/.config/omarchy/plugins/ai.bkblab.displaywright` —— 指向本仓库的符号链接。
- `~/.config/omarchy/shell.json` —— `plugins[]` 里加上 `ai.bkblab.displaywright`，
  `disabledPlugins[]` 里加上 `omarchy.background`。文件里其他内容一概不动，包括你的
  bar 布局。

禁用 `omarchy.background` 不是可选项。两个插件都会在 `WlrLayer.Background` 上放一个
不透明 surface，而 Wayland 对同一图层上两个 surface 的先后顺序**没有定义** —— 两个都
开着，意味着每次开机看到哪张壁纸全靠抛硬币。

把它顶掉，就得接下它的第二份工作。Omarchy 切主题时会调用 `background themeTransition`，
而这个调用是**唯一**把新配色应用到运行中 shell 的地方。displaywright 完整实现了整个
`background` IPC 接口，配色部分也在内，所以切主题依然会给一切换色。
`displaywright renderer uninstall` 会把这些全部还原。

## 命令行

窗口能做的一切都可以脚本化。

```bash
displaywright                       # 打开窗口
displaywright outputs               # Hyprland 报告的显示器
```

```bash
displaywright layout status              # 当前排布（人类可读）
displaywright layout dump                # 当前排布（JSON）
displaywright layout lua                 # 打印对应的 monitors.lua 代码块
displaywright layout diff                # 预览 `layout save` 会产生的改动
displaywright layout save                # 写入 monitors.lua（自动备份）
displaywright layout builtin off         # 关掉笔记本内置屏（坞站场景）
displaywright layout builtin on
displaywright layout builtin toggle      # 来回切 —— 适合绑快捷键
displaywright layout profiles            # 列出已保存的 profile
displaywright layout profile-save dock
displaywright layout profile-apply dock  # 无确认倒计时
displaywright layout profile-delete dock
```

```bash
displaywright wallpaper status
displaywright wallpaper set DP-1 ~/Downloads/a.jpg              # 复制进来，保持当前填充方式
displaywright wallpaper set DP-1 ~/Downloads/a.jpg --fit tile
displaywright wallpaper set eDP-1 ~/a.png --fit fit --backdrop '#101820'
displaywright wallpaper set span ~/Pictures/wide.jpg            # 铺过所有屏幕
displaywright wallpaper set DP-1 /mnt/big.jpg --no-copy         # 原地引用，不复制
displaywright wallpaper color DP-1 '#101820'
displaywright wallpaper clear DP-1                              # 交还给主题背景
displaywright wallpaper clear                                   # 所有屏幕
```

```bash
displaywright renderer status
displaywright renderer install [--copy]   # --copy 表示复制而非符号链接
displaywright renderer uninstall
```

## 键盘

| 按键 | 作用 |
| --- | --- |
| 方向键 / Shift+方向键 | 移动选中的屏幕 10 / 100 逻辑像素 |
| Tab | 在画布上切换选中的屏幕 |
| Ctrl+Return | 应用排布 |
| Ctrl+S | 保存到 monitors.lua |
| Ctrl+R | 从 Hyprland 重新读取 |
| Ctrl+Z | 丢弃排布改动 |
| Ctrl+O | 打开壁纸文件夹 |
| Ctrl+Q | 退出 |

## 两层「生效」的区别

排布这一半有两种途径，本工具都用上了：

1. `hyprctl eval 'hl.monitor({ … })'` —— **立刻生效但不持久**，`hyprctl reload` 或重启
   Hyprland 后就会回到配置文件的状态。Apply 走的是这条路，所以试错零成本。
2. `~/.config/hypr/monitors.lua` —— **持久生效**。确认满意后写盘，Hyprland 保存即自动重载。

所以：Apply 只是试，勾上「Also write …」或 Ctrl+S 才是存。两条路发的是**同一段 Lua**
（`MonitorState.lua_call()`），所以预览的 diff 就是实际运行的东西。

壁纸没有这层区分：配置文件就是唯一的状态，渲染器直接监听它。

### 版本兼容

Hyprland 0.56 的 Lua 配置改变了运行时接口，这里都做了自动回退：

| 操作 | Lua 配置（0.56+） | 旧 hyprlang |
| --- | --- | --- |
| 应用布局 | `hyprctl eval 'hl.monitor({…})'` | `hyprctl --batch 'keyword monitor …'` |
| 定位屏幕 | `hyprctl dispatch 'hl.dsp.focus{monitor="DP-1"}'` | `dispatch focusmonitor DP-1` |
| 移动光标 | `hyprctl dispatch 'hl.dsp.cursor.move{x=…, y=…}'` | `dispatch movecursor x y` |

注意 `hyprctl` 即使拒绝请求也返回 exit code 0（Lua 配置下 `keyword` 会回
`can't work with non-legacy parsers`），所以成功与否只能看回复文本 —— 代码里就是这么判断的。

## 关掉笔记本自带屏幕

在侧栏把内置屏的 Enabled 关掉，或者执行 `displaywright layout builtin off`。它**只在有
外接屏连着时**保持关闭 —— 外接屏一拔，内置屏就自己亮回来，**跟这个 app 开不开无关**。

这个保证不是 displaywright 自己造的。把 `disabled = true` 写进 `monitors.lua` 是个陷阱：
没有任何东西会去删它，于是你下次离坞就是一台黑屏机器。Omarchy 已经备好了避开这个陷阱的
零件，displaywright 只是往里面写：

| 零件 | 作用 | 时机 |
| --- | --- | --- |
| `~/.local/state/omarchy/toggles/hypr/internal-monitor-disable.lua` | 真正的"关闭"规则放在这里；被 Hyprland 配置在 `monitors.lua` **之后** `require`，所以它生效 | 配置加载时 |
| `omarchy-recover-internal-monitor.service` | 若物理上没接外接屏，就删掉这个文件 | 图形会话启动前 |
| `omarchy-hyprland-monitor-watch` | 一旦没有活跃的外接输出，就把内置屏点回来 | 热插拔时 |

所以即使内置屏处于关闭状态，`monitors.lua` 里保留的仍是一条**启用**规则 —— 因为 Omarchy
恢复内置屏时，正是从那条规则读取分辨率、位置和缩放。`tests/test_displays_omarchy_contract.py`
用假 `HOME` 驱动 Omarchy 自己的脚本，把这套行为固定下来。

如果是没有 Omarchy 的纯 Hyprland，displaywright 会退回把 `disabled = true` 写进
`monitors.lua`，并在侧栏明确提示：这种情况下没有任何东西会替你把内置屏打开，离坞前请先
自己恢复。

## 逻辑像素

Hyprland 的坐标是**逻辑**像素：分辨率先按 `transform` 旋转、再除以 `scale`。
3200×2000 的面板在 scale 2 下占 1600×1000 逻辑像素，所以一块 scale 1 的 2560×1440
显示器放在 x=1600 处正好贴住。画布和坐标输入框里的数字都在这个空间里，跨屏几何也是 ——
这正是它能和渲染器里 Quickshell `ShellScreen` 报的数字对上的原因。

两个画布都按逻辑尺寸绘制矩形，因为只有这样，相对位置、错位间隙和跨屏预览才是真实的。
壁纸页矩形下方标注的则是显示器的**真实分辨率** —— 壁纸实际要覆盖的像素数 —— 旋转过的
带 `↻` 标记。在 200% 缩放的笔记本屏上这两个数相差一倍，所以两个都有用。

非整数逻辑分辨率（例如 3200 / 1.3）Hyprland 会自行微调 scale，界面会给出提示；
Scale 旁的 **Auto** 按钮会按 EDID 上报的物理尺寸算真实 DPI，并优先挑能整除的缩放值。

## 你的壁纸文件夹

`~/Pictures/Displaywright`，首次运行时自动创建。（准确地说是 `XDG_PICTURES_DIR` 指向的
目录下的 `Displaywright`。）在你手动添加别的目录之前，它是图库**唯一**显示的文件夹；
菜单里的**「打开壁纸文件夹」**会直接打开它。

从选择器看不到的地方挑图 —— 下载目录、`/tmp` 里的临时文件、外接盘 —— 会被复制进来，
壁纸指向副本。这正是这个文件夹存在的理由，而且一举两得：一张清空 `~/Downloads` 就没了
的壁纸算不上壁纸；而拿整个 `~/Pictures` 当图库，里面绝大部分是截图。

菜单里的**「添加文件夹…」**可以纳入你已有的壁纸收藏；那些目录里的文件会原地使用，不再复制。

复制这件事做得很克制，不会攒垃圾：

- 选择器已经能看到的文件原地不动，所以点缩略图绝不会克隆出一份。
- 内容已经在文件夹里的文件会解析到那份副本，所以同一张图选两次不会变成两份。
- 名字撞车但内容不同的，存成 `name-2.ext`。
- 副本先写临时名再重命名就位，所以写到一半的文件不会被当成壁纸候选。

`wallpaper set --no-copy` 可以单次跳过复制。无论哪种方式，原文件都不会被动。

## 配置文件

两个都在 `~/.config/displaywright/` 下。

`wallpapers.json` 被渲染器监听，所以手改也生效；写入是原子的，写到一半的文件不可能出现
在屏幕上。

```json
{
  "version": 1,
  "monitors": {
    "eDP-1": { "kind": "image", "path": "/home/you/a.jpg", "fit": "fill" },
    "DP-1":  { "kind": "image", "path": "/home/you/b.png", "fit": "center",
               "backdrop": "#101820" }
  },
  "span": null,
  "folders": ["/home/you/Pictures/Wallpapers"]
}
```

没出现在 `monitors` 里的输出跟随主题背景。`span` 一旦设置，优先级高于 `monitors` 里的
所有条目。`folders` 只被图片选择器读取。解析不了的内容会被丢弃而不是报错 —— 一条写坏的
记录只让你损失那一张壁纸，不会搭上整个桌面。

`profiles.json` 保存命名的排布档案，每条都带一份保存时的显示器指纹。

## 动态壁纸

把渲染器做成这个形态的意义在于：它绘制的那个 surface 装得下的东西远不止一张图片。
每个 source 都带 `kind`，渲染器按它分派，所以剩下的工作就是每种格式一个 QML 文件。

| kind | 状态 |
|---|---|
| `image` | 已完成，上文描述的全部内容。 |
| `color` | 已完成。 |
| `video` | 已实现（`MediaPlayer`，循环、静音、全屏窗口遮挡时暂停）。类型检查干净，但**尚未在硬件上实跑过** —— 请当作未测试。 |
| `web` | 未开始。在背景 surface 上跑 `WebEngineView`；Wallpaper Engine 的「Web」类壁纸底层就是这个。 |
| `shader` | 未开始。用 `ShaderEffect` 跑片段着色器，做 Shadertoy 那类背景。 |

Wallpaper Engine 自己的 `.pkg` 场景格式**刻意不做**。它是私有二进制格式，而逆向出来的
播放器要求你在 Steam 上买了 Wallpaper Engine。将来真要支持，加一个 `kind` 就行，不用动
这里的任何其他部分。

## 项目结构

```
displaywright/
├── bin/displaywright         # 免安装启动脚本
├── displaywright/
│   ├── model.py              # Mode / MonitorState / Rect：几何、hyprctl 解析、Lua 生成
│   ├── hypr.py               # hyprctl 调用、方言回退、socket2 事件监听
│   ├── paths.py              # XDG 目录与原子写入辅助
│   ├── session.py            # 两页共享的状态
│   ├── canvas.py             # 缩小版的桌面：视图换算、命中测试、选中项
│   ├── drawing.py            # 两个画布共用的 cairo 辅助
│   ├── window.py             # 一个窗口，两个页面
│   ├── app.py                # Adw.Application
│   ├── cli.py                # 命令行入口
│   ├── migrate.py            # wallwright / hyprlayout -> displaywright
│   ├── displays/
│   │   ├── snapping.py       # 边缘吸附、推开重叠、校验、自动排列
│   │   ├── luawriter.py      # monitors.lua 生成、合并、diff、备份写入
│   │   ├── omarchy.py        # 内置屏开关
│   │   ├── profiles.py       # 布局档案（JSON）
│   │   ├── canvas.py         # 可拖拽的排布画布
│   │   └── page.py           # 画布 + 逐屏侧栏
│   └── wallpapers/
│       ├── model.py          # Fit / Kind / Source / Config
│       ├── store.py          # wallpapers.json，原子写入
│       ├── preview.py        # 每种填充方式下图片落在哪里
│       ├── span.py           # 一张图铺满整个桌面
│       ├── library.py        # 壁纸文件夹、缩略图、复制文件
│       ├── plugin.py         # 把渲染器装进 omarchy-shell
│       ├── shell.py          # omarchy-shell IPC
│       ├── canvas.py         # 带壁纸的排布画布
│       └── page.py           # 画布、填充控件、图片库
├── plugin/                   # QML 渲染器，跑在 omarchy-shell 里
│   ├── manifest.json         # Omarchy 插件契约，schemaVersion 1
│   ├── Wallpaper.qml         # 入口：每块屏一个 surface，监听配置文件
│   ├── Surface.qml           # 单块屏的 surface、过渡动画、IPC
│   ├── renderers/            # 每种 source kind 一个文件：image / color / video
│   └── README.md、LICENSE、preview.png   # 它自己作为仓库根发布时要用
└── tests/                    # 290 个测试，只用标准库 unittest
```

## 测试

```bash
make test             # python3 -m unittest discover -t . -s tests
make lint             # 编译 Python 字节码，并用 Quickshell 和 Omarchy 的真实模块对 QML 做类型检查
make validate-plugin  # 用 Omarchy 自带的 omarchy-plugin-validate 校验 plugin/
make run              # 从仓库直接运行窗口
```

- 纯逻辑层（几何、吸附、Lua 生成、profile、填充、跨屏、插件安装、迁移）不需要显示器
  也不需要合成器。
- `test_canvas.py` 直接驱动拖拽管线（按下 → 移动 → 释放、方向键微调、重叠推开、
  两种主题下的重绘）。
- `test_displays_page.py` 用真实的 `hyprctl monitors` 把整个窗口搭起来，验证
  「有改动才允许 Apply」、校验横幅、侧栏联动等。它**只读**：不会应用布局，而且所有
  XDG 目录都先被重定向到临时目录。
- `test_plugin_spec.py` 把 Omarchy 的插件契约（`PluginRegistry.qml` 和
  `omarchy-plugin-validate` 里的 manifest 规则）重新实现了一遍，所以一份会被用户 shell
  拒绝的 manifest 会先在测试里挂掉 —— 哪怕跑在没装 Omarchy 的 runner 上。机器上真有
  Omarchy 时，它还会额外调一次真正的校验器。
- 没装 PyGObject 时 GTK 测试会 skip 而不是失败，所以核心测试在哪都能跑。

## 已知边界

- `hyprctl` 只作用于当前运行的 Hyprland 实例；跨会话持久化只有写文件一条路。
- 未连接的显示器不会出现在界面里（`hyprctl monitors all` 也不报），它们在
  `monitors.lua` 里的规则会被原样保留。
- HDR / ICC / 色彩管理等 `HL.MonitorSpec` 字段暂未接入界面，写盘时也不会动你手写的这些行。
- 渲染器是以符号链接方式安装的，而 Omarchy 的插件监听不跟随符号链接 —— 所以改了 QML
  不会热重载。运行 `omarchy-restart-shell` 才会生效。

## 发布渲染器插件

`omarchy plugin add <url>` 是把仓库直接 clone 成 `~/.config/omarchy/plugins/<id>/`，
所以 `manifest.json` 必须在仓库根。而我们的它在 `plugin/` 里，和必须与之保持一致的
`preview.py` 放在一起 —— 把这两个拆成两个手工维护的仓库，正是「预览开始骗人」的开端。
所以改成发布时再把 subtree 切出去：

```bash
make publish-plugin      # 校验 + 跑测试 + git subtree split --prefix=plugin + push
```

产物是一个**生成的镜像仓库**，不要往里面直接提交，下次发布会 force-push 覆盖掉。

要上架社区目录 [omarchyplugins.com](https://omarchyplugins.com)，去开它的 issue 表单，
填插件仓库链接、分类和标签。他们会自动校验当前 commit，然后由维护者审核通过。

## 参与开发

欢迎提 issue 和 PR —— 测试怎么跑、报 bug 要附什么，见 [CONTRIBUTING.md](CONTRIBUTING.md)。

## 许可

MIT，见 [LICENSE](LICENSE)。
