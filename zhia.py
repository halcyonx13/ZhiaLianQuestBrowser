"""Builds the Zhia Lian event model from Project Gorgon data files.

build_model(data, version, live) returns one JSON-ready dict with quests,
NPCs, regions, chain links, titles, rewards and event items. Everything is
derived from the data each time the version changes; curated.py only adds
the few wiki facts the data doesn't encode.
"""
from __future__ import annotations

import html
import json
import re
from collections import OrderedDict, defaultdict
from datetime import datetime, timezone

import curated as C
from gorgon import GorgonData

QUEST_NAME_PREFIXES = ("Zhia Lian Event: ", "Zhia Lian's Whimsical Challenge: ")
CURRENCY_NAMES = {"Gold": "Councils", "LiveEventCredits": "Live Event Credits"}
ZHIA = "NPC_ZhiaLian"
BOOK_NPC = "EventTitleBooks"

# Objective types -> quest category, checked in this order.
CATEGORIES = [
    ("world", "World challenge", {"ScriptAtomicInt"}),
    ("combat", "Combat", {"Kill", "KillElite", "Bury", "UseAbilityOnTargets"}),
    ("crafting", "Crafting & cooking", {"UseRecipe"}),
    ("gathering", "Gathering", {"Collect", "Have", "Harvest", "Loot"}),
    ("errand", "Errands & oddities", set()),  # everything else
]
GROUP_RX = re.compile(
    r"group of \d|\d\+ (?:level|players)|bring (?:some )?friends|get (?:some |a bunch of |your )?friends|"
    r"gather (?:an army|your fellow)|need (?:a few )?friends|need assistance|need (?:some )?backup|"
    r"war band|posse|Elite",
    re.I,
)
SKILL_NOTE_RX = re.compile(r"\b(Gardening|Gourmand|Cooking|Alchemy|Tailoring|Necromancy) (\d+)")
ATTR_RX = re.compile(r"^\{([A-Z0-9_]+)\}\{([^}]*)\}(?:\{([^}]*)\})?$")
PERCENT_TYPES = {"AsBuffMod", "AsDebuffMod", "AsPercent"}


# ---------------------------------------------------------------- text helpers
def norm(s: str) -> str:
    return re.sub(r"[^a-z0-9]", "", (s or "").lower())


def camel_split(s: str) -> str:
    return re.sub(r"(?<=[a-z0-9])(?=[A-Z])", " ", s or "").strip()


def strip_tags(s: str) -> str:
    return re.sub(r"<[^>]+>", "", s or "")


def plain(s: str) -> str:
    return re.sub(r"\s+", " ", strip_tags(s)).strip()


def to_html(text: str) -> str:
    """Game text -> safe HTML. Keeps <i>, <b>, <em> and colors; splits paragraphs."""
    t = html.escape(text or "", quote=False)
    t = re.sub(r"&lt;(/?)(i|b|em)&gt;", r"<\1\2>", t)
    t = re.sub(r"&lt;color=(#[0-9a-fA-F]{3,8}|[a-zA-Z]+)&gt;", r'<span style="color:\1">', t)
    t = t.replace("&lt;/color&gt;", "</span>")
    t = re.sub(r"&lt;icon=\d+&gt;", "", t)
    paras = [p.strip() for p in re.split(r"\n\s*\n", t) if p.strip()]
    return "".join("<p>" + p.replace("\n", "<br>") + "</p>" for p in paras)


def flatten(req) -> list[dict]:
    """Quest requirements may be an object, a list, or nested lists (Or groups)."""
    out = []

    def walk(x):
        if isinstance(x, list):
            for y in x:
                walk(y)
        elif isinstance(x, dict):
            out.append(x)
            if x.get("T") == "Or":
                walk(x.get("List", []))

    walk(req)
    return out


def short_name(name: str) -> str:
    for p in QUEST_NAME_PREFIXES:
        if name.startswith(p):
            return name[len(p):]
    return name


def wiki_url(title: str) -> str:
    return "https://wiki.projectgorgon.com/wiki/" + title.replace(" ", "_")


