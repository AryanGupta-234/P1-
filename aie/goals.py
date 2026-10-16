"""Persistent user-directed goals and dependency-aware steps; no action executor."""
from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

GOAL_STATUSES = {"active", "paused", "completed", "abandoned"}
STEP_STATUSES = {"pending", "in_progress", "blocked", "completed", "cancelled"}


class GoalStore:
    def __init__(self, path: Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as db:
            db.execute("""CREATE TABLE IF NOT EXISTS goals (
                goal_id TEXT PRIMARY KEY, title TEXT NOT NULL, description TEXT NOT NULL,
                status TEXT NOT NULL, created_at TEXT NOT NULL, updated_at TEXT NOT NULL
            )""")
            db.execute("""CREATE TABLE IF NOT EXISTS goal_steps (
                step_id TEXT PRIMARY KEY, goal_id TEXT NOT NULL, title TEXT NOT NULL,
                description TEXT NOT NULL, status TEXT NOT NULL, dependencies_json TEXT NOT NULL,
                position INTEGER NOT NULL, created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
                FOREIGN KEY(goal_id) REFERENCES goals(goal_id) ON DELETE CASCADE
            )""")
            db.execute("""CREATE TABLE IF NOT EXISTS goal_history (
                history_id INTEGER PRIMARY KEY AUTOINCREMENT, goal_id TEXT NOT NULL,
                step_id TEXT, event_type TEXT NOT NULL, previous_json TEXT,
                current_json TEXT NOT NULL, occurred_at TEXT NOT NULL
            )""")
            db.execute("CREATE INDEX IF NOT EXISTS idx_goal_steps_goal_position ON goal_steps(goal_id, position)")
            db.execute("""CREATE TABLE IF NOT EXISTS goal_plan_drafts (draft_id TEXT PRIMARY KEY, goal_id TEXT NOT NULL, status TEXT NOT NULL, model TEXT NOT NULL, plan_json TEXT NOT NULL, plan_sha256 TEXT NOT NULL, created_at TEXT NOT NULL, updated_at TEXT NOT NULL, FOREIGN KEY(goal_id) REFERENCES goals(goal_id) ON DELETE CASCADE)""")

    def _connect(self):
        db = sqlite3.connect(self.path, timeout=10)
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA journal_mode=WAL")
        db.execute("PRAGMA busy_timeout=10000")
        db.execute("PRAGMA foreign_keys=ON")
        return db

    @staticmethod
    def _id(value):
        if not isinstance(value, str) or not value or len(value) > 64:
            raise ValueError("ID must contain 1..64 characters")

    @staticmethod
    def _title(value, field="title"):
        if not isinstance(value, str) or not value.strip() or len(value) > 240:
            raise ValueError(f"{field} must contain 1..240 characters")
        return value.strip()

    @staticmethod
    def _record(db, goal_id, step_id, event_type, previous, current, now):
        db.execute(
            "INSERT INTO goal_history(goal_id,step_id,event_type,previous_json,current_json,occurred_at) VALUES(?,?,?,?,?,?)",
            (goal_id, step_id, event_type,
             json.dumps(previous, ensure_ascii=False) if previous is not None else None,
             json.dumps(current, ensure_ascii=False), now),
        )

    @staticmethod
    def _decode(goal, steps):
        decoded = []
        by_id = {}
        for row in steps:
            item = {
                "step_id": row["step_id"], "title": row["title"],
                "description": row["description"], "status": row["status"],
                "dependencies": json.loads(row["dependencies_json"]),
                "position": row["position"], "created_at": row["created_at"],
                "updated_at": row["updated_at"],
            }
            decoded.append(item)
            by_id[item["step_id"]] = item
        for item in decoded:
            item["ready"] = item["status"] == "pending" and all(
                by_id.get(dep, {}).get("status") == "completed" for dep in item["dependencies"]
            )
        return {
            "goal_id": goal["goal_id"], "title": goal["title"],
            "description": goal["description"], "status": goal["status"],
            "created_at": goal["created_at"], "updated_at": goal["updated_at"],
            "steps": decoded, "steps_by_id": by_id,
            "progress": {
                "total": len(decoded),
                "completed": sum(s["status"] == "completed" for s in decoded),
                "ready": sum(s["ready"] for s in decoded),
            },
        }

    def create(self, title: str, description: str = ""):
        title = self._title(title)
        if not isinstance(description, str) or len(description) > 8000:
            raise ValueError("description must be at most 8000 characters")
        now, goal_id = datetime.now(timezone.utc).isoformat(), str(uuid4())
        with self._connect() as db:
            db.execute("INSERT INTO goals VALUES(?,?,?,'active',?,?)", (goal_id,title,description,now,now))
            self._record(db,goal_id,None,"goal.created",None,{"title":title,"description":description,"status":"active"},now)
        return self.get(goal_id)

    def get(self, goal_id: str):
        self._id(goal_id)
        with self._connect() as db:
            goal = db.execute("SELECT * FROM goals WHERE goal_id=?",(goal_id,)).fetchone()
            if goal is None:
                return None
            steps = db.execute("SELECT * FROM goal_steps WHERE goal_id=? ORDER BY position,step_id",(goal_id,)).fetchall()
        return self._decode(goal,steps)

    def list(self, status: str | None = None, limit: int = 50):
        if status is not None and (not isinstance(status, str) or status not in GOAL_STATUSES):
            raise ValueError("invalid goal status")
        if isinstance(limit,bool) or not isinstance(limit,int) or not 1 <= limit <= 200:
            raise ValueError("limit must be between 1 and 200")
        with self._connect() as db:
            if status is None:
                rows=db.execute("SELECT * FROM goals ORDER BY updated_at DESC, goal_id LIMIT ?",(limit,)).fetchall()
            else:
                rows=db.execute("SELECT * FROM goals WHERE status=? ORDER BY updated_at DESC, goal_id LIMIT ?",(status,limit)).fetchall()
            result=[]
            for goal in rows:
                steps=db.execute("SELECT * FROM goal_steps WHERE goal_id=? ORDER BY position,step_id",(goal["goal_id"],)).fetchall()
                result.append(self._decode(goal,steps))
        return result

    def add_step(self, goal_id: str, title: str, description: str = "", dependencies: list[str] | None = None):
        self._id(goal_id)
        title=self._title(title,"step title")
        if not isinstance(description,str) or len(description)>8000:
            raise ValueError("description must be at most 8000 characters")
        dependencies=[] if dependencies is None else dependencies
        if not isinstance(dependencies,list) or len(dependencies)>32:
            raise ValueError("dependencies must be a list of up to 32 unique step IDs")
        for dep in dependencies:
            self._id(dep)
        if len(set(dependencies)) != len(dependencies):
            raise ValueError("dependencies must be unique")
        now,step_id=datetime.now(timezone.utc).isoformat(),str(uuid4())
        with self._connect() as db:
            goal=db.execute("SELECT status FROM goals WHERE goal_id=?",(goal_id,)).fetchone()
            if goal is None or goal["status"]!="active":
                raise ValueError("an existing active goal is required")
            rows=db.execute("SELECT step_id FROM goal_steps WHERE goal_id=?",(goal_id,)).fetchall()
            existing={r["step_id"] for r in rows}
            if len(existing)>=200:
                raise ValueError("a goal can contain at most 200 steps")
            if any(dep not in existing for dep in dependencies):
                raise ValueError("dependencies must reference existing steps in this goal")
            db.execute(
                "INSERT INTO goal_steps VALUES(?,?,?,?, 'pending',?,?,?,?)",
                (step_id,goal_id,title,description,json.dumps(dependencies),len(existing),now,now),
            )
            self._record(db,goal_id,step_id,"step.created",None,{"title":title,"status":"pending","dependencies":dependencies},now)
            db.execute("UPDATE goals SET updated_at=? WHERE goal_id=?",(now,goal_id))
        return self.get(goal_id)["steps_by_id"][step_id]

    def update_step(self, goal_id: str, step_id: str, status: str):
        self._id(goal_id); self._id(step_id)
        if not isinstance(status, str) or status not in STEP_STATUSES:
            raise ValueError("invalid step status")
        now=datetime.now(timezone.utc).isoformat()
        with self._connect() as db:
            goal=db.execute("SELECT status FROM goals WHERE goal_id=?",(goal_id,)).fetchone()
            row=db.execute("SELECT * FROM goal_steps WHERE goal_id=? AND step_id=?",(goal_id,step_id)).fetchone()
            if goal is None or row is None or goal["status"]!="active":
                raise ValueError("an existing step on an active goal is required")
            if row["status"] in {"completed","cancelled"} and status!=row["status"]:
                raise ValueError("completed and cancelled steps are terminal")
            deps=json.loads(row["dependencies_json"])
            if deps:
                marks=",".join("?" for _ in deps)
                states={r["step_id"]:r["status"] for r in db.execute(f"SELECT step_id,status FROM goal_steps WHERE step_id IN ({marks})",deps)}
            else:
                states={}
            done=all(states.get(dep)=="completed" for dep in deps)
            if status in {"in_progress","completed"} and not done:
                raise ValueError("all dependencies must be completed first")
            old=row["status"]
            if old==status:
                return self.get(goal_id)["steps_by_id"][step_id]
            db.execute("UPDATE goal_steps SET status=?,updated_at=? WHERE step_id=?",(status,now,step_id))
            self._record(db,goal_id,step_id,"step.status_changed",{"status":old},{"status":status},now)
            statuses=[r[0] for r in db.execute("SELECT status FROM goal_steps WHERE goal_id=?",(goal_id,))]
            new_goal="completed" if statuses and all(s=="completed" for s in statuses) else "active"
            db.execute("UPDATE goals SET status=?,updated_at=? WHERE goal_id=?",(new_goal,now,goal_id))
            if new_goal!=goal["status"]:
                self._record(db,goal_id,None,"goal.status_changed",{"status":goal["status"]},{"status":new_goal},now)
        return self.get(goal_id)["steps_by_id"][step_id]

    def set_status(self, goal_id: str, status: str):
        self._id(goal_id)
        if not isinstance(status, str) or status not in GOAL_STATUSES:
            raise ValueError("invalid goal status")
        now=datetime.now(timezone.utc).isoformat()
        with self._connect() as db:
            row=db.execute("SELECT status FROM goals WHERE goal_id=?",(goal_id,)).fetchone()
            if row is None:
                raise ValueError("goal not found")
            if row["status"]=="completed" and status!="completed":
                raise ValueError("completed goals are terminal")
            if status == "completed":
                progress = db.execute(
                    "SELECT COUNT(*), SUM(CASE WHEN status='completed' THEN 1 ELSE 0 END) "
                    "FROM goal_steps WHERE goal_id = ?", (goal_id,)
                ).fetchone()
                if progress[0] == 0 or progress[1] != progress[0]:
                    raise ValueError("a goal can be completed only after every step is completed")
            if row["status"]!=status:
                db.execute("UPDATE goals SET status=?,updated_at=? WHERE goal_id=?",(status,now,goal_id))
                self._record(db,goal_id,None,"goal.status_changed",{"status":row["status"]},{"status":status},now)
        return self.get(goal_id)

    def set_goal_status(self, goal_id: str, status: str):
        """Compatibility-named explicit goal status transition."""
        return self.set_status(goal_id, status)

    def history(self, goal_id: str, limit: int = 100):
        self._id(goal_id)
        if isinstance(limit,bool) or not isinstance(limit,int) or not 1<=limit<=500:
            raise ValueError("limit must be between 1 and 500")
        with self._connect() as db:
            rows=db.execute("SELECT * FROM goal_history WHERE goal_id=? ORDER BY history_id DESC LIMIT ?",(goal_id,limit)).fetchall()
        return [{
            "history_id":r["history_id"],"step_id":r["step_id"],"event_type":r["event_type"],
            "previous":json.loads(r["previous_json"]) if r["previous_json"] else None,
            "current":json.loads(r["current_json"]),"occurred_at":r["occurred_at"],
        } for r in rows]


    def get_plan_draft(self, draft_id: str):
        import hashlib
        self._id(draft_id)
        with self._connect() as db:
            row = db.execute("SELECT * FROM goal_plan_drafts WHERE draft_id=?", (draft_id,)).fetchone()
        if row is None:
            return None
        payload = row["plan_json"]
        if hashlib.sha256(payload.encode("utf-8")).hexdigest() != row["plan_sha256"]:
            raise ValueError("plan draft integrity check failed")
        return {"draft_id": row["draft_id"], "goal_id": row["goal_id"], "status": row["status"],
                "model": row["model"], "plan": json.loads(payload), "sha256": row["plan_sha256"],
                "created_at": row["created_at"], "updated_at": row["updated_at"]}
