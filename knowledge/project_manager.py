import json
import os
from datetime import datetime
from typing import List, Dict, Optional


DATA_FILE = "./knowledge_store.json"


class ProjectManager:
    """
    Projects aur uploaded documents ko manage karta hai
    """

    def __init__(self):
        self._ensure_store()

    def _ensure_store(self):
        if not os.path.exists(DATA_FILE):
            with open(DATA_FILE, "w") as f:
                json.dump({"projects": {}}, f)

    def _load(self) -> Dict:
        with open(DATA_FILE, "r") as f:
            return json.load(f)

    def _save(self, data: Dict):
        with open(DATA_FILE, "w") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)

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
            # Auto-create project if not exists
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
                "name": info["name"],
                "description": info["description"],
                "document_count": len(info["documents"]),
                "created_at": info["created_at"]
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
