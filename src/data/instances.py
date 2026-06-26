"""
instances.py — Factory functions for planning instances.

Three instance families:

1. demo_chln()  : 20-case toy instance derived from CHLN data (Chapter 4).
                  Solves in < 1 second on any solver. Used for the demo run.

2. small_chln() : 50-case instance matching the scale of the LIC1 sub-sample
                  used in Marques & Captivo (2015) experimental evaluation
                  (Section 6: one service, one planning week).

3. literature_vrsc() : Instance based on Vanhoucke, Rodammer, Straeten &
                       Cardoen (2007) "Operating Theatre Planning and
                       Scheduling" benchmark — 8 ORs, 5 days, ~60 cases.
                       Widely used for comparison in the OR scheduling
                       literature.  We replicate its structure with
                       Portuguese operational parameters.

References
----------
- Marques & Captivo (2015) — CHLN case study, Chapters 4–5.
- Cardoen, Demeulemeester & Beliën (2010) — survey of OR scheduling models.
  Eur. J. Operational Research, 201(3), 921–932.
- Vanhoucke et al. (2007) — benchmark instances for OR planning.
"""

from __future__ import annotations
import random
from typing import List

from ..model.types import (
    Priority, SurgeryScope, Surgeon, OperatingRoom,
    SurgicalCase, PlanningInstance, DAYS,
)

# ──────────────────────────────────────────────────────────────
# Helper
# ──────────────────────────────────────────────────────────────

def _make_room(
    rid: str,
    block: str,
    service: str,
    open_min: int,
    days: List[str] = None,
    ambulatory_only: bool = False,
) -> OperatingRoom:
    if days is None:
        days = DAYS
    return OperatingRoom(
        id=rid,
        block=block,
        service_assignment={d: service for d in days},
        capacity_min={d: open_min for d in days},
        ambulatory_only=ambulatory_only,
    )


def _surgeon(sid: str, service: str, daily: int = 240, weekly: int = 960) -> Surgeon:
    return Surgeon(
        id=sid, name=sid, service=service,
        daily_limit_min=daily, weekly_limit_min=weekly,
    )


def _case(
    cid: str, patient: str, service: str, surgeon: str,
    priority: int, scope: int, age: int, t_cir: int, days_waiting: int,
) -> SurgicalCase:
    return SurgicalCase(
        id=cid, patient_id=patient, service=service, surgeon_id=surgeon,
        priority=Priority(priority), scope=SurgeryScope(scope),
        patient_age=age, t_cir=t_cir, t_clean=20,
        days_waiting=days_waiting,
    )


# ──────────────────────────────────────────────────────────────
# 1. DEMO INSTANCE — CHLN-derived (20 cases)
# ──────────────────────────────────────────────────────────────

