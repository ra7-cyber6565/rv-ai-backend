from fastapi import APIRouter
from pydantic import BaseModel
from knowledge.project_manager import ProjectManager

router = APIRouter()
manager = ProjectManager()


class ProjectCreate(BaseModel):
    project_id: str
    name: str
    description: str = ""


@router.post("/projects")
def create_project(body: ProjectCreate):
    """Naya research project banao"""
    return manager.create_project(body.project_id, body.name, body.description)


@router.get("/projects")
def list_projects():
    """Saare projects dekho"""
    return {"projects": manager.list_projects()}


@router.get("/projects/{project_id}")
def get_project(project_id: str):
    """Ek project ki details lo"""
    project = manager.get_project(project_id)
    if not project:
        return {"error": "Project nahi mila"}
    return project


@router.delete("/projects/{project_id}")
def delete_project(project_id: str):
    """Project delete karo"""
    return manager.delete_project(project_id)
