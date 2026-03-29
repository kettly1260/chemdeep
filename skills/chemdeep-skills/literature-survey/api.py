from .skill_impl import LiteratureSurveySkill
from fastapi import FastAPI, Request
from pydantic import BaseModel

app = FastAPI()
skill = LiteratureSurveySkill()

class SkillRequest(BaseModel):
    query: str
    language: str = 'zh'
    field: str = 'chemistry'
    mode: str = 'api'
    extra: dict = None

@app.post("/run")
def run_skill(req: SkillRequest):
    result = skill.run(
        query=req.query,
        language=req.language,
        field=req.field,
        mode=req.mode,
        **(req.extra or {})
    )
    return result