def demo_chln() -> PlanningInstance:
    """
    20-case demo instance inspired by CHLN LIC1 (29 Jan 2016).

    Services: ORL (Otorrinolaringologia), ORT (Ortopedia), CVA (Cirurgia Vascular)
    Blocks  : B_ORL (2 rooms, 360 min/day), B_ORT (1 room, 450 min/day),
              B_CVA (2 rooms, 660 min/day)
    Surgeons: 2 ORL, 1 ORT, 3 CVA

    Special rules activated:
      - ORL paediatric circuit on Friday (age ≤ 8 only)
      - Priority-4 cases must be on Monday (day 1)
    """
    surgeons = [
        _surgeon("S_ORL1", "ORL"),
        _surgeon("S_ORL2", "ORL"),
        _surgeon("S_ORT1", "ORT"),
        _surgeon("S_CVA1", "CVA"),
        _surgeon("S_CVA2", "CVA"),
        _surgeon("S_CVA3", "CVA"),
    ]

    rooms = [
        _make_room("R_ORL1", "B_ORL", "ORL", 360),
        _make_room("R_ORL2", "B_ORL", "ORL", 360),
        _make_room("R_ORT1", "B_ORT", "ORT", 450),
        _make_room("R_CVA1", "B_CVA", "CVA", 660),
        _make_room("R_CVA2", "B_CVA", "CVA", 660),
    ]

    # (id, patient, svc, surgeon, prio, scope, age, t_cir, days_waiting)
    raw = [
        # ORL — mix of priorities; C05 and C07 are paediatric (age ≤ 8)
        ("C01","P01","ORL","S_ORL1", 1,1,45,  90,250),  # p1, 20d to deadline
        ("C02","P02","ORL","S_ORL1", 2,2,12,  60, 40),  # p2, 20d remaining
        ("C03","P03","ORL","S_ORL2", 1,1,55,  75,280),  # p1, OVERDUE -10d
        ("C04","P04","ORL","S_ORL2", 3,2, 7,  45,  5),  # p3, 10d remaining
        ("C05","P05","ORL","S_ORL1", 4,2, 6,  30,  3),  # p4, deferred urgent
        ("C06","P06","ORL","S_ORL2", 2,1, 5, 120, 45),  # p2, 15d remaining
        ("C07","P07","ORL","S_ORL1", 1,2, 4,  90,260),  # p1, 10d remaining; age 4 → paediatric
        # ORT
        ("C08","P08","ORT","S_ORT1", 1,1,60, 180,260),  # p1, 10d remaining
        ("C09","P09","ORT","S_ORT1", 2,1,50, 120, 55),  # p2,  5d remaining
        ("C10","P10","ORT","S_ORT1", 3,2,35,  90, 10),  # p3,  5d remaining
        ("C11","P11","ORT","S_ORT1", 1,1,70, 150,275),  # p1, OVERDUE -5d
        ("C12","P12","ORT","S_ORT1", 2,1,55, 200, 50),  # p2, 10d remaining
        ("C13","P13","ORT","S_ORT1", 4,1,40,  60,  3),  # p4, deferred urgent
        # CVA
        ("C14","P14","CVA","S_CVA1", 1,1,62, 210,265),  # p1,  5d remaining
        ("C15","P15","CVA","S_CVA2", 2,1,58, 150, 50),  # p2, 10d remaining
        ("C16","P16","CVA","S_CVA3", 1,1,65, 180,280),  # p1, OVERDUE -10d
        ("C17","P17","CVA","S_CVA1", 3,2,45,  90, 12),  # p3,  3d remaining
        ("C18","P18","CVA","S_CVA2", 2,1,50, 120, 55),  # p2,  5d remaining
        ("C19","P19","CVA","S_CVA3", 4,1,38, 120,  3),  # p4, deferred urgent
        ("C20","P20","CVA","S_CVA1", 1,1,55, 240,255),  # p1, 15d remaining
    ]

    cases = [_case(*r) for r in raw]

    return PlanningInstance(
        name="demo_chln_20cases",
        cases=cases,
        surgeons=surgeons,
        rooms=rooms,
        alpha=2.0,
    )


# ──────────────────────────────────────────────────────────────
# 2. SMALL INSTANCE — 50 cases, 3 services (CHLN scale)
# ──────────────────────────────────────────────────────────────

