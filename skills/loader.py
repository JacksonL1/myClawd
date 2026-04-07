"""
skills/loader.py
扫描 Skills 目录，构建摘要供 system prompt 使用。
"""

import re
from pathlib import Path

import yaml

from config import settings


def _parse_frontmatter(content: str) -> dict:
    m = re.match(r"^---\s*\n(.*?)\n---\s*\n", content, re.DOTALL)
    if m:
        try:
            return yaml.safe_load(m.group(1)) or {}
        except Exception:
            pass
    return {}


def scan_skills(skills_dir: str | None = None) -> list[dict]:
    """
    扫描 skills_dir，返回所有 skill 的元信息列表。
    每项：{ name, description, path, script_files }
    """
    base = Path(skills_dir or settings.skills_dir)
    if not base.exists():
        return []

    skills = []
    for skill_md in sorted(base.glob("*/SKILL.md")):
        content = skill_md.read_text(encoding="utf-8", errors="replace")
        meta = _parse_frontmatter(content)

        name        = meta.get("name") or skill_md.parent.name
        description = meta.get("description", "")

        scripts_dir  = skill_md.parent / "scripts"
        script_files = (
            sorted(str(f) for f in scripts_dir.iterdir() if f.is_file())
            if scripts_dir.exists()
            else []
        )

        skills.append({
            "name":         name,
            "description":  description,
            "path":         str(skill_md),
            "script_files": script_files,
        })
    return skills


def load_skill_content(skill_path: str) -> str:
    """读取完整 SKILL.md，并附加 scripts 完整路径"""
    p = Path(skill_path)
    if not p.exists():
        # 兜底：在 skills_dir 下模糊搜索
        hits = list(Path(settings.skills_dir).glob("**/SKILL.md"))
        hits = [h for h in hits if skill_path.replace("\\", "/") in str(h).replace("\\", "/")]
        if not hits:
            return f"ERROR: 找不到 SKILL.md: {skill_path}"
        p = hits[0]

    content = p.read_text(encoding="utf-8", errors="replace")

    scripts_dir = p.parent / "scripts"
    if scripts_dir.exists():
        files = sorted(f for f in scripts_dir.iterdir() if f.is_file())
        if files:
            content += "\n\n## 可执行脚本（使用以下完整路径）\n"
            content += "\n".join(f"  {f.resolve()}" for f in files)
    return content


def build_skills_xml(skills: list[dict]) -> str:
    if not skills:
        return "<available_skills/>"
    lines = ["<available_skills>"]
    for s in skills:
        scripts = ""
        if s["script_files"]:
            names = ", ".join(Path(f).name for f in s["script_files"])
            scripts = f" scripts=[{names}]"
        lines.append(
            f'  <skill name="{s["name"]}" path="{s["path"]}">'
            f'{s["description"]}{scripts}</skill>'
        )
    lines.append("</available_skills>")
    return "\n".join(lines)
