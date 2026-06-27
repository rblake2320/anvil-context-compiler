"""ANVIL Context Compiler.

A zero-dependency core for compiling AI-agent work into cache-aware,
tool-minimized, evidence-bound execution plans.
"""

from .compiler import AnvilCompiler
from .models import CompileRequest, CompileResult, CompilerConfig

__all__ = ["AnvilCompiler", "CompileRequest", "CompileResult", "CompilerConfig"]
__version__ = "1.0.0"
