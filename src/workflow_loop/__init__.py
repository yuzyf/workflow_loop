# 包版本号，用于 pip/uv 安装时版本匹配
__version__ = "0.3.1"
# 产品身份标识：workflow --version 输出、安装脚本身份核对和安装事务校验共用同一组常量
# 本次发布版本为 0.3.1；后续发布使用尚未被 PyPI 占用的新版本号
PRODUCT_NAME = "workflow-loop"
PRODUCT_IDENTITY = f"{PRODUCT_NAME} {__version__}"
