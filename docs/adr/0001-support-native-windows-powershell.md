# 第一版支持原生 Windows PowerShell

Workflow Loop 第一版同时支持 macOS、Linux 和原生 Windows，而不是要求 Windows 用户进入 WSL。为避免只有安装入口表面可用，Windows 支持包括独立的 `install.ps1`、结构化测试命令、Windows 进程树超时终止、跨平台路径处理和 Windows 发布测试；终端脚本只做平台适配，项目写入继续由同一套 Python 逻辑负责。
