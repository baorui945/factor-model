# -*- coding: utf-8 -*-
"""
==============================================================================
factors.gates —— 判定型闸门（Gate）子包
==============================================================================

内置 F1 / F2 / F3 三个闸门；导入本包即完成注册。
"""

from .base import (GateFactor, register_gate, get_gate, all_gates,
                   build_gates)
from . import f1, f2, f3                      # noqa: F401  触发注册

__all__ = ['GateFactor', 'register_gate', 'get_gate', 'all_gates', 'build_gates']
