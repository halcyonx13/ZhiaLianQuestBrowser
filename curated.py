"""Facts about the Zhia Lian event that the game data doesn't spell out.

Everything else in the app is computed from the live JSON files. What's here
comes from the Project Gorgon wiki (mainly the Halloween 2024 page) and from
reading the quest text, and is kept short so it's easy to check each year.
Unknown names are ignored, so a renamed quest only loses its extra link.
"""

WIKI_EVENT_PAGE = "https://wiki.projectgorgon.com/wiki/Halloween_2024"

# Links the wiki describes but the data doesn't encode.
# kind "offered": the second quest is offered once the first one is in your
# journal (assigned), not only after it is finished.
# kind "completes": finishing the first quest ticks off the second one.
EXTRA_LINKS = [
    ("Event_Halloween_PartyPrep1", "Event_Halloween_DeliverBeer", "offered",
     "Once Zhia assigns the party prep, Brandon Mellus in Amulna asks you to deliver the beer first."),
    ("Event_Halloween_DeliverBeer", "Event_Halloween_DeliverBeer2", "offered",
     "After the last keg, report back to Brandon."),
    ("Event_Halloween_DeliverBeer2", "Event_Halloween_SoupPrep", "offered",
     "Brandon moves to the Red Wing Casino party room and asks for help with the food."),
    ("Event_Halloween_PumpkinRolls", "Event_Halloween_PartyPrep1", "completes",
     "Brandon's three food quests finish Preparing For The Big Party."),
    ("Event_Halloween_PartyPrep2", "Event_Halloween_HelpWestley", "offered",
     "Brandon offers this once Zhia assigns The Unfortunate Cultists."),
    ("Event_Halloween_PartyPrep2", "Event_Halloween_HelpDeville", "offered",
     "Brandon offers this once Zhia assigns The Unfortunate Cultists."),
    ("Event_Halloween_PartyPrep2", "Event_Halloween_HelpRick", "offered",
     "Brandon offers this once Zhia assigns The Unfortunate Cultists."),
    ("Event_Halloween_PartyPrep2", "Event_Halloween_HelpChaf", "offered",
     "Brandon offers this once Zhia assigns The Unfortunate Cultists."),
    ("Event_Halloween_HelpWestley", "Event_Halloween_TheElvenMedicine", "offered",
     "Brandon sends you to Westley in Serbule."),
    ("Event_Halloween_HelpDeville", "Event_Halloween_TheDonkeysCure", "offered",
     "Brandon sends you to Deville near Animal Town."),
    ("Event_Halloween_HelpRick", "Event_Halloween_TheMirrorBreaker", "offered",
     "Brandon sends you to Melandria in Gazluk Keep."),
    ("Event_Halloween_HelpChaf", "Event_Halloween_TheGamblersCurse", "offered",
     "Brandon sends you to Chaf in the Red Wing Casino."),
]

# Quests whose giver isn't in the FavorNpc field: (npc key, area key).
GIVER_OVERRIDES = {
    "Event_Halloween_DeliverBeer": ("NPC_Halloween_BrandonMellus", "AreaDesert1"),
    "Event_Halloween_DeliverBeer2": ("NPC_Halloween_BrandonMellus", "AreaCasino"),
}

# Short notes shown on each NPC's page.
NPC_ROLES = {
    "NPC_ZhiaLian": "The goddess of whimsy and unpredictability. She talks straight into your mind, "
                    "so her quests appear in your journal wherever you are.",
    "NPC_Halloween_BrandonMellus": "Leader of Zhia Lian's party cult. He starts in Amulna, a hamlet in the "
                                   "Ilmari Desert, and moves to the Red Wing Casino party room once the beer "
                                   "is delivered.",
    "Halloween_BatInTheHat": "A stylish bat in the Red Wing Casino who makes festive hats. "
                             "It arrives about a week before the first party.",
    "NPC_Halloween_Westley": "A cultist Zhia Lian turned into an elf. He went to Serbule looking for a cure.",
    "NPC_Halloween_Deville": "A cultist turned into a donkey. Look for him around Animal Town in Sun Vale.",
    "NPC_Melandria": "Speak to her in Gazluk Keep to free Rick, a cultist trapped as a mirror.",
    "Halloween_RickTheMirror": "A cultist trapped as a mirror in Gazluk Keep.",
    "NPC_Halloween_ChafSpringfield": "A cursed gambler at the Red Wing Casino.",
    "NPC_BriannaWiller": "A Serbule Hills farmer whose pumpkin patch is overrun. Her quest isn't part of "
                         "Zhia's chain.",
    "EventNPC_ZhiasAgent": "The turn-in point for Zhia Lian's Whimsical Challenges. Zhia marks him on the "
                           "Serbule map.",
    "NPC_Halloween_PartyPlanner": "Receives the beer kegs at the Red Wing Casino.",
}

