import json
import os
from datetime import datetime
from typing import List, Dict, Optional


DATA_FILE = os.getenv("KNOWLEDGE_STORE_FILE", "./knowledge_store.json")


class ProjectManager:
    """
    Projects aur uploaded documents ko manage karta hai.

    Storage path env-driven hai taaki laptop par metadata bhi configured D:/data
    root mein rahe, repository/C: mein silently na gire.
    """

    def __init__(self):
        self._ensure_store()

    def _ensure_store(self):
        directory = os.path.dirname(os.path.abspath(DATA_FILE))
        if directory:
            os.makedirs(directory, exist_ok=True)
        if not os.path.exists(DATA_FILE):
            with open(DATA_FILE, "w", encoding="utf-8") as f:
                json.dump({"projects": {}}, f)

    def _load(self) -> Dict:
        try:
            with open(DATA_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
            if not isinstance(data, dict) or not isinstance(data.get("projects"), dict):
                return {"projects": {}}
            return data
        except (FileNotFoundError, json.JSONDecodeError):
            return {"projects": {}}

    def _save(self, data: Dict):
        directory = os.path.dirname(os.path.abspath(DATA_FILE))
        if directory:
            os.makedirs(directory, exist_ok=True)
        tmp = DATA_FILE + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, DATA_FILE)

    def create_project(self, project_id: str, name: str, description: str = "") -> Dict:
        """Naya project banao"""
        data = self._load()
        if project_id in data["projects"]:
            return {"error": "Project already exists", "project_id": project_id}

        data["projects"][project_id] = {
            "name": name,
            "description": description,
            "created_at": datetime.now().isoformat(),
            "documents": []
        }
        self._save(data)
        return {"message": f"Project '{name}' create ho gaya", "project_id": project_id}

    def add_document(self, project_id: str, filename: str, chunks: int) -> Dict:
        """Project mein document add karo"""
        data = self._load()
        if project_id not in data["projects"]:
            data["projects"][project_id] = {
                "name": project_id,
                "description": "Auto-created",
                "created_at": datetime.now().isoformat(),
                "documents": []
            }

        doc_entry = {
            "filename": filename,
            "chunks": chunks,
            "uploaded_at": datetime.now().isoformat()
        }
        data["projects"][project_id]["documents"].append(doc_entry)
        self._save(data)
        return {"message": f"'{filename}' project mein add ho gaya", "chunks": chunks}

    def get_project(self, project_id: str) -> Optional[Dict]:
        """Project ki details lo"""
        data = self._load()
        return data["projects"].get(project_id)

    def list_projects(self) -> List[Dict]:
        """Saare projects ki list lo"""
        data = self._load()
        result = []
        for pid, info in data["projects"].items():
            result.append({
                "project_id": pid,
                "name": info.get("name", pid),
                "description": info.get("description", ""),
                "document_count": len(info.get("documents", [])),
                "created_at": info.get("created_at", "")
            })
        return result

    def delete_project(self, project_id: str) -> Dict:
        """Project delete karo"""
        data = self._load()
        if project_id not in data["projects"]:
            return {"error": "Project nahi mila"}
        del data["projects"][project_id]
        self._save(data)
        return {"message": f"Project '{project_id}' delete ho gaya"}
