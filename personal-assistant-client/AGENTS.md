# personal-assistant-client

> 本文件是 **personal-assistant-client** 目录的专用 instructions，仅适用于该目录下的相关工作。

## Directory Guide

`personal-assistant-client/` 是系统的**前端应用**，提供 Web Chat 对话界面，负责用户交互、消息渲染，以及飞书、OfficeClaw 等多接入渠道的客户端适配层。

开始前先阅读项目根目录的 [`AGENTS.md`](../AGENTS.md) 了解整体项目结构和规范。

## 设计指引

前端 UI 设计遵循 Apple 风格设计语言，详见 [`DESIGN.md`](DESIGN.md)。所有颜色、字体、间距、圆角、阴影和组件样式均按照 DESIGN.md 中定义的 design token 规范，禁止内联 hex 色值或硬编码尺寸。
