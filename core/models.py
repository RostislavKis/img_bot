# -*- coding: utf-8 -*-
"""РњРѕРґРµР»Рё РґР°РЅРЅС‹С… РґР»СЏ core РјРѕРґСѓР»СЏ."""
from enum import Enum
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional, Dict, Any


class TaskStatus(str, Enum):
    """РЎС‚Р°С‚СѓСЃ Р·Р°РґР°С‡Рё РіРµРЅРµСЂР°С†РёРё."""
    PENDING = "pending"
    QUEUED = "queued"
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class GenerationMode(str, Enum):
    """Р РµР¶РёРј РіРµРЅРµСЂР°С†РёРё."""
    IMAGE = "image"
    VIDEO = "video"


@dataclass
class GenerationTask:
    """Р—Р°РґР°С‡Р° РіРµРЅРµСЂР°С†РёРё РёР·РѕР±СЂР°Р¶РµРЅРёСЏ/РІРёРґРµРѕ."""
    task_id: str
    user_id: int
    workflow_name: str
    prompt: str
    mode: GenerationMode
    status: TaskStatus = TaskStatus.PENDING
    created_at: datetime = field(default_factory=datetime.now)
    updated_at: datetime = field(default_factory=datetime.now)
    result_file: Optional[str] = None
    error_message: Optional[str] = None
    comfy_prompt_id: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class WorkflowInfo:
    """РРЅС„РѕСЂРјР°С†РёСЏ Рѕ workflow."""
    name: str
    description: str
    mode: GenerationMode
    file_path: str
    supports_img2img: bool = False
