"""Which programs a Railhq Pass covers.

The Pass covers up to users.railhq_pass_workspaces of the programs a person owns (1, 3 or
10 by tier). They pick which (users.railhq_pass_pick, ordered program ids); picks they no
longer own are skipped and any slots left go to their oldest owned programs. The result is
denormalised onto merchants.railhq_pass, which plans.current reads.

refresh() is the one place that writes merchants.railhq_pass. Call it for the owner (old
and new) whenever the count, the picks or ownership changes."""

from pymongo.asynchronous.database import AsyncDatabase


def workspaces_from(who: dict) -> int:
    """The count from Railhq (ID token, user fetch or pass.updated event). An older
    accounts service sends only `pass`: one workspace."""
    if not who.get("pass"):
        return 0
    n = who.get("pass_workspaces")
    return max(1, int(n)) if n else 1


def allowance(user: dict | None) -> int:
    """How many programs this person's Pass covers; 0 without one."""
    if not user or not user.get("railhq_pass"):
        return 0
    n = user.get("railhq_pass_workspaces")
    return max(1, int(n)) if n else 1


async def owned(db: AsyncDatabase, user_id: str) -> list[dict]:
    return await db.merchants.find({"owner_id": user_id}, {"name": 1, "created_at": 1, "railhq_pass": 1}).sort([("created_at", 1), ("_id", 1)]).to_list(None)


def choose(user: dict | None, programs: list[dict]) -> list[str]:
    """Covered program ids, picks first, then oldest. `programs` is oldest first."""
    n = allowance(user)
    ids = [m["_id"] for m in programs]
    out: list[str] = []
    for pid in [*((user or {}).get("railhq_pass_pick") or []), *ids]:
        if len(out) >= n:
            break
        if pid in ids and pid not in out:
            out.append(pid)
    return out


async def refresh(db: AsyncDatabase, user_id: str | None) -> list[str]:
    """Recompute and store which of this person's programs their Pass covers."""
    if not user_id:
        return []
    user = await db.users.find_one({"_id": user_id}, {"railhq_pass": 1, "railhq_pass_workspaces": 1, "railhq_pass_pick": 1})
    programs = await owned(db, user_id)
    covered = choose(user, programs)
    ids = [m["_id"] for m in programs]
    if covered:
        await db.merchants.update_many({"_id": {"$in": covered}, "owner_id": user_id}, {"$set": {"railhq_pass": True}})
    rest = [i for i in ids if i not in covered]
    if rest:
        await db.merchants.update_many({"_id": {"$in": rest}, "owner_id": user_id}, {"$set": {"railhq_pass": False}})
    return covered


async def set_pass(db: AsyncDatabase, user_id: str, on: bool, workspaces: int | None = None) -> None:
    """Store a person's Pass (and its workspace count) and recompute their coverage."""
    n = (workspaces if workspaces is not None else 1) if on else 0
    await db.users.update_one({"_id": user_id}, {"$set": {"railhq_pass": on, "railhq_pass_workspaces": n}})
    await refresh(db, user_id)


async def backfill(db: AsyncDatabase) -> None:
    """Before tiers, the Pass covered every program its holder owned. Recompute for every
    Pass holder and every owner of a program still marked covered."""
    users = {u["_id"] async for u in db.users.find({"railhq_pass": True}, {"_id": 1})}
    users |= {m.get("owner_id") async for m in db.merchants.find({"railhq_pass": True}, {"owner_id": 1})}
    for uid in users - {None}:
        await refresh(db, uid)
