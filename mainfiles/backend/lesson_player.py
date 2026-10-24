"""
lesson_player.py — Wave-2 deep-knowledge: lesson player (OpenMAIC
port, script + player only).

OpenMAIC's classroom is a scene script played by a state machine.
Sangam's Learn previously produced one text blob; this module is
the playable half:

* Scene model: ``kind`` slide | quiz | interactive, body markdown,
  narration text, and a typed action list. The v1 action subset is
  ``speech`` (TTS narration), ``spotlight`` (visual focus target)
  and ``question`` (pause point: quiz / discussion prompt).
* Player state machine: idle -> playing -> paused -> live, mirroring
  OpenMAIC's PlaybackEngine modes. The cursor is (scene_index,
  action_index) and is persisted on the player snapshot, so an
  interrupt (a learner question) or a question action pauses
  playback and ``resume()`` continues at exactly the same scene.
* TTS narration hook: ``narrate`` is an injectable callable
  ``(text) -> audio ref | None``. The default is a no-op returning
  None — the player never fabricates audio; a caller wires Sangam's
  voice pipeline in.

Deliberately NOT ported: canvas slide editor, SVG whiteboard engine,
MP4 render service, PPTX/HTML export (parent follow-ups).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable

PLAYER_MODES = ("idle", "playing", "paused", "live")
SCENE_KINDS = ("slide", "quiz", "interactive")
ACTION_TYPES = ("speech", "spotlight", "question")


@dataclass
class LessonAction:
    type: str  # speech | spotlight | question
    text: str = ""  # speech: narration; question: the prompt
    target: str = ""  # spotlight: what to focus
    payload: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {"type": self.type, "text": self.text,
                "target": self.target, "payload": self.payload}

    @classmethod
    def from_dict(cls, data: dict) -> "LessonAction":
        action_type = data.get("type", "speech")
        if action_type not in ACTION_TYPES:
            raise ValueError(f"Unknown lesson action type: {action_type}")
        return cls(type=action_type, text=data.get("text", ""),
                   target=data.get("target", ""),
                   payload=dict(data.get("payload") or {}))


@dataclass
class LessonScene:
    index: int
    kind: str  # slide | quiz | interactive
    title: str
    body_markdown: str = ""
    narration_text: str = ""
    actions: list[LessonAction] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {"index": self.index, "kind": self.kind, "title": self.title,
                "body_markdown": self.body_markdown,
                "narration_text": self.narration_text,
                "actions": [a.to_dict() for a in self.actions]}

    @classmethod
    def from_dict(cls, data: dict) -> "LessonScene":
        kind = data.get("kind", "slide")
        if kind not in SCENE_KINDS:
            raise ValueError(f"Unknown scene kind: {kind}")
        return cls(
            index=int(data.get("index", 0)), kind=kind,
            title=data.get("title", ""), body_markdown=data.get("body_markdown", ""),
            narration_text=data.get("narration_text", ""),
            actions=[LessonAction.from_dict(a) for a in data.get("actions", [])],
        )


def scene_from_outline_section(section: dict, index: int) -> LessonScene:
    """Turn one outline section ({title, points, duration_min}) into
    a playable slide scene: narration joins the points, the speech
    action carries it, and a question action closes the scene so
    playback pauses for a check before moving on."""
    title = section.get("title", f"Scene {index + 1}")
    points = section.get("points") or []
    body = "\n".join(f"- {p}" for p in points)
    narration = " ".join(str(p) for p in points)
    actions = []
    if narration:
        actions.append(LessonAction(type="speech", text=narration))
    actions.append(LessonAction(
        type="question",
        text=f"What is the key idea of '{title}'?",
        payload={"auto": True, "duration_min": section.get("duration_min")},
    ))
    return LessonScene(index=index, kind="slide", title=title,
                       body_markdown=body, narration_text=narration,
                       actions=actions)


def lesson_from_outline(topic: str, outline: list[dict]) -> dict:
    """Outline (the shape /learn/outline already returns) -> a
    playable lesson dict {topic, scenes}. No model call here; the
    caller generates richer scene bodies separately if wanted."""
    scenes = [scene_from_outline_section(s, i) for i, s in enumerate(outline)]
    return {"topic": topic, "scenes": [s.to_dict() for s in scenes]}


class LessonPlayer:
    """Playback state machine over a scene list.

    Cursor semantics (OpenMAIC's PlaybackSnapshot, reduced):
    ``scene_index``/``action_index`` point at the NEXT action to
    execute. ``interrupt()`` (learner asks a question mid-lesson)
    saves the cursor and flips to ``live``; ``end_discussion()``
    returns to ``paused`` with the cursor untouched, so ``resume()``
    continues at the same scene. A ``question`` action encountered
    during ``play_step`` pauses playback (``awaiting_answer``) at
    that action; ``answer_question()`` consumes it and resumes.
    """

    def __init__(
        self, scenes: list[LessonScene],
        narrate: Callable[[str], Any | None] | None = None,
    ) -> None:
        if not scenes:
            raise ValueError("A lesson needs at least one scene")
        self.scenes = sorted(scenes, key=lambda s: s.index)
        self.narrate = narrate
        self.mode: str = "idle"
        self.scene_index = 0
        self.action_index = 0
        self.awaiting_answer: bool = False
        self.pending_question: dict | None = None
        self.discussion_log: list[dict] = []
        self.spoken: list[str] = []  # narration texts delivered, in order

    # -- lifecycle -------------------------------------------------

    def start(self) -> dict:
        if self.mode not in ("idle", "paused"):
            raise ValueError(f"Cannot start from mode {self.mode}")
        self.mode = "playing"
        return self.snapshot()

    def pause(self) -> dict:
        if self.mode != "playing":
            raise ValueError(f"Cannot pause from mode {self.mode}")
        self.mode = "paused"
        return self.snapshot()

    def resume(self) -> dict:
        """Resume at the saved cursor — never restarts the lesson."""
        if self.mode not in ("paused", "live"):
            raise ValueError(f"Cannot resume from mode {self.mode}")
        if self.mode == "live":
            raise ValueError("End the discussion before resuming playback")
        self.mode = "playing"
        return self.snapshot()

    def interrupt(self, question: str) -> dict:
        """Learner interrupts with a question: cursor saved, live
        discussion opens grounded in the current scene."""
        if self.mode not in ("playing", "paused"):
            raise ValueError(f"Cannot interrupt from mode {self.mode}")
        self.mode = "live"
        self.discussion_log.append(
            {"scene_index": self.scene_index, "action_index": self.action_index,
             "question": question})
        return self.snapshot()

    def end_discussion(self) -> dict:
        if self.mode != "live":
            raise ValueError(f"Cannot end discussion from mode {self.mode}")
        self.mode = "paused"  # cursor untouched: resume continues here
        return self.snapshot()

    def answer_question(self, answer: str) -> dict:
        """Answer the pending question action, then resume playing
        from the action after it."""
        if not self.awaiting_answer or self.pending_question is None:
            raise ValueError("No question is pending")
        self.pending_question["answer"] = answer
        self.discussion_log.append(dict(self.pending_question))
        self.awaiting_answer = False
        self.pending_question = None
        self.action_index += 1  # consume the question action
        self._advance_scene_if_done()
        self.mode = "playing"
        return self.snapshot()

    # -- stepping --------------------------------------------------

    def _advance_scene_if_done(self) -> None:
        while self.scene_index < len(self.scenes):
            if self.action_index < len(self.scenes[self.scene_index].actions):
                return
            self.scene_index += 1
            self.action_index = 0

    @property
    def finished(self) -> bool:
        return self.scene_index >= len(self.scenes)

    def current_scene(self) -> LessonScene | None:
        if self.finished:
            return None
        return self.scenes[self.scene_index]

    def play_step(self) -> dict:
        """Execute the next action. Speech returns its narration text
        (and calls the TTS hook when wired); spotlight returns its
        target; question pauses playback at that action. When the
        lesson ends, mode returns to idle."""
        if self.mode != "playing":
            raise ValueError(f"Cannot step while {self.mode}")
        self._advance_scene_if_done()
        if self.finished:
            self.mode = "idle"
            return {"done": True, **self.snapshot()}
        scene = self.scenes[self.scene_index]
        action = scene.actions[self.action_index]
        if action.type == "speech":
            audio = self.narrate(action.text) if self.narrate else None
            self.spoken.append(action.text)
            self.action_index += 1
            self._advance_scene_if_done()
            if self.finished:
                self.mode = "idle"
            return {"done": False, "action": "speech", "text": action.text,
                    "audio": audio, **self.snapshot()}
        if action.type == "spotlight":
            self.action_index += 1
            self._advance_scene_if_done()
            if self.finished:
                self.mode = "idle"
            return {"done": False, "action": "spotlight", "target": action.target,
                    **self.snapshot()}
        # question: pause here; the action is NOT consumed until answered.
        self.mode = "paused"
        self.awaiting_answer = True
        self.pending_question = {
            "scene_index": self.scene_index, "action_index": self.action_index,
            "question": action.text}
        return {"done": False, "action": "question", "question": action.text,
                **self.snapshot()}

    # -- persistence ------------------------------------------------

    def snapshot(self) -> dict:
        return {
            "mode": self.mode, "scene_index": self.scene_index,
            "action_index": self.action_index,
            "awaiting_answer": self.awaiting_answer,
            "finished": self.finished,
            "current_scene": self.current_scene().to_dict() if self.current_scene() else None,
        }

    def to_dict(self) -> dict:
        return {"scenes": [s.to_dict() for s in self.scenes],
                "cursor": self.snapshot(),
                "discussion_log": self.discussion_log,
                "spoken": self.spoken}

    @classmethod
    def from_dict(
        cls, data: dict,
        narrate: Callable[[str], Any | None] | None = None,
    ) -> "LessonPlayer":
        player = cls([LessonScene.from_dict(s) for s in data.get("scenes", [])],
                     narrate=narrate)
        cursor = data.get("cursor", {})
        player.scene_index = int(cursor.get("scene_index", 0))
        player.action_index = int(cursor.get("action_index", 0))
        player.mode = cursor.get("mode", "paused") if cursor.get("mode") in PLAYER_MODES else "paused"
        player.awaiting_answer = bool(cursor.get("awaiting_answer", False))
        if player.awaiting_answer and not player.finished:
            scene = player.scenes[player.scene_index]
            if player.action_index < len(scene.actions):
                action = scene.actions[player.action_index]
                player.pending_question = {
                    "scene_index": player.scene_index,
                    "action_index": player.action_index, "question": action.text}
        player.discussion_log = list(data.get("discussion_log", []))
        player.spoken = list(data.get("spoken", []))
        return player
