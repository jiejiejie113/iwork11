"""实时读模型统一异常。"""


class ReadModelError(RuntimeError):
    """实时读模型基础异常。"""


class ReadModelNotReadyError(ReadModelError):
    """当前业务日期没有可安全读取的完整快照。"""


class SnapshotValidationError(ReadModelError):
    """待发布快照未通过结构或业务日期校验。"""


class SnapshotPublishInProgressError(ReadModelError):
    """同一业务日期已有快照发布任务正在执行。"""
