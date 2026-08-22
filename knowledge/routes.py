from fastapi import APIRouter, Depends
from pydantic import BaseModel

from knowledge.project_manager import ProjectManager
from utils.admin_guard import require_admin

router = APIRouter()
manager = ProjectManager()


class ProjectCreate(BaseModel):
    project_id: str
    name: str
    description: str = ""


@router.post("/projects")
def create_project(body: ProjectCreate, _admin: None = Depends(require_admin)):
    """Naya server-side research project banao (admin-only)."""
    return manager.create_project(body.project_id, body.name, body.description)


@router.get("/projects")
def list_projects(_admin: None = Depends(require_admin)):
    """Server-side project metadata dekho (admin-only)."""
    return {"projects": manager.list_projects()}


@router.get("/projects/{project_id}")
def get_project(project_id: str, _admin: None = Depends(require_admin)):
    """Ek server-side project ki details lo (admin-only)."""
    project = manager.get_project(project_id)
    if not project:
        return {"error": "Project nahi mila"}
    return project


@router.delete("/projects/{project_id}")
def delete_project(project_id: str, _admin: None = Depends(require_admin)):
    """Server-side project delete karo (admin-only)."""
    return manager.delete_project(project_id)
