from __future__ import annotations

import copy
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List

from utils.logger import get_logger

log = get_logger(__name__)


@dataclass(frozen=True)
class WorkflowInfo:
    name: str
    kind: str
    path: Path


class WorkflowLoader:
    def __init__(self, workflows_dir: Path):
        self.workflows_dir = Path(workflows_dir)
        self._index: dict[str, WorkflowInfo] = {}
        self._cache: dict[str, Dict[str, Any]] = {}
        self._scan()

    def _guess_kind(self, name: str) -> str:
        if name.startswith("image_"):
            return "image"
        if name.startswith("video_"):
            return "video"
        if name.startswith("flux_"):
            return "flux"
        return "unknown"

    def _scan(self) -> None:
        self._index.clear()
        if not self.workflows_dir.exists():
            log.warning(f"Workflows dir not found: {self.workflows_dir}")
            return
        for p in sorted(self.workflows_dir.glob("*.json")):
            name = p.stem
            kind = self._guess_kind(name)
            self._index[name] = WorkflowInfo(name=name, kind=kind, path=p)
            log.info(f"Workflow indexed: {name} ({kind})")

    def get_available_workflows(self) -> List[WorkflowInfo]:
        return list(self._index.values())

    def _convert_ui_to_api(self, ui_data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Конвертирует UI workflow (с "nodes" как list) в API формат.
        
        UI формат:
        {
          "nodes": [ {"id": 11, "type": "DualCLIPLoader", "inputs": [...], "widgets_values": [...]}, ... ],
          "links": [ [link_id, src_node, src_slot, dst_node, dst_slot, type], ... ]
        }
        
        API формат:
        {
          "11": {"class_type": "DualCLIPLoader", "inputs": {"clip_name1": "...", ...}},
          ...
        }
        """
        nodes = ui_data.get("nodes", [])
        links = ui_data.get("links", [])
        
        if not isinstance(nodes, list):
            return {}
        
        # Индексируем links по link_id для быстрого поиска
        links_by_id: Dict[int, tuple] = {}
        for link in links:
            if isinstance(link, list) and len(link) >= 5:
                link_id = link[0]
                links_by_id[link_id] = tuple(link)  # [link_id, src_node, src_slot, dst_node, dst_slot, type]
        
        # Сначала собираем список ID всех валидных нод (не пропускаем)
        valid_node_ids = set()
        for node in nodes:
            if not isinstance(node, dict):
                continue
            
            node_id = str(node.get("id", ""))
            node_type = node.get("type", "")
            class_type = str(node.get("class_type", ""))
            
            if not node_id or not node_type:
                continue
            
            # Пропускаем служебные ноды UI
            skip_types = {"MarkdownNote", "Note"}
            if node_type in skip_types or class_type in skip_types:
                log.debug(f"Skipping UI service node {node_id} (type={node_type})")
                continue
            
            valid_node_ids.add(node_id)
        
        api_workflow = {}
        
        for node in nodes:
            if not isinstance(node, dict):
                continue
            
            node_id = str(node.get("id", ""))
            node_type = node.get("type", "")
            class_type = str(node.get("class_type", ""))
            
            if not node_id or not node_type:
                continue
            
            # Пропускаем служебные ноды UI
            skip_types = {"MarkdownNote", "Note"}
            if node_type in skip_types or class_type in skip_types:
                continue
            
            # Начинаем строить API inputs
            api_inputs = {}
            
            # 1) Обрабатываем UI inputs (ссылки на другие ноды)
            ui_inputs = node.get("inputs", [])
            if isinstance(ui_inputs, list):
                for inp in ui_inputs:
                    if not isinstance(inp, dict):
                        continue
                    
                    inp_name = inp.get("name")
                    link_id = inp.get("link")
                    
                    if inp_name and link_id is not None:
                        # Если link есть → ищем source node и slot
                        link_data = links_by_id.get(link_id)
                        if link_data and len(link_data) >= 5:
                            # [link_id, src_node, src_slot, dst_node, dst_slot, type]
                            src_node = str(link_data[1])
                            src_slot = link_data[2]
                            
                            # ВАЖНО: проверяем что src_node не был пропущен
                            if src_node in valid_node_ids:
                                api_inputs[inp_name] = [src_node, int(src_slot)]
                            else:
                                log.debug(f"Skipping link from invalid node {src_node} to {node_id}.{inp_name}")
            
            # 2) Обрабатываем widgets_values (статические значения)
            widgets_values = node.get("widgets_values", [])
            if isinstance(widgets_values, list) and widgets_values:
                # Маппинг widgets в inputs по типу ноды
                if node_type == "CLIPTextEncode":
                    if len(widgets_values) > 0:
                        api_inputs["text"] = widgets_values[0]
                
                elif node_type == "DualCLIPLoader":
                    if len(widgets_values) > 0:
                        api_inputs["clip_name1"] = widgets_values[0]
                    if len(widgets_values) > 1:
                        api_inputs["clip_name2"] = widgets_values[1]
                
                elif node_type == "UNETLoader":
                    if len(widgets_values) > 0:
                        api_inputs["unet_name"] = widgets_values[0]
                    if len(widgets_values) > 1 and widgets_values[1] != "default":
                        api_inputs["weight_dtype"] = widgets_values[1]
                
                elif node_type == "VAELoader":
                    if len(widgets_values) > 0:
                        api_inputs["vae_name"] = widgets_values[0]
                
                elif node_type == "LoadImage":
                    if len(widgets_values) > 0:
                        api_inputs["image"] = widgets_values[0]
                
                elif node_type == "HunyuanVideo15ImageToVideo":
                    # widgets_values: [width, height, num_frames, seed]
                    if len(widgets_values) > 0:
                        api_inputs["width"] = widgets_values[0]
                    if len(widgets_values) > 1:
                        api_inputs["height"] = widgets_values[1]
                    if len(widgets_values) > 2:
                        api_inputs["num_frames"] = widgets_values[2]
                    if len(widgets_values) > 3:
                        api_inputs["seed"] = widgets_values[3]
                
                elif node_type == "CreateVideo":
                    if len(widgets_values) > 0:
                        api_inputs["fps"] = widgets_values[0]
                
                elif node_type == "SaveVideo":
                    # widgets_values: [filename_prefix, format, codec, ...]
                    if len(widgets_values) > 0:
                        api_inputs["filename_prefix"] = widgets_values[0]
                    if len(widgets_values) > 1:
                        api_inputs["format"] = widgets_values[1]
                    if len(widgets_values) > 2:
                        api_inputs["codec"] = widgets_values[2]
            
            api_workflow[node_id] = {
                "class_type": node_type,
                "inputs": api_inputs
            }
        
        log.debug(f"Converted UI workflow to API: {len(api_workflow)} nodes")
        return api_workflow

    def load(self, name: str) -> Dict[str, Any]:
        """
        Загружает workflow JSON и нормализует его структуру.
        
        Поддерживает три формата:
        1) Плоский API: {"1": {"class_type": "...", "inputs": {...}}, ...}
        2) API с обёрткой: {"nodes": {"1": {...}, "2": {...}}}
        3) UI workflow: {"nodes": [ {"id": 11, "type": "...", ...} ], "links": [...]}
        
        Возвращает ВСЕГДА плоский API формат (dict с node_id -> node_data).
        """
        if name not in self._index:
            raise FileNotFoundError(f"Workflow not found: {name}")
        
        if name not in self._cache:
            p = self._index[name].path
            try:
                data = json.loads(p.read_text(encoding="utf-8-sig"))
            except json.JSONDecodeError as e:
                raise ValueError(f"Invalid JSON in {name}: {e}")
            
            if not isinstance(data, dict):
                raise ValueError(f"Workflow {name} must be a dict, got {type(data)}")
            
            # Определяем формат и нормализуем
            normalized = None
            
            # Случай 1: UI workflow (nodes как list)
            if "nodes" in data and isinstance(data["nodes"], list):
                log.debug(f"Detected UI workflow format for {name}")
                normalized = self._convert_ui_to_api(data)
            
            # Случай 2: API с обёрткой {"nodes": {...}}
            elif "nodes" in data and isinstance(data["nodes"], dict):
                log.debug(f"Detected wrapped API workflow format for {name}")
                normalized = data["nodes"]
            
            # Случай 3: Плоский API
            else:
                log.debug(f"Detected flat API workflow format for {name}")
                normalized = {k: v for k, v in data.items() if isinstance(v, dict) and "inputs" in v}
                if not normalized:
                    # fallback: старый формат {"1": {...}}
                    normalized = {k: v for k, v in data.items() if isinstance(v, dict)}
            
            if not normalized:
                raise ValueError(f"Workflow {name} has no valid nodes")
            
            self._cache[name] = normalized
            log.info(f"Workflow loaded: {name} ({len(normalized)} nodes)")
        
        return copy.deepcopy(self._cache[name])