# ---------------------------------------------------------------- the builder
class Builder:
    def __init__(self, data: dict, version: str, live: bool):
        self.d = data
        self.version = version
        self.live = live
        self.items = data["items"]
        self.recipes = data["recipes"]
        self.quests_all = data["quests"]
        self.abilities = data["abilities"]
        self.skills = data["skills"]
        self.attributes = data["attributes"]
        self.titles_all = data["playertitles"]
        self.areas = data["areas"]

        self.item_by_name = {v["InternalName"]: k for k, v in self.items.items() if "InternalName" in v}
        self.recipe_by_name = {v["InternalName"]: k for k, v in self.recipes.items() if "InternalName" in v}
        self.ability_by_name = {v["InternalName"]: k for k, v in self.abilities.items() if "InternalName" in v}
        self.quest_by_name = {v["InternalName"]: k for k, v in self.quests_all.items() if "InternalName" in v}
        self.region_of_area = {a: r for r, areas in C.REGIONS for a in areas}
        self.title_index = {norm(strip_tags(v.get("Title", ""))): k for k, v in self.titles_all.items()}
        self.title_scroll = {}
        for k, v in self.items.items():
            if v.get("BestowTitle"):
                self.title_scroll.setdefault(f"Title_{v['BestowTitle']}", k)
        self._build_npc_directory()
        self._build_monster_index()

    # ----- lookups
    def icon(self, icon_id):
        return GorgonData.icon_url(self.version, icon_id)

    def skill_name(self, key: str) -> str:
        s = self.skills.get(key) or {}
        return s.get("Name") or camel_split(key)

    def area_name(self, key: str) -> str:
        return (self.areas.get(key) or {}).get("FriendlyName") or camel_split(key.removeprefix("Area"))

    def item_ref(self, internal_name: str = None, key: str = None) -> dict:
        key = key or self.item_by_name.get(internal_name)
        it = self.items.get(key) if key else None
        if not it:
            return {"key": None, "name": camel_split(internal_name or "?"), "icon": None}
        return {"key": key, "name": it.get("Name", internal_name), "icon": self.icon(it.get("IconId"))}

    def recipe_ref(self, internal_name: str) -> dict:
        key = self.recipe_by_name.get(internal_name)
        r = self.recipes.get(key) if key else None
        if not r:
            return {"id": internal_name, "name": camel_split(internal_name), "icon": None}
        results = (r.get("ResultItems") or []) + (r.get("ProtoResultItems") or [])
        first = results[0]["ItemCode"] if results else None
        return {
            "id": internal_name,
            "key": key,
            "name": r.get("Name", internal_name),
            "skill": self.skill_name(r.get("Skill", "")),
            "level": r.get("SkillLevelReq", 0),
            "icon": self.icon(r.get("IconId")),
            "makes": self.item_ref(key=f"item_{first}") if first else None,
            "learn": self.recipe_sources(key),
        }

    def ability_ref(self, internal_name: str) -> dict:
        key = self.ability_by_name.get(internal_name)
        a = self.abilities.get(key) if key else None
        if not a:
            return {"id": internal_name, "name": camel_split(internal_name), "icon": None}
        return {
            "id": internal_name,
            "name": a.get("Name", internal_name),
            "skill": self.skill_name(a.get("Skill", "")) if a.get("Skill") not in (None, "Unknown") else None,
            "level": a.get("Level"),
            "desc": plain(a.get("Description", "")),
            "icon": self.icon(a.get("IconID")),
        }

    def title_key(self, raw: str):
        base = re.sub(r"^(Event_)?Halloween_", "", raw or "")
        return self.title_index.get(norm(base))

    def title_ref(self, raw: str) -> dict:
        key = self.title_key(raw)
        if not key:
            return {"key": None, "text": camel_split(re.sub(r"^(Event_)?Halloween_", "", raw)), "color": None}
        t = self.titles_all[key].get("Title", "")
        m = re.search(r"<color=([^>]+)>", t)
        return {"key": key, "text": strip_tags(t), "color": m.group(1) if m else None}

    # ----- NPCs
    def _build_npc_directory(self):
        info: dict[str, dict] = {}
        for k, v in self.d["npcs"].items():
            info[k] = {"name": v.get("Name"), "areas": [v["AreaName"]] if v.get("AreaName") else [],
                       "desc": v.get("Desc", "")}
        for sk, sv in self.d["strings_requested"].items():
            m = re.match(r"npc_(?:(Area[^/]+)/)?(.+)_(Name|Desc)$", sk)
            if not m:
                continue
            area, key, field = m.groups()
            rec = info.setdefault(key, {"name": None, "areas": [], "desc": ""})
            if field == "Name" and not rec["name"]:
                rec["name"] = sv
            if field == "Desc" and not rec["desc"]:
                rec["desc"] = sv
            if area and area not in rec["areas"]:
                rec["areas"].append(area)
        self.npc_info = info
        self.npc_by_name = defaultdict(list)
        for k, v in info.items():
            if v["name"]:
                self.npc_by_name[v["name"]].append(k)

    def npc_key_for_name(self, name: str):
        keys = self.npc_by_name.get(name, [])
        for k in keys:  # prefer event NPCs we know about
            if k in C.NPC_ROLES:
                return k
        for k in keys:
            if "Halloween" in k:
                return k
        return keys[0] if keys else None

    def _build_monster_index(self):
        # Only event monsters: generic names like "Ghost" live in many places.
        self.monster_areas = defaultdict(set)
        for sk, sv in self.d["strings_requested"].items():
            m = re.match(r"monster_(Area[^/]+)/[^/]*Halloween[^/]*_Name$", sk)
            if m:
                self.monster_areas[norm(sv)].add(m.group(1))

    # ----- event detection
    @staticmethod
    def is_event_quest(q: dict) -> bool:
        name = q.get("InternalName", "")
        sustain = json.dumps(q.get("RequirementsToSustain", {}))
        return (name.startswith("Event_Halloween") or "HalloweenQuests" in sustain
                or "Event_ZhiaWhim" in sustain)

    @staticmethod
    def is_title_book(q: dict) -> bool:
        for o in q.get("Objectives", []):
            for r in flatten(o.get("Requirements")):
                if r.get("T") == "TitleKnown" and str(r.get("Title", "")).startswith("Halloween_"):
                    return True
        return False

    # ----- per-quest parts
    def giver_for(self, q: dict):
        name = q["InternalName"]
        if name in C.GIVER_OVERRIDES:
            return C.GIVER_OVERRIDES[name]
        if self.is_title_book(q):
            return BOOK_NPC, None
        fn = q.get("FavorNpc")
        if fn:
            area, _, key = fn.rpartition("/")
            return key, area or None
        m = re.search(r"<i>([A-Z][^<\[\]:]{1,40}):\s*</i>", q.get("Description", ""))
        if m:
            speaker = m.group(1).strip()
            if speaker == "Zhia Lian":
                return ZHIA, None
            key = self.npc_key_for_name(speaker)
            if key:
                areas = self.npc_info.get(key, {}).get("areas", [])
                return key, areas[0] if len(areas) == 1 else None
        if q.get("IsAutoPreface"):
            return ZHIA, None
        return None, None

    def place_matches(self, text: str):
        found, t = [], text or ""
        for pat, region, spot in C.PLACE_PATTERNS:
            rx = re.compile(pat, re.I)
            if rx.search(t):
                found.append((region, spot))
                t = rx.sub(" ", t)
        return found

    def involved_npcs(self, text: str, giver: str):
        out = []
        for key, aliases in C.NPC_ALIASES.items():
            if key == giver:
                continue
            if any(re.search(r"\b" + re.escape(a) + r"\b", text) for a in aliases):
                out.append(key)
        return out

    def objective(self, o: dict) -> dict:
        notes = []
        for r in flatten(o.get("Requirements")):
            t = r.get("T")
            if t == "TimeOfDay":
                notes.append(f"Between {int(r.get('MinHour', 0)):02d}:00 and {int(r.get('MaxHour', 0)):02d}:00 game time")
            elif t == "ActiveCombatSkill":
                notes.append(f"{self.skill_name(r.get('Skill', ''))} must be your active skill")
        num = o.get("Number", 1)
        text = o.get("Description") or camel_split(o.get("Type", ""))
        return {
            "text": text,
            "count": num if isinstance(num, int) and num > 1 and str(num) not in text else None,
            "type": o.get("Type"),
            "notes": notes,
            "item": self.item_ref(o["ItemName"]) if o.get("ItemName") else None,
        }

    def parse_effect(self, raw: str, rw: dict, given: str, flags_set: list):
        m = re.match(r"^(\w+)(?:\((.*)\))?$", raw.strip())
        if not m:
            rw["other"].append(raw)
            return
        fn = m.group(1)
        args = [a.strip() for a in m.group(2).split(",")] if m.group(2) else []
        if fn == "DeltaNpcFavor" and len(args) == 2:
            key = args[0]
            rw["favor"].append({"npc": key, "name": (self.npc_info.get(key) or {}).get("name") or camel_split(key),
                                "amount": int(float(args[1]))})
        elif fn == "BestowTitle" and args:
            rw["titles"].append(self.title_ref(args[0]))
        elif fn == "SetInteractionFlag" and args:
            flags_set.append(args[0])
        elif fn == "LearnAbility" and args:
            a = self.ability_ref(args[0])
            a["given"] = given
            rw["abilities"].append(a)
        elif fn == "DeltaScriptAtomicInt" and args and args[0] == "SerbuleCommunityChestPoints":
            n = args[1] if len(args) > 1 else "1"
            rw["other"].append(f"+{n} point toward the Serbule community chest")
        elif re.match(r"ZhiasBlessing(\d+)$", fn):
            n = re.match(r"ZhiasBlessing(\d+)$", fn).group(1)
            rw["blessings"].append(int(n))
        else:
            rw["other"].append(camel_split(fn) + (f" ({', '.join(args)})" if args else ""))

    def rewards(self, q: dict, giver: str, flags_set: list) -> dict:
        rw = {"councils": 0, "currencies": [], "xp": [], "items": [], "recipes": [], "abilities": [],
              "titles": [], "favor": [], "blessings": [], "skillLevels": [], "other": [],
              "loot": None, "lootLevel": q.get("TSysLevel")}
        for r in q.get("Rewards", []):
            t = r.get("T")
            if t in ("Currency", "WorkOrderCurrency"):
                cur, amt = r.get("Currency", ""), r.get("Amount", 0)
                if cur == "Gold":
                    rw["councils"] += amt
                else:
                    rw["currencies"].append({"id": cur, "name": CURRENCY_NAMES.get(cur, camel_split(cur)),
                                             "amount": amt})
            elif t == "SkillXp":
                rw["xp"].append({"skill": self.skill_name(r.get("Skill", "")), "xp": r.get("Xp")})
            elif t == "Recipe":
                rr = self.recipe_ref(r.get("Recipe"))
                rr["given"] = "reward"
                rw["recipes"].append(rr)
            elif t == "Ability":
                a = self.ability_ref(r.get("Ability"))
                a["given"] = "reward"
                rw["abilities"].append(a)
            else:
                amt = r.get("Xp") or r.get("Amount") or r.get("Credits")
                rw["other"].append(f"{amt} {camel_split(t)}" if amt else camel_split(t))
        for it in q.get("Rewards_Items", []):
            rw["items"].append({**self.item_ref(it.get("Item")), "qty": it.get("StackSize", 1), "given": "reward"})
        for it in q.get("PreGiveItems", []):
            rw["items"].append({**self.item_ref(it.get("Item")), "qty": it.get("StackSize", 1), "given": "start"})
        for name in q.get("PreGiveRecipes", []):
            rr = self.recipe_ref(name)
            rr["given"] = "start"
            rw["recipes"].append(rr)
        for e in q.get("PreGiveEffects", []):
            self.parse_effect(e, rw, "start", flags_set)
        for e in q.get("Rewards_Effects", []):
            self.parse_effect(e, rw, "reward", flags_set)
        if q.get("Reward_Favor") and giver:
            rw["favor"].append({"npc": giver, "name": (self.npc_info.get(giver) or {}).get("name") or camel_split(giver),
                                "amount": q["Reward_Favor"]})
        for skill, n in (q.get("Reward_SkillLevels") or {}).items():
            rw["skillLevels"].append({"skill": self.skill_name(skill), "levels": n})
        prof = q.get("Rewards_NamedLootProfile")
        if prof:
            rw["loot"] = "Random Halloween loot" if "Halloween" in prof else camel_split(prof)
        return rw

    def category(self, objectives: list) -> str:
        types = {o.get("Type") for o in objectives}
        for key, _label, ts in CATEGORIES:
            if types & ts:
                return key
        return "errand"

    def repeat_text(self, q: dict):
        d, h, m = q.get("ReuseTime_Days"), q.get("ReuseTime_Hours"), q.get("ReuseTime_Minutes")
        if d:
            return f"Repeatable after {d} days (once per event)" if d >= 30 else f"Repeatable after {d} days"
        if h:
            return f"Repeatable after {h} hours"
        if m:
            return f"Repeatable after {m} minutes"
        return None

    def requirement_texts(self, q: dict) -> list[str]:
        out = []
        for r in flatten(q.get("Requirements")):
            t = r.get("T")
            if t == "HasEffectKeyword" and r.get("Keyword") == "Event_ZhiaWhim":
                out.append("Only while Zhia Lian has a Whimsical Challenge running (server-wide)")
            elif t == "IsNotGuest":
                out.append("Not available on guest accounts")
            elif t == "MinSkillLevel":
                out.append(f"{self.skill_name(r.get('Skill', ''))} level {r.get('Level')}")
            elif t == "MinFavorLevel":
                npc = (r.get("Npc") or "").rpartition("/")[2]
                out.append(f"{camel_split(r.get('Level', ''))} favor with "
                           f"{(self.npc_info.get(npc) or {}).get('name') or camel_split(npc)}")
        return out

    def quest_record(self, key: str, q: dict) -> dict:
        name = q.get("Name", q["InternalName"])
        giver, giver_area = self.giver_for(q)
        objectives = [self.objective(o) for o in q.get("Objectives", [])]
        desc_plain = plain(q.get("Description", ""))
        strong_text = name + "\n" + "\n".join(o["text"] for o in objectives)

        # where the quest happens
        strong = self.place_matches(strong_text)
        weak = [] if strong else self.place_matches(desc_plain)
        mon = []
        if not strong and not weak:
            for o in q.get("Objectives", []):
                if o.get("Type") in ("Kill", "KillElite"):
                    areas = self.monster_areas.get(norm(o.get("Target", "")), set())
                    if 1 <= len(areas) <= 2:
                        mon += [(self.region_of_area.get(a, self.area_name(a)), None) for a in sorted(areas)]
        involved = self.involved_npcs(strong_text, giver)
        npc_places = []
        if giver_area:
            npc_places.append((self.region_of_area.get(giver_area, self.area_name(giver_area)),
                               (self.npc_info.get(giver) or {}).get("name")))
        for k in involved:
            areas = (self.npc_info.get(k) or {}).get("areas", [])
            if len(areas) == 1:
                npc_places.append((self.region_of_area.get(areas[0], self.area_name(areas[0])),
                                   (self.npc_info.get(k) or {}).get("name")))
        regions: "OrderedDict[str, list]" = OrderedDict()
        for region, spot in strong + weak + mon + npc_places:
            spots = regions.setdefault(region, [])
            if spot and spot not in spots:
                spots.append(spot)
        if not regions:
            regions[C.ANYWHERE] = []

        # tags and notes
        notes = [plain(n) for n in re.findall(r"\[([^\]]+)\]", strip_tags(q.get("Description", "")))]
        tags = []
        if GROUP_RX.search(desc_plain) or any(o.get("Type") == "KillElite" for o in q.get("Objectives", [])):
            tags.append("Group recommended")
        if any("game time" in n for o in objectives for n in o["notes"]) or re.search(
                r"at night|nighttime|midnight|wee hours", desc_plain, re.I):
            tags.append("Night")
        for skill, lvl in SKILL_NOTE_RX.findall(" ".join(notes)):
            tags.append(f"{skill} {lvl}")
        for o in objectives:
            for n in o["notes"]:
                if n.endswith("active skill"):
                    tags.append(n.split(" must")[0] + " active")

        flags_set: list[str] = []
        rw = self.rewards(q, giver, flags_set)
        flags_needed = []
        for o in q.get("Objectives", []):
            if o.get("Type") == "InteractionFlag" and o.get("Target"):
                flags_needed.append(o["Target"])
            flags_needed += o.get("InteractionFlags", []) or []

        internal = q["InternalName"]
        if self.is_title_book(q):
            kind = "book"
        elif internal.startswith("Event_Halloween_ZhiaWhim") or "Event_ZhiaWhim" in json.dumps(q.get("Requirements", [])):
            kind = "challenge"
        elif giver == ZHIA:
            kind = "zhia"
        else:
            kind = "npc"

        preface = q.get("PrefaceText", "")
        return {
            "id": internal,
            "key": key,
            "num": int(key.rsplit("_", 1)[1]),
            "name": name,
            "short": short_name(name),
            "kind": kind,
            "giver": giver,
            "involved": involved,
            "regions": [{"region": r, "spots": s} for r, s in regions.items()],
            "category": self.category(q.get("Objectives", [])),
            "tags": list(dict.fromkeys(tags)),
            "notes": notes,
            "descHtml": to_html(q.get("Description", "")),
            "prefaceHtml": to_html(preface) if preface and plain(preface) != desc_plain else None,
            "successHtml": to_html(q.get("SuccessText", "")) if q.get("SuccessText") else None,
            "objectives": objectives,
            "requirements": self.requirement_texts(q),
            "rewards": rw,
            "repeat": self.repeat_text(q),
            "wiki": wiki_url(name),
            "_flagsSet": flags_set,
            "_flagsNeeded": flags_needed,
            "_followups": q.get("FollowUpQuests", []),
            "_requires": [r.get("Quest") for r in flatten(q.get("Requirements"))
                          if r.get("T") in ("QuestCompleted", "QuestCompletedRecently")],
        }

    # ----- sources text
    def npc_display(self, key: str) -> str:
        return (self.npc_info.get(key) or {}).get("name") or camel_split(key)

    def item_sources(self, item_key: str, quest_names: dict) -> list[str]:
        out, crafted = [], OrderedDict()  # skill -> levels, so enchanted variants share a line
        for e in (self.d["sources_items"].get(item_key) or {}).get("entries", []):
            t = e.get("type")
            if e.get("npc") == "AdminTestNpc":
                continue
            if t == "Recipe":
                r = self.recipes.get(f"recipe_{e.get('recipeId')}") or {}
                crafted.setdefault(self.skill_name(r.get("Skill", "")), set()).add(r.get("SkillLevelReq", 0))
            elif t in ("Quest", "QuestObjectiveMacGuffin"):
                qk = f"quest_{e.get('questId')}"
                out.append("Quest: " + quest_names.get(qk, (self.quests_all.get(qk) or {}).get("Name", qk)))
            elif t in ("Vendor", "Barter", "NpcGift", "HangOut"):
                label = {"Vendor": "Sold by", "Barter": "Bartered from", "NpcGift": "Gift from",
                         "HangOut": "Hang out with"}[t]
                out.append(f"{label} {self.npc_display(e.get('npc', ''))}")
            elif t == "Item":
                it = self.items.get(f"item_{e.get('itemTypeId')}") or {}
                out.append(f"From {it.get('Name', 'another item')}")
            else:
                out.append(camel_split(t))
        made = [f"Crafted with {skill} {' or '.join(str(x) for x in sorted(lv))}" for skill, lv in crafted.items()]
        return list(dict.fromkeys(made + out))

    def recipe_sources(self, recipe_key: str) -> list[str]:
        out = []
        for e in (self.d["sources_recipes"].get(recipe_key) or {}).get("entries", []):
            t = e.get("type")
            if e.get("npc") == "AdminTestNpc":
                continue
            if t == "Training":
                out.append(f"Trained by {self.npc_display(e.get('npc', ''))}")
            elif t == "Skill":
                out.append(f"Learned automatically ({self.skill_name(e.get('skill', ''))})")
            elif t == "Item":
                it = self.items.get(f"item_{e.get('itemTypeId')}") or {}
                out.append(f"Scroll: {it.get('Name', 'a recipe scroll')}")
            elif t == "Quest":
                qk = f"quest_{e.get('questId')}"
                out.append("Quest: " + (self.quests_all.get(qk) or {}).get("Name", qk))
            elif t == "NpcGift":
                out.append(f"Gift from {self.npc_display(e.get('npc', ''))}")
            elif t == "HangOut":
                out.append(f"Hang out with {self.npc_display(e.get('npc', ''))}")
            else:
                out.append(camel_split(t))
        return list(dict.fromkeys(out))

    def describe_effect(self, desc: str) -> str:
        m = ATTR_RX.match(desc)
        if not m:
            return plain(re.sub(r"<icon=\d+>", "", desc))
        token, raw, skill = m.group(1), m.group(2), m.group(3)
        try:
            val = float(raw)
        except ValueError:
            return f"{token} {raw}"
        a = self.attributes.get(token, {})
        dt = a.get("DisplayType", "AsBuffDelta")
        label = a.get("Label", camel_split(token))
        if dt == "AsBool":
            value = "Yes" if val else "No"
        else:
            x = val * 100 if dt in PERCENT_TYPES or dt == "AsDoubleTimes100" else val
            value = f"{x:+g}" + ("%" if dt in PERCENT_TYPES else "")
            if dt in PERCENT_TYPES:
                label = label.rstrip(" %")
        return f"{label} {value}" + (f" (with {self.skill_name(skill)} active)" if skill else "")

    # ---------------------------------------------------------------- assemble
    def build(self) -> dict:
        records = {}
        for k, q in self.quests_all.items():
            if self.is_event_quest(q) or self.is_title_book(q):
                records[q["InternalName"]] = self.quest_record(k, q)
        quests = sorted(records.values(), key=lambda r: (r["kind"] == "book", r["num"]))
        ids = set(records)

        # ----- links
        edges: "OrderedDict[tuple, dict]" = OrderedDict()

        def link(a, b, kind, note=None):
            if a not in ids or b not in ids or a == b:
                return
            e = edges.setdefault((a, b), {"from": a, "to": b, "kinds": [], "notes": []})
            if kind not in e["kinds"]:
                e["kinds"].append(kind)
            if note and note not in e["notes"]:
                e["notes"].append(note)

        setters = defaultdict(list)
        for r in quests:
            for f in r["_flagsSet"]:
                setters[f].append(r["id"])
        for r in quests:
            for f in r["_followups"]:
                link(r["id"], f, "followup")
            for p in r["_requires"]:
                link(p, r["id"], "requires")
            for f in r["_flagsNeeded"]:
                for s in setters.get(f, []):
                    link(s, r["id"], "completes")
        for a, b, kind, note in C.EXTRA_LINKS:
            link(a, b, kind, note)

        # ----- chains (connected groups)
        adj = defaultdict(set)
        for (a, b) in edges:
            adj[a].add(b)
            adj[b].add(a)
        seen, comps = set(), []
        for r in quests:
            if r["id"] in seen:
                continue
            stack, comp = [r["id"]], []
            while stack:
                x = stack.pop()
                if x in seen:
                    continue
                seen.add(x)
                comp.append(x)
                stack += adj[x]
            comps.append(comp)
        by_id = {r["id"]: r for r in quests}
        chains, singles = [], defaultdict(list)
        for comp in comps:
            comp.sort(key=lambda i: by_id[i]["num"])
            if len(comp) == 1 and by_id[comp[0]]["kind"] in ("challenge", "book"):
                singles[by_id[comp[0]]["kind"]].append(comp[0])
                continue
            if "Event_Halloween_CandiedApple" in comp:
                name = "Zhia Lian's quest tree"
                blurb = ("Zhia starts everyone with Candied Apples and Kill Skeletons. Each quest you finish "
                         "unlocks more, and the party branch brings in Brandon Mellus and his cursed cultists.")
            else:
                parents = {b for (a, b) in edges}
                root = next((i for i in comp if i not in parents), comp[0])
                name = by_id[root]["short"]
                giver = by_id[root]["giver"]
                blurb = f"Given by {self.npc_display(giver)}." if giver else ""
            chains.append({"id": comp[0], "name": name, "blurb": blurb, "quests": comp})
        if singles.get("challenge"):
            chains.append({"id": "challenges", "name": "Whimsical challenges",
                           "blurb": "Server-wide goals Zhia sets at random. Everyone delivers to Zhia's Agent in "
                                    "Serbule; success earns a blessing, failure brings her wrath.",
                           "quests": singles["challenge"]})
        if singles.get("book"):
            chains.append({"id": "books", "name": "Title collection books",
                           "blurb": "Read the book, then collect its six event titles for a bonus skill level.",
                           "quests": singles["book"]})
        chains.sort(key=lambda c: -len(c["quests"]) if c["id"] not in ("challenges", "books") else 0)

        # ----- NPCs
        npcs = {}

        def npc_rec(key):
            if key not in npcs:
                if key == BOOK_NPC:
                    npcs[key] = {"key": key, "name": "Event title books", "areas": [], "regions": [],
                                 "desc": "", "role": "Each book starts a collection quest. Read it from your "
                                                     "inventory.", "gives": [], "involved": []}
                else:
                    info = self.npc_info.get(key) or {}
                    areas = info.get("areas", [])
                    npcs[key] = {
                        "key": key,
                        "name": info.get("name") or camel_split(key),
                        "areas": [self.area_name(a) for a in areas],
                        "regions": list(dict.fromkeys(self.region_of_area.get(a, self.area_name(a)) for a in areas)),
                        "desc": "" if "Placeholder" in info.get("desc", "") else info.get("desc", ""),
                        "role": C.NPC_ROLES.get(key, ""),
                        "gives": [], "involved": [],
                    }
            return npcs[key]

        npc_rec(ZHIA)
        for r in quests:
            if r["giver"]:
                npc_rec(r["giver"])["gives"].append(r["id"])
            for k in r["involved"]:
                npc_rec(k)["involved"].append(r["id"])
        for k, n in npcs.items():
            n["involved"] = [i for i in n["involved"] if i not in n["gives"]]
        npc_list = sorted(npcs.values(), key=lambda n: (n["key"] != ZHIA, n["key"] == BOOK_NPC,
                                                        -len(n["gives"]), -len(n["involved"]), n["name"]))

        # ----- regions
        region_names = [r for r, _ in C.REGIONS] + [C.ANYWHERE]
        regions = []
        for rn in region_names:
            qids = [r["id"] for r in quests if any(x["region"] == rn for x in r["regions"])]
            if not qids:
                continue
            regions.append({
                "name": rn,
                "areas": [n for n in dict.fromkeys(self.area_name(a) for r, al in C.REGIONS if r == rn
                                                   for a in al if a in self.areas) if n != rn],
                "quests": qids,
                "npcs": [n["key"] for n in npc_list if rn in n["regions"]],
            })

        model = {
            "event": {
                "name": "Zhia Lian",
                "version": self.version,
                "live": self.live,
                "built": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                "wiki": C.WIKI_EVENT_PAGE,
                "credit": f"Some portions copyright {datetime.now().year} Elder Game, LLC.",
            },
            # display order: the main quest types first, server-wide challenges last
            "categories": [{"id": k, "label": label} for k, label, _ in CATEGORIES[1:] + CATEGORIES[:1]],
            "quests": [{k: v for k, v in r.items() if not k.startswith("_")} for r in quests],
            "edges": list(edges.values()),
            "chains": chains,
            "npcs": npc_list,
            "regions": regions,
        }
        model["rewards"] = self.rewards_section(quests)
        return model

    # ---------------------------------------------------------------- rewards tab
    def rewards_section(self, quests: list) -> dict:
        quest_names = {r["key"]: r["name"] for r in quests}
        event_quests = [r for r in quests if r["kind"] != "book"]

        # totals
        councils = sum(r["rewards"]["councils"] for r in event_quests)
        lec_quests = [r["id"] for r in event_quests
                      if any(c["id"] == "LiveEventCredits" for c in r["rewards"]["currencies"])]
        lec_total = sum(c["amount"] for r in event_quests for c in r["rewards"]["currencies"]
                        if c["id"] == "LiveEventCredits")
        zhia_favor = sum(f["amount"] for r in event_quests for f in r["rewards"]["favor"] if f["npc"] == ZHIA)

        # quest reward items, aggregated
        agg = OrderedDict()
        for r in event_quests:
            for it in r["rewards"]["items"]:
                k = it["key"] or it["name"]
                a = agg.setdefault(k, {**{x: it[x] for x in ("key", "name", "icon")}, "total": 0, "quests": []})
                a["total"] += it["qty"]
                a["quests"].append({"id": r["id"], "qty": it["qty"], "given": it["given"]})
        reward_items = sorted(agg.values(), key=lambda a: (-len(a["quests"]), a["name"]))

        # recipes and abilities from quests
        recipes, abilities = OrderedDict(), OrderedDict()
        for r in event_quests:
            for rr in r["rewards"]["recipes"]:
                e = recipes.setdefault(rr["id"], {**rr, "quests": []})
                e["quests"].append({"id": r["id"], "given": rr["given"]})
            for a in r["rewards"]["abilities"]:
                e = abilities.setdefault(a["id"], {**a, "quests": []})
                e["quests"].append({"id": r["id"], "given": a["given"]})

        # recipes the quests ask you to craft
        needed = OrderedDict()
        for r in event_quests:
            q = self.quests_all[r["key"]]
            for o in q.get("Objectives", []):
                if o.get("Type") == "UseRecipe" and o.get("Target") in self.recipe_by_name:
                    e = needed.setdefault(o["Target"], {**self.recipe_ref(o["Target"]), "quests": []})
                    e["quests"].append(r["id"])

        # titles
        title_keys = OrderedDict()
        for k, v in self.titles_all.items():
            if re.search(r"Zhia Lian event", v.get("Tooltip", ""), re.I):
                title_keys[k] = True
        bestowed = defaultdict(list)
        for r in quests:
            for t in r["rewards"]["titles"]:
                if t["key"]:
                    title_keys[t["key"]] = True
                    bestowed[t["key"]].append(r["id"])
        book_needs = defaultdict(list)
        for r in quests:
            if r["kind"] != "book":
                continue
            for o in self.quests_all[r["key"]].get("Objectives", []):
                for req in flatten(o.get("Requirements")):
                    if req.get("T") == "TitleKnown":
                        tk = self.title_key(req.get("Title", ""))
                        if tk:
                            title_keys[tk] = True
                            book_needs[tk].append(r["id"])
        titles = []
        for k in title_keys:
            v = self.titles_all[k]
            t = v.get("Title", "")
            m = re.search(r"<color=([^>]+)>", t)
            tip = v.get("Tooltip", "")
            how = []
            if bestowed.get(k):
                how.append("quest")
            if "trick-or-treat" in tip.lower():
                how.append("trick-or-treating")
            if re.search(r"Party Cultist", t):
                how.append("party chest")
            scroll = self.title_scroll.get(k)
            titles.append({
                "key": k, "text": strip_tags(t), "color": m.group(1) if m else None, "tooltip": tip,
                "retired": "Lint_NotObtainable" in v.get("Keywords", []),
                "quests": bestowed.get(k, []), "books": book_needs.get(k, []), "how": how,
                "scroll": self.item_ref(key=scroll) if scroll else None,
                "num": int(k.split("_")[1]),
            })
        titles.sort(key=lambda t: (t["retired"], -len(t["quests"]), t["num"]))

        # blessings and wrath (whimsical challenges)
        blessings = []
        for k, v in self.d["effects"].items():
            n = v.get("Name", "")
            if n.startswith("Zhia's Blessing") or n.startswith("Zhia's Wrath"):
                dur = v.get("Duration")
                try:
                    dur = int(dur)
                except (TypeError, ValueError):
                    dur = None
                blessings.append({"name": n, "desc": plain(v.get("Desc", "")), "icon": self.icon(v.get("IconId")),
                                  "kind": "blessing" if "Blessing" in n else "wrath",
                                  "duration": f"{dur // 60} minutes" if dur and dur > 0 else "Until the next challenge"})
        blessings.sort(key=lambda b: (b["kind"] != "blessing", b["name"]))

        return {
            "totals": {
                "councils": councils, "liveEventCredits": lec_total, "liveEventCreditQuests": lec_quests,
                "zhiaFavor": zhia_favor, "titles": sum(1 for t in titles if not t["retired"]),
                "quests": len(event_quests),
            },
            "titles": titles,
            "items": self.event_items(event_quests, quest_names),
            "rewardItems": reward_items,
            "recipes": list(recipes.values()),
            "abilities": list(abilities.values()),
            "craftNeeds": list(needed.values()),
            "blessings": blessings,
        }

    def event_items(self, event_quests: list, quest_names: dict) -> list:
        """Items that only exist for this event, grouped for display."""
        obtainable = {k for k, v in self.items.items() if "Lint_NotObtainable" not in (v.get("Keywords") or [])}
        marked = set()
        for k in obtainable:
            v = self.items[k]
            n = v.get("InternalName", "")
            kws = {x.split("=")[0] for x in v.get("Keywords") or []}
            if n.startswith("Title_"):
                continue  # title scrolls are shown with the titles
            if (re.search(r"Halloween|Zhia", n) or kws & {"HalloweenCandy", "MasqueradeMask", "FloatingPumpkin"}
                    or re.search(r"Zhia Lian", v.get("Description", ""))):
                marked.add(k)
        # loot keys handed out by event quests
        for r in event_quests:
            for it in r["rewards"]["items"]:
                if it["key"] and "EventLootKey" in (self.items[it["key"]].get("Keywords") or []):
                    marked.add(it["key"])

        def first_result(rec):
            res = (rec.get("ResultItems") or []) + (rec.get("ProtoResultItems") or [])
            return f"item_{res[0]['ItemCode']}" if res else None

        # recipes tied to the event: taught by event quests, or making a marked item
        event_recipes = set()
        for r in event_quests:
            for rr in r["rewards"]["recipes"]:
                if rr.get("key"):
                    event_recipes.add(rr["key"])
        for k, rec in self.recipes.items():
            if first_result(rec) in marked:
                event_recipes.add(k)
        # recipes taught by marked scrolls
        for k in list(marked):
            for rn in self.items[k].get("BestowRecipes") or []:
                if rn in self.recipe_by_name:
                    event_recipes.add(self.recipe_by_name[rn])
        recipe_names = {self.recipes[k]["InternalName"] for k in event_recipes}
        for k in event_recipes:
            res = first_result(self.recipes[k])
            if res in obtainable:
                marked.add(res)
        for k in obtainable:  # scrolls that teach an event recipe
            if set(self.items[k].get("BestowRecipes") or []) & recipe_names:
                marked.add(k)
        # Whole families: when one numbered tier is marked (BatWitchHat3), so are its
        # siblings (BatWitchHat4 to 11), even if only one of them mentions the event.
        tier_rx = re.compile(r"^(.*?[A-Za-z_])(\d+)$")
        by_base = defaultdict(list)
        for k in obtainable:
            m = tier_rx.match(self.items[k].get("InternalName", ""))
            if m:
                by_base[m.group(1)].append(k)
        for k in list(marked):
            m = tier_rx.match(self.items[k].get("InternalName", ""))
            if m:
                marked.update(by_base[m.group(1)])

        groups = OrderedDict((g, []) for g in ("wearable", "scroll", "candy", "food", "key", "other"))
        quest_rewarders = defaultdict(list)
        for r in event_quests:
            for it in r["rewards"]["items"]:
                if it["key"]:
                    quest_rewarders[it["key"]].append(r["id"])
        for k in marked:
            v = self.items[k]
            kws = {x.split("=")[0] for x in v.get("Keywords") or []}
            if v.get("EquipSlot"):
                g = "wearable"
            elif v.get("BestowRecipes") or v.get("BestowAbility"):
                g = "scroll"
            elif kws & {"Candy", "HalloweenCandy"}:
                g = "candy"
            elif kws & {"Food", "Edible", "Drink", "Snack", "Meal"} or v.get("FoodDesc"):
                g = "food"
            elif "EventLootKey" in kws or v.get("InternalName") == "ZhiaLianEventKey":
                g = "key"
            else:
                g = "other"
            groups[g].append({
                "key": k,
                "name": v.get("Name", k),
                "icon": self.icon(v.get("IconId")),
                "desc": plain(v.get("Description", "")),
                "slot": camel_split(v.get("EquipSlot", "")) or None,
                "level": v.get("CraftingTargetLevel"),
                "food": v.get("FoodDesc"),
                "stats": [self.describe_effect(e) for e in v.get("EffectDescs") or []],
                "skillReqs": [f"{self.skill_name(s)} {lvl}" for s, lvl in (v.get("SkillReqs") or {}).items()],
                "sources": self.item_sources(k, quest_names),
                "quests": quest_rewarders.get(k, []),
            })
        labels = {"wearable": "Wearables", "scroll": "Recipe and skill scrolls", "candy": "Candy",
                  "food": "Seasonal food and drink", "key": "Keys", "other": "Other event items"}
        out = []
        quality = ["Rough", "Crude", "Decent", "Nice", "Quality", "Great", "Amazing", "Astounding",
                   "Awesome", "Incredible", "Marvelous"]

        def sort_key(i):
            name = re.sub(r"^\W+", "", re.sub(r"^\w+: ", "", i["name"]))
            first, _, rest = name.partition(" ")
            if first in quality:  # group a family together, weakest first
                return (rest.lower(), quality.index(first), name)
            return (name.lower(), -1, name)

        for g, items in groups.items():
            if items:
                items.sort(key=sort_key)
                out.append({"id": g, "label": labels[g], "items": items})
        return out


def build_model(data: dict, version: str, live: bool) -> dict:
    return Builder(data, version, live).build()
