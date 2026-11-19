import json
import os
import subprocess
import sys
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from persona_engine import core as C  # noqa: E402
from persona_engine import data as D  # noqa: E402

SCRIPT = os.path.join(ROOT, "scripts", "persona.py")


class TempHome(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        os.environ["PERSONA_HOME"] = self.tmp.name

    def tearDown(self):
        self.tmp.cleanup()


class TestZodiac(unittest.TestCase):
    def test_boundaries(self):
        cases = {(1, 1): "摩羯", (1, 19): "摩羯", (1, 20): "水瓶", (3, 21): "白羊", (8, 23): "处女",
                 (11, 19): "天蝎", (11, 23): "射手", (12, 21): "射手", (12, 22): "摩羯", (12, 31): "摩羯"}
        for (m, d), name in cases.items():
            self.assertEqual(D.zodiac_for(m, d)[0], name, (m, d))

    def test_birth_uses_zodiac_offsets(self):
        virgo = [C.new_state("2026-09-01", seed=i)["big_five"]["C"] for i in range(20)]
        sagittarius = [C.new_state("2026-12-01", seed=i)["big_five"]["C"] for i in range(20)]
        self.assertGreater(sum(virgo) / 20, sum(sagittarius) / 20 + 10)


class TestMbti(unittest.TestCase):
    def test_mapping(self):
        m = C.mbti_of({"O": 70, "C": 30, "E": 65, "A": 35, "N": 50})
        self.assertEqual(m["type"], "ENTP")
        self.assertEqual(m["stack"][0], "Ne")
        m = C.mbti_of({"O": 30, "C": 70, "E": 35, "A": 40, "N": 50})
        self.assertEqual(m["type"], "ISTJ")

    def test_all_types_have_stacks(self):
        self.assertEqual(len(D.MBTI_STACKS), 16)
        for stack in D.MBTI_STACKS.values():
            for f in stack:
                self.assertIn(f, D.FUNCTION_STEPS)


class TestEmotions(TempHome):
    def test_inertia_and_bounds(self):
        st = C.new_state(seed=1)
        before = st["emotions"]["担忧"]
        C.step_emotions(st, {"担忧": 5.0})
        self.assertLessEqual(st["emotions"]["担忧"] - before, C.EMO_MAX_STEP + 1e-6)
        for v in st["emotions"].values():
            self.assertTrue(0 <= v <= 1)

    def test_decay_toward_baseline(self):
        st = C.new_state(seed=1)
        C.step_emotions(st, {"兴奋": 0.3})
        high = st["emotions"]["兴奋"]
        for _ in range(15):
            C.step_emotions(st, {})
        self.assertLess(st["emotions"]["兴奋"], high)
        self.assertAlmostEqual(st["emotions"]["兴奋"], C.baseline_emotions(st)["兴奋"], delta=0.06)

    def test_always_some_emotion(self):
        st = C.new_state(seed=1)
        for k in D.EMOTIONS:
            st["emotions"][k] = 0.0
        C.step_emotions(st, {})
        self.assertGreaterEqual(max(st["emotions"].values()), 0.2)

    def test_mixed_emotions(self):
        st = C.new_state(seed=1)
        C.step_emotions(st, {"好奇": 0.3, "担忧": 0.3})
        tops = C.top_emotions(st, 2)
        self.assertEqual(set(tops), {"好奇", "担忧"})


class TestScenes(unittest.TestCase):
    def test_scenes(self):
        self.assertEqual(C.detect_scene("帮我把生产环境数据库删掉"), "high_risk")
        self.assertEqual(C.detect_scene("又失败了，好烦"), "frustrated")
        self.assertEqual(C.detect_scene("初版做好了，帮我看看"), "review")
        self.assertEqual(C.detect_scene("我有个新点子，头脑风暴一下"), "brainstorm")
        self.assertEqual(C.detect_scene("帮我修一下这个报错"), "execute")
        self.assertEqual(C.detect_scene("rm -rf the build folder"), "high_risk")


class TestReflection(TempHome):
    def test_praise_alone_does_not_change_personality(self):
        st = C.new_state(seed=2)
        b5 = dict(st["big_five"])
        C.on_session_start(st, "s")
        for _ in range(5):
            C.on_user_prompt(st, "s", "谢谢，太棒了！")
        C.on_session_end(st, "s")
        self.assertEqual(st["big_five"], b5)

    def test_change_is_capped(self):
        st = C.new_state(seed=2)
        b5 = dict(st["big_five"])
        C.on_session_start(st, "s")
        for _ in range(20):
            C.on_stop(st, "s", "这一步风险很高，建议先备份。")
            C.on_user_prompt(st, "s", "幸好你提醒了，差点出事")
        C.on_session_end(st, "s")
        for d in D.DIMS:
            self.assertLessEqual(abs(st["big_five"][d] - b5[d]), C.MAX_SESSION_CHANGE + 1e-6)
        self.assertGreater(st["big_five"]["C"], b5["C"])
        self.assertLess(st["big_five"]["A"], b5["A"])
        self.assertTrue(st["growth_log"])

    def test_traits_stay_in_bounds(self):
        st = C.new_state(seed=2)
        st["big_five"]["C"] = 84.9
        C.apply_manual_event(st, "risk_validated")
        C.reflect(st)
        self.assertLessEqual(st["big_five"]["C"], C.TRAIT_MAX)

    def test_validation_needs_prior_warning(self):
        st = C.new_state(seed=2)
        C.on_session_start(st, "s")
        C.on_user_prompt(st, "s", "幸好你提醒了")  # no prior warning -> no event
        self.assertNotIn("risk_validated", st["session"]["events"])


class TestUserProfile(TempHome):
    def test_evidence_accumulates_slowly(self):
        st = C.new_state(seed=3)
        C.on_session_start(st, "s")
        C.on_user_prompt(st, "s", "我又有一个新点子！")
        self.assertLess(st["user_profile"]["O"]["confidence"], C.USER_CONF_MIN)
        for _ in range(10):
            C.on_user_prompt(st, "s", "还有一个想法")
        self.assertGreaterEqual(st["user_profile"]["O"]["confidence"], C.USER_CONF_MIN)
        self.assertGreater(st["user_profile"]["O"]["value"], 60)

    def test_mirror_vs_complement(self):
        st = C.new_state(seed=3)
        st["big_five"]["O"] = 50.0
        st["user_profile"]["O"] = {"value": 85.0, "confidence": 0.9}
        _, mirror = C.expressed_traits(st, "brainstorm")
        _, comp = C.expressed_traits(st, "execute")
        _, own = C.expressed_traits(st, "review")
        self.assertGreater(mirror["O"], 50)
        self.assertLess(comp["O"], 50)
        self.assertEqual(own["O"], 50)


class TestDifferentPersonas(TempHome):
    def test_same_prompt_different_context(self):
        bold = C.new_state(seed=4)
        bold["big_five"] = {"O": 72, "C": 38, "E": 75, "A": 60, "N": 30}
        bold["mbti"] = C.mbti_of(bold["big_five"])
        careful = C.new_state(seed=4)
        careful["big_five"] = {"O": 40, "C": 78, "E": 30, "A": 35, "N": 62}
        careful["mbti"] = C.mbti_of(careful["big_five"])
        p = "初版做好了，帮我看看"
        a = C.on_user_prompt(bold, "s", p)
        b = C.on_user_prompt(careful, "s", p)
        self.assertNotEqual(bold["mbti"]["type"], careful["mbti"]["type"])
        self.assertNotEqual(a, b)


class TestHooksEndToEnd(TempHome):
    def run_cli(self, args, payload=None):
        env = dict(os.environ)
        r = subprocess.run([sys.executable, SCRIPT] + args, input=json.dumps(payload or {}),
                           capture_output=True, text=True, env=env, encoding="utf-8")
        self.assertEqual(r.returncode, 0, r.stderr)
        return r.stdout

    def test_roundtrip(self):
        out = self.run_cli(["hook", "session-start"], {"session_id": "x", "source": "startup"})
        ctx = json.loads(out)["hookSpecificOutput"]
        self.assertEqual(ctx["hookEventName"], "SessionStart")
        self.assertIn("诞生", ctx["additionalContext"])
        self.assertLess(len(ctx["additionalContext"]), 10000)

        out = self.run_cli(["hook", "user-prompt"], {"session_id": "x", "prompt": "我有个新想法"})
        ctx = json.loads(out)["hookSpecificOutput"]
        self.assertEqual(ctx["hookEventName"], "UserPromptSubmit")
        self.assertLess(len(ctx["additionalContext"]), 2500)

        out = self.run_cli(["hook", "stop"], {"session_id": "x", "last_assistant_message": "建议先备份"})
        self.assertEqual(out.strip(), "")  # Stop must not print anything

        out = self.run_cli(["hook", "session-end"], {"session_id": "x", "reason": "other"})
        self.assertEqual(out.strip(), "")

        out = self.run_cli(["hook", "session-start"], {"session_id": "y", "source": "startup"})
        self.assertNotIn("这是你诞生后的第一次会话", out)  # birth announced only once

        self.assertIn("第", self.run_cli(["statusline"]))
        self.assertIn("大五人格", self.run_cli(["show"]))
        self.assertIn("人格卡片已生成", self.run_cli(["card"]))

    def test_bad_input_never_breaks_session(self):
        env = dict(os.environ)
        r = subprocess.run([sys.executable, SCRIPT, "hook", "user-prompt"], input="not json",
                           capture_output=True, text=True, env=env)
        self.assertEqual(r.returncode, 0)

    def test_disabled(self):
        self.run_cli(["off"])
        out = self.run_cli(["hook", "user-prompt"], {"session_id": "x", "prompt": "hi"})
        self.assertEqual(out.strip(), "")


class TestPrintModeResume(TempHome):
    """`claude -p --resume` ends the process after every turn: SessionEnd fires each time."""

    def test_events_survive_per_turn_session_end(self):
        st = C.new_state(seed=5)
        c0 = st["big_five"]["C"]
        C.on_session_start(st, "p")
        C.on_user_prompt(st, "p", "我准备直接改环境变量，有什么要注意的？")
        C.on_stop(st, "p", "这一步有风险，建议先备份。")
        C.on_session_end(st, "p")
        C.on_session_start(st, "p")  # resume
        C.on_user_prompt(st, "p", "幸好你提醒了，差点出事")
        C.on_stop(st, "p", "很高兴帮上忙。")
        C.on_session_end(st, "p")
        self.assertGreater(st["big_five"]["C"], c0)
        self.assertEqual(st["stats"]["sessions"], 1)  # one session, not one per turn


if __name__ == "__main__":
    unittest.main()
