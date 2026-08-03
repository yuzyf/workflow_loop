# 包版本号，用于 pip/uv 安装时版本匹配
__version__ = "0.1.0"
# 产品身份标识：workflow --version 输出、安装脚本身份核对和安装事务校验共用同一组常量
# 当前产品只存在一个版本 0.1.0，不设兼容版本范围（CONTEXT.md "Fixed Product Version"）
PRODUCT_NAME = "workflow-loop"
PRODUCT_IDENTITY = f"{PRODUCT_NAME} {__version__}"
