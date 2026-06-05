"""Enterprise Agent OS — Core module (lazy imports, zero-install friendly)."""
from __future__ import annotations
from typing import Any


def __getattr__(name: str) -> Any:
    """Lazy import — only loads modules when accessed."""
    _imports = {
        "settings": lambda: __import__("graxia_tool.core.config", fromlist=["settings"]).settings,
        "setup_logging": lambda: __import__("graxia_tool.core.logging", fromlist=["setup_logging"]).setup_logging,
        "get_logger": lambda: __import__("graxia_tool.core.logging", fromlist=["get_logger"]).get_logger,
        "PromptCache": lambda: __import__("graxia_tool.core.prompt_cache", fromlist=["PromptCache"]).PromptCache,
        # Heavy deps — only load when accessed
        "get_db": lambda: __import__("graxia_tool.core.database", fromlist=["get_db"]).get_db,
        "init_db": lambda: __import__("graxia_tool.core.database", fromlist=["init_db"]).init_db,
        "close_db": lambda: __import__("graxia_tool.core.database", fromlist=["close_db"]).close_db,
        "get_current_user": lambda: __import__("graxia_tool.core.auth", fromlist=["get_current_user"]).get_current_user,
        "require_admin": lambda: __import__("graxia_tool.core.auth", fromlist=["require_admin"]).require_admin,
        "create_access_token": lambda: __import__("graxia_tool.core.auth", fromlist=["create_access_token"]).create_access_token,
        "classify_intent": lambda: __import__("graxia_tool.core.intent_router", fromlist=["classify_intent"]).classify_intent,
        "Orchestrator": lambda: __import__("graxia_tool.core.orchestrator", fromlist=["Orchestrator"]).Orchestrator,
        "OutputValidator": lambda: __import__("graxia_tool.core.output_validator", fromlist=["OutputValidator"]).OutputValidator,
        "ApprovalFlow": lambda: __import__("graxia_tool.core.approval_flow", fromlist=["ApprovalFlow"]).ApprovalFlow,
        "RunLogger": lambda: __import__("graxia_tool.core.run_logger", fromlist=["RunLogger"]).RunLogger,
        "TokenBudgetManager": lambda: __import__("graxia_tool.core.token_budget", fromlist=["TokenBudgetManager"]).TokenBudgetManager,
        "ModelRouter": lambda: __import__("graxia_tool.core.model_router", fromlist=["ModelRouter"]).ModelRouter,
        "ContextCompressor": lambda: __import__("graxia_tool.core.context_compressor", fromlist=["ContextCompressor"]).ContextCompressor,
        "CostLedger": lambda: __import__("graxia_tool.core.cost_ledger", fromlist=["CostLedger"]).CostLedger,
    }
    if name in _imports:
        return _imports[name]()
    raise AttributeError(f"module 'graxia_tool.core' has no attribute '{name}'")