# Names to look for in objective and quest text, per NPC key.
NPC_ALIASES = {
    "NPC_Halloween_BrandonMellus": ["Brandon Mellus", "Brandon"],
    "NPC_Halloween_Westley": ["Westley"],
    "NPC_Halloween_Deville": ["Deville"],
    "NPC_Melandria": ["Melandria"],
    "Halloween_RickTheMirror": ["Rick"],
    "NPC_Halloween_ChafSpringfield": ["Chaf"],
    "NPC_BriannaWiller": ["Brianna Willer", "Brianna"],
    "Halloween_BatInTheHat": ["The Bat in the Hat"],
    "EventNPC_ZhiasAgent": ["Zhia's Agent", "my agent"],
    "NPC_Halloween_PartyPlanner": ["Party Planner"],
}

# Overworld regions, in rough order of the game's map, and the area keys in each.
REGIONS = [
    ("Anagoge Island", ["AreaNewbieIsland"]),
    ("Serbule", ["AreaSerbule", "AreaSerbuleCaves", "AreaMyconianCave", "AreaTomb1"]),
    ("Serbule Hills", ["AreaSerbule2"]),
    ("Eltibule", ["AreaEltibule", "AreaCave1"]),
    ("Red Wing Casino", ["AreaCasino"]),
    ("Sun Vale", ["AreaSunVale", "AreaSunValeCaves"]),
    ("Kur Mountains", ["AreaKurMountains", "AreaKurCaves", "AreaCave2"]),
    ("Ilmari Desert", ["AreaDesert1", "AreaDesert1Caves", "AreaDesert2"]),
    ("Rahu", ["AreaRahu", "AreaRahuCaves"]),
    ("Gazluk", ["AreaGazluk", "AreaGazlukCaves", "AreaGazlukKeep"]),
    ("Fae Realm", ["AreaFaeRealm1", "AreaFaeRealm1Caves"]),
    ("Povus", ["AreaPovus", "AreaPovusCaves", "AreaPovusCaves2"]),
    ("Vidaria", ["AreaVidaria", "AreaVidariaCaves"]),
    ("Statehelm", ["AreaStatehelm", "AreaStatehelmCaves", "AreaStatehelmCaves2"]),
]
ANYWHERE = "Anywhere"

# Place names in quest text -> (region, specific spot or None).
# Checked in order; each match is removed from the text before the next
# pattern runs, so "Serbule Hills" never also counts as "Serbule".
PLACE_PATTERNS = [
    (r"Red Wing Casino|Casino Party Planner|party room|party site", "Red Wing Casino", None),
    (r"Amulna|hamlet in the Ilmari", "Ilmari Desert", "Amulna"),
    (r"small lake in the Ilmari", "Ilmari Desert", "Small lake (at night)"),
    (r"collapsed cave in the Ilmari", "Ilmari Desert", "Collapsed cave"),
    (r"Ilmari", "Ilmari Desert", None),
    (r"Rahu Sewers?|sewers? (?:under|beneath) Rahu|deep in the sewers|beneath Rahu|underneath Rahu",
     "Rahu", "Rahu Sewers"),
    (r"Rahu", "Rahu", None),
    (r"Kur Tower|ruined (?:Kur )?tower|tower in Kur", "Kur Mountains", "Ruined Kur Tower dungeon"),
    (r"yeti[- ]infested cave|yeti cave", "Kur Mountains", "Yeti cave"),
    (r"snow in Kur", "Kur Mountains", "Campfire by a stream, near an orc settlement"),
    (r"\bKur\b", "Kur Mountains", None),
    (r"Gazluk Keep", "Gazluk", "Gazluk Keep"),
    (r"cave in Gazluk|Gazluk, in a cave", "Gazluk", "Gazluk caves"),
    (r"Gazluk", "Gazluk", None),
    (r"Eltibule graveyard", "Eltibule", "Eltibule graveyard"),
    (r"Eltibule, beneath the little keep", "Eltibule", "Beneath Eltibule Keep"),
    (r"Eltibule, deep underground", "Eltibule", "Dungeons beneath Eltibule"),
    (r"Eltibule", "Eltibule", None),
    (r"Serbule Crypt", "Serbule", "Serbule Crypt"),
    (r"Borghild", "Serbule", "Borghild"),
    (r"cave in Serbule", "Serbule", "Serbule caves"),
    (r"Serbule Hills", "Serbule Hills", None),
    (r"Serbule", "Serbule", None),
    (r"Winter Nexus", "Sun Vale", "Winter Nexus"),
    (r"Animal Town", "Sun Vale", "Animal Town"),
    (r"Sun Vale", "Sun Vale", None),
    (r"under Povus|mountain-sized mushroom", "Povus", "Caves under Povus"),
    (r"Povus", "Povus", None),
    (r"Vidaria", "Vidaria", None),
    (r"Statehelm", "Statehelm", None),
    (r"Fae Realm|fae realm portal|Winter Court", "Fae Realm", None),
    (r"Anagoge", "Anagoge Island", None),
]
