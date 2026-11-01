# 目录

[简介](README.md)

# 使用工具

- [安装与连接](guide/install.md)
- [分三个阶段调色](guide/workflow.md)
  - [线性](guide/linear.md)
  - [影调](guide/tone.md)
  - [色彩](guide/color.md)
- [共享与复用调色](guide/shared-grades.md)
- [选择工作白点](guide/working-white.md)
- [反向调色与调色堆栈](guide/inverse-stack.md)
- [Blender 中的渲染方式](guide/render-methods.md)

# 理解模型

- [线性校正](theory/linear.md)
- [外观坐标与调色](theory/structure.md)
  - [保持饱和度的影调曲线](theory/tone.md)
  - [按影调塑形的色彩算子](theory/color.md)
- [求值与插值](theory/evaluation.md)
  - [有界 H–K 保护](theory/hk-guard.md)
  - [直接求值与采样求值](theory/lut.md)

# 项目开发

- [架构与运行时](development/architecture.md)
- [构建、测试与来源追踪](development/building.md)
- [参与贡献与发布](development/contributing.md)
  - [代码与调色模型](development/contributing-model.md)
  - [本地化](development/localization.md)
  - [文档与媒体](development/documentation.md)
  - [测试与测量](development/testing.md)
  - [LUT 采样实验：上界 128](development/lut-domain-study.md)
  - [发布](development/publishing.md)
  - [完整正向与反向数学规范](development/forward-inverse-math.md)

# 参考

- [致谢与参考文献](reference/credits.md)
- [许可证](reference/license.md)
