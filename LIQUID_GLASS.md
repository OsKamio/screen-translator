# 液态玻璃主题

重新启动更新后的程序，在「设置 → 界面 → 主题与外观 → 界面主题」选择「液态玻璃」，点击「保存更改」。
已有「跟随系统」「浅色」「深色」继续可选；默认主题不变。
液态玻璃会跟随 Windows 的浅色/深色外观，关闭系统「透明效果」时使用不透明表面。
界面动效开关及 Windows 的动画辅助功能偏好继续生效。

## 视觉与交互

- 中性的浅灰蓝 / 深石板底色，只有低对比柔光，搭配折射边缘、轻雾化和柔和高光；不绘制彩色条纹。
- 设置分组卡片、胶囊导航、主次操作按钮、悬浮入口、翻译结果和实时译文窗口使用统一材质。
- 文字独立按当前屏幕 DPI 绘制，不随材质一起折射；输入框、原生列表及菜单使用可读性优先的雾面配色。
- 保留原生控件的鼠标、键盘、焦点及点击语义。实时正文不播放位移或透明度动画。
- 设置窗口使用与主题统一的标题栏，外轮廓为 28px 平滑圆角；结果与实时窗口也使用同一外层圆角。
- 支持标题栏拖动、边缘缩放、双击最大化/还原及关闭。最大化时取消圆角，恢复窗口后重新显示。

## 对所提供 React 参考的原生适配

参考来源是用户提供的 Aceternity UI Liquid Glass 组件、demo 及 Liquid Glass Hero 文本。
保留圆角盒 SDF、Snell 折射、边缘深度、RGB 位移差、轻雾化与 tint 的建模思路，使用 Qt、NumPy 和 OpenCV 实现。
距离场使用解析法线，直接计算高度积分的导数，避免逐像素重复计算多张距离场。

| 参考行为 | 本应用的实现 |
| --- | --- |
| DOM / SVG 的 backdrop-filter | Qt 原生缓存材质，无 React、Tailwind 或 WebView 运行时 |
| 折射页面后面的内容 | 只采样应用自行绘制的色彩背景；不折射任意控件文字或桌面窗口 |
| demo 的在线办公室照片 | 代码生成的柔焦背景，无示例图片、下载请求或素材网络依赖 |
| Hero 的整屏图片、营销文案与导航 | 在现有功能界面中借鉴浮动胶囊与轻折射；保持工具的表单和翻译布局，背景使用安静的中性色 |
| 可调 bevel / scale / aberration / frost / tint | 正文表面预设为深度 14、强度 48、色散 4；导航借鉴 Hero 的深度 12、强度 32，色散进一步减至 2。frost 0.4；浅色白 tint 0.12，深色 0.06 |
| demo 拖动透镜 | 保留应用原有窗口拖动、导航伸缩与按钮反馈，不增加额外透镜控件 |
| reduced transparency / reduced motion | 跟随 Windows 透明效果和动画偏好，以及应用动效开关 |

这是适配后的玻璃主题，视觉不会与浏览器 demo 逐像素相同。
玻璃效果不触发桌面截图，不改变实时翻译的下层窗口抓屏、录屏可见或失败分离策略。

设置窗口通过 Qt 原生绘制统一圆角外轮廓与标题栏。透明边缘保留抗锯齿，未使用硬边区域 mask。
拖动与缩放使用 [QWindow 系统交互接口](https://doc.qt.io/qtforpython-6/PySide6/QtGui/QWindow.html)，
快速/排队的鼠标输入使用同一锚点继续处理，避免进入系统拖动时已经松开按键而丢失位移。
主题切换不重建现有窗口，不改变实时取景位置。

## 性能与验证

大面积材质先即时绘制同源底色，再由单个后台工作线程计算折射；QPixmap 转换和控件刷新留在 GUI 线程。
后台任务有数量上限，切换主题后丢弃旧结果；窗口销毁后不访问其控件。
正文、边框始终保持原生 DPI；柔焦材质单张采样限制约 11 万像素，缓存限制 32MiB，位移场缓存 3 个尺寸。
导航与悬浮入口动画只变换已有材质，空闲时没有持续刷新循环。

```powershell
python scripts/check_glass_theme.py
python scripts/run_checks.py --desktop --report checks.json
python scripts/benchmark_switch.py --theme glass --scheme dark glass-switch.json
python scripts/check_live_no_flicker.py --theme=glass
python scripts/check_live_local_e2e.py --theme=glass
python scripts/check_native_frame.py --out frame-preview
```

专项检查覆盖深浅跟随、保存选择、首次异步材质、缓存上限、减少透明效果、滚动坐标及实时窗口句柄/几何/正文像素稳定性。
切换基准记录 Qt 绘制和事件循环间隔，不将其标为显卡呈现帧率。
窗口外框检查覆盖浅/深与玻璃/普通主题，验证四角透明度、抗锯齿过渡、标题栏实际颜色、句柄稳定、最大化还原及重新打开。