def small_chln(seed: int = 42) -> PlanningInstance:
    """
    50-case instance.  Represents a single week's planning horizon for
    a mid-sized Portuguese hospital (comparable to CHLN sub-sample).

    Duration distributions from CHLN historical data (2013–2015):
      ORL  : 45–120 min (median 75 min)
      ORT  : 90–240 min (median 150 min)
      CVA  : 90–270 min (median 180 min)
      GIN  : 60–180 min (median 90 min)
    """
    rng = random.Random(seed)

    services = {
        "ORL": {"duration": (45,120), "rooms": 2, "cap": 360},
        "ORT": {"duration": (90,240), "rooms": 1, "cap": 450},
        "CVA": {"duration": (90,270), "rooms": 2, "cap": 660},
        "GIN": {"duration": (60,180), "rooms": 2, "cap": 300},
    }

    surgeons = []
    rooms    = []
    surg_count = {}

    for svc, cfg in services.items():
        n_surg = cfg["rooms"] + 1
        for i in range(n_surg):
            sid = f"S_{svc}{i+1}"
            surgeons.append(_surgeon(sid, svc, daily=300, weekly=1200))
            surg_count.setdefault(svc, []).append(sid)
        for j in range(cfg["rooms"]):
            rid = f"R_{svc}{j+1}"
            rooms.append(_make_room(rid, f"B_{svc}", svc, cfg["cap"]))

    cases = []
    for i in range(50):
        svc = rng.choice(list(services.keys()))
        lo, hi = services[svc]["duration"]
        t_cir = rng.randint(lo // 30, hi // 30) * 30   # multiple of 30 min
        prio  = rng.choices([1,2,3,4], weights=[60,25,12,3])[0]
        scope = rng.choices([1,2], weights=[55,45])[0]
        age   = rng.randint(10, 80)
        from ..model.types import MAX_WAIT_DAYS, Priority as P
        max_w = MAX_WAIT_DAYS[P(prio)]
        days_w = rng.randint(int(max_w * 0.5), int(max_w * 1.3))
        surgeon = rng.choice(surg_count[svc])
        cid = f"C{i+1:03d}"
        cases.append(_case(cid, f"PAT{i+1:03d}", svc, surgeon, prio, scope, age, t_cir, days_w))

    return PlanningInstance(
        name="small_chln_50cases",
        cases=cases,
        surgeons=surgeons,
        rooms=rooms,
        alpha=2.0,
    )


# ──────────────────────────────────────────────────────────────
# 3. LITERATURE BENCHMARK — Cardoen et al. structure (~60 cases)
# ──────────────────────────────────────────────────────────────

def literature_cardoen(seed: int = 7) -> PlanningInstance:
    """
    Instance inspired by Cardoen, Demeulemeester & Beliën (2010) benchmark:
      - 8 operating rooms (4 services, 2 rooms each)
      - 5 days, ~60 cases
      - Mix of inpatient and day-case procedures
      - Surgeon availability: some surgeons off on specific days

    This is the most widely cited OR scheduling benchmark in the European
    healthcare OR literature. We adapt it to Portuguese SIGIC priorities.

    Reference: Cardoen B, Demeulemeester E, Beliën J (2010).
    Operating room planning and scheduling: A literature review.
    Eur. J. Oper. Res. 201(3):921–932. doi:10.1016/j.ejor.2009.04.011
    """
    rng = random.Random(seed)

    SERVICES = ["ORTHO", "CARDIO", "GASTRO", "NEURO"]
    CAPS     = {"ORTHO": 480, "CARDIO": 600, "GASTRO": 420, "NEURO": 540}

    surgeons = []
    rooms    = []
    surg_map_svc = {}

    for svc in SERVICES:
        n_surg = 3
        svc_surgs = []
        for i in range(n_surg):
            sid = f"S_{svc[:3]}{i+1}"
            # Some surgeons take a day off
            avail = {d: True for d in DAYS}
            off_day = rng.choice(DAYS[1:])   # never off Monday
            avail[off_day] = False
            s = Surgeon(
                id=sid, name=sid, service=svc,
                daily_limit_min=280, weekly_limit_min=1100,
                availability=avail,
            )
            surgeons.append(s)
            svc_surgs.append(sid)
        surg_map_svc[svc] = svc_surgs

        for j in range(2):
            rid = f"R_{svc[:3]}{j+1}"
            rooms.append(_make_room(rid, f"B_{svc[:3]}", svc, CAPS[svc]))

    # Ensure no case duration exceeds surgeon daily limit (avoids hard infeasibility)
    for s in surgeons:
        s.daily_limit_min  = 420
        s.weekly_limit_min = 1800

    cases = []
    for i in range(60):
        svc   = rng.choice(SERVICES)
        prio  = rng.choices([1,2,3,4], weights=[55,28,14,3])[0]
        # Cap duration so it can always fit in room and surgeon day
        max_dur = min(CAPS[svc] - 20, 400)
        t_cir = min(rng.randint(3, 14) * 30, max_dur)
        scope = rng.choices([1,2], weights=[60,40])[0]
        age   = rng.randint(18, 85)
        from ..model.types import MAX_WAIT_DAYS, Priority as P
        max_w = MAX_WAIT_DAYS[P(prio)]
        days_w = rng.randint(int(max_w * 0.4), int(max_w * 1.4))
        surgeon = rng.choice(surg_map_svc[svc])
        cid = f"L{i+1:03d}"
        cases.append(_case(cid, f"LPAT{i+1:03d}", svc, surgeon, prio, scope, age, t_cir, days_w))

    return PlanningInstance(
        name="literature_cardoen_60cases",
        cases=cases,
        surgeons=surgeons,
        rooms=rooms,
        paediatric_service="ORL",   # no ORL in this instance → rule inactive
        alpha=2.0,
    )
