"""
Drive history for the rank: the last few ranked drives, so the trip card can show personal bests and streaks.

This file is part of zoompilot and is licensed under the MIT License.
See the LICENSE.md file in the root directory for more details.

Kept in boom-boom's store (history.json), written when the trip card appears in Park. A drive is one onroad
session: parking and driving on updates its entry rather than adding another. Each entry is small (style, rank,
score, points, distance, best 0-30), and only the last MAX_DRIVES are kept. Display only.
"""
import uuid

from .scoring import DriveScore

HISTORY = "BoomDriveHistory"
MAX_DRIVES = 30
GOOD_RANKS = ("S", "A")


def entry(score: DriveScore, drive_id: str) -> dict:
  rs = score.rank_score()
  return {"id": drive_id, "flavour": score.flavour, "rank": score.rank(), "score": None if rs is None else round(rs, 1),
          "points": score.points, "km": round(score.driver_distance / 1000, 2), "best_0_30": score.best_0_30}


def record(drives: list[dict], new: dict) -> list[dict]:
  """The history with `new` added, or replacing the entry of the same drive, trimmed to MAX_DRIVES."""
  kept = [d for d in drives if d.get("id") != new["id"]]
  return (kept + [new])[-MAX_DRIVES:]


def summary(drives: list[dict], current: dict) -> dict:
  """Records for the current drive against the earlier ones of the same style."""
  earlier = [d for d in drives if d.get("flavour") == current["flavour"] and d.get("id") != current["id"]]
  best_points = max((d.get("points", 0) for d in earlier), default=None)
  launches = [d["best_0_30"] for d in earlier if d.get("best_0_30")]
  streak = 0
  if current["rank"] in GOOD_RANKS:
    streak = 1
    for d in reversed(earlier):
      if d.get("rank") not in GOOD_RANKS:
        break
      streak += 1
  return {
    "best_points": best_points,
    "new_best": bool(earlier) and current["points"] > (best_points or 0),
    "new_launch_best": current["best_0_30"] is not None and bool(launches) and current["best_0_30"] < min(launches),
    "streak": streak,
  }


def line(s: dict) -> str:
  """One short line for the card, '' when there is nothing to say yet."""
  parts = []
  if s["new_best"]:
    parts.append("NEW BEST")
  elif s["best_points"]:
    parts.append(f"best {s['best_points']:,}")
  if s["new_launch_best"]:
    parts.append("0-30 PB")
  if s["streak"] >= 2:
    parts.append(f"{s['streak']} in a row A+")
  return "  |  ".join(parts)


class DriveHistory:
  """Reads the history once, saves this drive when asked, and holds the card's line."""

  def __init__(self):
    self.drive_id = uuid.uuid4().hex[:12]
    self.line = ""
    self._drives: list[dict] | None = None

  def new_drive(self) -> None:
    self.drive_id = uuid.uuid4().hex[:12]
    self.line = ""

  def save(self, params, score: DriveScore) -> None:
    if self._drives is None:
      loaded = params.get(HISTORY)
      self._drives = [d for d in loaded if isinstance(d, dict)] if isinstance(loaded, list) else []
    current = entry(score, self.drive_id)
    if current["rank"] is None and current["points"] == 0:
      return  # too little of the driver's own driving to remember
    self.line = line(summary(self._drives, current))
    self._drives = record(self._drives, current)
    params.put(HISTORY, self._drives)
